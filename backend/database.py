import os
import json
from datetime import datetime, timezone
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

PG_CONFIG = {
    "host": os.environ.get("PGHOST", "localhost"),
    "port": os.environ.get("PGPORT", "5432"),
    "dbname": os.environ.get("PGDATABASE", "gradeops"),
    "user": os.environ.get("PGUSER", "postgres"),
    "password": os.environ.get("PGPASSWORD"),
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    name TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'professor',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS courses (
    id SERIAL PRIMARY KEY,
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
    id SERIAL PRIMARY KEY,
    course_id INTEGER NOT NULL REFERENCES courses(id),
    filename TEXT NOT NULL,
    question_id TEXT,
    student_identifier TEXT,
    student_answer TEXT,
    initial_grading TEXT,
    final_grading TEXT,
    top_retrieval_similarity REAL,
    retrieved_chunks TEXT,
    flagged_for_review BOOLEAN,
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
    conn = psycopg2.connect(cursor_factory=psycopg2.extras.RealDictCursor, **PG_CONFIG)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(SCHEMA)


# --- Users ---

def create_user(email: str, password_hash: str, name: str, role: str = "professor"):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users (email, password_hash, name, role, created_at)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING *
                """,
                (email, password_hash, name, role, datetime.now(timezone.utc).isoformat()),
            )
            return dict(cur.fetchone())


def get_user_by_email(email: str):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE email = %s", (email,))
            row = cur.fetchone()
            return dict(row) if row else None


def get_user_by_id(user_id: int):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            row = cur.fetchone()
            return dict(row) if row else None


# --- Courses ---

def create_course(owner_id: int, name: str, description: str = None):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO courses (owner_id, name, description, created_at)
                VALUES (%s, %s, %s, %s)
                RETURNING *
                """,
                (owner_id, name, description, datetime.now(timezone.utc).isoformat()),
            )
            return dict(cur.fetchone())


def get_course(course_id: int):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM courses WHERE id = %s", (course_id,))
            row = cur.fetchone()
            return dict(row) if row else None


def list_courses_for_user(owner_id: int):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM courses WHERE owner_id = %s ORDER BY created_at DESC", (owner_id,)
            )
            return [dict(r) for r in cur.fetchall()]


def user_owns_course(user_id: int, course_id: int) -> bool:
    course = get_course(course_id)
    return course is not None and course["owner_id"] == user_id


# --- Rubrics ---

def save_rubric(course_id: int, rubric_dict: dict):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO rubrics (course_id, rubric_json, uploaded_at)
                VALUES (%s, %s, %s)
                ON CONFLICT (course_id) DO UPDATE SET
                    rubric_json = EXCLUDED.rubric_json,
                    uploaded_at = EXCLUDED.uploaded_at
                """,
                (course_id, json.dumps(rubric_dict), datetime.now(timezone.utc).isoformat()),
            )


def get_rubric(course_id: int):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM rubrics WHERE course_id = %s", (course_id,))
            row = cur.fetchone()
            if row is None:
                return None
            d = dict(row)
            d["rubric_json"] = json.loads(d["rubric_json"])
            return d


# --- Materials ---

def save_material_record(course_id: int, filename: str, chunk_count: int):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO materials (course_id, filename, chunk_count, uploaded_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (course_id, filename) DO UPDATE SET
                    chunk_count = EXCLUDED.chunk_count,
                    uploaded_at = EXCLUDED.uploaded_at
                """,
                (course_id, filename, chunk_count, datetime.now(timezone.utc).isoformat()),
            )


def list_materials(course_id: int):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM materials WHERE course_id = %s ORDER BY filename", (course_id,)
            )
            return [dict(r) for r in cur.fetchall()]


# --- Submissions ---

def save_transcribed_answer(course_id: int, filename: str, question_id: str, student_identifier: str, transcription: str):
    """Save a newly-uploaded, freshly-transcribed answer as 'ungraded' --
    this is the pre-grading state. save_grading_result() later updates this
    same row once the answer has actually been scored."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO submissions (course_id, filename, question_id, student_identifier, student_answer, ta_status)
                VALUES (%s, %s, %s, %s, %s, 'ungraded')
                ON CONFLICT (course_id, filename) DO UPDATE SET
                    question_id = EXCLUDED.question_id,
                    student_identifier = EXCLUDED.student_identifier,
                    student_answer = EXCLUDED.student_answer,
                    ta_status = 'ungraded'
                """,
                (course_id, filename, question_id, student_identifier, transcription),
            )


def save_grading_result(course_id: int, state: dict):
    """Upsert a submission's grading result, scoped to a course."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO submissions (
                    course_id, filename, question_id, student_answer, initial_grading, final_grading,
                    top_retrieval_similarity, retrieved_chunks, flagged_for_review,
                    flag_reason, ta_status, graded_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'graded', %s)
                ON CONFLICT (course_id, filename) DO UPDATE SET
                    question_id = EXCLUDED.question_id,
                    student_answer = EXCLUDED.student_answer,
                    initial_grading = EXCLUDED.initial_grading,
                    final_grading = EXCLUDED.final_grading,
                    top_retrieval_similarity = EXCLUDED.top_retrieval_similarity,
                    retrieved_chunks = EXCLUDED.retrieved_chunks,
                    flagged_for_review = EXCLUDED.flagged_for_review,
                    flag_reason = EXCLUDED.flag_reason,
                    ta_status = 'graded',
                    graded_at = EXCLUDED.graded_at
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
                    bool(state["flagged_for_review"]),
                    state["flag_reason"],
                    datetime.now(timezone.utc).isoformat(),
                ),
            )


def get_submission(course_id: int, filename: str):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM submissions WHERE course_id = %s AND filename = %s", (course_id, filename)
            )
            row = cur.fetchone()
            return _row_to_dict(row) if row else None


def list_submissions(course_id: int):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM submissions WHERE course_id = %s ORDER BY flagged_for_review DESC, filename ASC",
                (course_id,),
            )
            return [_row_to_dict(r) for r in cur.fetchall()]


def set_ta_decision(course_id: int, filename: str, status: str, override_score: float = None, notes: str = None):
    """status should be 'accepted' or 'overridden'."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE submissions
                SET ta_status = %s, ta_override_score = %s, ta_notes = %s, reviewed_at = %s
                WHERE course_id = %s AND filename = %s
                """,
                (status, override_score, notes, datetime.now(timezone.utc).isoformat(), course_id, filename),
            )


def _row_to_dict(row):
    d = dict(row)
    for json_field in ("initial_grading", "final_grading", "retrieved_chunks"):
        if d.get(json_field):
            d[json_field] = json.loads(d[json_field])
    # NOTE: flagged_for_review no longer needs a manual bool() conversion here
    # -- it's a native Postgres BOOLEAN now, so psycopg2 already returns a
    # real Python bool (unlike SQLite's INTEGER 0/1 workaround).
    return d


if __name__ == "__main__":
    # Quick standalone check: run this file directly to verify the
    # connection works and tables get created, before wiring in the rest.
    print(f"Connecting to Postgres: {PG_CONFIG['user']}@{PG_CONFIG['host']}:{PG_CONFIG['port']}/{PG_CONFIG['dbname']}")
    init_db()
    print("Connected successfully and schema created (or already existed).")