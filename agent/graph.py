"""
grading agent, built as a LangGraph state machine.

Implements the agent design from the project brief:
  extract answer -> retrieve context -> score against rubric ->
  self-check score against rubric edge cases -> generate justification ->
  flag low-confidence cases for human review

Note: "score" and "generate justification" happen together in the score_answer
node (asking an LLM to justify alongside scoring is more reliable than
splitting it into a separate call), and self-check is a genuine second,
independent LLM pass -- this is what makes it a real check rather than
decoration.

Usage:
    from graph import build_graph, run_on_example
    graph = build_graph()
    result = run_on_example(graph, "Q1_variantA.jpeg")
"""

import os
import sys
import json
import re
import time
import importlib
from typing import TypedDict, Optional, List, Dict, Any

from dotenv import load_dotenv
from groq import Groq
import chromadb
from sentence_transformers import SentenceTransformer
from langgraph.graph import StateGraph, END

load_dotenv()

# Make backend/database.py and backend/vector_store.py importable from here.
# This creates a two-way dependency (backend already imports agent/graph.py),
# which isn't the cleanest layering, but is a pragmatic choice for a project
# this size rather than introducing a shared third package.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(SCRIPT_DIR, "..", "backend")
sys.path.insert(0, BACKEND_DIR)
import database
import vector_store

# --- Config ---
RETRIEVAL_DIR = os.path.join(SCRIPT_DIR, "..", "retrieval")
RUBRIC_PATH = os.path.join(SCRIPT_DIR, "..", "rubric", "rubric.json")
TRANSCRIPTIONS_PATH = os.path.join(SCRIPT_DIR, "..", "vision", "transcriptions.json")
GRADING_PROMPT_PATH = os.path.join(SCRIPT_DIR, "prompts", "grading_prompt.md")
SELF_CHECK_PROMPT_PATH = os.path.join(SCRIPT_DIR, "prompts", "self_check_prompt.md")

EMBEDDING_MODEL = "all-MiniLM-L6-v2"
CHROMA_DB_PATH = os.path.join(RETRIEVAL_DIR, "chroma_db")
COLLECTION_NAME = f"gradeops_reference_{EMBEDDING_MODEL.replace('/', '_').replace('-', '_')}"
TOP_K = 3

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")

# Fallback models tried in order if the primary model is rate-limited. Each
# model has its own separate quota bucket on Groq, so switching models is a
# real escape from a daily-quota wall, not just a retry. Configurable via
# .env; defaults to two other commonly-available free-tier Groq models.
# Run list_groq_models.py first to confirm which model IDs are actually valid
# for your account -- guessing an invalid ID just produces a 404, as happened
# with 'llama-3.3-70b-versatile' earlier on this account.
GROQ_FALLBACK_MODELS = [
    m.strip() for m in os.environ.get(
        "GROQ_FALLBACK_MODELS", "openai/gpt-oss-20b,qwen/qwen3.6-27b"
    ).split(",") if m.strip()
]

# Below this wait time, just retry the SAME model (cheap, no need to burn a
# fallback). Above it, assume it's a daily-quota-type wait and switch models
# immediately instead of blocking.
SHORT_WAIT_RETRY_THRESHOLD_SECONDS = 15

# Confidence thresholds -- NOTE: these are first-pass heuristics based on the
# similarity range observed during Phase 2 testing (roughly 0.24-0.52 across
# correct/partial/wrong answers), not a rigorously tuned cutoff. Revisit this
# in Phase 4 once you have more labeled cases to calibrate against.
RETRIEVAL_SIMILARITY_THRESHOLD = 0.25


# --- Shared resources, loaded once ---
_embed_model = None
_collection = None
_groq_client = None
_rubric = None
_transcriptions = None


def _load_shared_resources():
    """Loads resources needed in BOTH demo and course mode: the embedding
    model (used for both the fixed demo collection and per-course
    collections) and the Groq client. Does NOT load the demo-specific
    rubric/transcriptions/collection -- those are only needed in demo mode,
    and eagerly loading them here would crash course-only usage (e.g. a
    fresh install that never ran the Phase 1 demo setup, so the demo
    ChromaDB collection doesn't exist)."""
    global _embed_model, _groq_client
    if _embed_model is None:
        print("Loading embedding model...")
        _embed_model = SentenceTransformer(EMBEDDING_MODEL)
    if _groq_client is None:
        if not GROQ_API_KEY:
            raise EnvironmentError("GROQ_API_KEY not set. Add it to your .env file.")
        _groq_client = Groq(api_key=GROQ_API_KEY)


def _load_demo_resources():
    """Loads the fixed demo rubric/transcriptions/vector collection. Only
    called from the demo-mode branch of extract_answer/retrieve_context --
    never needed, and would fail, in course-only usage."""
    global _collection, _rubric, _transcriptions
    if _collection is None:
        print("Connecting to demo ChromaDB collection...")
        client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
        _collection = client.get_collection(COLLECTION_NAME)
    if _rubric is None:
        with open(RUBRIC_PATH, "r", encoding="utf-8") as f:
            _rubric = json.load(f)
    if _transcriptions is None:
        with open(TRANSCRIPTIONS_PATH, "r", encoding="utf-8") as f:
            _transcriptions = json.load(f)


def _extract_prompt_body(prompt_md_path):
    with open(prompt_md_path, "r", encoding="utf-8") as f:
        content = f.read()
    marker = "---"
    idx = content.find(marker)
    return content[idx + len(marker):].strip() if idx != -1 else content


def _parse_wait_seconds(error_str):
    """Parse Groq's rate-limit wait time out of its error message. Groq uses
    several formats depending on the limit type: '134.999999ms' for short
    per-minute waits, or '23m53.376s' for longer per-day waits. A naive regex
    for just seconds-or-ms will silently mis-parse the 'Xm Y.Zs' format by
    only grabbing the seconds part and dropping the minutes -- this handles
    both correctly."""
    match = re.search(r"try again in (.+?)\.\s*Need", error_str)
    if not match:
        return None
    duration_str = match.group(1)

    total_seconds = 0.0
    hours = re.search(r"([\d.]+)h", duration_str)
    minutes = re.search(r"([\d.]+)m(?!s)", duration_str)  # 'm' not followed by 's' (avoid matching 'ms')
    ms = re.search(r"([\d.]+)ms", duration_str)
    seconds = re.search(r"([\d.]+)s(?!\w)", duration_str) if not ms else None

    if hours:
        total_seconds += float(hours.group(1)) * 3600
    if minutes:
        total_seconds += float(minutes.group(1)) * 60
    if ms:
        total_seconds += float(ms.group(1)) / 1000
    elif seconds:
        total_seconds += float(seconds.group(1))

    return total_seconds if total_seconds > 0 else None


def _call_groq_with_retry(messages, max_retries=3, max_auto_wait_seconds=1800):
    """Call Groq's chat completions with automatic retry AND model fallback.

    Strategy:
    - Try GROQ_MODEL first.
    - On a rate-limit error with a SHORT required wait (per-minute limits are
      usually sub-second to a few seconds): just wait and retry the same model.
    - On a rate-limit error with a LONG required wait (daily quota, can be
      ~20-25 min): don't block -- immediately try the next model in
      GROQ_FALLBACK_MODELS instead, since it has a separate quota bucket.
    - Only falls back to actually waiting if every model (primary + all
      fallbacks) is rate-limited with a long wait.

    Returns (response, model_actually_used) -- the caller should record which
    model served the request, since primary vs. fallback can differ between
    the scoring pass and the self-check pass for the same answer, which is
    worth knowing when interpreting results.
    """
    models_to_try = [GROQ_MODEL] + GROQ_FALLBACK_MODELS
    long_wait_fallback = None  # (model, wait_seconds) saved in case everything is long-waited

    for model in models_to_try:
        for attempt in range(max_retries):
            try:
                response = _groq_client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0,
                    response_format={"type": "json_object"},
                )
                if model != GROQ_MODEL:
                    print(f"    (served by fallback model: {model})")
                return response, model
            except Exception as e:
                error_str = str(e)
                is_rate_limit = "rate_limit_exceeded" in error_str or "429" in error_str
                if not is_rate_limit:
                    raise  # a real error, not a quota issue -- don't mask it by falling back

                wait_seconds = _parse_wait_seconds(error_str)
                if wait_seconds is None:
                    wait_seconds = 2 ** attempt

                if wait_seconds <= SHORT_WAIT_RETRY_THRESHOLD_SECONDS:
                    wait_seconds += 1.0  # small safety buffer
                    print(f"    Rate limited on {model} (short wait), retrying in {wait_seconds:.1f}s...")
                    time.sleep(wait_seconds)
                    continue  # retry same model
                else:
                    print(f"    {model} rate-limited with long wait ({wait_seconds/60:.1f} min) -- trying next model...")
                    if long_wait_fallback is None or wait_seconds < long_wait_fallback[1]:
                        long_wait_fallback = (model, wait_seconds)
                    break  # give up on this model, move to next one in the outer loop

    # Every model was long-wait rate-limited -- wait out the shortest one, if under the cap
    if long_wait_fallback:
        model, wait_seconds = long_wait_fallback
        if wait_seconds > max_auto_wait_seconds:
            raise RuntimeError(
                f"All models (primary + fallbacks) are rate-limited; shortest wait "
                f"({model}: {wait_seconds/60:.1f} min) still exceeds the "
                f"{max_auto_wait_seconds/60:.0f} min auto-wait cap. Wait and retry later, "
                f"or add more models to GROQ_FALLBACK_MODELS in .env."
            )
        print(f"    All models rate-limited. Waiting {wait_seconds/60:.1f} min on {model}...")
        time.sleep(wait_seconds + 2.0)
        response = _groq_client.chat.completions.create(
            model=model, messages=messages, temperature=0,
            response_format={"type": "json_object"},
        )
        return response, model

    raise RuntimeError("Failed to get a response from any configured model.")


def get_transcriptions():
    """Public accessor -- ensures demo resources are loaded, then returns
    the transcriptions list. Use this instead of importing _transcriptions
    directly, since 'from graph import _transcriptions' would copy its value
    (None) at import time, before this has ever run."""
    _load_demo_resources()
    return _transcriptions


def get_embed_model():
    """Public accessor for the loaded embedding model, so other parts of the
    app (e.g. plagiarism detection) can reuse it instead of loading a second
    copy of the same model into memory."""
    _load_shared_resources()
    return _embed_model


# --- State schema ---
class GradingState(TypedDict):
    course_id: Optional[int]  # None = demo mode (fixed files); set = course mode (DB-backed)
    filename: str
    question_id: str
    question_data: Optional[Dict[str, Any]]
    student_answer: Optional[str]
    retrieved_chunks: Optional[List[Dict[str, Any]]]
    top_similarity: Optional[float]
    initial_grading: Optional[Dict[str, Any]]
    final_grading: Optional[Dict[str, Any]]
    score_model_used: Optional[str]
    self_check_model_used: Optional[str]
    flagged_for_review: Optional[bool]
    flag_reason: Optional[str]
    error: Optional[str]


# --- Nodes ---

def extract_answer(state: GradingState) -> GradingState:
    """Load the transcribed answer and its rubric question for this filename.

    Course mode (state['course_id'] is set): reads from the per-course
    database -- the rubric a professor uploaded, and the transcribed answer
    from a student upload.
    Demo mode (state['course_id'] is None): reads from the original fixed
    demo files (rubric.json, transcriptions.json) -- preserves the exact
    validated behavior from Phase 1/2 testing, so existing scripts
    (score_single_example.py, batch_run_agent.py, etc.) keep working
    unchanged."""
    course_id = state.get("course_id")

    if course_id is not None:
        submission = database.get_submission(course_id, state["filename"])
        if submission is None or not submission.get("student_answer"):
            return {**state, "error": f"No usable transcription found for '{state['filename']}' in course {course_id}"}

        rubric_record = database.get_rubric(course_id)
        if rubric_record is None:
            return {**state, "error": f"No rubric uploaded for course {course_id}"}

        question_data = next(
            (q for q in rubric_record["rubric_json"]["questions"]
             if q["question_id"] == submission["question_id"]),
            None
        )
        if question_data is None:
            return {**state, "error": f"No rubric question '{submission['question_id']}' found in course {course_id}'s rubric"}

        return {
            **state,
            "question_id": submission["question_id"],
            "question_data": question_data,
            "student_answer": submission["student_answer"],
        }

    # --- Demo mode (unchanged from Phase 2) ---
    _load_demo_resources()
    entry = next((t for t in _transcriptions if t["filename"] == state["filename"]), None)
    if entry is None or entry.get("transcription") is None:
        return {**state, "error": f"No usable transcription found for {state['filename']}"}

    question_data = next(
        (q for q in _rubric["questions"] if q["question_id"] == entry["question_id"]), None
    )
    if question_data is None:
        return {**state, "error": f"No rubric found for question_id {entry['question_id']}"}

    return {
        **state,
        "question_id": entry["question_id"],
        "question_data": question_data,
        "student_answer": entry["transcription"],
    }


def retrieve_context(state: GradingState) -> GradingState:
    """Retrieve grounding chunks using question + student answer combined.

    Course mode: queries this course's own uploaded-material vector
    collection. Demo mode: queries the fixed Phase 1 demo collection
    (unchanged from before)."""
    if state.get("error"):
        return state

    course_id = state.get("course_id")
    query = f"{state['question_data']['prompt']}\n\nStudent's answer: {state['student_answer']}"

    _load_shared_resources()  # ensures _embed_model is loaded either way

    if course_id is not None:
        chunks = vector_store.query_course_collection(course_id, query, _embed_model, k=TOP_K)
        if not chunks:
            return {
                **state,
                "error": f"No reference material uploaded for course {course_id} yet -- "
                         f"upload materials before grading."
            }
    else:
        _load_demo_resources()
        query_embedding = _embed_model.encode([query], normalize_embeddings=True).tolist()
        results = _collection.query(query_embeddings=query_embedding, n_results=TOP_K)
        chunks = []
        for chunk_id, doc, meta, dist in zip(
            results["ids"][0], results["documents"][0],
            results["metadatas"][0], results["distances"][0]
        ):
            chunks.append({
                "chunk_id": chunk_id, "text": doc,
                "section": meta["section"], "similarity": 1 - dist,
            })

    top_similarity = chunks[0]["similarity"] if chunks else 0.0
    return {**state, "retrieved_chunks": chunks, "top_similarity": top_similarity}


def score_answer(state: GradingState) -> GradingState:
    """First-pass scoring: LLM scores against rubric with citations."""
    if state.get("error"):
        return state

    system_prompt = _extract_prompt_body(GRADING_PROMPT_PATH)
    criteria_text = "\n".join(
        f"- {c['criterion_id']}: {c['description']} (max {c['marks']} marks)"
        for c in state["question_data"]["criteria"]
    )
    chunks_text = "\n\n".join(
        f"[{c['chunk_id']}] (similarity: {c['similarity']:.3f})\n{c['text']}"
        for c in state["retrieved_chunks"]
    )
    user_message = f"""QUESTION: {state['question_data']['prompt']}

RUBRIC CRITERIA:
{criteria_text}

RETRIEVED REFERENCE MATERIAL:
{chunks_text}

STUDENT'S TRANSCRIBED ANSWER:
{state['student_answer']}

Grade this answer according to the rubric criteria above. Output only the JSON."""

    response, model_used = _call_groq_with_retry([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ])
    initial_grading = json.loads(response.choices[0].message.content)
    return {**state, "initial_grading": initial_grading, "score_model_used": model_used}


def self_check(state: GradingState) -> GradingState:
    """Second, independent LLM pass: review the initial grading for mistakes."""
    if state.get("error"):
        return state

    system_prompt = _extract_prompt_body(SELF_CHECK_PROMPT_PATH)
    chunks_text = "\n\n".join(
        f"[{c['chunk_id']}] (similarity: {c['similarity']:.3f})\n{c['text']}"
        for c in state["retrieved_chunks"]
    )
    user_message = f"""QUESTION: {state['question_data']['prompt']}

RETRIEVED REFERENCE MATERIAL:
{chunks_text}

STUDENT'S TRANSCRIBED ANSWER:
{state['student_answer']}

INITIAL GRADING DECISION TO REVIEW:
{json.dumps(state['initial_grading'], indent=2)}

Review this grading decision per your instructions. Output only the JSON."""

    response, model_used = _call_groq_with_retry([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ])
    final_grading = json.loads(response.choices[0].message.content)
    return {**state, "final_grading": final_grading, "self_check_model_used": model_used}


def check_confidence(state: GradingState) -> GradingState:
    """Deterministic node: decide whether this case should be flagged for
    human review.

    NOTE ON DESIGN: an earlier version of this node auto-flagged based on a
    fixed retrieval-similarity threshold. Testing showed this produces false
    positives -- Q3's retrieval similarities run consistently lower than other
    questions even for fully correct answers (a property of this embedding
    model on this topic, not a sign of weak grounding), so a single global
    cutoff isn't reliable without per-question calibration this project
    doesn't have data for yet. The self-check step's own self-reported
    confidence has proven better calibrated in testing (e.g. correctly landing
    on "medium" for the one genuinely ambiguous case, Q2_variantA, and "high"
    for every clearly correct or clearly wrong case). So: self-reported
    confidence is now the PRIMARY trigger. Retrieval similarity is still
    recorded and shown for transparency, but only contributes to flagging when
    it's low AND the self-check step itself isn't confident -- i.e. it needs
    to agree with another signal, not fire alone. Revisit with a properly
    calibrated per-question threshold once more labeled data exists (Phase 4).
    """
    if state.get("error"):
        return {**state, "flagged_for_review": True, "flag_reason": state["error"]}

    self_reported = state["final_grading"].get("self_reported_confidence", "medium")
    low_similarity = state["top_similarity"] < RETRIEVAL_SIMILARITY_THRESHOLD

    if self_reported == "low":
        flagged = True
        reason = "Self-check step reported low confidence in this grading."
    elif self_reported == "medium" and low_similarity:
        flagged = True
        reason = (
            f"Self-check reported medium confidence AND retrieval similarity "
            f"was low ({state['top_similarity']:.3f}) -- two weak signals together."
        )
    else:
        flagged = False
        reason = None

    return {**state, "flagged_for_review": flagged, "flag_reason": reason}


def build_graph():
    graph = StateGraph(GradingState)
    graph.add_node("extract_answer", extract_answer)
    graph.add_node("retrieve_context", retrieve_context)
    graph.add_node("score_answer", score_answer)
    graph.add_node("self_check", self_check)
    graph.add_node("check_confidence", check_confidence)

    graph.set_entry_point("extract_answer")
    graph.add_edge("extract_answer", "retrieve_context")
    graph.add_edge("retrieve_context", "score_answer")
    graph.add_edge("score_answer", "self_check")
    graph.add_edge("self_check", "check_confidence")
    graph.add_edge("check_confidence", END)

    return graph.compile()


def run_on_example(graph, filename: str, course_id: int = None) -> GradingState:
    initial_state: GradingState = {
        "course_id": course_id,
        "filename": filename, "question_id": "", "question_data": None,
        "student_answer": None, "retrieved_chunks": None, "top_similarity": None,
        "initial_grading": None, "final_grading": None,
        "score_model_used": None, "self_check_model_used": None,
        "flagged_for_review": None, "flag_reason": None, "error": None,
    }
    return graph.invoke(initial_state)


if __name__ == "__main__":
    graph = build_graph()
    result = run_on_example(graph, "Q1_variantA.jpeg")

    print("\n=== INITIAL GRADING ===")
    print(json.dumps(result["initial_grading"], indent=2))
    print("\n=== FINAL GRADING (after self-check) ===")
    print(json.dumps(result["final_grading"], indent=2))
    print(f"\n=== CONFIDENCE ===")
    print(f"Flagged for review: {result['flagged_for_review']}")
    if result["flag_reason"]:
        print(f"Reason: {result['flag_reason']}")