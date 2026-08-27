from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from google.adk.agents.run_config import RunConfig
from rag_tools import search_docs
from db_tools import get_inventory,get_product_data,get_supplier_data,get_forecast,get_sales_history,get_open_pos
from planning_tools import calculate_projected_inventory,calculate_forward_average_demand,calculate_projected_wos,calculate_target_inventory,calculate_gap_to_target,detect_stockout_exposure,adjust_order_quantity,check_replenishment_arrival_risk,calculate_replenishment_requirement

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

DONE:
- Answer as soon as sufficient evidence is available.
- For factual questions, return the requested facts without unnecessary analysis.
- For deterministic planning questions, return the calculated result and relevant supporting facts.
- For planning judgements or recommendations, use the required business data, deterministic calculations, and relevant NovaTech policy evidence.
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
        adjust_order_quantity,detect_stockout_exposure,check_replenishment_arrival_risk,
    ],
)

# --------------------------------------------------
# SUPPLYPILOT ARCHITECTURE
# --------------------------------------------------
# SupplyPilot Agent
# │
# ├── RETRIEVAL / DATA
# │   ├── search_docs → Pinecone / NovaTech policy
# │   ├── get_inventory → current stock
# │   ├── get_product_data → product + MOQ + order multiple + supplier
# │   ├── get_supplier_data → supplier + lead time
# │   ├── get_forecast → future weekly demand
# │   ├── get_sales_history → historical sales
# │   └── get_open_pos → incoming supply + expected arrivals
# │
# └── DETERMINISTIC PLANNING
#     ├── calculate_projected_inventory → physical inventory + unmet demand
#     ├── calculate_forward_average_demand → rolling forward demand
#     ├── calculate_projected_wos → projected WOS
#     ├── calculate_target_inventory → WOS target converted to units
#     ├── calculate_gap_to_target → inventory gap vs target
#     ├── calculate_replenishment_requirement → gap converted to required quantity
#     ├── adjust_order_quantity → MOQ + order multiple adjustment
#     ├── detect_stockout_exposure → stockout timing + unmet demand
#     └── check_replenishment_arrival_risk → stockout timing vs standard arrival

# --------------------------------------------------
# RUNNER
# event_callback is optional:
# - normal POST /agent → event_callback=None
# - streaming UI → receives live llm_call / act / observe / final events
# --------------------------------------------------

async def run_agent(message: str,event_callback=None):
    session_service = InMemorySessionService()
    runner = Runner(agent=root_agent,app_name="supplypilot",session_service=session_service)
    session = await session_service.create_session(app_name="supplypilot",user_id="test_user")
    content = types.Content(role="user",parts=[types.Part(text=message)])
    run_config = RunConfig(max_llm_calls=8)

    final_response = "(no response)"
    llm_calls = 0
    steps = []

    async for event in runner.run_async(user_id="test_user",session_id=session.id,new_message=content,run_config=run_config):

        # GEMINI CALL
        if getattr(event,"usage_metadata",None):
            llm_calls += 1
            print(f"\nGEMINI CALL #{llm_calls}")
            print("Usage:",event.usage_metadata)

            if event_callback:
                await event_callback({"type":"llm_call","number":llm_calls})

        if not event.content or not event.content.parts:
            continue

        for part in event.content.parts:

            # ACT
            if getattr(part,"function_call",None):
                tool_name = part.function_call.name
                arguments = part.function_call.args

                print("\nACT")
                print(f"Tool: {tool_name}")
                print(f"Arguments: {arguments}")

                if event_callback:
                    await event_callback({"type":"act","tool":tool_name,"arguments":arguments})

            # OBSERVE
            elif getattr(part,"function_response",None):
                tool_name = part.function_response.name
                result = part.function_response.response
                result_text = str(result)
                truncated_result = result_text[:500] + "..." if len(result_text) > 500 else result_text

                print("\nOBSERVE")
                print(f"Tool: {tool_name}")
                print(f"Result: {result}")

                steps.append({"tool":tool_name,"observation":truncated_result})

                if event_callback:
                    await event_callback({"type":"observe","tool":tool_name,"observation":truncated_result})

            # FINAL
            elif getattr(part,"text",None) and event.is_final_response():
                final_response = part.text

                print("\nFINAL")
                print(final_response)

                if event_callback:
                    await event_callback({"type":"final","answer":final_response})

    print(f"\nTOTAL GEMINI CALLS: {llm_calls}")

    return {"answer":final_response,"steps":steps,"llm_calls":llm_calls}