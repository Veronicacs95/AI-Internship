"""Week 3 SupplyPilot Agent Streamlit demo.

Run:
    export API_BASE_URL=https://ai-internship-jfg1.onrender.com
    streamlit run rag_demo.py

Architecture:
    Streamlit → FastAPI /agent on Render → Google ADK Agent
    → DB tools + deterministic planning tools + search_docs → Pinecone

Additional tabs:
    /ingest → ingest/update policy documents
    /health/pinecone → test Pinecone connection
    /debug/retrieve → inspect RAG retrieval
"""

import json
import os
import httpx
import streamlit as st

# --------------------------------------------------
# PAGE SETUP
# --------------------------------------------------

st.set_page_config(page_title="SupplyPilot Agent", layout="wide")
st.title("SupplyPilot — AI Supply Planning Agent")
st.caption("Streamlit → FastAPI on Render → Google ADK → PostgreSQL + deterministic planning tools + Pinecone policy RAG")

default_api_url = os.getenv("API_BASE_URL") or "http://127.0.0.1:8000"
base_url = st.sidebar.text_input("FastAPI base URL", value=default_api_url)

st.sidebar.markdown("### Backend")
st.sidebar.code(base_url)
st.sidebar.info("Streamlit is only the UI. Agent logic, tools, database access and RAG run in FastAPI / ADK.")

# --------------------------------------------------
# API HELPERS
# --------------------------------------------------

def stream_agent(base_url: str, message: str):
    """Stream live events from POST /agent."""
    try:
        with httpx.stream(
            "POST",
            f"{base_url.rstrip('/')}/agent",
            json={"message": message},
            timeout=180.0,
        ) as response:
            if response.status_code != 200:
                yield {"type": "http_error", "status": response.status_code, "message": response.read().decode()}
                return

            for line in response.iter_lines():
                if not line or not line.startswith("data:"):
                    continue

                try:
                    yield json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    yield {"type": "error", "message": f"Invalid stream event: {line}"}

    except httpx.HTTPError as exc:
        yield {"type": "error", "message": str(exc)}


def call_ingest(base_url: str, text: str, document_id: str, source: str | None = None):
    payload = {"text": text, "document_id": document_id}

    if source:
        payload["source"] = source

    try:
        response = httpx.post(f"{base_url.rstrip('/')}/ingest", json=payload, timeout=180.0)
        return response.status_code, response.json()
    except httpx.HTTPError as exc:
        return 0, {"error": str(exc)}


def check_pinecone(base_url: str):
    try:
        response = httpx.get(f"{base_url.rstrip('/')}/health/pinecone", timeout=60.0)
        return response.status_code, response.json()
    except httpx.HTTPError as exc:
        return 0, {"error": str(exc)}


def debug_retrieve(base_url: str, question: str, top_k: int = 5):
    try:
        response = httpx.get(
            f"{base_url.rstrip('/')}/debug/retrieve",
            params={"question": question, "top_k": top_k},
            timeout=120.0,
        )
        return response.status_code, response.json()
    except httpx.HTTPError as exc:
        return 0, {"error": str(exc)}

# --------------------------------------------------
# TABS
# --------------------------------------------------

agent_tab, ingest_tab, pinecone_tab = st.tabs(["🤖 SupplyPilot Agent", "📄 Ingest Policy", "🔎 Pinecone Debug"])

# ==================================================
# TAB 1 — SUPPLYPILOT AGENT
# ==================================================

with agent_tab:
    st.subheader("Ask SupplyPilot")
    st.write("Enter a normal supply-planning question. SupplyPilot decides which tools are required.")

    message = st.text_area("Task / Question", placeholder="Example: When will LAP-101 first run out of stock?", height=120)

    if st.button("Run SupplyPilot", type="primary", key="run_agent"):
        if not message.strip():
            st.error("Please enter a question.")
        else:
            final_answer = None
            llm_calls = 0
            tool_steps = []

            # One dynamic status line while the agent works
            live_status = st.empty()
            live_status.info("🧠 SupplyPilot is thinking...")

            for event in stream_agent(base_url, message):
                event_type = event.get("type")

                if event_type == "llm_call":
                    llm_calls = event.get("number", llm_calls)
                    live_status.info("🧠 SupplyPilot is thinking...")

                elif event_type == "act":
                    tool_name = event.get("tool", "Unknown tool")
                    arguments = event.get("arguments", {})
                    live_status.info(f"🔧 Running {tool_name}...")

                elif event_type == "observe":
                    tool_name = event.get("tool", "Unknown tool")
                    observation = event.get("observation", "No observation returned.")
                    tool_steps.append({"tool": tool_name, "observation": observation})
                    live_status.info(f"✅ {tool_name} completed. Thinking about the next step...")

                elif event_type == "final":
                    final_answer = event.get("answer", "No answer returned.")
                    live_status.info("🧠 Preparing final answer...")

                elif event_type == "done":
                    llm_calls = event.get("llm_calls", llm_calls)
                    live_status.success("✅ SupplyPilot analysis complete")

                elif event_type == "http_error":
                    live_status.error(f"Agent API error — HTTP {event.get('status')}")
                    st.error(event.get("message", "Unknown API error."))
                    break

                elif event_type == "error":
                    live_status.error("Agent execution failed.")
                    st.error(event.get("message", "Unknown agent error."))
                    break

            if final_answer:
                st.markdown("## Final Answer")
                st.success(final_answer)

                col1, col2 = st.columns(2)
                col1.metric("Tool executions", len(tool_steps))
                col2.metric("Gemini calls", llm_calls)

                # Detailed trace stays hidden unless you want to inspect it
                with st.expander("🔍 View Agent Execution Trace"):
                    for index, step in enumerate(tool_steps, start=1):
                        st.markdown(f"### Step {index}")
                        st.markdown(f"**ACT — Tool:** `{step['tool']}`")
                        st.markdown("**OBSERVE — Result:**")
                        st.code(step["observation"], language="json")


# ==================================================
# TAB 2 — INGEST POLICY
# ==================================================

with ingest_tab:
    st.subheader("Ingest / Update a Policy Document")
    st.write("Send policy text to the live FastAPI `/ingest` endpoint for Pinecone indexing.")

    document_id = st.text_input("Document ID", placeholder="Example: POL-106", key="document_id")
    source = st.text_input(
        "Source filename (optional)",
        placeholder="Example: POL-106_lead_time_stockout_expedite.txt",
        key="source",
    )
    document_text = st.text_area(
        "Document text",
        height=300,
        placeholder="Paste the policy document here...",
        key="document_text",
    )

    if st.button("Ingest document", type="primary", key="ingest_document"):
        if not document_text.strip():
            st.error("Document text cannot be empty.")
        elif not document_id.strip():
            st.error("Document ID cannot be empty.")
        else:
            with st.spinner("Indexing document in Pinecone..."):
                status, data = call_ingest(base_url, document_text, document_id, source or None)

            if status == 200:
                st.success("Document indexed successfully.")

                col1, col2, col3 = st.columns(3)
                col1.metric("Document ID", data.get("document_id", "Unknown"))
                col2.metric("Chunks indexed", data.get("chunks_indexed", 0))
                col3.metric("Status", data.get("status", "Unknown"))

                with st.expander("Full API response"):
                    st.json(data)

            elif status:
                st.error(f"API returned HTTP {status}")
                st.json(data)

            else:
                st.error("Could not reach FastAPI.")
                st.json(data)

# ==================================================
# TAB 3 — PINECONE DEBUG
# ==================================================

with pinecone_tab:
    st.subheader("Pinecone Connection & Retrieval")

    st.markdown("### Pinecone Health")

    if st.button("Check Pinecone", key="check_pinecone"):
        with st.spinner("Checking Pinecone..."):
            status, data = check_pinecone(base_url)

        if status == 200:
            st.success("Pinecone connection is healthy.")

            col1, col2, col3 = st.columns(3)
            col1.metric("Index", data.get("index", "Unknown"))
            col2.metric("Dimension", data.get("dimension", "Unknown"))
            col3.metric("Vectors", data.get("total_vector_count", 0))

        else:
            st.error("Pinecone health check failed.")
            st.json(data)

    st.markdown("### Test Policy Retrieval")

    retrieval_question = st.text_input(
        "Policy retrieval query",
        placeholder="Example: When should an order be expedited?",
        key="retrieval_question",
    )

    top_k = st.slider("Top K", min_value=1, max_value=10, value=5)

    if st.button("Retrieve from Pinecone", key="retrieve_pinecone"):
        if not retrieval_question.strip():
            st.error("Enter a retrieval query.")
        else:
            with st.spinner("Searching Pinecone..."):
                status, data = debug_retrieve(base_url, retrieval_question, top_k)

            if status == 200:
                st.success(f"Retrieved {len(data)} chunks.")

                for index, chunk in enumerate(data, start=1):
                    document_id = chunk.get("document_id", "Unknown")
                    score = chunk.get("score", 0)

                    with st.expander(f"{index}. {document_id} — score {score:.3f}"):
                        st.write(chunk.get("chunk_text", ""))
                        st.caption(f"Source: {chunk.get('source', 'Unknown')}")

            elif status:
                st.error(f"Retrieval API returned HTTP {status}")
                st.json(data)

            else:
                st.error("Could not reach FastAPI.")
                st.json(data)