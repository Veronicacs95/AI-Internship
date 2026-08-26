"""Week 1 live demo — five stages in one file, built up live in class."""

import os
import re
import time
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError
from pinecone import Pinecone

from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings, ChatOpenAI

import psycopg

from db_tools import (get_inventory, get_product_data, get_supplier_data, get_forecast, get_sales_history, get_open_pos)
from planning_tools import (calculate_projected_inventory, calculate_forward_average_demand, calculate_projected_wos, calculate_target_inventory, calculate_gap_to_target, detect_stockout_exposure, adjust_order_quantity, check_replenishment_arrival_risk)
from rag_tools import (PINECONE_INDEX_NAME,pinecone_index,extract_metadata,chunk_text,build_embedding_texts,embed_chunks,build_vectors,upsert_vectors,retrieve_chunks,build_rag_context,build_grounding_prompt,)

from rag_tools import search_docs

from google.adk.agents import Agent

## --------------------------------------------------
# 1. LOAD ENVIRONMENT
# --------------------------------------------------

_ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(_ENV_PATH)


DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not configured")

# --------------------------------------------------
# 2. CREATE CLIENTS
# --------------------------------------------------

app = FastAPI()

# Existing OpenAI client used by /ask
client = OpenAI()


# --------------------------------------------------
# 5. EXISTING WEEK 1 MODEL CONFIG
# --------------------------------------------------

DEFAULT_MODEL = "gpt-4o"

MODEL_PRICES_PER_1K: dict[str, tuple[float, float]] = {
    "gpt-4o": (0.0025, 0.01),
    "gpt-4o-mini": (0.00015, 0.0006),
    "o3-mini": (0.0011, 0.0044),
}

# --------------------------------------------------
# 6. PYDANTIC MODELS
# --------------------------------------------------


class Answer(BaseModel):
    """Structured model output — this is what turns a chatbot into a component."""

    answer: str
    confidence: float = Field(ge=0.0, le=1.0)
    sources_needed: bool


class AskRequest(BaseModel):
    """Typed request body so bad input is rejected before we spend tokens."""

    question: str
    force_bad: bool = False  # Stage 3 demo knob — first attempt breaks schema on purpose.
    model: str | None = None  # Stage 4 — optional override to swap models live.


class AskResponse(BaseModel):
    """Typed response so callers always get the same shape back."""

    answer: Answer
    tokens_used: int
    model: str
    latency_ms: int
    cost_usd: float
        # NEW WEEK 2    
    retrieved_chunk_ids: list[str]



# NEW — Week 2 ingest request
class IngestRequest(BaseModel):
    """Typed request so callers always the same shape back."""
    text: str
    document_id: str
    source: str | None = None


# NEW — Week 2 Retrive Pinecone request
class RetrievedChunk(BaseModel):
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
# 7. EXISTING WEEK 1 HELPERS
# --------------------------------------------------


def compute_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Turn real usage into dollars — same prompt, different model, different cost."""

    prices = MODEL_PRICES_PER_1K.get(model, MODEL_PRICES_PER_1K[DEFAULT_MODEL])
    input_per_1k, output_per_1k = prices
    return (prompt_tokens / 1000 * input_per_1k) + (completion_tokens / 1000 * output_per_1k)


def call_model_structured(question: str, model: str) -> tuple[Answer, int, int, int]:
    """
    Stage 2 center: OpenAI structured output forces exactly the Answer schema.
    Returns parsed answer plus token counts from billing metadata.
    """

    completion = client.chat.completions.parse(
        model=model,
        messages=[{"role": "user", "content": question}],
        response_format=Answer,
    )

    parsed = completion.choices[0].message.parsed
    if parsed is None:
        raise ValueError("Model returned no parseable structured output")

    usage = completion.usage
    total = usage.total_tokens if usage else 0
    prompt_tokens = usage.prompt_tokens if usage else 0
    completion_tokens = usage.completion_tokens if usage else 0
    return parsed, total, prompt_tokens, completion_tokens


def call_model_unsafe(question: str, model: str) -> tuple[Answer, int, int, int]:
    """
    Stage 3 demo path: free-form JSON call, then validate locally.
    The bad instruction makes confidence a string so Pydantic rejects it reliably.
    """

    completion = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": (
                    f"{question}\n\n"
                    "Reply with ONLY a JSON object using keys answer, confidence, sources_needed. "
                    "Set confidence to the string 'very high' (not a number)."
                ),
            }
        ],
    )

    raw = completion.choices[0].message.content or ""
    # Guardrail: refuse malformed output instead of passing it through to clients.
    answer = Answer.model_validate_json(raw)

    usage = completion.usage
    total = usage.total_tokens if usage else 0
    prompt_tokens = usage.prompt_tokens if usage else 0
    completion_tokens = usage.completion_tokens if usage else 0
    return answer, total, prompt_tokens, completion_tokens

# --------------------------------------------------
# 8.1 EXISTING POST /ask
# --------------------------------------------------

@app.post("/ask")
def ask(body: AskRequest) -> AskResponse:
    """Answer one question with structured output, guardrails, and cost visibility."""

    model = body.model or DEFAULT_MODEL
    last_error: str | None = None


    retrieved_chunks = retrieve_chunks(question=body.question,top_k=5,)
    context = build_rag_context(retrieved_chunks)

    grounding_prompt = build_grounding_prompt(question=body.question,context=context,)

    retrieved_chunk_ids = [
        chunk["id"]
        for chunk in retrieved_chunks ]


    # Stage 3: one retry keeps the logic legible while still protecting callers.
    for attempt in range(2):
        try:
            start = time.perf_counter()

            # First attempt with force_bad uses the unsafe path; retry uses structured output.
            use_bad_path = body.force_bad and attempt == 0
            if use_bad_path:
                answer, tokens_used, prompt_tokens, completion_tokens = call_model_unsafe(
                    grounding_prompt, model
                )
            else:
                answer, tokens_used, prompt_tokens, completion_tokens = call_model_structured(
                    grounding_prompt, model
                )

            latency_ms = int((time.perf_counter() - start) * 1000)
            cost_usd = compute_cost_usd(model, prompt_tokens, completion_tokens)

            return AskResponse(
                answer=answer,
                tokens_used=tokens_used,
                model=model,
                latency_ms=latency_ms,
                cost_usd=round(cost_usd, 6),
                # NEW WEEK 2
                retrieved_chunk_ids=(retrieved_chunk_ids),
            )

        except (ValidationError, ValueError) as exc:
            last_error = str(exc)
            continue

    # Clean failure — never leak a half-parsed response to the client.
    raise HTTPException(
        status_code=502,
        detail=f"Model response failed schema validation after retry: {last_error}",
    )


# --------------------------------------------------
# 8.2 GET /health/pinecone/db
# --------------------------------------------------

@app.get("/health/pinecone")
def pinecone_health():
    stats = pinecone_index.describe_index_stats()

    return {
        "status": "ok",
        "index": PINECONE_INDEX_NAME,
        "dimension": stats.dimension,
        "total_vector_count": stats.total_vector_count,
    }


@app.get("/health/db")
def db_health():
    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1;")
                result = cursor.fetchone()

        return {
            "status": "ok",
            "database": "postgres",
            "test_query": result[0],}

    except Exception as exc:
        raise HTTPException(status_code=500,detail=f"Database connection failed: {str(exc)}",)


# --------------------------------------------------
# 8.3 POST /ingest
# --------------------------------------------------

@app.post("/ingest")
def ingest(body: IngestRequest):

    # 1. Validate
    if not body.text.strip():
        raise HTTPException(
            status_code=400,
            detail="Text cannot be empty.",
        )

    if not body.document_id.strip():
        raise HTTPException(
            status_code=400,
            detail="document_id cannot be empty.",
        )

    try:

        # 2. Metadata
        source = body.source or "Unknown"

        metadata = extract_metadata(
            body.text,
            source, )

        # API document_id is source of truth
        metadata["document_id"] = body.document_id

        # 3. Chunk
        chunks = chunk_text(
            body.text)

        # 4. Prepare text for embedding
        embedding_texts = build_embedding_texts(
            chunks,
            metadata,  )


        # 5. Embed
        text_embeddings = embed_chunks(
            embedding_texts)


        # 6. Build Pinecone vectors
        vectors = build_vectors(
        chunks,
        embedding_texts,
        text_embeddings,
        metadata,
        )


        # 7. Persist to Pinecone
        upsert_vectors(
            vectors)

        return {
            "document_id": body.document_id,
            "chunks_indexed": len(vectors),
            "status": "indexed",
        }

    except ValueError as exc:

        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=f"Ingestion failed: {str(exc)}",
        )


# --------------------------------------------------
# 8.3 GETT /debug/retrieve
# --------------------------------------------------


@app.get("/debug/retrieve",response_model=list[RetrievedChunk],)
def debug_retrieve(question: str,top_k: int = 5,):

    return retrieve_chunks(
        question=question,
        top_k=top_k,)





# --------------------------------------------------
# 8.3 GETT /DB Tool
# --------------------------------------------------


@app.get("/products/{sku}")
def product_by_sku(sku: str):
    result = get_product_data(sku)

    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"SKU {sku} not found"
        )

    return result


@app.get("/forecast/{sku}")
def forecast_by_sku(sku: str):
    return get_forecast(sku)


@app.get("/sales/{sku}")
def sales_by_sku(sku: str):
    return get_sales_history(sku)


@app.get("/purchase-orders/{sku}")
def purchase_orders_by_sku(sku: str):
    return get_open_pos(sku)


@app.get("/suppliers/{supplier_id}")
def supplier_by_id(supplier_id: str):
    result = get_supplier_data(supplier_id)

    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Supplier {supplier_id} not found"
        )

    return result



