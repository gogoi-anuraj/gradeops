"""
SQLite persistence for GRADEOPS+, now multi-tenant: professors/TAs sign up,
create courses, and each course owns its own rubric, reference material, and
graded submissions.

NOTE: still SQLite, not PostgreSQL (see earlier note in this project) --
still a deliberate scope choice for a project this size, though multi-tenancy
is exactly the kind of thing that would push a real deployment toward
PostgreSQL for concurrent-write safety.
"""

import sqlite3
import json
import os
from datetime import datetime, timezone
from contextlib import contextmanager

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gradeops.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    name TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'professor',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS courses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id INTEGER NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,
    description TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rubrics (
    course_id INTEGER PRIMARY KEY REFERENCES courses(id),
    rubric_json TEXT NOT NULL,
    uploaded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS materials (
    course_id INTEGER NOT NULL REFERENCES courses(id),
    filename TEXT NOT NULL,
    chunk_count INTEGER NOT NULL,
    uploaded_at TEXT NOT NULL,
    PRIMARY KEY (course_id, filename)
);

CREATE TABLE IF NOT EXISTS submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id INTEGER NOT NULL REFERENCES courses(id),
    filename TEXT NOT NULL,
    question_id TEXT,
    student_identifier TEXT,
    student_answer TEXT,
    initial_grading TEXT,
    final_grading TEXT,
    top_retrieval_similarity REAL,
    retrieved_chunks TEXT,
    flagged_for_review INTEGER,
    flag_reason TEXT,
    ta_status TEXT DEFAULT 'ungraded',
    ta_override_score REAL,
    ta_notes TEXT,
    graded_at TEXT,
    reviewed_at TEXT,
    UNIQUE(course_id, filename)
);
"""


@contextmanager
def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_connection() as conn:
        conn.executescript(SCHEMA)


# --- Users ---

def create_user(email: str, password_hash: str, name: str, role: str = "professor"):
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO users (email, password_hash, name, role, created_at) VALUES (?, ?, ?, ?, ?)",
            (email, password_hash, name, role, datetime.now(timezone.utc).isoformat()),
        )
        # Fetch within the SAME connection/transaction -- opening a second
        # connection here (e.g. via get_user_by_id) would try to read before
        # this INSERT has committed, and see nothing yet.
        row = conn.execute("SELECT * FROM users WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return dict(row)


def get_user_by_email(email: str):
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        return dict(row) if row else None


def get_user_by_id(user_id: int):
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None


# --- Courses ---

def create_course(owner_id: int, name: str, description: str = None):
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO courses (owner_id, name, description, created_at) VALUES (?, ?, ?, ?)",
            (owner_id, name, description, datetime.now(timezone.utc).isoformat()),
        )
        row = conn.execute("SELECT * FROM courses WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return dict(row)


def get_course(course_id: int):
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone()
        return dict(row) if row else None


def list_courses_for_user(owner_id: int):
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM courses WHERE owner_id = ? ORDER BY created_at DESC", (owner_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def user_owns_course(user_id: int, course_id: int) -> bool:
    course = get_course(course_id)
    return course is not None and course["owner_id"] == user_id


# --- Rubrics ---

def save_rubric(course_id: int, rubric_dict: dict):
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO rubrics (course_id, rubric_json, uploaded_at) VALUES (?, ?, ?)
            ON CONFLICT(course_id) DO UPDATE SET
                rubric_json=excluded.rubric_json,
                uploaded_at=excluded.uploaded_at
            """,
            (course_id, json.dumps(rubric_dict), datetime.now(timezone.utc).isoformat()),
        )


def get_rubric(course_id: int):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM rubrics WHERE course_id = ?", (course_id,)
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["rubric_json"] = json.loads(d["rubric_json"])
        return d


# --- Materials ---

def save_material_record(course_id: int, filename: str, chunk_count: int):
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO materials (course_id, filename, chunk_count, uploaded_at) VALUES (?, ?, ?, ?)
            ON CONFLICT(course_id, filename) DO UPDATE SET
                chunk_count=excluded.chunk_count,
                uploaded_at=excluded.uploaded_at
            """,
            (course_id, filename, chunk_count, datetime.now(timezone.utc).isoformat()),
        )


def list_materials(course_id: int):
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM materials WHERE course_id = ? ORDER BY filename", (course_id,)
        ).fetchall()
        return [dict(r) for r in rows]


# --- Submissions (now course-scoped) ---

def save_grading_result(course_id: int, state: dict):
    """Upsert a submission's grading result, scoped to a course."""
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO submissions (
                course_id, filename, question_id, student_answer, initial_grading, final_grading,
                top_retrieval_similarity, retrieved_chunks, flagged_for_review,
                flag_reason, ta_status, graded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'graded', ?)
            ON CONFLICT(course_id, filename) DO UPDATE SET
                question_id=excluded.question_id,
                student_answer=excluded.student_answer,
                initial_grading=excluded.initial_grading,
                final_grading=excluded.final_grading,
                top_retrieval_similarity=excluded.top_retrieval_similarity,
                retrieved_chunks=excluded.retrieved_chunks,
                flagged_for_review=excluded.flagged_for_review,
                flag_reason=excluded.flag_reason,
                ta_status='graded',
                graded_at=excluded.graded_at
            """,
            (
                course_id,
                state["filename"],
                state["question_id"],
                state["student_answer"],
                json.dumps(state["initial_grading"]),
                json.dumps(state["final_grading"]),
                state["top_similarity"],
                json.dumps(state["retrieved_chunks"] or []),
                1 if state["flagged_for_review"] else 0,
                state["flag_reason"],
                datetime.now(timezone.utc).isoformat(),
            ),
        )


def get_submission(course_id: int, filename: str):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM submissions WHERE course_id = ? AND filename = ?", (course_id, filename)
        ).fetchone()
        return _row_to_dict(row) if row else None


def list_submissions(course_id: int):
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM submissions WHERE course_id = ? ORDER BY flagged_for_review DESC, filename ASC",
            (course_id,),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]


def set_ta_decision(course_id: int, filename: str, status: str, override_score: float = None, notes: str = None):
    """status should be 'accepted' or 'overridden'."""
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE submissions
            SET ta_status = ?, ta_override_score = ?, ta_notes = ?, reviewed_at = ?
            WHERE course_id = ? AND filename = ?
            """,
            (status, override_score, notes, datetime.now(timezone.utc).isoformat(), course_id, filename),
        )


def save_transcribed_answer(course_id: int, filename: str, question_id: str, student_identifier: str, transcription: str):
    """Save a newly-uploaded, freshly-transcribed answer as 'ungraded' --
    this is the pre-grading state. save_grading_result() later updates this
    same row once the answer has actually been scored."""
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO submissions (course_id, filename, question_id, student_identifier, student_answer, ta_status)
            VALUES (?, ?, ?, ?, ?, 'ungraded')
            ON CONFLICT(course_id, filename) DO UPDATE SET
                question_id=excluded.question_id,
                student_identifier=excluded.student_identifier,
                student_answer=excluded.student_answer,
                ta_status='ungraded'
            """,
            (course_id, filename, question_id, student_identifier, transcription),
        )


def _row_to_dict(row):
    d = dict(row)
    for json_field in ("initial_grading", "final_grading", "retrieved_chunks"):
        if d.get(json_field):
            d[json_field] = json.loads(d[json_field])
    if "flagged_for_review" in d:
        d["flagged_for_review"] = bool(d["flagged_for_review"])
    return d