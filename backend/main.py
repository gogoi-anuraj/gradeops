"""
backend API.

Wraps the LangGraph grading agent (agent/graph.py) and exposes it over HTTP,
with SQLite persistence for grading results and TA review decisions. This is
what the Phase 3 React dashboard will call

Run:
    cd backend
    uvicorn main:app --reload
"""

import os
import sys

from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

import database
import auth
import chunking
import vector_store
import vlm_transcribe

# Make agent/graph.py importable from here
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
AGENT_DIR = os.path.join(SCRIPT_DIR, "..", "agent")
sys.path.insert(0, AGENT_DIR)

from graph import build_graph, run_on_example, get_embed_model  # noqa: E402

app = FastAPI(title="GRADEOPS+ API")

# Allow the React dev server (different origin) to call this API.
# Wide open for local development -- tighten before any real deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_graph = None  # built lazily on first use, since it loads the embedding model


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


@app.on_event("startup")
def on_startup():
    database.init_db()


class ReviewDecision(BaseModel):
    status: str  # "accepted" or "overridden"
    override_score: Optional[float] = None
    notes: Optional[str] = None


class SignupRequest(BaseModel):
    email: str
    password: str
    name: str
    role: str = "professor"


class LoginRequest(BaseModel):
    email: str
    password: str


class CourseCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None


class RubricCriterion(BaseModel):
    criterion_id: str
    description: str
    marks: float


class RubricQuestion(BaseModel):
    question_id: str
    prompt: str
    total_marks: float
    criteria: list[RubricCriterion]


class RubricUpload(BaseModel):
    exam_id: str
    reference_source: Optional[str] = None
    questions: list[RubricQuestion]


def _user_public(user: dict) -> dict:
    """Strip the password hash before returning a user object to the client."""
    return {"id": user["id"], "email": user["email"], "name": user["name"], "role": user["role"]}


@app.post("/auth/signup")
def signup(req: SignupRequest):
    if database.get_user_by_email(req.email):
        raise HTTPException(status_code=400, detail="An account with this email already exists.")
    if len(req.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")

    password_hash = auth.hash_password(req.password)
    user = database.create_user(req.email, password_hash, req.name, req.role)
    token = auth.create_access_token(user["id"])
    return {"access_token": token, "token_type": "bearer", "user": _user_public(user)}


@app.post("/auth/login")
def login(req: LoginRequest):
    user = database.get_user_by_email(req.email)
    if user is None or not auth.verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Incorrect email or password.")

    token = auth.create_access_token(user["id"])
    return {"access_token": token, "token_type": "bearer", "user": _user_public(user)}


@app.get("/auth/me")
def get_me(current_user: dict = Depends(auth.get_current_user)):
    return _user_public(current_user)


@app.post("/courses")
def create_course(req: CourseCreateRequest, current_user: dict = Depends(auth.get_current_user)):
    return database.create_course(current_user["id"], req.name, req.description)


@app.get("/courses")
def list_my_courses(current_user: dict = Depends(auth.get_current_user)):
    return database.list_courses_for_user(current_user["id"])


def _require_course_access(course_id: int, current_user: dict) -> dict:
    """Raises 404 if the course doesn't exist, 403 if it exists but isn't
    owned by the current user. Returns the course record if access is OK."""
    course = database.get_course(course_id)
    if course is None:
        raise HTTPException(status_code=404, detail=f"Course {course_id} not found.")
    if course["owner_id"] != current_user["id"]:
        raise HTTPException(status_code=403, detail="You don't have access to this course.")
    return course


@app.post("/courses/{course_id}/rubric")
def upload_rubric(course_id: int, rubric: RubricUpload, current_user: dict = Depends(auth.get_current_user)):
    _require_course_access(course_id, current_user)

    # Sanity check: each question's criteria marks should sum to its total_marks --
    # a mismatch here would silently produce a wrong max-score display later,
    # far from where the actual data-entry mistake happened.
    for q in rubric.questions:
        criteria_sum = sum(c.marks for c in q.criteria)
        if criteria_sum != q.total_marks:
            raise HTTPException(
                status_code=400,
                detail=f"Question '{q.question_id}': criteria marks sum to {criteria_sum}, "
                       f"but total_marks is {q.total_marks}. These must match."
            )

    database.save_rubric(course_id, rubric.model_dump())
    return database.get_rubric(course_id)


@app.get("/courses/{course_id}/rubric")
def get_rubric(course_id: int, current_user: dict = Depends(auth.get_current_user)):
    _require_course_access(course_id, current_user)

    rubric = database.get_rubric(course_id)
    if rubric is None:
        raise HTTPException(status_code=404, detail="No rubric uploaded for this course yet.")
    return rubric


@app.post("/courses/{course_id}/materials")
async def upload_materials(
    course_id: int,
    file: UploadFile = File(...),
    current_user: dict = Depends(auth.get_current_user),
):
    """Upload one .md/.txt reference material file. It's chunked and embedded
    into this course's own vector collection -- never mixed with another
    course's material. Re-uploading a file with the same name replaces its
    chunks rather than duplicating them. To upload multiple files, call this
    endpoint once per file (Swagger UI/browsers don't reliably support
    multi-file array uploads, so one-at-a-time is both simpler and gives
    independent success/failure per file)."""
    _require_course_access(course_id, current_user)
    embed_model = get_embed_model()

    if not file.filename.lower().endswith((".md", ".txt")):
        raise HTTPException(
            status_code=400,
            detail=f"'{file.filename}': only .md and .txt files are supported."
        )

    raw_bytes = await file.read()
    try:
        raw_text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=400,
            detail=f"'{file.filename}': could not decode as UTF-8 text."
        )

    chunks = chunking.chunk_markdown(raw_text, file.filename)
    if not chunks:
        raise HTTPException(
            status_code=400,
            detail=f"'{file.filename}': produced zero chunks -- check the file has content and headers."
        )

    vector_store.store_chunks(course_id, chunks, embed_model)
    database.save_material_record(course_id, file.filename, len(chunks))
    return {"filename": file.filename, "chunk_count": len(chunks)}


@app.get("/courses/{course_id}/materials")
def list_materials(course_id: int, current_user: dict = Depends(auth.get_current_user)):
    _require_course_access(course_id, current_user)
    return database.list_materials(course_id)


@app.post("/courses/{course_id}/answers")
async def upload_answer(
    course_id: int,
    question_id: str = Form(...),
    student_identifier: str = Form(None),
    file: UploadFile = File(...),
    current_user: dict = Depends(auth.get_current_user),
):
    """Upload one student's handwritten answer image. Transcribes it via a
    vision-capable LLM and saves it as 'ungraded' -- call
    POST /courses/{course_id}/submissions/{filename}/grade next to score it.

    Like materials upload, this takes ONE file per request (not a list) --
    Swagger UI/browsers don't reliably render multi-file array inputs as an
    actual file picker."""
    _require_course_access(course_id, current_user)

    if not file.filename.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
        raise HTTPException(
            status_code=400,
            detail=f"'{file.filename}': only image files (.jpg, .jpeg, .png, .webp) are supported."
        )

    rubric = database.get_rubric(course_id)
    if rubric is None:
        raise HTTPException(
            status_code=400,
            detail="Upload a rubric for this course before uploading student answers."
        )
    valid_question_ids = {q["question_id"] for q in rubric["rubric_json"]["questions"]}
    if question_id not in valid_question_ids:
        raise HTTPException(
            status_code=400,
            detail=f"question_id '{question_id}' not found in this course's rubric. "
                   f"Valid options: {sorted(valid_question_ids)}"
        )

    image_bytes = await file.read()
    try:
        transcription = vlm_transcribe.transcribe_image_bytes(image_bytes, file.filename)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Transcription failed: {e}")

    database.save_transcribed_answer(course_id, file.filename, question_id, student_identifier, transcription)
    return database.get_submission(course_id, file.filename)


@app.get("/courses/{course_id}/answers")
def list_answers(course_id: int, current_user: dict = Depends(auth.get_current_user)):
    _require_course_access(course_id, current_user)
    return database.list_submissions(course_id)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/courses/{course_id}/submissions")
def list_all_submissions(course_id: int, current_user: dict = Depends(auth.get_current_user)):
    """List every submission (uploaded answers) for this course, from the
    per-course database -- ungraded ones show ta_status='ungraded'. Already
    sorted flagged-for-review-first by database.list_submissions()."""
    _require_course_access(course_id, current_user)
    return database.list_submissions(course_id)


@app.get("/courses/{course_id}/submissions/{filename}")
def get_submission_detail(course_id: int, filename: str, current_user: dict = Depends(auth.get_current_user)):
    _require_course_access(course_id, current_user)

    submission = database.get_submission(course_id, filename)
    if submission is None:
        raise HTTPException(status_code=404, detail=f"'{filename}' has not been graded yet in this course.")
    return submission


@app.post("/courses/{course_id}/submissions/{filename}/grade")
def grade_submission(course_id: int, filename: str, current_user: dict = Depends(auth.get_current_user)):
    """Run the full LangGraph agent on this filename and persist the result
    under this course."""
    _require_course_access(course_id, current_user)

    existing = database.get_submission(course_id, filename)
    if existing is None or not existing.get("student_answer"):
        raise HTTPException(
            status_code=404,
            detail=f"No transcribed answer found for '{filename}' in this course. "
                   f"Upload it first via POST /courses/{course_id}/answers."
        )

    graph = get_graph()
    state = run_on_example(graph, filename, course_id=course_id)

    if state.get("error"):
        raise HTTPException(status_code=422, detail=state["error"])

    database.save_grading_result(course_id, state)
    return database.get_submission(course_id, filename)


@app.post("/courses/{course_id}/submissions/{filename}/review")
def submit_ta_review(course_id: int, filename: str, decision: ReviewDecision, current_user: dict = Depends(auth.get_current_user)):
    """TA accepts the AI grade as-is, or overrides it with their own score."""
    _require_course_access(course_id, current_user)

    submission = database.get_submission(course_id, filename)
    if submission is None:
        raise HTTPException(status_code=404, detail=f"'{filename}' has not been graded yet.")

    if decision.status not in ("accepted", "overridden"):
        raise HTTPException(status_code=400, detail="status must be 'accepted' or 'overridden'")

    if decision.status == "overridden" and decision.override_score is None:
        raise HTTPException(status_code=400, detail="override_score is required when status is 'overridden'")

    database.set_ta_decision(course_id, filename, decision.status, decision.override_score, decision.notes)
    return database.get_submission(course_id, filename)