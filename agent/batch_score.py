"""
Batch version of score_single_example.py — runs grading on ALL transcribed
answers (all question types, all variants), not just one. Use this to check
whether the agent handles numeric/arithmetic questions (Q2, Q4) as well as
it handles conceptual ones (Q1, Q3), before formalizing into LangGraph.

"""

import os
import json
import time
from dotenv import load_dotenv
from groq import Groq
import chromadb
from sentence_transformers import SentenceTransformer

load_dotenv()

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RETRIEVAL_DIR = os.path.join(SCRIPT_DIR, "..", "retrieval")
RUBRIC_PATH = os.path.join(SCRIPT_DIR, "..", "rubric", "rubric.json")
TRANSCRIPTIONS_PATH = os.path.join(SCRIPT_DIR, "..", "vision", "transcriptions.json")
PROMPT_PATH = os.path.join(SCRIPT_DIR, "prompts", "grading_prompt.md")
OUTPUT_PATH = os.path.join(SCRIPT_DIR, "batch_grading_results.json")

EMBEDDING_MODEL = "all-MiniLM-L6-v2"
CHROMA_DB_PATH = os.path.join(RETRIEVAL_DIR, "chroma_db")
COLLECTION_NAME = f"gradeops_reference_{EMBEDDING_MODEL.replace('/', '_').replace('-', '_')}"
TOP_K = 3

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")


def load_json(path):
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Not found: {os.path.abspath(path)}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_system_prompt(prompt_md_path):
    with open(prompt_md_path, "r", encoding="utf-8") as f:
        content = f.read()
    marker = "---"
    idx = content.find(marker)
    return content[idx + len(marker):].strip() if idx != -1 else content


def retrieve_context(query_text, embed_model, collection, k=TOP_K):
    query_embedding = embed_model.encode([query_text], normalize_embeddings=True).tolist()
    results = collection.query(query_embeddings=query_embedding, n_results=k)
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


def build_user_message(question, criteria, retrieved_chunks, student_answer):
    criteria_text = "\n".join(
        f"- {c['criterion_id']}: {c['description']} (max {c['marks']} marks)"
        for c in criteria
    )
    chunks_text = "\n\n".join(
        f"[{c['chunk_id']}] (similarity: {c['similarity']:.3f})\n{c['text']}"
        for c in retrieved_chunks
    )
    return f"""QUESTION: {question}

RUBRIC CRITERIA:
{criteria_text}

RETRIEVED REFERENCE MATERIAL:
{chunks_text}

STUDENT'S TRANSCRIBED ANSWER:
{student_answer}

Grade this answer according to the rubric criteria above. Output only the JSON."""


def main():
    if not GROQ_API_KEY:
        raise EnvironmentError("GROQ_API_KEY not set. Add it to your .env file.")

    rubric = load_json(RUBRIC_PATH)
    transcriptions = load_json(TRANSCRIPTIONS_PATH)
    system_prompt = extract_system_prompt(PROMPT_PATH)
    questions_by_id = {q["question_id"]: q for q in rubric["questions"]}

    print("Loading embedding model + connecting to ChromaDB...")
    embed_model = SentenceTransformer(EMBEDDING_MODEL)
    client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
    collection = client.get_collection(COLLECTION_NAME)
    groq_client = Groq(api_key=GROQ_API_KEY)

    results = []
    for i, entry in enumerate(transcriptions, 1):
        filename = entry["filename"]
        question_id = entry["question_id"]
        student_answer = entry["transcription"]

        if question_id not in questions_by_id or student_answer is None:
            print(f"[{i}/{len(transcriptions)}] Skipping {filename} (no rubric or failed transcription)")
            continue

        question_data = questions_by_id[question_id]
        print(f"[{i}/{len(transcriptions)}] Grading {filename}...")

        retrieval_query = f"{question_data['prompt']}\n\nStudent's answer: {student_answer}"
        retrieved_chunks = retrieve_context(retrieval_query, embed_model, collection)
        top_similarity = retrieved_chunks[0]["similarity"] if retrieved_chunks else 0.0

        user_message = build_user_message(
            question_data["prompt"], question_data["criteria"], retrieved_chunks, student_answer
        )

        try:
            response = groq_client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                temperature=0,
                response_format={"type": "json_object"},
            )
            grading_result = json.loads(response.choices[0].message.content)
            status = "success"
        except Exception as e:
            grading_result = None
            status = f"error: {e}"
            print(f"  FAILED: {e}")

        results.append({
            "filename": filename,
            "question_id": question_id,
            "variant": entry.get("variant"),
            "top_retrieval_similarity": top_similarity,
            "retrieved_chunk_ids": [c["chunk_id"] for c in retrieved_chunks],
            "grading_result": grading_result,
            "status": status,
        })

        time.sleep(2)  # be polite to the free-tier rate limit

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\n{'='*80}")
    print(f"{'File':<20} {'Score':<10} {'Confidence':<12} Status")
    print(f"{'='*80}")
    for r in results:
        if r["grading_result"]:
            score = f"{r['grading_result']['total_score']}/{r['grading_result']['total_max']}"
        else:
            score = "N/A"
        print(f"{r['filename']:<20} {score:<10} {r['top_retrieval_similarity']:<12.3f} {r['status']}")

    print(f"\nSaved full results to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()