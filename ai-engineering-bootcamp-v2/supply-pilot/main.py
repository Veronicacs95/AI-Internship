import os
import json
import asyncio
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agent import run_agent
from db_tools import get_inventory, get_product_data, get_supplier_data, get_forecast, get_sales_history, get_open_pos
from rag_tools import PINECONE_INDEX_NAME, pinecone_index, extract_metadata, chunk_text, build_embedding_texts, embed_chunks, build_vectors, upsert_vectors, retrieve_chunks


# --------------------------------------------------
# 1. LOAD ENVIRONMENT
# --------------------------------------------------

_ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(_ENV_PATH)

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not configured")


# --------------------------------------------------
# 2. CREATE FASTAPI APP
# --------------------------------------------------

app = FastAPI(
    title="SupplyPilot API",
    description="AI-powered supply planning copilot using Google ADK, PostgreSQL, deterministic planning tools and Pinecone RAG.",
    version="1.0.0",
)


# --------------------------------------------------
# 3. PYDANTIC MODELS
# --------------------------------------------------

class AgentRequest(BaseModel):
    """User message sent to the SupplyPilot ADK agent."""
    message: str


class IngestRequest(BaseModel):
    """Policy document sent to the Pinecone ingestion pipeline."""
    text: str
    document_id: str
    source: str | None = None


class RetrievedChunk(BaseModel):
    """Chunk returned from Pinecone retrieval."""
    id: str
    score: float
    chunk_index: int
    chunk_text: str
    embedding_text: str
    title: str
    author: str
    document_id: str
    effective_date: str
    last_review: str
    next_review: str
    classification: str
    owner: str
    approver: str
    related: str
    source: str


# --------------------------------------------------
# FASTAPI ARCHITECTURE
# --------------------------------------------------
#
# FastAPI main.py
# │
# ├── GET /health
# │     → HEALTH CHECK
# │     → test that FastAPI / Render is running
# │
# ├── POST /agent
# │     → MAIN SUPPLYPILOT ENTRYPOINT
# │     → streams the agent execution live
# │        ↓
# │     ADK Agent
# │        ├── DB tools → PostgreSQL
# │        ├── planning tools → deterministic calculations
# │        └── search_docs → Pinecone / policy RAG
# │
# ├── POST /ingest
# │     → DOCUMENT MANAGEMENT
# │     → load/update policy documents in Pinecone
# │
# ├── GET /health/pinecone
# │     → TEST / DEBUG
# │     → check Pinecone connection
# │
# ├── GET /health/db
# │     → TEST / DEBUG
# │     → check PostgreSQL connection
# │
# ├── GET /debug/retrieve
# │     → TEST / DEBUG
# │     → test RAG retrieval independently
# │
# ├── GET /products/{sku}
# ├── GET /inventory/{sku}
# ├── GET /forecast/{sku}
# ├── GET /sales/{sku}
# ├── GET /purchase-orders/{sku}
# └── GET /suppliers/{supplier_id}
#       → TEST / DEBUG DB ENDPOINTS
#
# NOTE:
# The agent does NOT call these GET endpoints.
# ADK calls the Python DB, RAG and planning functions directly.
# The GET endpoints exist only to test components independently.


# --------------------------------------------------
# 4. GET /health
# --------------------------------------------------

@app.get("/health")
def health():
    """Check that the FastAPI / Render service is running."""
    return {
        "status": "ok",
        "service": "SupplyPilot API",
    }


# --------------------------------------------------
# 5. POST /agent — STREAMING ADK AGENT
# --------------------------------------------------

# USER
#  │
#  │ "When will LAP-101 run out of stock?"
#  ▼
# POST /agent
#  │
#  ▼
# FastAPI
#  │
#  ▼
# run_agent()
#  │
#  ├── ACT → get_inventory()
#  │       └── OBSERVE → 85
#  │
#  ├── ACT → get_forecast()
#  │       └── OBSERVE → [...]
#  │
#  ├── ACT → calculate_projected_inventory()
#  │       └── OBSERVE → [...]
#  │
#  └── FINAL → "LAP-101 will run out in CW+2"
#           │
#           ├──────────────────────────────► USER
#           │                                sees final answer
#           │
#           ▼
#    complete trace created
#           │
#           ▼
#    return trace to FastAPI
#           │
#           ▼
#    save_agent_trace(result)
#           │
#           ▼
#    PostgreSQL
#    agent_traces
#           │
#           ▼
#         DONE
#           │
#           └──────────────────────────────► USER
#                                            stream closes

@app.post("/agent")
async def agent_endpoint(body: AgentRequest):
    """
    Run SupplyPilot and stream observable events live.

    Event types:
    - llm_call
    - act
    - observe
    - final
    - done
    - error
    """

    if not body.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    async def event_generator():
        queue = asyncio.Queue()

        async def event_callback(event: dict):
            await queue.put(event)

        async def execute_agent():
            try:
                result = await run_agent(body.message, event_callback=event_callback)

                save_agent_trace(result)

                await queue.put({
                    "type": "done",
                    "llm_calls": result["llm_calls"],
                })

            except Exception as exc:
                await queue.put({
                    "type": "error",
                    "message": str(exc),
                })

            finally:
                await queue.put(None)

        task = asyncio.create_task(execute_agent())

        while True:
            event = await queue.get()

            if event is None:
                break

            yield f"data: {json.dumps(event, default=str)}\n\n"

        await task

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# --------------------------------------------------
# 6. POST /ingest
# --------------------------------------------------

@app.post("/ingest")
def ingest(body: IngestRequest):
    """Chunk, embed and index a NovaTech policy document in Pinecone."""

    if not body.text.strip():
        raise HTTPException(status_code=400, detail="Text cannot be empty.")

    if not body.document_id.strip():
        raise HTTPException(status_code=400, detail="document_id cannot be empty.")

    try:
        source = body.source or "Unknown"

        metadata = extract_metadata(body.text, source)
        metadata["document_id"] = body.document_id

        chunks = chunk_text(body.text)
        embedding_texts = build_embedding_texts(chunks, metadata)
        text_embeddings = embed_chunks(embedding_texts)

        vectors = build_vectors(
            chunks,
            embedding_texts,
            text_embeddings,
            metadata,
        )

        upsert_vectors(vectors)

        return {
            "document_id": body.document_id,
            "chunks_indexed": len(vectors),
            "status": "indexed",
        }

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {str(exc)}")


# --------------------------------------------------
# 7. GET /health/pinecone
# --------------------------------------------------

@app.get("/health/pinecone")
def pinecone_health():
    """Check that FastAPI can reach Pinecone."""

    try:
        stats = pinecone_index.describe_index_stats()

        return {
            "status": "ok",
            "index": PINECONE_INDEX_NAME,
            "dimension": stats.dimension,
            "total_vector_count": stats.total_vector_count,
        }

    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Pinecone connection failed: {str(exc)}")


# --------------------------------------------------
# 8. GET /health/db
# --------------------------------------------------

@app.get("/health/db")
def db_health():
    """Check that FastAPI can reach PostgreSQL."""

    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1;")
                result = cursor.fetchone()

        return {
            "status": "ok",
            "database": "postgres",
            "test_query": result[0],
        }

    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Database connection failed: {str(exc)}")


# --------------------------------------------------
# 9. GET /debug/retrieve
# --------------------------------------------------

@app.get("/debug/retrieve", response_model=list[RetrievedChunk])
def debug_retrieve(question: str, top_k: int = 5):
    """Test Pinecone retrieval independently of the agent."""
    return retrieve_chunks(question=question, top_k=top_k)


# --------------------------------------------------
# 10. DB TEST / DEBUG ENDPOINTS
# --------------------------------------------------

@app.get("/inventory/{sku}")
def inventory_by_sku(sku: str):
    """Test get_inventory directly."""

    result = get_inventory(sku)

    if result is None:
        raise HTTPException(status_code=404, detail=f"Inventory for SKU {sku} not found")

    return result


@app.get("/products/{sku}")
def product_by_sku(sku: str):
    """Test get_product_data directly."""

    result = get_product_data(sku)

    if result is None:
        raise HTTPException(status_code=404, detail=f"SKU {sku} not found")

    return result


@app.get("/forecast/{sku}")
def forecast_by_sku(sku: str):
    """Test get_forecast directly."""
    return get_forecast(sku)


@app.get("/sales/{sku}")
def sales_by_sku(sku: str):
    """Test get_sales_history directly."""
    return get_sales_history(sku)


@app.get("/purchase-orders/{sku}")
def purchase_orders_by_sku(sku: str):
    """Test get_open_pos directly."""
    return get_open_pos(sku)


@app.get("/suppliers/{supplier_id}")
def supplier_by_id(supplier_id: str):
    """Test get_supplier_data directly."""

    result = get_supplier_data(supplier_id)

    if result is None:
        raise HTTPException(status_code=404, detail=f"Supplier {supplier_id} not found")

    return result