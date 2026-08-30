
import os
import json
import time

from graph import build_graph, run_on_example, get_transcriptions

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_PATH = os.path.join(SCRIPT_DIR, "agent_batch_results.json")


def main():
    transcriptions = get_transcriptions()
    filenames = [t["filename"] for t in transcriptions if t.get("transcription")]

    print(f"Running full agent graph on {len(filenames)} examples...\n")
    graph = build_graph()

    results = []
    self_check_corrections = 0

    for i, filename in enumerate(filenames, 1):
        print(f"[{i}/{len(filenames)}] {filename}...")
        try:
            state = run_on_example(graph, filename)

            initial_total = state["initial_grading"]["total_score"] if state["initial_grading"] else None
            final_total = state["final_grading"]["total_score"] if state["final_grading"] else None
            was_corrected = (initial_total != final_total) if (initial_total is not None and final_total is not None) else None

            # Also check if any individual citation or justification changed,
            # even if the total score didn't (like the Q1_variantA case)
            citation_changed = False
            if state["initial_grading"] and state["final_grading"]:
                initial_cites = {c["criterion_id"]: c.get("cited_chunk_id") for c in state["initial_grading"]["criteria_scores"]}
                final_cites = {c["criterion_id"]: c.get("cited_chunk_id") for c in state["final_grading"]["criteria_scores"]}
                citation_changed = initial_cites != final_cites

            if was_corrected or citation_changed:
                self_check_corrections += 1

            results.append({
                "filename": filename,
                "question_id": state["question_id"],
                "initial_score": f"{initial_total}/{state['initial_grading']['total_max']}" if state["initial_grading"] else None,
                "final_score": f"{final_total}/{state['final_grading']['total_max']}" if state["final_grading"] else None,
                "score_changed_by_self_check": was_corrected,
                "citation_changed_by_self_check": citation_changed,
                "self_check_notes": state["final_grading"].get("self_check_notes") if state["final_grading"] else None,
                "self_reported_confidence": state["final_grading"].get("self_reported_confidence") if state["final_grading"] else None,
                "top_retrieval_similarity": state["top_similarity"],
                "flagged_for_review": state["flagged_for_review"],
                "flag_reason": state["flag_reason"],
                "full_final_grading": state["final_grading"],
            })
        except Exception as e:
            print(f"  FAILED: {e}")
            results.append({"filename": filename, "error": str(e)})

        time.sleep(5)  # be polite to the free-tier TPM limit (2 LLM calls per example)

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\n{'='*100}")
    print(f"{'File':<20} {'Initial':<10} {'Final':<10} {'Changed?':<10} {'Confidence':<12} {'Flagged?'}")
    print(f"{'='*100}")
    for r in results:
        if "error" in r:
            print(f"{r['filename']:<20} ERROR: {r['error']}")
            continue
        changed = "yes" if (r["score_changed_by_self_check"] or r["citation_changed_by_self_check"]) else "no"
        print(f"{r['filename']:<20} {r['initial_score']:<10} {r['final_score']:<10} {changed:<10} "
              f"{str(r['self_reported_confidence']):<12} {r['flagged_for_review']}")

    print(f"\nSelf-check made a correction (score or citation) in {self_check_corrections}/{len(filenames)} cases.")
    flagged_count = sum(1 for r in results if r.get("flagged_for_review"))
    print(f"Flagged for human review: {flagged_count}/{len(filenames)} cases.")
    print(f"\nFull results saved to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()