import sys
import os
import json

BACKEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend")
sys.path.insert(0, BACKEND_DIR)
import vector_store  # noqa: E402
from sentence_transformers import SentenceTransformer  # noqa: E402

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LABELS_PATH = os.path.join(SCRIPT_DIR, "..", "retrieval", "eval", "retrieval_labels.json")

EMBEDDING_MODEL = "all-MiniLM-L6-v2"  # must match what was used to embed the course's materials
K_VALUES = [1, 3, 5]


def recall_at_k(retrieved_ids, correct_ids, k):
    top_k = set(retrieved_ids[:k])
    return 1.0 if top_k & set(correct_ids) else 0.0


def reciprocal_rank(retrieved_ids, correct_ids):
    for rank, rid in enumerate(retrieved_ids, 1):
        if rid in correct_ids:
            return 1.0 / rank
    return 0.0


def get_available_chunk_ids(collection):
    """Returns the set of chunk_ids actually stored in this collection, so we
    can tell apart 'retrieval failed to find the right chunk' from 'the right
    chunk was never uploaded in the first place' -- very different things,
    and only the former should count against the retrieval score."""
    all_items = collection.get(include=[])  # ids are always included by default
    return set(all_items["ids"])


def main():
    if len(sys.argv) < 2:
        print("Usage: python eval_retrieval_course.py <course_id>")
        sys.exit(1)
    course_id = int(sys.argv[1])

    if not os.path.isfile(LABELS_PATH):
        raise FileNotFoundError(f"Labels file not found at: {LABELS_PATH}")
    with open(LABELS_PATH, "r", encoding="utf-8") as f:
        labels = json.load(f)

    collection = vector_store.get_course_collection(course_id)
    chunk_count = collection.count()
    if chunk_count == 0:
        raise RuntimeError(
            f"Course {course_id}'s vector collection is empty. "
            f"Upload reference material to this course before running this eval."
        )
    available_chunk_ids = get_available_chunk_ids(collection)
    print(f"Evaluating against course {course_id}'s collection ({chunk_count} chunks)\n")

    model = SentenceTransformer(EMBEDDING_MODEL)

    max_k = max(K_VALUES)
    recall_scores = {k: [] for k in K_VALUES}
    rr_scores = []
    skipped = []  # labels whose correct chunk(s) aren't in this course at all

    print(f"{'Question ID':<8} {'Recall@1':<10} {'Recall@3':<10} {'Recall@5':<10} {'RR':<8} Top match")
    print("-" * 90)

    for item in labels:
        correct_ids = item["correct_chunk_ids"]

        # Skip labels entirely unrelated to what's actually in this course --
        # scoring these would penalize the course for content it was never
        # given, not for a real retrieval failure.
        if not (set(correct_ids) & available_chunk_ids):
            skipped.append(item["question_id"])
            print(f"{item['question_id']:<8} {'SKIP':<10} {'SKIP':<10} {'SKIP':<10} {'--':<8} (target chunk not in this course's material)")
            continue

        chunks = vector_store.query_course_collection(course_id, item["question"], model, k=max_k)
        retrieved_ids = [c["chunk_id"] for c in chunks]

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
    print("\n=== SUMMARY (fair comparison -- only questions covered by this course's uploaded material) ===")
    if not recall_scores[K_VALUES[0]]:
        print("No labeled questions matched this course's material -- upload more chapters, or use a course-specific label set.")
    else:
        for k in K_VALUES:
            avg = sum(recall_scores[k]) / len(recall_scores[k])
            print(f"Recall@{k}: {avg:.3f}  ({sum(recall_scores[k]):.0f}/{len(recall_scores[k])} applicable questions)")
        mrr = sum(rr_scores) / len(rr_scores)
        print(f"MRR:       {mrr:.3f}")

    print(f"\nApplicable: {len(recall_scores[K_VALUES[0]])} | Skipped (not in this course): {len(skipped)} | "
          f"Total labels: {len(labels)}")
    if skipped:
        print(f"Skipped question IDs: {', '.join(skipped)}")
    print(f"Course: {course_id} | Chunks in collection: {chunk_count} | Embedding model: {EMBEDDING_MODEL}")


if __name__ == "__main__":
    main()