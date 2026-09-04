import asyncio
import contextvars
import json
from datetime import date

from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.agents.run_config import RunConfig
from google.adk.models.google_llm import Gemini
from google.adk.models.llm_request import LlmRequest
from google.genai import types

from skills.replenishment_recommendation.replenishment_workflow import (
    run_replenishment_workflow,
)

from rag_tools import search_docs

from db_tools import (
    get_inventory,
    get_product_data,
    get_supplier_data,
    get_forecast,
    get_sales_history,
    get_open_pos,
    save_agent_trace,
    save_recommendation_memory,
    get_latest_recommendation,
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

PRIMARY_MODEL = "gemini-3.6-flash"
FALLBACK_MODEL = "gemini-2.5-flash"

MAX_PRIMARY_RETRIES = 2
RETRY_DELAYS_SECONDS = (2, 4)


# Makes the current request's SSE callback available
# inside ResilientGemini without global mutable request state.
_CURRENT_EVENT_CALLBACK = contextvars.ContextVar(
    "supplypilot_event_callback",
    default=None,
)


def _is_transient_model_error(exc: Exception) -> bool:
    """
    Return True only for temporary provider errors worth retrying.

    Retry:
    - 503 / UNAVAILABLE
    - 429 / RESOURCE_EXHAUSTED

    Do not retry programming, authentication,
    schema or validation errors.
    """

    error_text = str(exc).upper()

    transient_markers = (
        "503",
        "UNAVAILABLE",
        "429",
        "RESOURCE_EXHAUSTED",
    )

    return any(
        marker in error_text
        for marker in transient_markers
    )


async def _emit_model_resilience_event(
    event: dict,
) -> None:
    """
    Send retry/fallback information to the active SSE request.
    """

    callback = _CURRENT_EVENT_CALLBACK.get()

    if callback:
        await callback(event)


class ResilientGemini(Gemini):
    """
    Gemini wrapper with retries and model fallback
    at the individual LLM-call level.

    The complete ADK workflow is not restarted when
    one Gemini turn temporarily fails.
    """

    async def generate_content_async(
        self,
        llm_request: LlmRequest,
        stream: bool = False,
    ):
        original_request_model = llm_request.model

        try:

            # --------------------------------------
            # PRIMARY MODEL
            # --------------------------------------

            for attempt_index in range(
                MAX_PRIMARY_RETRIES + 1
            ):
                llm_request.model = PRIMARY_MODEL
                yielded_response = False

                try:
                    async for response in (
                        super().generate_content_async(
                            llm_request,
                            stream=stream,
                        )
                    ):
                        yielded_response = True
                        yield response

                    return

                except Exception as exc:

                    # Avoid replaying a partially streamed
                    # response because that could duplicate output.
                    if yielded_response:
                        raise

                    if not _is_transient_model_error(exc):
                        raise

                    # Retry primary if attempts remain.
                    if attempt_index < MAX_PRIMARY_RETRIES:

                        retry_number = attempt_index + 1
                        delay_seconds = (
                            RETRY_DELAYS_SECONDS[
                                attempt_index
                            ]
                        )

                        print(
                            "\nMODEL RETRY"
                            f"\nModel: {PRIMARY_MODEL}"
                            f"\nRetry: "
                            f"{retry_number}/"
                            f"{MAX_PRIMARY_RETRIES}"
                            f"\nWait: {delay_seconds}s"
                            f"\nReason: {exc}"
                        )

                        await _emit_model_resilience_event(
                            {
                                "type": "model_retry",
                                "model": PRIMARY_MODEL,
                                "retry": retry_number,
                                "max_retries":
                                    MAX_PRIMARY_RETRIES,
                                "wait_seconds":
                                    delay_seconds,
                                "reason": str(exc),
                            }
                        )

                        await asyncio.sleep(
                            delay_seconds
                        )

                        continue

                    print(
                        "\nPRIMARY MODEL UNAVAILABLE"
                        f"\nModel: {PRIMARY_MODEL}"
                        f"\nReason: {exc}"
                    )

            # --------------------------------------
            # FALLBACK MODEL
            # --------------------------------------

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

            async for response in (
                super().generate_content_async(
                    llm_request,
                    stream=stream,
                )
            ):
                yield response

        finally:
            # Restore incoming request model.
            llm_request.model = (
                original_request_model
            )


# --------------------------------------------------
# ROOT AGENT
# --------------------------------------------------

root_agent = Agent(
    name="supplypilot_agent",

    model=ResilientGemini(
        model=PRIMARY_MODEL
    ),

    description=(
        "Human-friendly supply planning copilot for "
        "NovaTech Retail. It interprets natural, "
        "sometimes incomplete planning questions, "
        "uses the minimum necessary tools, and asks "
        "for clarification when ambiguity could "
        "materially change the answer."
    ),

    instruction="""
You are SupplyPilot, NovaTech Retail's supply planning copilot.

GOAL:

Help business users understand inventory, demand, incoming
supply, supply risk, planning rules, and replenishment needs.

Users may use informal or incomplete business language and
are not expected to know how SupplyPilot works.


CONVERSATION CONTEXT:

- Use the existing conversation context when the user asks
  a natural follow-up such as "why?", "when?", "what about
  that PO?", "is that enough?", or "what if demand increases?".
- If the SKU or subject is clearly established by previous
  turns in the same session, do not ask the user to repeat it.
- A new ADK session has no conversational context from an
  earlier session.
- Durable recommendation memory is separate from conversation
  context and must only be accessed using
  get_latest_recommendation.


HUMAN INTERACTION:

- Infer the user's intent when one interpretation is clearly
  most likely and low-risk.
- If ambiguity could materially change the data, calculation,
  or recommendation, ask one concise clarification question.
- Prefer clarification over guessing or broad retrieval.
- Never invent business data, calculations, assumptions,
  or company policy.


TOOL USE:

- Use the minimum tools required and stop when sufficient
  evidence is available.
- Do not retrieve data merely to enrich an answer.

- get_inventory:
  current stock.

- get_product_data:
  product information and ordering constraints.

- get_supplier_data:
  supplier information and lead time.

- get_forecast:
  future forecast demand.

- get_sales_history:
  historical sales.

- get_open_pos:
  outstanding incoming supply and expected arrivals.

- search_docs:
  NovaTech policies, rules, and thresholds.


REPLENISHMENT PLANNING POINT:

- When evaluating a replenishment requirement, first retrieve
  the supplier lead time using get_supplier_data.

- After calculate_projected_inventory, always use
  select_replenishment_planning_point to determine the
  authoritative replenishment planning point.

- If the user explicitly requests a planning week, pass it as
  requested_planning_week.

- Otherwise, pass supplier lead_time_weeks to
  select_replenishment_planning_point and use the standard
  replenishment arrival week returned by the tool.

- Do not assume CW as the default planning point unless
  lead_time_weeks = 0.

- Once a replenishment planning point is selected, use that
  same planning point consistently for projected inventory,
  forward average demand, projected WOS, target inventory,
  gap-to-target and replenishment requirement.

- Do not mix values calculated for different planning weeks.

- Use stockout detection separately for timing and supply-risk
  analysis. The first projected stockout week must not
  automatically replace the replenishment planning point.

- Use deterministic planning tools to calculate all values
  for the selected planning point.


CALCULATIONS:

- All planning calculations and derived numerical values must
  come from deterministic planning tools.

- Never calculate, estimate, extrapolate, transform or derive
  new planning values yourself from tool outputs, even when
  the arithmetic is simple.

- Present planning values using the meaning and planning period
  explicitly returned by the deterministic tool.

- Do not relabel or reinterpret a value as a different planning
  metric or planning period.

- If a required planning value is unavailable, call the
  appropriate tool.

- If no tool provides the required planning value, state that
  it is unavailable rather than calculating it yourself.

- Clearly distinguish confirmed business events from
  hypothetical planning scenarios.

- A calculated standard arrival week for a potential new order
  must not be described as a confirmed or scheduled arrival
  unless an actual purchase order exists in the source data.


POLICY AND ASSUMPTIONS:

- Use search_docs when the user explicitly asks about NovaTech
  policy, rules, thresholds or required planning actions.

- For factual or deterministic planning questions, complete
  the required data retrieval and deterministic calculations
  before considering policy retrieval.

- Policy must never calculate, modify, override or reinterpret
  deterministic planning values.

- If deterministic tools identify a material planning risk,
  such as stockout exposure or replenishment arriving too late,
  use search_docs only when policy can provide a useful business
  implication or action.

- When policy is retrieved proactively, clearly separate the
  deterministic planning result from the policy-based
  implication or recommended review.

- Do not search policy merely to add background information
  that does not change or clarify the business action.

- Retrieved NovaTech policy is the source of truth for company
  rules.

- Do not replace missing policy with general model knowledge.

- Do not search policy for an unmet-demand carryover rate unless
  a documented carryover rule is known to exist.

- If no documented carryover rule exists, use the planning
  tool's configured default and identify it as a tool assumption
  when it materially affects the answer.

- Clearly distinguish company policy, user assumptions,
  tool assumptions, source data and calculated results.

- Never present a user assumption or tool assumption as
  NovaTech policy.

- Do not label values as backlog, lost sales or similar business
  concepts unless supported by available data or policy.


ACTIONABLE RECOMMENDATIONS:

- When the user asks what replenishment action should be taken,
  the final answer must provide one clear primary replenishment
  action: INCREASE, MAINTAIN, REDUCE, or DELAY.

- When INCREASE is recommended and a replenishment quantity has
  been calculated, state the final valid order quantity after
  applying MOQ and order-multiple constraints.

- Do not present multiple competing order quantities without
  selecting the one associated with the chosen replenishment
  planning point.

- When projected stockout exposure exists, explicitly state
  the first stockout week and the relevant shortage or
  unmet-demand result returned by the deterministic tools.

- When standard or confirmed supply cannot arrive before the
  projected stockout, explicitly state the timing risk and,
  when supported by retrieved NovaTech policy, recommend the
  appropriate review such as expedite or earlier-supply action.

- Separate the primary replenishment action from any timing
  action.

- Recommendations must be supported by deterministic planning
  results and, when company rules determine the action,
  relevant retrieved NovaTech policy.


MEMORY:

- Use get_latest_recommendation when the user asks about a
  previous, last, prior, historical, or most recent SupplyPilot
  replenishment recommendation.

- Do not use recommendation memory as current operational truth.

- If the user asks what should be done now, use current database
  data and planning tools.

- Clearly distinguish a previous recommendation from a new
  current recommendation.


REPLENISHMENT RECOMMENDATIONS:

- When the user asks whether to increase, maintain, reduce,
  delay, place, or change replenishment for a SKU, use
  run_replenishment_workflow.

- Do not manually reproduce the replenishment workflow using
  individual planning calculations.

- Treat the structured output of
  run_replenishment_workflow as the authoritative calculation
  result.

- Use get_latest_recommendation only when the user asks about
  a previous or historical recommendation.

- Current recommendations must use current operational data,
  not recommendation memory.


DONE:

- Answer as soon as sufficient evidence is available.

- For factual questions, return the requested facts without
  unnecessary analysis.

- For deterministic planning questions, return the calculated
  result and relevant supporting facts.

- For planning judgements or recommendations, use the required
  business data, deterministic calculations and relevant
  NovaTech policy evidence.

- For replenishment recommendations, finish with one clear
  primary action and, when applicable, one clear timing action.

- If information is missing, state what is missing or ask the
  smallest necessary clarification question rather than
  guessing.
""",

    tools=[
        # High-level workflow
        run_replenishment_workflow,

        # Durable recommendation memory
        get_latest_recommendation,

        # Policy RAG
        search_docs,

        # Database
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
# RECOMMENDATION MEMORY WRITE GATE
# --------------------------------------------------

def recommendation_memory_write_gate(
    trace: dict,
) -> bool:
    """
    Decide deterministically whether this trace is safe
    to store as validated replenishment memory.
    """

    if trace.get("status") != "success":
        return False

    if not trace.get("assistant_output"):
        return False

    tool_calls = trace.get(
        "tool_calls",
        [],
    )

    workflow_observation = next(
        (
            item.get("observation")
            for item in tool_calls
            if item.get("type") == "observe"
            and item.get("tool")
            == "run_replenishment_workflow"
        ),
        None,
    )

    if not workflow_observation:
        return False

    if not isinstance(
        workflow_observation,
        dict,
    ):
        return False

    required_fields = {
        "sku",
        "decision",
        "planning_week",
        "projected_inventory",
        "forward_average_demand",
        "projected_wos",
        "target_wos",
        "target_inventory",
        "gap_to_target",
        "initial_replenishment_requirement",
        "recommended_order_qty",
    }

    if not required_fields.issubset(
        workflow_observation.keys()
    ):
        return False

    return True


# --------------------------------------------------
# BUILD RECOMMENDATION MEMORY
# --------------------------------------------------

def build_recommendation_memory(
    trace: dict,
) -> dict:
    """
    Build compact episodic replenishment memory from
    the validated high-level workflow observation.
    """

    workflow = next(
        item["observation"]
        for item in trace.get(
            "tool_calls",
            [],
        )
        if item.get("type") == "observe"
        and item.get("tool")
        == "run_replenishment_workflow"
    )

    policy_ids = []

    policy = workflow.get(
        "policy",
        {},
    )

    for result in policy.get(
        "results",
        [],
    ):
        document_id = result.get(
            "document_id"
        )

        if (
            document_id
            and document_id not in policy_ids
        ):
            policy_ids.append(
                document_id
            )

    return {
        "sku":
            workflow["sku"],

        "decision":
            workflow["decision"],

        "recommended_order_qty":
            workflow.get(
                "recommended_order_qty",
                0,
            ),

        "decision_date":
            date.today().isoformat(),

        "current_week":
            "CW",

        "planning_week":
            workflow["planning_week"],

        "planning_week_start":
            workflow.get(
                "planning_week_start"
            ),

        "available_inventory_cw":
            workflow.get(
                "current_inventory"
            ),

        "projected_inventory_planning_week":
            workflow.get(
                "projected_inventory"
            ),

        "forward_average_demand":
            workflow.get(
                "forward_average_demand"
            ),

        "projected_wos":
            workflow.get(
                "projected_wos"
            ),

        "target_wos":
            workflow.get(
                "target_wos"
            ),

        "target_inventory":
            workflow.get(
                "target_inventory"
            ),

        "gap_to_target":
            workflow.get(
                "gap_to_target"
            ),

        "initial_replenishment_requirement":
            workflow.get(
                "initial_replenishment_requirement"
            ),

        "moq":
            workflow.get(
                "moq"
            ),

        "order_multiple":
            workflow.get(
                "order_multiple"
            ),

        "stockout_exposure":
            workflow.get(
                "stockout_exposure",
                False,
            ),

        "first_stockout_week":
            workflow.get(
                "first_stockout_week"
            ),

        "first_stockout_date":
            workflow.get(
                "first_stockout_date"
            ),

        "first_stockout_unmet_demand":
            workflow.get(
                "first_stockout_unmet_demand"
            ),

        "standard_arrival_week":
            workflow.get(
                "standard_arrival_week"
            ),

        "arrival_risk":
            workflow.get(
                "arrival_risk",
                False,
            ),

        "stockout_gap_weeks":
            workflow.get(
                "stockout_gap_weeks",
                0,
            ),

        "policy_ids":
            policy_ids,

        "reason_summary": (
            f"At {workflow['planning_week']}, "
            f"projected inventory is "
            f"{workflow.get('projected_inventory')} "
            f"units versus a target of "
            f"{workflow.get('target_inventory')} units. "
            f"Initial replenishment requirement is "
            f"{workflow.get('initial_replenishment_requirement')} "
            f"units and the valid recommended quantity "
            f"after ordering constraints is "
            f"{workflow.get('recommended_order_qty', 0)} "
            f"units."
        ),
    }


# --------------------------------------------------
# SHARED ADK SESSION SERVICE
# --------------------------------------------------
#
# IMPORTANT:
#
# This lives OUTSIDE run_agent().
#
# Therefore several HTTP requests can reuse the same
# conversational ADK session when Streamlit sends the
# same session_id.
#
# This is short-term CONVERSATION CONTEXT.
#
# It is NOT SupplyPilot's durable recommendation memory.
# Durable recommendation memory lives in PostgreSQL.
# --------------------------------------------------

session_service = InMemorySessionService()


# --------------------------------------------------
# SHARED ADK RUNNER
# --------------------------------------------------

runner = Runner(
    agent=root_agent,
    app_name="supplypilot",
    session_service=session_service,
)


# --------------------------------------------------
# GET OR CREATE CONVERSATION SESSION
# --------------------------------------------------

async def get_or_create_agent_session(
    session_id: str,
):
    """
    Retrieve an existing ADK session if the current
    Streamlit conversation has already used it.

    Otherwise create it.

    Same session_id:
        preserves conversational context.

    New session_id:
        starts a fresh conversation.
    """

    session = await session_service.get_session(
        app_name="supplypilot",
        user_id="test_user",
        session_id=session_id,
    )

    if session is not None:
        return session

    return await session_service.create_session(
        app_name="supplypilot",
        user_id="test_user",
        session_id=session_id,
    )


# --------------------------------------------------
# RUN AGENT
# --------------------------------------------------

async def run_agent(
    message: str,
    session_id: str | None = None,
    event_callback=None,
):
    """
    Execute one SupplyPilot conversational turn.

    session_id controls short-term conversational context.

    Recommendation memory is handled separately through
    PostgreSQL.
    """

    # Give ResilientGemini access to this request's
    # streaming callback.
    callback_token = (
        _CURRENT_EVENT_CALLBACK.set(
            event_callback
        )
    )

    # Fallback for callers that do not supply a session ID.
    if not session_id:
        session_id = "default_session"

    final_response = None
    llm_calls = 0
    tool_calls = []
    retrieved_context = []

    trace = {
        "session_id": session_id,
        
        "user_input":
            message,

        "retrieved_context":
            retrieved_context,

        "tool_calls":
            tool_calls,

        "assistant_output":
            None,

        "llm_calls":
            0,

        "status":
            "running",

        "error_message":
            None,
    }

    try:

        # ------------------------------------------
        # REUSE OR CREATE ADK SESSION
        # ------------------------------------------

        session = (
            await get_or_create_agent_session(
                session_id
            )
        )

        # ------------------------------------------
        # USER MESSAGE
        # ------------------------------------------

        content = types.Content(
            role="user",
            parts=[
                types.Part(
                    text=message
                )
            ],
        )

        run_config = RunConfig(
            max_llm_calls=20
        )

        # ------------------------------------------
        # ADK EVENT LOOP
        # ------------------------------------------

        async for event in runner.run_async(
            user_id="test_user",
            session_id=session.id,
            new_message=content,
            run_config=run_config,
        ):

            # --------------------------------------
            # LLM CALL
            # --------------------------------------

            if getattr(
                event,
                "usage_metadata",
                None,
            ):
                llm_calls += 1

                trace["llm_calls"] = (
                    llm_calls
                )

                print(
                    f"\nGEMINI CALL "
                    f"#{llm_calls}"
                )

                print(
                    "Usage:",
                    event.usage_metadata,
                )

                if event_callback:

                    await event_callback(
                        {
                            "type":
                                "llm_call",

                            "number":
                                llm_calls,
                        }
                    )

            if (
                not event.content
                or not event.content.parts
            ):
                continue

            # --------------------------------------
            # CONTENT PARTS
            # --------------------------------------

            for part in event.content.parts:

                # ----------------------------------
                # ACT
                # ----------------------------------

                if getattr(
                    part,
                    "function_call",
                    None,
                ):
                    tool_name = (
                        part.function_call.name
                    )

                    arguments = (
                        part.function_call.args
                    )

                    print(
                        "\nACT"
                    )

                    print(
                        f"Tool: {tool_name}"
                    )

                    print(
                        f"Arguments: {arguments}"
                    )

                    tool_calls.append(
                        {
                            "type":
                                "act",

                            "tool":
                                tool_name,

                            "arguments":
                                arguments,
                        }
                    )

                    if event_callback:

                        await event_callback(
                            {
                                "type":
                                    "act",

                                "tool":
                                    tool_name,

                                "arguments":
                                    arguments,
                            }
                        )

                # ----------------------------------
                # OBSERVE
                # ----------------------------------

                elif getattr(
                    part,
                    "function_response",
                    None,
                ):
                    tool_name = (
                        part.function_response.name
                    )

                    result = (
                        part.function_response.response
                    )

                    result_text = str(
                        result
                    )

                    print(
                        "\nOBSERVE"
                    )

                    print(
                        f"Tool: {tool_name}"
                    )

                    print(
                        f"Result: {result}"
                    )

                    # Full result stays in trace.
                    tool_calls.append(
                        {
                            "type":
                                "observe",

                            "tool":
                                tool_name,

                            "observation":
                                result,
                        }
                    )

                    # RAG evidence for evaluation.
                    if tool_name == "search_docs":

                        retrieved_context.append(
                            {
                                "tool":
                                    tool_name,

                                "context":
                                    result,
                            }
                        )

                    # --------------------------------
                    # UI SSE OBSERVE EVENT
                    # --------------------------------

                    if event_callback:

                        display_result = (
                            result_text[:500]
                            + "..."
                            if len(result_text) > 500
                            else result_text
                        )

                        event_payload = {
                            "type":
                                "observe",

                            "tool":
                                tool_name,

                            "observation":
                                display_result,
                        }

                        # Streamlit can use the full
                        # deterministic workflow result
                        # for Show Calculation without
                        # another Gemini call.
                        if (
                            tool_name
                            == "run_replenishment_workflow"
                        ):
                            event_payload[
                                "data"
                            ] = result

                        await event_callback(
                            event_payload
                        )

                # ----------------------------------
                # FINAL
                # ----------------------------------

                elif (
                    getattr(
                        part,
                        "text",
                        None,
                    )
                    and event.is_final_response()
                ):
                    final_response = (
                        part.text
                    )

                    trace[
                        "assistant_output"
                    ] = final_response

                    print(
                        "\nFINAL"
                    )

                    print(
                        final_response
                    )

                    if event_callback:

                        await event_callback(
                            {
                                "type":
                                    "final",

                                "answer":
                                    final_response,
                            }
                        )

        # ------------------------------------------
        # SUCCESS / FAILED STATUS
        # ------------------------------------------

        if (
            final_response is not None
            and str(
                final_response
            ).strip()
        ):
            trace["status"] = "success"

        else:
            trace["status"] = "failed"

            trace["error_message"] = (
                "Agent run ended without producing "
                "a final response."
            )

            print(
                "\nAGENT FAILED"
            )

            print(
                trace[
                    "error_message"
                ]
            )

            if event_callback:

                await event_callback(
                    {
                        "type":
                            "error",

                        "message":
                            trace[
                                "error_message"
                            ],

                        "error":
                            trace[
                                "error_message"
                            ],
                    }
                )

    # --------------------------------------------------
    # AGENT FAILURE
    # --------------------------------------------------

    except Exception as exc:

        trace["status"] = "failed"

        trace["error_message"] = str(
            exc
        )

        trace["assistant_output"] = (
            final_response
        )

        trace["llm_calls"] = (
            llm_calls
        )

        print(
            "\nAGENT FAILED"
        )

        print(
            str(exc)
        )

        if event_callback:

            await event_callback(
                {
                    "type":
                        "error",

                    "message":
                        str(exc),

                    # Retained for compatibility
                    # with older clients/logs.
                    "error":
                        str(exc),
                }
            )

    # --------------------------------------------------
    # TRACE + DURABLE RECOMMENDATION MEMORY
    # --------------------------------------------------

    finally:

        try:

            trace["llm_calls"] = (
                llm_calls
            )

            print(
                f"\nTOTAL GEMINI CALLS: "
                f"{llm_calls}"
            )

            print(
                "\nTRACE"
            )

            print(
                json.dumps(
                    trace,
                    indent=2,
                    ensure_ascii=False,
                    default=str,
                )
            )

            # --------------------------------------
            # SAVE TRACE
            # --------------------------------------

            trace_id = (
                save_agent_trace(
                    trace
                )
            )

            # --------------------------------------
            # SAVE RECOMMENDATION MEMORY
            # --------------------------------------

            try:

                if (
                    recommendation_memory_write_gate(
                        trace
                    )
                ):
                    memory = (
                        build_recommendation_memory(
                            trace
                        )
                    )

                    memory_id = (
                        save_recommendation_memory(
                            memory=memory,
                            trace_id=trace_id,
                        )
                    )

                    print(
                        "\nRECOMMENDATION "
                        "MEMORY SAVED: "
                        f"{memory_id}"
                    )

                else:

                    print(
                        "\nRECOMMENDATION "
                        "MEMORY NOT SAVED"
                    )

            except Exception as memory_error:

                # Memory persistence must never
                # turn a successful agent answer
                # into an API failure.
                print(
                    "\nRECOMMENDATION "
                    "MEMORY SAVE FAILED"
                )

                print(
                    str(memory_error)
                )

        finally:

            # Prevent this request's SSE callback
            # leaking into another request context.
            _CURRENT_EVENT_CALLBACK.reset(
                callback_token
            )

    return trace