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



## --------------------------------------------------
# 1. LOAD ENVIRONMENT
# --------------------------------------------------

_ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(_ENV_PATH)


PINECONE_INDEX_NAME = os.getenv(
    "PINECONE_INDEX_NAME",
    "week2-rag",
)

EMBEDDING_MODEL = os.getenv(
    "EMBEDDING_MODEL",
    "text-embedding-3-small",
)

EMBEDDING_DIMENSIONS = int(
    os.getenv("EMBEDDING_DIMENSIONS", "512")
)

CHUNK_SIZE = int(
    os.getenv("CHUNK_SIZE", "800")
)

CHUNK_OVERLAP = int(
    os.getenv("CHUNK_OVERLAP", "100")
)

# --------------------------------------------------
# 2. CREATE CLIENTS
# --------------------------------------------------

app = FastAPI()

# Existing OpenAI client used by /ask
client = OpenAI()

# Pinecone connection
pinecone = Pinecone()
pinecone_index = pinecone.Index(PINECONE_INDEX_NAME)


# --------------------------------------------------
# 3. EMBEDIN MODEL
# --------------------------------------------------

# Embedding client
embeddings = OpenAIEmbeddings(
    model=EMBEDDING_MODEL,
    dimensions=EMBEDDING_DIMENSIONS,
)

# --------------------------------------------------
# 4. TEXT SPLITTER
# --------------------------------------------------

splitter = RecursiveCharacterTextSplitter(
    chunk_size=CHUNK_SIZE,
    chunk_overlap=CHUNK_OVERLAP,
    separators=["\n\n", "\n", ". ", " ", ""],
)

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
# 7.2. NEW HELPERS WEEK 2
# --------------------------------------------------

def extract_metadata(text: str, source: str) -> dict:

    lines = text.splitlines()

    # First non-empty line = title
    title = next(
        (line.strip() for line in lines if line.strip()),
        "Unknown"
    )

    fields = {
        "Author": "author",
        "Document ID": "document_id",
        "Effective date": "effective_date",
        "Last review": "last_review",
        "Next review": "next_review",
        "Classification": "classification",
        "Owner": "owner",
        "Approver": "approver",
        "Related": "related",
    }

    metadata = {
        "title": title,
        "source": source,
    }

    for label, key in fields.items():

        match = re.search(
            rf"^{re.escape(label)}:\s*(.+)$",
            text,
            re.MULTILINE,
        )

        metadata[key] = (
            match.group(1).strip()
            if match
            else "Unknown"
        )

    return metadata

def chunk_text(text: str) -> list[str]:

    chunks = splitter.split_text(text)

    if not chunks:
        raise ValueError("No chunks could be created.")

    return chunks

def build_embedding_texts(
    chunks: list[str],
    metadata: dict,
) -> list[str]:

    embedding_texts = []

    for chunk in chunks:

        embedding_text = (
            f"Title: {metadata['title']}\n"
            f"Document ID: {metadata['document_id']}\n"
            f"{chunk}"
        )

        embedding_texts.append(embedding_text)

    return embedding_texts

def embed_chunks(
    embedding_texts: list[str],
) -> list[list[float]]:

    return embeddings.embed_documents(
        embedding_texts
    )

def build_vectors(
    chunks: list[str],
    embedding_texts: list[str],
    text_embeddings: list[list[float]],
    metadata: dict,) -> list[dict]:

    vectors = []

    document_id = metadata["document_id"]

    for i, (chunk, embedding_text, embedding) in enumerate(
        zip(chunks, embedding_texts, text_embeddings)
    ):

        vector = {
            "id": f"{document_id}-{i}",

            "values": embedding,

            "metadata": {
                **metadata,
                "chunk_index": i,
                "chunk_text": chunk,
                "embedding_text": embedding_text,
            },
        }

        vectors.append(vector)

    return vectors

def upsert_vectors(vectors: list[dict]) -> None:

    pinecone_index.upsert(
        vectors=vectors
    )



# RAG function

def retrieve_chunks(question: str,top_k: int = 5,) -> list[dict]:

    # 1. Embed the user's question
    query_embedding = embeddings.embed_query(question) # Dimension 512 and model defined before

    # 2. Search Pinecone
    results = pinecone_index.query(
        vector=query_embedding,
        top_k=top_k,
        include_metadata=True,
    )

    chunks = []

    # 3. Extract each result + all stored metadata
    for match in results.matches:

        metadata = match.metadata or {}

        chunks.append(
            {
                "id": match.id,
                "score": match.score,
                "chunk_index": metadata.get("chunk_index", -1),

                # Original document chunk
                "chunk_text": metadata.get("chunk_text","",),

                # EXACT string that generated the stored vector
                "embedding_text": metadata.get("embedding_text","",),
                "title": metadata.get("title", "Unknown"),
                "author": metadata.get("author", "Unknown"),
                "document_id": metadata.get("document_id", "Unknown"),
                "effective_date": metadata.get("effective_date", "Unknown"),
                "last_review": metadata.get("last_review", "Unknown"),
                "next_review": metadata.get("next_review", "Unknown"),
                "classification": metadata.get("classification", "Unknown"),
                "owner": metadata.get("owner", "Unknown"),
                "approver": metadata.get("approver", "Unknown"),
                "related": metadata.get("related", "Unknown"),

                "source": metadata.get("source", "Unknown"),
            }
        )

    return chunks





def build_rag_context(retrieved_chunks: list[dict]) -> str:

    context_parts = []

    for chunk in retrieved_chunks:

        context_parts.append(
            f"Chunk ID: {chunk['id']}\n"
            f"Document ID: {chunk['document_id']}\n"
            f"{chunk['chunk_text']}"
        )

    return "\n\n---\n\n".join(context_parts)

def build_grounding_prompt(
    question: str,
    context: str,) -> str:

    return f"""
    Answer using ONLY the context below.

    If the context does not contain the answer, say:
    "I don't have enough information to answer that."

    Cite the document_id of each chunk you used.

    Context:
    {context}

    Question:
    {question}
    """

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
# 8.2 GET /health/pinecone
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