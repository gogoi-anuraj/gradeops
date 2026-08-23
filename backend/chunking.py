"""
Semantic chunker for uploaded reference material -- same algorithm as
retrieval/chunk_reference_material.py from Phase 1, refactored to operate on
raw text content (from an upload) rather than reading files from a fixed
folder, so it can run per-course, on demand.
"""

import re

MAX_WORDS = 400  # soft ceiling per chunk before forcing a paragraph split


def _strip_image_markdown(text):
    """Remove ![...](...) image lines, keeping the italic caption text that
    follows (captions in, images out -- per the Phase 1 project decision)."""
    return re.sub(r"^!\[[^\]]*\]\([^)]*\)\s*$\n?", "", text, flags=re.MULTILINE)


def _split_on_headers(text, level_pattern):
    parts = re.split(level_pattern, text)
    blocks = []
    if parts[0].strip():
        blocks.append((None, parts[0]))
    for i in range(1, len(parts), 2):
        header = parts[i].strip()
        body = parts[i + 1] if i + 1 < len(parts) else ""
        blocks.append((header, body))
    return blocks


def _split_long_text(text, max_words=MAX_WORDS):
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks = []
    current = []
    current_words = 0
    for p in paragraphs:
        w = len(p.split())
        if current_words + w > max_words and current:
            chunks.append("\n\n".join(current))
            current = [p]
            current_words = w
        else:
            current.append(p)
            current_words += w
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def chunk_markdown(raw_text: str, filename: str) -> list[dict]:
    """Chunk a single markdown document's raw text into retrieval-ready
    chunks. Returns a list of dicts with chunk_id, source_file, chapter_title,
    section, text, word_count -- same shape as Phase 1's chunks.json entries."""
    raw_text = _strip_image_markdown(raw_text)

    title_match = re.match(r"#\s+(.+)", raw_text)
    chapter_title = title_match.group(1).strip() if title_match else filename

    body = re.sub(r"^#\s+.+\n", "", raw_text, count=1)

    chunks = []
    h2_blocks = _split_on_headers(body, r"\n##\s+([^\n#][^\n]*)\n")

    for section_title, section_body in h2_blocks:
        section_label = section_title if section_title else "Introduction"
        h3_blocks = _split_on_headers(section_body, r"\n###\s+([^\n#][^\n]*)\n")

        if len(h3_blocks) == 1 and h3_blocks[0][0] is None:
            candidates = [(section_label, section_body)]
        else:
            candidates = []
            for sub_title, sub_body in h3_blocks:
                label = f"{section_label} — {sub_title}" if sub_title else section_label
                candidates.append((label, sub_body))

        for label, content in candidates:
            content = content.strip()
            if not content:
                continue
            word_count = len(content.split())
            if word_count > MAX_WORDS:
                sub_pieces = _split_long_text(content)
                for idx, piece in enumerate(sub_pieces, 1):
                    chunks.append({
                        "text": piece.strip(),
                        "section": f"{label} (part {idx})" if len(sub_pieces) > 1 else label,
                    })
            else:
                chunks.append({"text": content, "section": label})

    base_name = re.sub(r"\.(md|txt)$", "", filename, flags=re.IGNORECASE)
    result = []
    for i, c in enumerate(chunks, 1):
        chunk_id = f"{base_name}__chunk{i:02d}"
        result.append({
            "chunk_id": chunk_id,
            "source_file": filename,
            "chapter_title": chapter_title,
            "section": c["section"],
            "text": c["text"],
            "word_count": len(c["text"].split()),
        })
    return result