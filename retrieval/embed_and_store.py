"""
Embed chunks.json and populate a persistent ChromaDB collection.

Run this locally (not in a constrained sandbox) since sentence-transformers
pulls in torch (~1-2GB depending on model).

Setup:
    pip install sentence-transformers chromadb

Usage:
    python embed_and_store.py

To switch embedding models later (e.g. MiniLM -> bge-large-en for your final
eval run), just change EMBEDDING_MODEL below and re-run. ChromaDB will store
each model's vectors in a separately named collection, so you can keep both
around and compare Recall@k / MRR between them later.
"""

import json
import os
import chromadb
from sentence_transformers import SentenceTransformer

# --- Config: change this one line to swap embedding models later ---
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
# EMBEDDING_MODEL = "BAAI/bge-large-en-v1.5"   # swap to this for final eval run

# Collection name includes the model name so multiple models can coexist
COLLECTION_NAME = f"gradeops_reference_{EMBEDDING_MODEL.replace('/', '_').replace('-', '_')}"

# Resolve paths relative to THIS script's location, not the current working
# directory — this way it works the same whether you run it from a terminal
# inside retrieval/, from the project root, or from an IDE's "Run" button
# (which often uses a different working directory than you'd expect).
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CHUNKS_PATH = os.path.join(SCRIPT_DIR, "chunks.json")
CHROMA_DB_PATH = os.path.join(SCRIPT_DIR, "chroma_db")


def main():
    print(f"Loading embedding model: {EMBEDDING_MODEL}")
    model = SentenceTransformer(EMBEDDING_MODEL)

    print(f"Loading chunks from {CHUNKS_PATH}")
    if not os.path.isfile(CHUNKS_PATH):
        raise FileNotFoundError(
            f"chunks.json not found at: {CHUNKS_PATH}\n"
            f"Run chunk_reference_material.py first (from the same retrieval/ "
            f"folder) to generate it."
        )
    with open(CHUNKS_PATH, "r", encoding="utf-8") as f:
        chunks = json.load(f)
    if not chunks:
        raise ValueError(
            f"chunks.json at {CHUNKS_PATH} is empty (0 chunks). "
            f"Re-run chunk_reference_material.py and check its output count."
        )
    print(f"Loaded {len(chunks)} chunks")

    # bge models expect a specific instruction prefix for best retrieval performance
    texts = [c["text"] for c in chunks]
    if "bge" in EMBEDDING_MODEL.lower():
        # bge recommends prefixing QUERIES (not documents) with an instruction;
        # documents are embedded as-is. Handled at query time separately.
        pass

    print("Computing embeddings...")
    embeddings = model.encode(texts, show_progress_bar=True, normalize_embeddings=True)

    print(f"Connecting to ChromaDB at {CHROMA_DB_PATH}")
    client = chromadb.PersistentClient(path=CHROMA_DB_PATH)

    # Fresh collection each run to avoid duplicate/stale entries during dev
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass
    collection = client.create_collection(
        name=COLLECTION_NAME,
        metadata={"embedding_model": EMBEDDING_MODEL},
    )

    ids = [c["chunk_id"] for c in chunks]
    metadatas = [
        {
            "source_file": c["source_file"],
            "chapter_title": c["chapter_title"],
            "section": c["section"],
            "word_count": c["word_count"],
        }
        for c in chunks
    ]

    print(f"Populating collection '{COLLECTION_NAME}'...")
    collection.add(
        ids=ids,
        embeddings=embeddings.tolist(),
        documents=texts,
        metadatas=metadatas,
    )

    print(f"Done. {collection.count()} chunks stored in ChromaDB.")
    print(f"\nCollection name: {COLLECTION_NAME}")
    print("Use this exact name when querying in the next script.")


if __name__ == "__main__":
    main()