

from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
import asyncio

from google.adk.agents.run_config import RunConfig
from rag_tools import search_docs


from db_tools import (get_inventory,get_product_data,get_supplier_data,get_forecast,get_sales_history,get_open_pos,)
from planning_tools import (calculate_projected_inventory,calculate_forward_average_demand,calculate_projected_wos,calculate_target_inventory,calculate_gap_to_target,detect_stockout_exposure,adjust_order_quantity,check_replenishment_arrival_risk,)


# --- Root Agent --- 

root_agent = Agent(
    name="supplypilot_agent",
    model="gemini-3.6-flash",
    description=(
        "Human-friendly supply planning copilot for NovaTech Retail. "
        "It interprets natural, sometimes incomplete planning questions, "
        "uses the minimum necessary tools, and asks for clarification when "
        "ambiguity could materially change the answer." ),

    instruction="""
        You are SupplyPilot, NovaTech Retail's supply planning copilot.

        GOAL:
        Help business users understand inventory, demand, incoming supply, supply risk,
        planning rules, and replenishment needs. Users may use informal or incomplete
        business language and are not expected to know how SupplyPilot works.

        HUMAN INTERACTION:
        - Infer the user's intent when one interpretation is clearly most likely and low-risk.
        - If ambiguity could materially change the data, calculation, or recommendation,
        ask one concise clarification question.
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
        - All planning calculations and derived numerical values must come from
        deterministic planning tools.
        - Never calculate, estimate, extrapolate, transform, or derive new planning
        values yourself from tool outputs, even when the arithmetic is simple.
        - Present only planning values explicitly returned by the relevant tool.
        - If a required planning value is unavailable, call the appropriate tool.
        If no tool provides it, state that it is unavailable rather than calculating it.

        POLICY AND ASSUMPTIONS:
        - Use search_docs for policy questions and when a planning judgement or
        recommendation depends on NovaTech policy.
        - Retrieved NovaTech policy is the source of truth for company rules.
        - Do not replace missing policy with general model knowledge.
        - Do not search policy for an unmet-demand carryover rate unless a documented
        carryover rule is known to exist.
        - If no documented carryover rule exists, use the planning tool's configured
        default and identify it as a tool assumption when it materially affects the answer.
        - Clearly distinguish company policy, user assumptions, tool assumptions,
        source data, and calculated results.
        - Never present a user or tool assumption as NovaTech policy.
        - Do not label values as backlog, lost sales, or similar business concepts unless
        supported by the available data or policy.

        DONE:
        Answer as soon as sufficient evidence is available.
        For factual questions, return the requested facts without unnecessary analysis.
        For planning judgements or recommendations, use the required business data,
        deterministic calculations, and relevant NovaTech policy evidence.
        If information is missing, state what is missing or ask the smallest necessary
        clarification question rather than guessing.
    """,
    tools=[
    # RAG tools 
    search_docs,
    # DB tools
    get_inventory,get_product_data,get_supplier_data,get_forecast,get_sales_history,get_open_pos,
    # Planning calculations
    calculate_projected_inventory,calculate_forward_average_demand,calculate_projected_wos,
    calculate_target_inventory,calculate_gap_to_target,detect_stockout_exposure,adjust_order_quantity,check_replenishment_arrival_risk,
    ],)

# USER
#   ↓
# ADK AGENT
#   │
#   ├── db_tools.py
#   │     → retrieve real business data
#   │
#   ├── rag_tools.py
#   │     → retrieve NovaTech policy
#   │
#   └── planning_tools.py      ← NOW
#         → calculate numbers deterministically

# --------------------------------------------------

# SupplyPilot Agent
#     │
#     ├── search_docs RAG tool
#     │     → Pinecone / policy
#     │
#     ├── get_inventory DB tool
#     │     → current stock
#     │
#     ├── get_product_data  DB tool
#     │     → product + MOQ + supplier
#     │
#     ├── get_supplier_data DB tool
#     │     → lead time + supplier details
#     │
#     ├── get_forecast DB tool
#     │     → future demand
#     │
#     ├── get_sales_history DB tool
#     │     → historical sales
#     │
#     └── get_open_pos DB tool
#           → incoming supply


# --- Runner --- 

async def run_agent(message: str):

    session_service = InMemorySessionService()

    runner = Runner(agent=root_agent,app_name="supplypilot",session_service=session_service,)
    session = await session_service.create_session(app_name="supplypilot",user_id="test_user",)

    content = types.Content(role="user",parts=[types.Part(text=message)],)

    run_config = RunConfig(max_llm_calls=8,)

    final_response = "(no response)"
    
    llm_calls = 0

    async for event in runner.run_async(user_id="test_user",session_id=session.id,new_message=content,run_config=run_config,):

        # Count Gemini responses that contain usage information
        if getattr(event, "usage_metadata", None):
            llm_calls += 1
            print(f"\nGEMINI CALL #{llm_calls}")
            print("Usage:", event.usage_metadata)

        # Log the agent/tool event stream
        if event.content and event.content.parts:

            for part in event.content.parts:

                if getattr(part, "function_call", None):
                    print("\nACT")
                    print(f"Tool: {part.function_call.name}")
                    print(f"Arguments: {part.function_call.args}")

                elif getattr(part, "function_response", None):
                    print("\nOBSERVE")
                    print(f"Tool: {part.function_response.name}")
                    print(f"Result: {part.function_response.response}")

                elif getattr(part, "text", None):
                    if event.is_final_response():
                        print("\nFINAL")
                        print(part.text)
                        final_response = part.text

    print(f"\nTOTAL GEMINI CALLS: {llm_calls}")

    return final_response

async def main():
    response = await run_agent(
        "How far below or above target is LAP-101 at CW+2?"
    )

    print("\nFINAL RESPONSE:")
    print(response)

if __name__ == "__main__":
    asyncio.run(main())