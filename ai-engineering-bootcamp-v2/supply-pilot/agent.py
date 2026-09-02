from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from google.adk.agents.run_config import RunConfig
from rag_tools import search_docs
from db_tools import get_inventory,get_product_data,get_supplier_data,get_forecast,get_sales_history,get_open_pos,save_agent_trace
from planning_tools import calculate_projected_inventory,calculate_forward_average_demand,calculate_projected_wos,calculate_target_inventory,calculate_gap_to_target,detect_stockout_exposure,adjust_order_quantity,check_replenishment_arrival_risk,calculate_replenishment_requirement, select_replenishment_planning_point

import json
from pathlib import Path

# --------------------------------------------------
# ROOT AGENT
# --------------------------------------------------

root_agent = Agent(
    name="supplypilot_agent",
    model="gemini-3.6-flash",
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
        get_inventory,get_product_data,get_supplier_data,get_forecast,get_sales_history,get_open_pos,
        # Deterministic planning
        calculate_projected_inventory,calculate_forward_average_demand,calculate_projected_wos,
        calculate_target_inventory,calculate_gap_to_target,calculate_replenishment_requirement,
        adjust_order_quantity,detect_stockout_exposure,check_replenishment_arrival_risk,select_replenishment_planning_point
    ],
)

# --------------------------------------------------
# SUPPLYPILOT ARCHITECTURE
# --------------------------------------------------

# SupplyPilot Agent
#     │
#     ├── RETRIEVAL / DATA TOOLS
#     │     │
#     │     ├── RAG TOOL
#     │     │     │
#     │     │     └── search_docs
#     │     │           → Pinecone / NovaTech policies
#     │     │
#     │     └── DATABASE TOOLS — PostgreSQL
#     │           │
#     │           ├── get_inventory
#     │           │     → current stock
#     │           │
#     │           ├── get_product_data
#     │           │     → product + MOQ + order multiple + supplier
#     │           │
#     │           ├── get_supplier_data
#     │           │     → lead time + supplier details
#     │           │
#     │           ├── get_forecast
#     │           │     → future weekly demand
#     │           │
#     │           ├── get_sales_history
#     │           │     → historical sales
#     │           │
#     │           └── get_open_pos
#     │                 → open incoming supply + expected arrivals
#     │
#     └── DETERMINISTIC PLANNING TOOLS — Python
#           │
#           ├── calculate_projected_inventory
#           │     → projected inventory by week
#           │     → unmet demand + carried unmet demand
#           │
#           ├── calculate_forward_average_demand
#           │     → rolling forward average weekly demand
#           │
#           ├── calculate_projected_wos
#           │     → projected Weeks of Supply (WOS)
#           │
#           ├── calculate_target_inventory
#           │     → target WOS converted into inventory units
#           │
#           ├── calculate_gap_to_target
#           │     → inventory above / below target
#           │
#           ├── calculate_replenishment_requirement
#           │     → below-target gap converted into required quantity
#           │
#           ├── adjust_order_quantity
#           │     → required quantity adjusted for MOQ + order multiple
#           │
#           ├── detect_stockout_exposure
#           │     → first stockout week + unmet-demand exposure
#           │
#           └── check_replenishment_arrival_risk
#                 → compares stockout timing vs standard lead-time arrival
# --------------------------------------------------
# RUNNER
# event_callback is optional:
# - normal POST /agent → event_callback=None
# - streaming UI → receives live llm_call / act / observe / final events
# --------------------------------------------------

async def run_agent(message: str, event_callback=None):

    # Create the ADK session and runner
    session_service = InMemorySessionService()

    runner = Runner(
        agent=root_agent,
        app_name="supplypilot",
        session_service=session_service
    )

    session = await session_service.create_session(
        app_name="supplypilot",
        user_id="test_user"
    )

    # Convert the user message into ADK content
    content = types.Content(
        role="user",
        parts=[types.Part(text=message)]
    )

    run_config = RunConfig(max_llm_calls=20)

    # Initialize trace data before the agent starts
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
        "error_message": None
    }

    try:

        # Run the agent and process its event stream
        async for event in runner.run_async(
            user_id="test_user",
            session_id=session.id,
            new_message=content,
            run_config=run_config
        ):

            # Track each LLM call
            if getattr(event, "usage_metadata", None):
                llm_calls += 1
                trace["llm_calls"] = llm_calls

                print(f"\nGEMINI CALL #{llm_calls}")
                print("Usage:", event.usage_metadata)

                if event_callback:
                    await event_callback({
                        "type": "llm_call",
                        "number": llm_calls
                    })

            if not event.content or not event.content.parts:
                continue

            for part in event.content.parts:

                # ACT: record the tool selected by the agent
                if getattr(part, "function_call", None):
                    tool_name = part.function_call.name
                    arguments = part.function_call.args

                    print("\nACT")
                    print(f"Tool: {tool_name}")
                    print(f"Arguments: {arguments}")

                    tool_calls.append({
                        "type": "act",
                        "tool": tool_name,
                        "arguments": arguments
                    })

                    if event_callback:
                        await event_callback({
                            "type": "act",
                            "tool": tool_name,
                            "arguments": arguments
                        })

                # OBSERVE: record the result returned by the tool
                elif getattr(part, "function_response", None):
                    tool_name = part.function_response.name
                    result = part.function_response.response
                    result_text = str(result)

                    print("\nOBSERVE")
                    print(f"Tool: {tool_name}")
                    print(f"Result: {result}")

                    tool_calls.append({
                        "type": "observe",
                        "tool": tool_name,
                        "observation": result
                    })

                    # Store RAG evidence separately for grounding evaluation
                    if tool_name == "search_docs":
                        retrieved_context.append({
                            "tool": tool_name,
                            "context": result
                        })

                    if event_callback:
                        display_result = (
                            result_text[:500] + "..."
                            if len(result_text) > 500
                            else result_text
                        )

                        await event_callback({
                            "type": "observe",
                            "tool": tool_name,
                            "observation": display_result
                        })

                # FINAL: capture the agent's final answer
                elif getattr(part, "text", None) and event.is_final_response():
                    final_response = part.text
                    trace["assistant_output"] = final_response

                    print("\nFINAL")
                    print(final_response)

                    if event_callback:
                        await event_callback({
                            "type": "final",
                            "answer": final_response
                        })

        # A run is successful only if a final response was actually produced
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
                await event_callback({
                    "type": "error",
                    "error": trace["error_message"]
                })

    except Exception as e:

        # Preserve failed runs, including max-LLM-call failures
        trace["status"] = "failed"
        trace["error_message"] = str(e)
        trace["assistant_output"] = final_response
        trace["llm_calls"] = llm_calls

        print("\nAGENT FAILED")
        print(str(e))

        if event_callback:
            await event_callback({
                "type": "error",
                "error": str(e)
            })

    finally:

        # Always save the trace, whether the run succeeds or fails
        trace["llm_calls"] = llm_calls

        print(f"\nTOTAL GEMINI CALLS: {llm_calls}")

        print("\nTRACE")
        print(
            json.dumps(
                trace,
                indent=2,
                ensure_ascii=False,
                default=str
            )
        )

        save_agent_trace(trace)

    return trace