"""RAG tools for NovaTech policy retrieval and document ingestion."""

import os
import re
from pathlib import Path

from dotenv import load_dotenv
from pinecone import Pinecone
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings


# 1. LOAD ENVIRONMENT

_ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(_ENV_PATH)

PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME","week2-rag",)

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL","text-embedding-3-small",)

EMBEDDING_DIMENSIONS = int(os.getenv("EMBEDDING_DIMENSIONS", "512"))

CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "800"))

CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "100"))


# 2. CREATE RAG CLIENTS

pinecone = Pinecone()

pinecone_index = pinecone.Index(PINECONE_INDEX_NAME)

embeddings = OpenAIEmbeddings(model=EMBEDDING_MODEL,dimensions=EMBEDDING_DIMENSIONS,)


# 3. TEXT SPLITTER

splitter = RecursiveCharacterTextSplitter(chunk_size=CHUNK_SIZE,chunk_overlap=CHUNK_OVERLAP,separators=["\n\n","\n",". "," ","",],)



# 4. INGESTION HELPERS

def extract_metadata(text: str, source: str) -> dict:
    """Extract NovaTech document metadata from document text."""

    lines = text.splitlines()

    title = next(
        (line.strip()
            for line in lines
            if line.strip()),"Unknown",)

    fields = {
        "Author": "author",
        "Document ID": "document_id",
        "Effective date": "effective_date",
        "Last review": "last_review",
        "Next review": "next_review",
        "Classification": "classification",
        "Owner": "owner",
        "Approver": "approver",
        "Related": "related", }

    metadata = {"title": title,"source": source,}

    for label, key in fields.items():
        match = re.search(
            rf"^{re.escape(label)}:\s*(.+)$",text,re.MULTILINE,)
        metadata[key] = (
            match.group(1).strip()
            if match
            else "Unknown")

    return metadata


def chunk_text(text: str) -> list[str]:
    """Split a document into overlapping chunks."""

    chunks = splitter.split_text(text)

    if not chunks:
        raise ValueError("No chunks could be created.")

    return chunks


def build_embedding_texts(chunks: list[str],metadata: dict) -> list[str]:
    """
    Add useful document metadata to each chunk
    before embedding.
    """

    embedding_texts = []

    for chunk in chunks:
        embedding_text = (
            f"Title: {metadata['title']}\n"
            f"Document ID: {metadata['document_id']}\n"
            f"{chunk}" )

        embedding_texts.append(embedding_text)

    return embedding_texts


def embed_chunks(embedding_texts: list[str],) -> list[list[float]]:
    """Create embeddings for document chunks."""

    return embeddings.embed_documents(embedding_texts)


def build_vectors(chunks: list[str],embedding_texts: list[str],text_embeddings: list[list[float]],metadata: dict,) -> list[dict]:
    """Build Pinecone vectors with metadata."""

    vectors = []

    document_id = metadata["document_id"]

    for i, (chunk,embedding_text,embedding,) in enumerate(
        zip(chunks,embedding_texts,text_embeddings,)):
        vector = {
            "id": f"{document_id}-{i}",
            "values": embedding,
            "metadata": {
                **metadata,
                "chunk_index": i,
                "chunk_text": chunk,
                "embedding_text": embedding_text,
            },}

        vectors.append(vector)

    return vectors


def upsert_vectors(vectors: list[dict],) -> None:
    """Store vectors in Pinecone."""

    pinecone_index.upsert(vectors=vectors)


# 5. POLICY RETRIEVAL

def retrieve_chunks(question: str,top_k: int = 5,) -> list[dict]:
    """
    Retrieve the most relevant NovaTech policy
    chunks from Pinecone.
    """

    # Convert the question into an embedding.
    query_embedding = embeddings.embed_query(question)

    # Search Pinecone.
    results = pinecone_index.query(
        vector=query_embedding,
        top_k=top_k,
        include_metadata=True,)

    chunks = []

    for match in results.matches:
        metadata = match.metadata or {}

        chunks.append(
            {
                "id": match.id,
                "score": match.score,
                "chunk_index": metadata.get("chunk_index",-1,),
                "chunk_text": metadata.get("chunk_text","",),
                "embedding_text": metadata.get("embedding_text","",),
                "title": metadata.get("title","Unknown",),
                "author": metadata.get("author","Unknown",),
                "document_id": metadata.get("document_id","Unknown",),
                "effective_date": metadata.get("effective_date","Unknown",),
                "last_review": metadata.get("last_review","Unknown",),
                "next_review": metadata.get("next_review","Unknown",),
                "classification": metadata.get("classification","Unknown",),
                "owner": metadata.get("owner","Unknown",),
                "approver": metadata.get("approver","Unknown",),
                "related": metadata.get("related","Unknown",),
                "source": metadata.get("source","Unknown",),
            }
        )

    return chunks


# 6. RAG CONTEXT HELPERS

def build_rag_context(retrieved_chunks: list[dict],) -> str:
    """Convert retrieved chunks into LLM context."""

    context_parts = []

    for chunk in retrieved_chunks:
        context_parts.append(
            f"Chunk ID: {chunk['id']}\n"
            f"Document ID: {chunk['document_id']}\n"
            f"{chunk['chunk_text']}"
                )

    return "\n\n---\n\n".join(context_parts )


def build_grounding_prompt(question: str,context: str,) -> str:
    """Build the grounded Week 2 RAG prompt."""

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


# 7. ADK-FRIENDLY POLICY TOOL

def search_docs(query: str,) -> dict:
    """
    Search NovaTech planning policy documents.

    Use this tool when the user asks about NovaTech
    planning policy, business rules, WOS thresholds,
    replenishment rules, supplier constraints, or when
    a planning judgement or recommendation needs
    company-policy evidence.
    """

    try:
        chunks = retrieve_chunks(question=query,top_k=5,)

        if not chunks:
            return {
                "status": "error",
                "message": (
                    "No relevant NovaTech policy "
                    "documents were found." ),
                "results": [],
            }

        return {
            "status": "success",
            "results": chunks,
        }

    except Exception as exc:
        return {
            "status": "error",
            "message": (
                f"Policy retrieval failed: {str(exc)}"
            ),
            "results": [],
        }