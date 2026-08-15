

from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from openai import OpenAI
from dotenv import load_dotenv
from pathlib import Path
import os

import re
from pathlib import Path
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from dotenv import load_dotenv
from pathlib import Path
import re

import random


# --------------------------------------------------
# 1. LOAD ENVIRONMENT
# --------------------------------------------------

ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(ENV_PATH)

docs_folder = Path("northwind-sample-docs")


# --------------------------------------------------
# 2. EMBEDDING MODEL
# --------------------------------------------------

embeddings = OpenAIEmbeddings(
    model="text-embedding-3-small",
    dimensions=512,
)



# --------------------------------------------------
# 3. EXTRACT DOCUMENT-LEVEL METADATA
# --------------------------------------------------

def extract_metadata(text: str, source: str) -> dict:

    lines = text.splitlines()

    # First non-empty line = document title
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
        "Related": "related"
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


# --------------------------------------------------
# 4. PROCESS ONE DOCUMENT
# --------------------------------------------------

def process_document(file_path: Path) -> tuple[dict, list[str]]:

    # Read entire document
    text = file_path.read_text()

    # Filename becomes source metadata
    source = file_path.name

    # Extract metadata for this document
    metadata = extract_metadata(text, source)

    # Create chunks
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=800,
        chunk_overlap=100,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    chunks = splitter.split_text(text)
    
    random_chunk = random.choice(chunks)


    return metadata, chunks


# --------------------------------------------------
# 5. PROCESS THE WHOLE FOLDER
# --------------------------------------------------

vectors = []

for file_path in docs_folder.glob("*.txt"):

    # One document
    metadata, chunks = process_document(file_path)

    document_id = metadata["document_id"]

    if document_id == "Unknown":
        print(f"Skipping {file_path.name}: no Document ID")
        continue


    # --------------------------------------------------
    # 6. BUILD TEXT USED FOR EMBEDDINGS
    # --------------------------------------------------

    embedding_texts = []

    for chunk in chunks:

        embedding_text = (
            f"Title: {metadata['title']}\n"
            f"Document ID: {metadata['document_id']}\n"
            f"{chunk}"
)

        embedding_texts.append(embedding_text)

    # --------------------------------------------------
    # 7. EMBED ALL CHUNKS FOR THIS DOCUMENT
    # --------------------------------------------------

    text_embeddings = embeddings.embed_documents(
        embedding_texts
    )

    print("Embeddings:", len(text_embeddings))

    # --------------------------------------------------
    # 8. CREATE PINECONE RECORDS
    # --------------------------------------------------

    for i, (chunk, embedding) in enumerate(
        zip(chunks, text_embeddings)
    ):

        vector = {
            # Unique Pinecone ID for THIS chunk
            "id": f"{document_id}-{i}",

            # 512-number embedding
            "values": embedding,

            # Information stored alongside the vector
            "metadata": {
                **metadata,
                "chunk_index": i,
                "text": chunk,
            },
        }

        vectors.append(vector)


# --------------------------------------------------
# 9. VERIFY BEFORE WRITING TO PINECONE
# --------------------------------------------------

print("\n================================")
print("TOTAL VECTORS PREPARED:", len(vectors))

if vectors:
    print("\nExample vector:")
    print("ID:", vectors[0]["id"])
    print("Dimensions:", len(vectors[0]["values"]))
    print("Metadata:", vectors[0]["metadata"])