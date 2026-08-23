"""
Test the core grading logic on ONE example before wrapping it in a full
LangGraph agent. This proves retrieval + LLM scoring work together correctly
on a real transcribed answer before adding more moving parts.
"""

import os
import json
import re
from dotenv import load_dotenv
from groq import Groq
import chromadb
from sentence_transformers import SentenceTransformer

load_dotenv()

# --- Config ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RETRIEVAL_DIR = os.path.join(SCRIPT_DIR, "..", "retrieval")
RUBRIC_PATH = os.path.join(SCRIPT_DIR, "..", "rubric", "rubric.json")
TRANSCRIPTIONS_PATH = os.path.join(SCRIPT_DIR, "..", "vision", "transcriptions.json")
PROMPT_PATH = os.path.join(SCRIPT_DIR, "prompts", "grading_prompt.md")

EMBEDDING_MODEL = "all-MiniLM-L6-v2"  # must match what retrieval/embed_and_store.py used
CHROMA_DB_PATH = os.path.join(RETRIEVAL_DIR, "chroma_db")
COLLECTION_NAME = f"gradeops_reference_{EMBEDDING_MODEL.replace('/', '_').replace('-', '_')}"
TOP_K = 3

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")

# --- Which example to test on ---
TEST_QUESTION_ID = "Q1"
TEST_FILENAME = "Q1_variantC.jpeg"


def load_json(path):
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Not found: {os.path.abspath(path)}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_system_prompt(prompt_md_path):
    """Pull just the prompt content out of grading_prompt.md, skipping the
    markdown explanation header at the top."""
    with open(prompt_md_path, "r", encoding="utf-8") as f:
        content = f.read()
    marker = "---"
    idx = content.find(marker)
    return content[idx + len(marker):].strip() if idx != -1 else content


def retrieve_context(question_text, embed_model, collection, k=TOP_K):
    query_embedding = embed_model.encode([question_text], normalize_embeddings=True).tolist()
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
        raise EnvironmentError(
            "GROQ_API_KEY not set. Add it to your .env file. "
        )

    print("Loading rubric, transcriptions, and prompt template...")
    rubric = load_json(RUBRIC_PATH)
    transcriptions = load_json(TRANSCRIPTIONS_PATH)
    system_prompt = extract_system_prompt(PROMPT_PATH)

    question_data = next(q for q in rubric["questions"] if q["question_id"] == TEST_QUESTION_ID)
    transcription_entry = next(t for t in transcriptions if t["filename"] == TEST_FILENAME)
    student_answer = transcription_entry["transcription"]

    print(f"Testing on: {TEST_FILENAME} (Question {TEST_QUESTION_ID})\n")

    print("Loading embedding model + connecting to ChromaDB...")
    embed_model = SentenceTransformer(EMBEDDING_MODEL)
    client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
    collection = client.get_collection(COLLECTION_NAME)

    print("Retrieving grounding context...")
    retrieval_query = f"{question_data['prompt']}\n\nStudent's answer: {student_answer}"
    retrieved_chunks = retrieve_context(retrieval_query, embed_model, collection)

    for c in retrieved_chunks:
        print(f"  [{c['chunk_id']}] similarity={c['similarity']:.3f} — {c['section']}")

    top_similarity = retrieved_chunks[0]["similarity"] if retrieved_chunks else 0.0
    print(f"\nTop retrieval similarity: {top_similarity:.3f}")

    user_message = build_user_message(
        question_data["prompt"], question_data["criteria"], retrieved_chunks, student_answer
    )

    print("\nCalling Groq for grading...")
    groq_client = Groq(api_key=GROQ_API_KEY)
    response = groq_client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )

    raw_output = response.choices[0].message.content
    result = json.loads(raw_output)

    print("\nGRADING RESULT")
    print(json.dumps(result, indent=2))

    print(f"\nSUMMARY")
    print(f"Total score: {result['total_score']}/{result['total_max']}")
    print(f"Retrieval confidence (top similarity): {top_similarity:.3f}")


if __name__ == "__main__":
    main()