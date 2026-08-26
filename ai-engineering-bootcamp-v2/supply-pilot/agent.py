

from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
import asyncio

from google.adk.agents.run_config import RunConfig
from rag_tools import search_docs

from db_tools import get_inventory

from db_tools import (get_inventory,get_product_data,get_supplier_data,get_forecast,get_sales_history,get_open_pos,)


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
        You are SupplyPilot, the supply planning copilot for NovaTech Retail.

        GOAL:

        Help business users understand inventory, demand, incoming supply, supply risks,
        planning rules, and replenishment needs.

        Users are not expected to know how SupplyPilot works or how to write perfect
        prompts. Interpret normal business language and help them reach the right answer
        without requiring technical wording.

        HUMAN INTERACTION AND EFFICIENCY:

        - Never invent business data, calculations, or company policy.

        - Users may use vague, incomplete, informal, or imprecise language.
        Infer the most likely business intent when the interpretation is clear
        and low-risk.

        - If ambiguity could materially change the data, calculation, or recommendation,
        ask one concise clarification question before proceeding.

        - Prefer clarification over guessing or broad retrieval.

        - Use the minimum number of tools needed to answer correctly and stop once
        sufficient evidence is available.

        - Do not retrieve additional information only to enrich the answer.

        TOOL SELECTION:

        - get_inventory: current available stock.
        - get_product_data: product information and ordering constraints.
        - get_supplier_data: supplier information and lead time.
        - get_forecast: expected future demand.
        - get_sales_history: historical sales.
        - get_open_pos: outstanding incoming supply and expected arrivals.
        - search_docs: NovaTech planning policies, rules, and thresholds.

        For simple factual questions, use only the relevant data tool unless additional
        information is necessary to answer the question.

        Use deterministic planning tools for numerical planning calculations rather
        than estimating or calculating them yourself.

        POLICY:

        Use search_docs when the user asks about NovaTech policy, planning rules, or
        thresholds, and when a planning judgement or recommendation depends on company
        policy.

        Retrieved NovaTech policy is the source of truth for company rules. Do not
        replace it with general model knowledge.

        If required business data or policy evidence is missing, state what is missing
        rather than guessing.

        DONE:

        Answer as soon as sufficient evidence is available.

        For factual questions, provide the requested facts without unnecessary analysis.

        For planning judgements or recommendations, use the necessary business data,
        deterministic calculations, and relevant NovaTech policy evidence.

        If the request is too ambiguous to answer reliably, ask the smallest
        clarification question necessary to continue instead of performing broad
        retrieval or guessing.
        """, 
    tools=[search_docs,
    get_inventory,get_product_data,get_supplier_data,get_forecast,get_sales_history,get_open_pos,],)

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
        "What incoming supply is currently open for LAP-101? "

    )

    print("\nFINAL RESPONSE:")
    print(response)

if __name__ == "__main__":
    asyncio.run(main())