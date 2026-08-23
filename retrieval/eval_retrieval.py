"""
Evaluate retrieval quality: Recall@k and MRR (Mean Reciprocal Rank) against
the hand-labeled (question -> correct chunk_id) pairs in retrieval_labels.json.

Run this after embed_and_store.py has populated the collection.

Usage:
    python eval_retrieval.py
"""

import json
import os
import chromadb
from sentence_transformers import SentenceTransformer

EMBEDDING_MODEL = "all-MiniLM-L6-v2"  # must match embed_and_store.py
COLLECTION_NAME = f"gradeops_reference_{EMBEDDING_MODEL.replace('/', '_').replace('-', '_')}"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CHROMA_DB_PATH = os.path.join(SCRIPT_DIR, "chroma_db")
LABELS_PATH = os.path.join(SCRIPT_DIR, "eval", "retrieval_labels.json")

K_VALUES = [1, 3, 5]


def recall_at_k(retrieved_ids, correct_ids, k):
    top_k = set(retrieved_ids[:k])
    return 1.0 if top_k & set(correct_ids) else 0.0


def reciprocal_rank(retrieved_ids, correct_ids):
    for rank, rid in enumerate(retrieved_ids, 1):
        if rid in correct_ids:
            return 1.0 / rank
    return 0.0


def main():
    if not os.path.isfile(LABELS_PATH):
        raise FileNotFoundError(
            f"Labels file not found at: {LABELS_PATH}\n"
            f"Expected it at retrieval/eval/retrieval_labels.json"
        )

    with open(LABELS_PATH, "r", encoding="utf-8") as f:
        labels = json.load(f)

    model = SentenceTransformer(EMBEDDING_MODEL)
    client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
    collection = client.get_collection(COLLECTION_NAME)

    max_k = max(K_VALUES)
    recall_scores = {k: [] for k in K_VALUES}
    rr_scores = []

    print(f"Evaluating {len(labels)} labeled questions against '{COLLECTION_NAME}'\n")
    print(f"{'Question ID':<8} {'Recall@1':<10} {'Recall@3':<10} {'Recall@5':<10} {'RR':<8} Top match")
    print("-" * 90)

    for item in labels:
        query = item["question"]
        correct_ids = item["correct_chunk_ids"]

        query_embedding = model.encode([query], normalize_embeddings=True).tolist()
        results = collection.query(query_embeddings=query_embedding, n_results=max_k)
        retrieved_ids = results["ids"][0]

        row = [item["question_id"]]
        for k in K_VALUES:
            score = recall_at_k(retrieved_ids, correct_ids, k)
            recall_scores[k].append(score)
            row.append(f"{score:.0f}")

        rr = reciprocal_rank(retrieved_ids, correct_ids)
        rr_scores.append(rr)

        top_match = retrieved_ids[0] if retrieved_ids else "N/A"
        hit_marker = "✓" if top_match in correct_ids else " "
        print(f"{item['question_id']:<8} {row[1]:<10} {row[2]:<10} {row[3]:<10} {rr:<8.2f} {hit_marker} {top_match}")

    print("-" * 90)
    print("\n=== SUMMARY ===")
    for k in K_VALUES:
        avg = sum(recall_scores[k]) / len(recall_scores[k])
        print(f"Recall@{k}: {avg:.3f}  ({sum(recall_scores[k]):.0f}/{len(recall_scores[k])} questions)")
    mrr = sum(rr_scores) / len(rr_scores)
    print(f"MRR:       {mrr:.3f}")
    print(f"\nEmbedding model: {EMBEDDING_MODEL}")


if __name__ == "__main__":
    main()