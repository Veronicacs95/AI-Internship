import asyncio
import contextvars
import json

from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.agents.run_config import RunConfig
from google.adk.models.google_llm import Gemini
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from datetime import date

from rag_tools import search_docs
from db_tools import (
    get_inventory,
    get_product_data,
    get_supplier_data,
    get_forecast,
    get_sales_history,
    get_open_pos,
    save_agent_trace,save_recommendation_memory,
)
from planning_tools import (
    calculate_projected_inventory,
    calculate_forward_average_demand,
    calculate_projected_wos,
    calculate_target_inventory,
    calculate_gap_to_target,
    detect_stockout_exposure,
    adjust_order_quantity,
    check_replenishment_arrival_risk,
    calculate_replenishment_requirement,
    select_replenishment_planning_point,
)


# --------------------------------------------------
# MODEL RESILIENCE CONFIGURATION
# --------------------------------------------------
#
# Normal flow:
#   1. Use PRIMARY_MODEL.
#   2. If Gemini returns a temporary 503/429-style error,
#      retry the SAME model twice with exponential backoff.
#   3. If the primary model is still unavailable,
#      make the SAME model turn with FALLBACK_MODEL.
#
# This happens at the model-call layer, so the whole ADK agent run
# does NOT restart from the beginning when one Gemini turn fails.
# --------------------------------------------------

PRIMARY_MODEL = "gemini-3.6-flash"
FALLBACK_MODEL = "gemini-2.5-flash"

MAX_PRIMARY_RETRIES = 2
RETRY_DELAYS_SECONDS = (2, 4)

# This lets the resilient model publish retry/fallback events into the
# current request's existing SSE event_callback without using global
# mutable request state.
_CURRENT_EVENT_CALLBACK = contextvars.ContextVar(
    "supplypilot_event_callback",
    default=None,)


def _is_transient_model_error(exc: Exception) -> bool:
    """
    Return True only for errors that are reasonable to retry.

    Current retryable cases:
    - 503 / UNAVAILABLE: provider temporarily overloaded/unavailable
    - 429 / RESOURCE_EXHAUSTED: temporary capacity/rate-limit pressure

    Programming errors, authentication errors, invalid requests, bad tool
    schemas, etc. are NOT retried.
    """
    error_text = str(exc).upper()

    transient_markers = (
        "503",
        "UNAVAILABLE",
        "429",
        "RESOURCE_EXHAUSTED",
    )

    return any(marker in error_text for marker in transient_markers)


async def _emit_model_resilience_event(event: dict) -> None:
    """
    Send retry/fallback information to the existing streaming callback.

    If run_agent() was called without an event_callback, this simply does
    nothing.
    """
    callback = _CURRENT_EVENT_CALLBACK.get()

    if callback:
        await callback(event)


class ResilientGemini(Gemini):
    """
    Gemini model wrapper that adds retry + fallback behavior per LLM turn.

    Important:
    This wraps Gemini at generate_content_async(), which is the individual
    model-call layer used by ADK.

    Therefore, if Gemini fails on (for example) LLM call #5, SupplyPilot
    retries that model turn rather than restarting the complete agent run
    and repeating calls #1-#4 and their tools.
    """

    async def generate_content_async(
        self,
        llm_request: LlmRequest,
        stream: bool = False,
    ):
        original_request_model = llm_request.model

        try:
            # ------------------------------------------
            # PRIMARY MODEL: initial call + 2 retries
            # ------------------------------------------
            for attempt_index in range(MAX_PRIMARY_RETRIES + 1):
                llm_request.model = PRIMARY_MODEL
                yielded_response = False

                try:
                    async for response in super().generate_content_async(
                        llm_request,
                        stream=stream,
                    ):
                        yielded_response = True
                        yield response

                    # Successful model turn.
                    return

                except Exception as exc:
                    # If part of a streaming model response has already been
                    # emitted, retrying the same turn could duplicate output.
                    # In that rare case, fail normally rather than replay it.
                    if yielded_response:
                        raise

                    if not _is_transient_model_error(exc):
                        raise

                    # There are still primary-model retries available.
                    if attempt_index < MAX_PRIMARY_RETRIES:
                        retry_number = attempt_index + 1
                        delay_seconds = RETRY_DELAYS_SECONDS[attempt_index]

                        print(
                            "\nMODEL RETRY"
                            f"\nModel: {PRIMARY_MODEL}"
                            f"\nRetry: {retry_number}/{MAX_PRIMARY_RETRIES}"
                            f"\nWait: {delay_seconds}s"
                            f"\nReason: {exc}"
                        )

                        await _emit_model_resilience_event(
                            {
                                "type": "model_retry",
                                "model": PRIMARY_MODEL,
                                "retry": retry_number,
                                "max_retries": MAX_PRIMARY_RETRIES,
                                "wait_seconds": delay_seconds,
                                "reason": str(exc),
                            }
                        )

                        await asyncio.sleep(delay_seconds)
                        continue

                    # No primary retries remain. Exit the primary loop and
                    # move to the fallback model.
                    print(
                        "\nPRIMARY MODEL UNAVAILABLE"
                        f"\nModel: {PRIMARY_MODEL}"
                        f"\nReason: {exc}"
                    )

            # ------------------------------------------
            # FALLBACK MODEL: one attempt
            # ------------------------------------------
            print(
                "\nMODEL FALLBACK"
                f"\nFrom: {PRIMARY_MODEL}"
                f"\nTo: {FALLBACK_MODEL}"
            )

            await _emit_model_resilience_event(
                {
                    "type": "model_fallback",
                    "from_model": PRIMARY_MODEL,
                    "to_model": FALLBACK_MODEL,
                }
            )

            llm_request.model = FALLBACK_MODEL

            async for response in super().generate_content_async(
                llm_request,
                stream=stream,
            ):
                yield response

        finally:
            # Keep the incoming request object clean after this turn.
            llm_request.model = original_request_model


# --------------------------------------------------
# ROOT AGENT
# --------------------------------------------------

root_agent = Agent(
    name="supplypilot_agent",
    model=ResilientGemini(model=PRIMARY_MODEL),
    description=(
        "Human-friendly supply planning copilot for NovaTech Retail. "
        "It interprets natural, sometimes incomplete planning questions, uses the minimum necessary tools, "
        "and asks for clarification when ambiguity could materially change the answer."
    ),
    instruction="""
    You are SupplyPilot, NovaTech Retail's supply planning copilot.

    GOAL:
    Help business users understand inventory, demand, incoming supply, supply risk, planning rules, and replenishment needs.
    Users may use informal or incomplete business language and are not expected to know how SupplyPilot works.

    HUMAN INTERACTION:
    - Infer the user's intent when one interpretation is clearly most likely and low-risk.
    - If ambiguity could materially change the data, calculation, or recommendation, ask one concise clarification question.
    - Prefer clarification over guessing or broad retrieval.
    - Never invent business data, calculations, assumptions, or company policy.

    TOOL USE:
    - Use the minimum tools required and stop when sufficient evidence is available.
    - Do not retrieve data merely to enrich an answer.
    - get_inventory: current stock.
    - get_product_data: product and ordering constraints.
    - get_supplier_data: supplier and lead time.
    - get_forecast: future forecast demand.
    - get_sales_history: historical sales.
    - get_open_pos: outstanding incoming supply and expected arrivals.
    - search_docs: NovaTech policies, rules, and thresholds.

    REPLENISHMENT PLANNING POINT:
    - When evaluating a replenishment requirement, first retrieve the supplier lead time using get_supplier_data.
    - After calculate_projected_inventory, always use select_replenishment_planning_point to determine the authoritative replenishment planning point.
    - If the user explicitly requests a planning week, pass it as requested_planning_week.
    - Otherwise, pass the supplier lead_time_weeks to select_replenishment_planning_point and use the standard replenishment arrival week returned by the tool.
    - Do not assume CW as the default planning point unless lead_time_weeks = 0.
    - Once a replenishment planning point is selected, use that same planning point consistently for projected inventory, forward average demand, projected WOS, target inventory, gap-to-target, and replenishment requirement.
    - Do not mix values calculated for different planning weeks.
    - Use stockout detection separately for timing and supply-risk analysis. The first projected stockout week must not automatically replace the replenishment planning point.
    - Use deterministic planning tools to calculate all values for the selected planning point.

    CALCULATIONS:
    - All planning calculations and derived numerical values must come from deterministic planning tools.
    - Never calculate, estimate, extrapolate, transform, or derive new planning values yourself from tool outputs, even when the arithmetic is simple.
    - Present planning values using the meaning and planning period explicitly returned by the deterministic tool.
    - Do not relabel or reinterpret a value as a different planning metric or planning period.
    - If a required planning value is unavailable, call the appropriate tool.
    - If no tool provides the required planning value, state that it is unavailable rather than calculating it yourself.
    - Clearly distinguish confirmed business events from hypothetical planning scenarios.
    - A calculated standard arrival week for a potential new order must not be described as a confirmed or scheduled arrival unless an actual purchase order exists in the source data.

    POLICY AND ASSUMPTIONS:
    - Use search_docs when the user explicitly asks about NovaTech policy, rules, thresholds, or required planning actions.
    - For factual or deterministic planning questions, complete the required data retrieval and deterministic calculations before considering policy retrieval.
    - Policy must never calculate, modify, override, or reinterpret deterministic planning values.
    - If deterministic tools identify a material planning risk, such as stockout exposure or replenishment arriving too late, use search_docs only when policy can provide a useful business implication or action.
    - When policy is retrieved proactively, clearly separate the deterministic planning result from the policy-based implication or recommended review.
    - Do not search policy merely to add background information that does not change or clarify the business action.
    - Retrieved NovaTech policy is the source of truth for company rules.
    - Do not replace missing policy with general model knowledge.
    - Do not search policy for an unmet-demand carryover rate unless a documented carryover rule is known to exist.
    - If no documented carryover rule exists, use the planning tool's configured default and identify it as a tool assumption when it materially affects the answer.
    - Clearly distinguish company policy, user assumptions, tool assumptions, source data, and calculated results.
    - Never present a user assumption or tool assumption as NovaTech policy.
    - Do not label values as backlog, lost sales, or similar business concepts unless supported by available data or policy.

    ACTIONABLE RECOMMENDATIONS:
    - When the user asks what replenishment action should be taken, the final answer must provide one clear primary replenishment action: INCREASE, MAINTAIN, REDUCE, or DELAY.
    - When INCREASE is recommended and a replenishment quantity has been calculated, state the final valid order quantity after applying MOQ and order-multiple constraints.
    - Do not present multiple competing order quantities without selecting the one associated with the chosen replenishment planning point.
    - When projected stockout exposure exists, explicitly state the first stockout week and the relevant shortage or unmet-demand result returned by the deterministic tools.
    - When standard or confirmed supply cannot arrive before the projected stockout, explicitly state the timing risk and, when supported by retrieved NovaTech policy, recommend the appropriate review such as expedite or earlier-supply action.
    - Separate the primary replenishment action from any timing action. For example: primary action = INCREASE; timing action = review expedite or earlier supply.
    - Recommendations must be supported by the deterministic planning results and, when company rules determine the action, relevant retrieved NovaTech policy.

    DONE:
    - Answer as soon as sufficient evidence is available.
    - For factual questions, return the requested facts without unnecessary analysis.
    - For deterministic planning questions, return the calculated result and relevant supporting facts.
    - For planning judgements or recommendations, use the required business data, deterministic calculations, and relevant NovaTech policy evidence.
    - For replenishment recommendations, finish with one clear primary action and, when applicable, one clear timing action.
    - If information is missing, state what is missing or ask the smallest necessary clarification question rather than guessing.
    """,
    tools=[
        # RAG
        search_docs,

        # DB
        get_inventory,
        get_product_data,
        get_supplier_data,
        get_forecast,
        get_sales_history,
        get_open_pos,

        # Deterministic planning
        calculate_projected_inventory,
        calculate_forward_average_demand,
        calculate_projected_wos,
        calculate_target_inventory,
        calculate_gap_to_target,
        calculate_replenishment_requirement,
        adjust_order_quantity,
        detect_stockout_exposure,
        check_replenishment_arrival_risk,
        select_replenishment_planning_point,
    ],
)


# --------------------------------------------------
# SUPPLYPILOT ARCHITECTURE
# --------------------------------------------------
# **Evals & Memory/SKIlls


# SupplyPilot Agent
#     │
#     ├── RESILIENT GEMINI MODEL
#     │     │
#     │     ├── Primary: gemini-3.6-flash
#     │     ├── transient failure → retry after 2s
#     │     ├── transient failure → retry after 4s
#     │     └── still unavailable → gemini-2.5-flash fallback
#     │
#     ├── RETRIEVAL / DATA TOOLS
#     │     │
#     │     ├── RAG TOOL
#     │     │     └── search_docs
#     │     │           → Pinecone / NovaTech policies
#     │     │
#     │     └── DATABASE TOOLS — PostgreSQL
#     │           ├── get_inventory
#     │           │     → current stock
#     │           ├── get_product_data
#     │           │     → product + MOQ + order multiple + supplier
#     │           ├── get_supplier_data
#     │           │     → lead time + supplier details
#     │           ├── get_forecast
#     │           │     → future weekly demand
#     │           ├── get_sales_history
#     │           │     → historical sales
#     │           └── get_open_pos
#     │                 → open incoming supply + expected arrivals
#     │
#     └── DETERMINISTIC PLANNING TOOLS — Python
#           ├── calculate_projected_inventory
#           │     → projected inventory by week
#           │     → unmet demand + carried unmet demand
#           ├── calculate_forward_average_demand
#           │     → rolling forward average weekly demand
#           ├── calculate_projected_wos
#           │     → projected Weeks of Supply (WOS)
#           ├── calculate_target_inventory
#           │     → target WOS converted into inventory units
#           ├── calculate_gap_to_target
#           │     → inventory above / below target
#           ├── calculate_replenishment_requirement
#           │     → below-target gap converted into required quantity
#           ├── adjust_order_quantity
#           │     → required quantity adjusted for MOQ + order multiple
#           ├── detect_stockout_exposure
#           │     → first stockout week + unmet-demand exposure
#           ├── check_replenishment_arrival_risk
#           │     → compares stockout timing vs standard lead-time arrival
#           └── select_replenishment_planning_point
#                 → authoritative replenishment planning point
#
# --------------------------------------------------
# RUNNER
# --------------------------------------------------
#
# event_callback is optional:
# - normal run → event_callback=None
# - POST /agent streaming UI → receives live events
#
# Existing events:
# - llm_call
# - act
# - observe
# - final
# - error
#
# New resilience events:
# - model_retry
# - model_fallback
#
# --------------------------------------------------


def recommendation_memory_write_gate(trace: dict) -> bool:
    """
    Decide deterministically whether this trace is safe to store
    as validated replenishment memory.
    """

    if trace.get("status") != "success":
        return False

    if not trace.get("assistant_output"):
        return False

    tool_calls = trace.get("tool_calls", [])

    observed_tools = {
        item.get("tool")
        for item in tool_calls
        if item.get("type") == "observe"
    }

    required_tools = {
        "get_product_data",
        "get_inventory",
        "get_supplier_data",
        "get_forecast",
        "get_open_pos",
        "calculate_projected_inventory",
        "select_replenishment_planning_point",
        "calculate_forward_average_demand",
        "calculate_projected_wos",
        "calculate_target_inventory",
        "calculate_gap_to_target",
        "calculate_replenishment_requirement",
        "adjust_order_quantity",
        "detect_stockout_exposure",
        "check_replenishment_arrival_risk",
    }

    if not required_tools.issubset(observed_tools):
        return False

    return True


def build_recommendation_memory(trace: dict) -> dict:
    """
    Build a compact episodic replenishment memory from trusted
    deterministic tool observations.
    """

    observations = {
        item["tool"]: item["observation"]
        for item in trace.get("tool_calls", [])
        if item.get("type") == "observe"
    }

    product = observations["get_product_data"]
    inventory = observations["get_inventory"]
    planning_point = observations["select_replenishment_planning_point"]
    forward_demand = observations["calculate_forward_average_demand"]
    projected_wos = observations["calculate_projected_wos"]
    target_inventory = observations["calculate_target_inventory"]
    gap = observations["calculate_gap_to_target"]
    requirement = observations["calculate_replenishment_requirement"]
    adjusted_order = observations["adjust_order_quantity"]
    stockout = observations["detect_stockout_exposure"]
    arrival = observations["check_replenishment_arrival_risk"]

    recommended_qty = adjusted_order.get("recommended_order_qty", 0)

    decision = (
        "INCREASE"
        if recommended_qty > 0
        else "MAINTAIN"
    )

    policy_ids = []

    for item in trace.get("retrieved_context", []):
        context = item.get("context", {})

        for result in context.get("results", []):
            document_id = result.get("document_id")

            if document_id and document_id not in policy_ids:
                policy_ids.append(document_id)

    return {
        "sku": product["sku"],
        "decision": decision,
        "recommended_order_qty": recommended_qty,

       "decision_date": date.today().isoformat(),
        "current_week": "CW",

        "planning_week": planning_point["planning_week"],
        "planning_week_start": planning_point.get("week_start"),

        "available_inventory_cw": inventory.get("available_inventory"),
        "projected_inventory_planning_week":
            planning_point.get("projected_inventory"),

        "forward_average_demand":
            forward_demand.get("average_weekly_demand"),

        "projected_wos":
            projected_wos.get("projected_wos"),

        "target_wos":
            target_inventory.get("target_wos"),

        "target_inventory":
            target_inventory.get("target_inventory"),

        "gap_to_target":
            gap.get("gap_units"),

        "initial_replenishment_requirement":
            requirement.get("required_qty"),

        "moq":
            product.get("moq"),

        "order_multiple":
            product.get("order_multiple"),

        "stockout_exposure":
            stockout.get("stockout_exposure", False),

        "first_stockout_week":
            stockout.get("first_stockout_week"),

        "first_stockout_date":
            stockout.get("first_stockout_date"),

        "first_stockout_unmet_demand":
            stockout.get("first_stockout_unmet_demand"),

        "standard_arrival_week":
            arrival.get("expected_arrival_week"),

        "arrival_risk":
            arrival.get("arrival_risk", False),

        "stockout_gap_weeks":
            arrival.get("stockout_gap_weeks"),

        "policy_ids":
            policy_ids,

        "reason_summary":
            (
                f"At {planning_point['planning_week']}, projected inventory "
                f"is {planning_point.get('projected_inventory')} units versus "
                f"a target of {target_inventory.get('target_inventory')} units. "
                f"Initial replenishment requirement is "
                f"{requirement.get('required_qty')} units and the valid "
                f"recommended quantity after ordering constraints is "
                f"{recommended_qty} units."
            ),
    }



async def run_agent(message: str, event_callback=None):
    # Make the current SSE callback available to ResilientGemini for this
    # request only.
    callback_token = _CURRENT_EVENT_CALLBACK.set(event_callback)

    # Create the ADK session and runner.
    session_service = InMemorySessionService()

    runner = Runner(
        agent=root_agent,
        app_name="supplypilot",
        session_service=session_service,
    )

    session = await session_service.create_session(
        app_name="supplypilot",
        user_id="test_user",
    )

    # Convert the user message into ADK content.
    content = types.Content(
        role="user",
        parts=[types.Part(text=message)],
    )

    run_config = RunConfig(max_llm_calls=20)

    # Initialize trace data before the agent starts.
    final_response = None
    llm_calls = 0
    tool_calls = []
    retrieved_context = []

    trace = {
        "user_input": message,
        "retrieved_context": retrieved_context,
        "tool_calls": tool_calls,
        "assistant_output": None,
        "llm_calls": 0,
        "status": "running",
        "error_message": None,
    }

    try:
        # Run the agent and process its event stream.
        async for event in runner.run_async(
            user_id="test_user",
            session_id=session.id,
            new_message=content,
            run_config=run_config,
        ):
            # Track each successful ADK LLM response event.
            if getattr(event, "usage_metadata", None):
                llm_calls += 1
                trace["llm_calls"] = llm_calls

                print(f"\nGEMINI CALL #{llm_calls}")
                print("Usage:", event.usage_metadata)

                if event_callback:
                    await event_callback(
                        {
                            "type": "llm_call",
                            "number": llm_calls,
                        }
                    )

            if not event.content or not event.content.parts:
                continue

            for part in event.content.parts:
                # ACT: record the tool selected by the agent.
                if getattr(part, "function_call", None):
                    tool_name = part.function_call.name
                    arguments = part.function_call.args

                    print("\nACT")
                    print(f"Tool: {tool_name}")
                    print(f"Arguments: {arguments}")

                    tool_calls.append(
                        {
                            "type": "act",
                            "tool": tool_name,
                            "arguments": arguments,
                        }
                    )

                    if event_callback:
                        await event_callback(
                            {
                                "type": "act",
                                "tool": tool_name,
                                "arguments": arguments,
                            }
                        )

                # OBSERVE: record the result returned by the tool.
                elif getattr(part, "function_response", None):
                    tool_name = part.function_response.name
                    result = part.function_response.response
                    result_text = str(result)

                    print("\nOBSERVE")
                    print(f"Tool: {tool_name}")
                    print(f"Result: {result}")

                    tool_calls.append(
                        {
                            "type": "observe",
                            "tool": tool_name,
                            "observation": result,
                        }
                    )

                    # Store RAG evidence separately for grounding evaluation.
                    if tool_name == "search_docs":
                        retrieved_context.append(
                            {
                                "tool": tool_name,
                                "context": result,
                            }
                        )

                    if event_callback:
                        display_result = (
                            result_text[:500] + "..."
                            if len(result_text) > 500
                            else result_text
                        )

                        await event_callback(
                            {
                                "type": "observe",
                                "tool": tool_name,
                                "observation": display_result,
                            }
                        )

                # FINAL: capture the agent's final answer.
                elif getattr(part, "text", None) and event.is_final_response():
                    final_response = part.text
                    trace["assistant_output"] = final_response

                    print("\nFINAL")
                    print(final_response)

                    if event_callback:
                        await event_callback(
                            {
                                "type": "final",
                                "answer": final_response,
                            }
                        )

        # A run is successful only if a final response was actually produced.
        if final_response is not None and str(final_response).strip():
            trace["status"] = "success"
        else:
            trace["status"] = "failed"
            trace["error_message"] = (
                "Agent run ended without producing a final response."
            )

            print("\nAGENT FAILED")
            print(trace["error_message"])

            if event_callback:
                await event_callback(
                    {
                        "type": "error",
                        "error": trace["error_message"],
                    }
                )

    except Exception as e:
        # Preserve failed runs, including max-LLM-call failures and a
        # fallback-model failure.
        trace["status"] = "failed"
        trace["error_message"] = str(e)
        trace["assistant_output"] = final_response
        trace["llm_calls"] = llm_calls

        print("\nAGENT FAILED")
        print(str(e))

        if event_callback:
            await event_callback(
                {
                    "type": "error",
                    "error": str(e),
                }
            )

    finally:
        try:
            trace["llm_calls"] = llm_calls

            ...

            trace_id = save_agent_trace(trace)

            try:
                if recommendation_memory_write_gate(trace):
                    memory = build_recommendation_memory(trace)

                    memory_id = save_recommendation_memory(
                        memory=memory,
                        trace_id=trace_id,
                    )

                    print(f"\nRECOMMENDATION MEMORY SAVED: {memory_id}")
                else:
                    print("\nRECOMMENDATION MEMORY NOT SAVED")

            except Exception as memory_error:
                print("\nRECOMMENDATION MEMORY SAVE FAILED")
                print(str(memory_error))



        finally:
            _CURRENT_EVENT_CALLBACK.reset(callback_token)


    return trace
