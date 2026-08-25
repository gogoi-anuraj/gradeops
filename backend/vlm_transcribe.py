"""
Live OCR/transcription for student answer image uploads, via Groq's
qwen/qwen3.6-27b -- a genuinely vision-capable model hosted directly by
Groq (confirmed available on this project's account via list_groq_models.py),
not routed through a third-party aggregator. Reuses the SAME GROQ_API_KEY
already used for grading -- no separate account or key needed.

Note: Groq documents this model as "preview" (evaluation-stage, not
guaranteed-stable production infra) -- fine for this project's scope.

Setup: already installed (groq package used elsewhere in this project).

Add to backend/.env (same key you already use for grading):
    GROQ_API_KEY=your_groq_api_key
    VLM_MODEL=qwen/qwen3.6-27b
"""

import os
import base64
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
VLM_MODEL = os.environ.get("VLM_MODEL", "qwen/qwen3.6-27b")

TRANSCRIPTION_PROMPT = """You are transcribing a student's handwritten exam answer for automated grading.

Transcribe EXACTLY what is written in the image, including:
- All handwritten text, word for word
- Mathematical equations and formulas (write them in plain text, e.g. "F = ma", "a = 4 m/s^2")
- If there is a free-body diagram or sketch, describe it in words: what shapes/objects are drawn,
  what force vectors are shown (labeled with direction, e.g. "arrow pointing up labeled N"), and
  any labels present

Do not correct spelling or grammar. Do not add commentary or grade the answer. Just transcribe
faithfully what is on the page, in the same order it appears.

Output only the transcription, nothing else."""

_client = None


def _get_client():
    global _client
    if _client is None:
        if not GROQ_API_KEY:
            raise EnvironmentError(
                "GROQ_API_KEY not set. Add to backend/.env (same key used for grading):\n"
                "  GROQ_API_KEY=your_groq_api_key\n"
                "  VLM_MODEL=qwen/qwen3.6-27b"
            )
        _client = Groq(api_key=GROQ_API_KEY)
    return _client


def transcribe_image_bytes(image_bytes: bytes, filename: str) -> str:
    """Transcribe a handwritten answer image (raw bytes, as received from an
    upload) using a vision-capable LLM. Returns the transcribed text."""
    client = _get_client()

    ext = os.path.splitext(filename)[1].lower().lstrip(".")
    if ext == "jpg":
        ext = "jpeg"
    if ext not in ("jpeg", "png", "webp", "gif"):
        ext = "jpeg"  # reasonable fallback for unrecognized extensions

    b64_image = base64.b64encode(image_bytes).decode("utf-8")

    response = client.chat.completions.create(
        model=VLM_MODEL,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": TRANSCRIPTION_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/{ext};base64,{b64_image}"},
                    },
                ],
            }
        ],
        max_completion_tokens=2000,
        temperature=0,
        reasoning_effort="none",  # qwen3.6 is a reasoning model by default -- this
                                   # disables the <think>...</think> preamble, since
                                   # we want direct transcription output, not reasoning
    )
    raw_output = response.choices[0].message.content.strip()

    # Defensive fallback: if a <think> block slipped through anyway (e.g. if
    # reasoning_effort isn't honored for some request), strip it and keep only
    # whatever follows the closing tag.
    if "<think>" in raw_output:
        if "</think>" in raw_output:
            raw_output = raw_output.split("</think>", 1)[1].strip()
        else:
            # Truncated mid-thought with no closing tag -- nothing usable follows
            raise RuntimeError(
                "Model response was cut off mid-reasoning with no final answer "
                "reached. Try increasing max_completion_tokens further."
            )

    return raw_output