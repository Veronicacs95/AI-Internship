"""Week 2 RAG Streamlit demo.

Run:
    export API_BASE_URL=https://ai-internship-jfg1.onrender.com
    streamlit run rag_demo.py
"""
import json
import os
import httpx
import streamlit as st


# Page setup
st.set_page_config(page_title="Week 2 RAG Demo", layout="wide")
st.title("Week 2 — RAG Demo")
st.caption("Streamlit → FastAPI on Render → Pinecone + OpenAI")


# Get FastAPI URL from environment, otherwise use localhost
default_api_url = os.getenv("API_BASE_URL") or "http://127.0.0.1:8000"

# Allow the API URL to be changed from the sidebar
base_url = st.sidebar.text_input("FastAPI base URL", value=default_api_url)
st.sidebar.markdown("### Backend")
st.sidebar.code(base_url)
st.sidebar.info("Streamlit is only the front end. RAG logic stays inside FastAPI.")


def call_ingest(base_url: str, text: str, document_id: str, source: str | None = None):
    # Build the JSON expected by POST /ingest
    payload = {"text": text, "document_id": document_id}

    # Add source only when provided
    if source:
        payload["source"] = source

    try:
        # Send the document to the live FastAPI
        response = httpx.post(f"{base_url.rstrip('/')}/ingest", json=payload, timeout=120.0)
        return response.status_code, response.json()

    except httpx.HTTPError as exc:
        return 0, {"error": str(exc)}


def call_ask(base_url: str, question: str):
    # Build the JSON expected by POST /ask
    payload = {"question": question}

    try:
        # Send question to FastAPI, which performs the RAG pipeline
        response = httpx.post(f"{base_url.rstrip('/')}/ask", json=payload, timeout=120.0)
        return response.status_code, response.json()

    except httpx.HTTPError as exc:
        return 0, {"error": str(exc)}


# Two simple UI paths: ingest documents or ask questions
ingest_tab, ask_tab = st.tabs(["📄 Ingest", "💬 Ask RAG"])


with ingest_tab:
    st.subheader("Ingest a document")
    st.write("Paste document text and send it to the live FastAPI `/ingest` endpoint.")

    document_id = st.text_input("Document ID", placeholder="Example: POL-101")
    source = st.text_input("Source filename (optional)", placeholder="Example: doc1_handbook.txt")
    document_text = st.text_area("Document text", height=320, placeholder="Paste the document text here...")

    if st.button("Ingest document", type="primary"):
        # Do not send empty input to FastAPI
        if not document_text.strip():
            st.error("Document text cannot be empty.")

        elif not document_id.strip():
            st.error("Document ID cannot be empty.")

        else:
            with st.spinner("Sending document to FastAPI..."):
                status, data = call_ingest(base_url, document_text, document_id, source or None)

            if status == 200:
                st.success("Document indexed successfully.")

                # Show the important /ingest response fields
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


with ask_tab:
    st.subheader("Ask the RAG system")
    st.write("The question is sent to the live FastAPI `/ask` endpoint.")

    question = st.text_input("Question", placeholder="Example: How many remote days are allowed?")

    if st.button("Ask", type="primary"):
        # Do not send an empty question
        if not question.strip():
            st.error("Question cannot be empty.")

        else:
            with st.spinner("Retrieving context and generating answer..."):
                status, data = call_ask(base_url, question)

            if status == 200:
                # Extract structured response returned by FastAPI
                answer_data = data.get("answer", {})
                answer_text = answer_data.get("answer", "No answer returned.")
                confidence = answer_data.get("confidence", 0)
                sources_needed = answer_data.get("sources_needed", False)
                retrieved_ids = data.get("retrieved_chunk_ids", [])

                # Clearly distinguish an answer from a RAG refusal
                if "don't have enough information" in answer_text.lower():
                    st.warning(answer_text)
                else:
                    st.success(answer_text)

                # Show which Pinecone chunks were retrieved
                st.markdown("### Retrieved chunk IDs")

                if retrieved_ids:
                    st.write(" → ".join(retrieved_ids))
                else:
                    st.info("No retrieved chunk IDs were returned.")

                # Show useful API information
                col1, col2, col3 = st.columns(3)
                col1.metric("Confidence", confidence)
                col2.metric("Tokens used", data.get("tokens_used", 0))
                col3.metric("Cost USD", data.get("cost_usd", 0))

                st.write(f"**Model:** {data.get('model', 'Unknown')}")
                st.write(f"**Latency:** {data.get('latency_ms', 0)} ms")
                st.write(f"**Sources needed:** {sources_needed}")

                # Keep raw JSON available for debugging
                with st.expander("Full API response"):
                    st.json(data)

            elif status:
                st.error(f"API returned HTTP {status}")
                st.json(data)

            else:
                st.error("Could not reach FastAPI.")
                st.json(data)