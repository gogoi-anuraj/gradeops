"""
Course-scoped vector storage for uploaded reference material. Each course
gets its own ChromaDB collection, so Course A's material is never retrieved
while grading Course B's answers.

Uses a SEPARATE persistent path from Phase 1's retrieval/chroma_db (which
holds the original demo course's data) -- keeps course-uploaded data cleanly
separate from the fixed demo dataset used during development.
"""

import os
import chromadb

CHROMA_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "course_vector_store")

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
    return _client


def _collection_name(course_id: int) -> str:
    return f"course_{course_id}_reference"


def get_course_collection(course_id: int):
    client = _get_client()
    return client.get_or_create_collection(name=_collection_name(course_id))


def store_chunks(course_id: int, chunks: list[dict], embed_model):
    """Embed and store chunks for a course. Uses upsert (not add) so
    re-uploading the same file replaces its old chunks by matching chunk_id,
    rather than erroring on duplicate IDs or leaving stale duplicates."""
    if not chunks:
        return

    collection = get_course_collection(course_id)
    texts = [c["text"] for c in chunks]
    embeddings = embed_model.encode(texts, normalize_embeddings=True).tolist()

    collection.upsert(
        ids=[c["chunk_id"] for c in chunks],
        embeddings=embeddings,
        documents=texts,
        metadatas=[
            {
                "source_file": c["source_file"],
                "chapter_title": c["chapter_title"],
                "section": c["section"],
                "word_count": c["word_count"],
            }
            for c in chunks
        ],
    )


def query_course_collection(course_id: int, query_text: str, embed_model, k: int = 3):
    """Retrieve the top-k most relevant chunks for a course, given a query
    string. Used by the grading agent (Stage 6) once wired in."""
    collection = get_course_collection(course_id)
    if collection.count() == 0:
        return []

    query_embedding = embed_model.encode([query_text], normalize_embeddings=True).tolist()
    results = collection.query(query_embeddings=query_embedding, n_results=min(k, collection.count()))

    chunks = []
    for chunk_id, doc, meta, dist in zip(
        results["ids"][0], results["documents"][0],
        results["metadatas"][0], results["distances"][0]
    ):
        chunks.append({
            "chunk_id": chunk_id,
            "text": doc,
            "section": meta["section"],
            "similarity": 1 - dist,
        })
    return chunks