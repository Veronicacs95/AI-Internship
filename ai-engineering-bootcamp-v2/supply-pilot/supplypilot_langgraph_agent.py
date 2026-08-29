


# BUSINESS LOGIC DOES NOT CHANGE

# rag_tools.py
# db_tools.py
# planning_tools.py
#       │
#       │
#       ▼
# ──────────────────────────────
# ORCHESTRATION LAYER CHANGES
# ──────────────────────────────

# | Concept              | ADK                           | LangGraph                    |
# | -------------------- | ----------------------------- | ---------------------------- |
# | LLM                  | Gemini                        | Gemini                       |
# | Prompt               | `instruction=`                | system message               |
# | Tools                | `tools=[...]`                 | `bind_tools(...)` + ToolNode |
# | Tool decision        | ADK handles it                | conditional edge             |
# | Run tool             | ADK handles it                | ToolNode                     |
# | Return result to LLM | ADK handles it                | edge back to LLM node        |
# | Conversation data    | ADK session                   | graph state                  |
# | Loop                 | largely provided by framework | explicitly drawn with edges  |
# | Start execution      | `Runner`                      | compiled graph               |
# | Stop runaway loop    | `max_llm_calls`               | `recursion_limit`            |


# |  ADK code                | LangGraph equivalent                |
# | ---------------------------- | ----------------------------------- |
# | `Agent(...)`                 | model node + graph                  |
# | `instruction="""..."""`      | system message / prompt             |
# | `tools=[...]`                | `model.bind_tools([...])`           |
# | `Runner(...)`                | compiled graph                      |
# | `InMemorySessionService()`   | graph state/checkpointer later      |
# | `types.Content(...)`         | `HumanMessage(...)`                 |
# | ADK function call            | AI message containing `tool_calls`  |
# | ADK function response        | `ToolMessage`                       |
# | `runner.run_async()`         | `graph.stream()` / `graph.invoke()` |
# | `RunConfig(max_llm_calls=8)` | `config={"recursion_limit": ...}`   |
# | ADK event loop               | LangGraph node/event stream         |


# -----------------------

# User
#  ↓
# ADK Agent
#  ↓
# Gemini thinks
#  ↓
# ADK decides whether to call tool
#  ↓
# ADK executes tool
#  ↓
# ADK gives observation back to Gemini
#  ↓
# Gemini may call another tool
#  ↓
# Final answer

# -----------------------
# LangGraph Graph:

#            ┌─────────────┐
#            │    START    │
#            └──────┬──────┘
#                   ↓
#            ┌─────────────┐
#            │ AGENT NODE  │
#            │   Gemini    │
#            └──────┬──────┘
#                   │
#              tool call?
#              /         \
#            YES          NO
#             ↓            ↓
#      ┌────────────┐     END
#      │ TOOL NODE  │
#      │ search_docs│
#      └─────┬──────┘
#            │
#            │ observation added
#            ↓
#      ┌─────────────┐
#      │ AGENT NODE  │
#      └──────┬──────┘
#             │
#             └──── repeat if necessary


from typing import Annotated
from typing_extensions import TypedDict

from langchain_core.messages import HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from langchain_core.messages import SystemMessage

from rag_tools import search_docs

# STATE
class SupplyPilotState(TypedDict):
    messages: Annotated[list, add_messages]

# MODEL
model = ChatGoogleGenerativeAI(
    model="gemini-3.6-flash",
    temperature=0,)

# TOOL
# Exactly ONE real tool for the first LangGraph demo
tools = [search_docs]

model_with_tools = model.bind_tools(tools)

# INSTRUCTION
SYSTEM_INSTRUCTION ="""
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
    """


# MODEL NODE
# THINK

def supplypilot_node(state: SupplyPilotState):

    print("\nTHINK")
    print("SupplyPilot is deciding what to do...")

    messages = [
        SystemMessage(content=SYSTEM_INSTRUCTION),
        *state["messages"],
    ]

    response = model_with_tools.invoke(messages)

    return {
        "messages": [response]
    }

# TOOL NODE
# ACT + OBSERVE
tool_node = ToolNode(tools)

# GRAPH

builder = StateGraph(SupplyPilotState)

builder.add_node("supplypilot",supplypilot_node,)

builder.add_node("tools",tool_node,)

builder.add_edge(START,"supplypilot",)

builder.add_conditional_edges("supplypilot",tools_condition,)

builder.add_edge("tools","supplypilot",)

graph = builder.compile()

# RUNNER

def run_agent(message: str):
    print("\n===================================")
    print("SUPPLYPILOT LANGGRAPH")
    print("===================================")

    final_answer = "(no response)"

    for event in graph.stream(
        {"messages": [HumanMessage(content=message)]},
        config={"recursion_limit": 6},
        stream_mode="updates",
    ):
        # OBSERVE
        if "tools" in event:
            print("\nOBSERVE")
            tool_messages = event["tools"].get("messages", [])

            for tool_message in tool_messages:
                print(f"Tool result: {tool_message.content}")

        # SUPPLYPILOT RESPONSE
        if "supplypilot" in event:
            messages = event["supplypilot"].get("messages", [])

            for response_message in messages:
                # Final answer = message without another tool call
                if not getattr(response_message, "tool_calls", None) and response_message.content:
                    final_answer = response_message.content

    # Gemini can return the answer as content blocks.
    # Extract only the readable text.
    if isinstance(final_answer, list):
        answer_text = "".join(
            block.get("text", "")
            for block in final_answer
            if isinstance(block, dict) and block.get("type") == "text"
        )
    else:
        answer_text = str(final_answer)

    return {"answer": answer_text}
        
# LOCAL TEST
if __name__ == "__main__":

    import json

    result = run_agent(
        "What is NovaTech's target Weeks of Supply?"
    )

    print("\nANSWER:")
    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        )
    )