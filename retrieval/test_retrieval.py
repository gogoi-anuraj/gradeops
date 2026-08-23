"""
Sanity-check retrieval: run a few manual queries against the populated
ChromaDB collection and print the top-k results, so you can eyeball whether
retrieval is actually returning relevant chunks before moving on.

Run this after embed_and_store.py.

Usage:
    python test_retrieval.py
"""

import os
import chromadb
from sentence_transformers import SentenceTransformer

EMBEDDING_MODEL = "all-MiniLM-L6-v2"  # must match what you used in embed_and_store.py
COLLECTION_NAME = f"gradeops_reference_{EMBEDDING_MODEL.replace('/', '_').replace('-', '_')}"

# Resolve relative to this script's own location (same fix as the other
# scripts) so it works no matter what working directory it's launched from.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CHROMA_DB_PATH = os.path.join(SCRIPT_DIR, "chroma_db")

TOP_K = 3

# One test query per rubric question — check these return sensible chunks
TEST_QUERIES = [
    "Newton's first law and inertial reference frame",
    "block accelerating under an applied force on a frictionless surface",
    "Newton's third law action reaction pair swimmer pushing off wall",
    "friction force coefficient of kinetic friction box pulled by rope",
]


def main():
    model = SentenceTransformer(EMBEDDING_MODEL)

    if not os.path.isdir(CHROMA_DB_PATH):
        raise FileNotFoundError(
            f"chroma_db folder not found at: {CHROMA_DB_PATH}\n"
            f"Run embed_and_store.py first (from this same retrieval/ folder) "
            f"to create and populate it."
        )

    client = chromadb.PersistentClient(path=CHROMA_DB_PATH)

    try:
        collection = client.get_collection(COLLECTION_NAME)
    except Exception as e:
        available = [c.name for c in client.list_collections()]
        raise RuntimeError(
            f"Collection '{COLLECTION_NAME}' not found in {CHROMA_DB_PATH}.\n"
            f"Collections that DO exist there: {available}\n"
            f"Make sure EMBEDDING_MODEL here matches what embed_and_store.py used."
        ) from e

    print(f"Collection '{COLLECTION_NAME}' has {collection.count()} chunks\n")

    for query in TEST_QUERIES:
        print(f"QUERY: {query}")
        print("-" * 70)
        query_embedding = model.encode([query], normalize_embeddings=True).tolist()
        results = collection.query(query_embeddings=query_embedding, n_results=TOP_K)

        for rank, (chunk_id, doc, meta, dist) in enumerate(zip(
            results["ids"][0], results["documents"][0],
            results["metadatas"][0], results["distances"][0]
        ), 1):
            similarity = 1 - dist  # cosine distance -> similarity
            print(f"  [{rank}] {chunk_id} (similarity: {similarity:.3f})")
            print(f"      section: {meta['section']}")
            print(f"      preview: {doc[:120].strip()}...")
        print()


if __name__ == "__main__":
    main()