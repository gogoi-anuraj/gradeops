# GRADEOPS+

A multi-tenant, RAG-grounded exam grading pipeline. Professors sign up, create a course, upload their rubric and reference material, upload scanned handwritten student answers, and get AI-generated grades — each one grounded in retrieved course material, self-checked for errors, and flagged for human review when confidence is low.

Built as an extension of the original GRADEOPS problem statement, turning a plain "VLM + agentic LLM" grading pipeline into a genuine Retrieval-Augmented Generation system: every grade is grounded in retrieved reference material rather than the model's own memory, and every citation is checked against what was actually retrieved.

---

## Screenshots

<!-- Add screenshots below. Suggested shots: login/signup screen, course selector,
     rubric panel (both empty-state upload form and populated view), materials
     panel mid-upload, answers panel with graded/flagged rows, and the full
     submission detail/review screen showing the three-column layout. -->

**Login / Signup**

`[screenshots/login_signup.jpg]`

**Course selector**

`[screenshots/course_selector.png]`

**Rubric upload / view**

`[screenshots/rubric.png]`

**Reference material upload**

`[screenshots/reference.png]`

**Student answers list**

`[screenshots/answerlist.png]`

**Grading review (detail view with citations & evidence)**

`[screenshots/grading.png]`

---

## What it does

```
Professor signs up, creates a course
        │
        ▼
Uploads rubric (JSON) ──► Uploads reference material (.md/.txt)
                                    │ chunked + embedded
                                    ▼
                          Course-specific vector collection
        │
        ▼
Uploads scanned student answers (images)
        │ transcribed by a vision-language model
        ▼
LangGraph grading agent:
  extract → retrieve grounding context → score against rubric →
  self-check for errors → confidence-flag for human review
        │
        ▼
TA reviews in dashboard: sees the answer, the AI's per-criterion score,
the cited evidence chunks, and accepts or overrides the grade
```

## Why this is RAG, not just "an LLM that grades"

Rubrics are terse ("2 marks for correct derivation") and don't contain the reference material an LLM needs to judge partial correctness. This pipeline retrieves the actual relevant textbook/lecture content *before* scoring, and requires every awarded/denied mark to cite the specific chunk that supports it — closing the "confidently wrong partial credit with no grounding" loophole that a rubric-only LLM grader has.

---

## Architecture

| Layer | Component |
|---|---|
| Auth | JWT + bcrypt, multi-tenant (each professor's courses, rubrics, material, and submissions are isolated) |
| OCR/Vision | Self-hosted Qwen2.5-VL (batch, via Colab notebook) for offline testing; Groq `qwen3.6-27b` (live, hosted) for real-time answer uploads |
| Embeddings | `all-MiniLM-L6-v2`, one collection per course |
| Vector Store | ChromaDB (persistent, course-scoped collections) |
| Chunking | Semantic (markdown header-based, with paragraph-level fallback for long sections) |
| Grading Agent | LangGraph state machine: extract → retrieve → score → self-check → confidence-flag |
| Grading LLM | Groq (`openai/gpt-oss-120b` primary, with automatic fallback to `openai/gpt-oss-20b` / `qwen/qwen3.6-27b` on rate limits) |
| Backend | FastAPI |
| Database | PostgreSQL |
| Frontend | React (Vite) |

---

## Project structure

```
gradeops-plus/
├── agent/
│   ├── graph.py                 # LangGraph grading agent (dual demo/course mode)
│   └── prompts/                 # grading_prompt.md, self_check_prompt.md
├── backend/
│   ├── main.py                  # FastAPI app — auth, courses, uploads, grading endpoints
│   ├── auth.py                  # password hashing, JWT
│   ├── database.py              # PostgreSQL persistence layer
│   ├── chunking.py               # reusable semantic chunker (uploads)
│   ├── vector_store.py           # course-scoped ChromaDB wrapper
│   └── vlm_transcribe.py         # live OCR for answer uploads (Groq vision)
├── dashboard/                    # React frontend
│   └── src/
│       ├── AuthContext.jsx
│       └── components/
│           ├── LoginPage.jsx
│           ├── CourseSelector.jsx
│           ├── RubricPanel.jsx
│           ├── MaterialsPanel.jsx
│           ├── AnswersPanel.jsx
│           └── SubmissionDetail.jsx
├── retrieval/                    # reference material, chunking, embedding, eval
│   └── eval/
│       └── retrieval_labels.json # hand-labeled (question → correct chunk) pairs
│   
└── vision/                       # Colab notebook + batch transcription scripts
```

---

## Setup

### 1. Database
Install PostgreSQL locally, create a database, and set credentials in `backend/.env` (see `.env.example`).

### 2. Backend
```bash
cd backend
pip install -r requirements.txt   # fastapi, psycopg2-binary, bcrypt, PyJWT, groq, chromadb, sentence-transformers, python-multipart
```
Fill in `backend/.env`:
```
PGHOST=localhost
PGPORT=5432
PGDATABASE=gradeops
PGUSER=postgres
PGPASSWORD=your_password

JWT_SECRET_KEY=          # generate: python -c "import secrets; print(secrets.token_hex(32))"

GROQ_API_KEY=            # free at console.groq.com
GROQ_MODEL=openai/gpt-oss-120b
GROQ_FALLBACK_MODELS=openai/gpt-oss-20b,qwen/qwen3.6-27b
VLM_MODEL=qwen/qwen3.6-27b
```
Run it:
```bash
uvicorn main:app --reload
```
Visit `http://127.0.0.1:8000/docs` to confirm it's up.

### 3. Frontend
```bash
cd dashboard
npm install
npm run dev
```
Visit `http://localhost:5173`.

### 4. First-time usage
1. Sign up as a professor
2. Create a course
3. Upload a rubric (JSON — see `rubric/rubric.json` for the expected shape)
4. Upload reference material (`.md`/`.txt` chapter files)
5. Upload a student answer image, tagged with a question ID
6. Grade it, then review/accept/override from the dashboard

---

## Evaluation

### Retrieval quality (Phase 1 baseline, demo dataset)
Hand-labeled 24-question eval set, `all-MiniLM-L6-v2`, dense retrieval only:

| Metric | Score |
|---|---|
| Recall@1 | 0.750 |
| Recall@3 | 0.917 |
| Recall@5 | 0.917 |
| MRR | 0.833 |

Re-validated on real course-scoped data (`evaluation/eval_retrieval_course.py`) with automatic filtering for questions not covered by whatever material has actually been uploaded to that course — perfect scores on the applicable subset, consistent with the baseline, though sample size on course data is still small pending fuller chapter uploads.

### Grading agent validation (Phase 2, qualitative + spot-checked)
Across correct/partial/wrong answer variants for all 4 test questions:
- Correctly detects arithmetic errors (e.g. a miscalculated `20/5 = 10` instead of `4`)
- Correctly detects formula errors (e.g. `f = μ×m` instead of `f = μN`)
- Self-check caught a genuine fabricated citation in testing (cited a chunk for a claim it didn't actually support), while correctly preserving the underlying score
- Self-check also demonstrated a documented over-correction in one case (penalized an OCR-artifact-driven numeric inconsistency), which was fixed with an explicit OCR-leniency instruction in the self-check prompt
- Observed run-to-run score variance in a small number of cases even at temperature=0 — a known characteristic of some hosted inference stacks, worth measuring via repeated-run consistency in addition to single-run human agreement


---

## Known limitations

- **Diagram transcription**: VLMs transcribe hand-drawn diagram *labels* more reliably than *directions* (arrows). The grading prompt includes an explicit leniency rule (award at least half credit when direction can't be confirmed) to avoid penalizing students for this OCR gap rather than a real answer deficiency.
- **Free-tier LLM inference variance**: occasional run-to-run score differences observed even at temperature=0, likely due to batching/hardware nondeterminism on the hosted inference side.

---

## Tech stack

Python · FastAPI · PostgreSQL · React (Vite) · LangGraph · ChromaDB · sentence-transformers · Groq (LLM inference + hosted vision) · Qwen2.5-VL (self-hosted, Colab) · JWT/bcrypt