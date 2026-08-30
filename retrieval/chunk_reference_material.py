"""
Semantic chunker

Strategy:
- Split primarily on ## headers (major sections/concepts)
- Further split on ### headers when present (worked examples, "Check Your
  Understanding" boxes) — these are natural self-contained retrieval units
- If a resulting chunk still exceeds MAX_WORDS, split on blank-line paragraph
  boundaries to keep chunks a reasonable size for embedding + retrieval
- Each chunk keeps metadata: source file, chapter/section title, chunk index
"""

import re
import json
import os
import glob

MAX_WORDS = 400  # soft ceiling per chunk before we force a paragraph split


def split_on_headers(text, level_pattern):
    """Split text into (header_title, body) blocks at a given header level."""
    parts = re.split(level_pattern, text)
    # re.split with a capturing group interleaves [pre, header1, body1, header2, body2, ...]
    blocks = []
    if parts[0].strip():
        blocks.append((None, parts[0]))
    for i in range(1, len(parts), 2):
        header = parts[i].strip()
        body = parts[i + 1] if i + 1 < len(parts) else ""
        blocks.append((header, body))
    return blocks


def split_long_text(text, max_words=MAX_WORDS):
    """Fallback: split an overly long block on blank-line paragraph boundaries."""
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


def strip_image_markdown(text):
    """Remove ![...](...) image lines, keeping the italic caption text that
    follows on the next line (per project decision: captions in, images out)."""
    return re.sub(r"^!\[[^\]]*\]\([^)]*\)\s*$\n?", "", text, flags=re.MULTILINE)


def chunk_file(path):
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    raw = strip_image_markdown(raw)

    filename = os.path.basename(path)
    # Top-level chapter title, e.g. "5.4 Mass and Weight"
    title_match = re.match(r"#\s+(.+)", raw)
    chapter_title = title_match.group(1).strip() if title_match else filename

    # Strip the H1 title line before splitting on H2
    body = re.sub(r"^#\s+.+\n", "", raw, count=1)

    chunks = []
    h2_blocks = split_on_headers(body, r"\n##\s+([^\n#][^\n]*)\n")

    for section_title, section_body in h2_blocks:
        section_label = section_title if section_title else "Introduction"

        # Check for H3 subsections within this H2 block (worked examples, etc.)
        h3_blocks = split_on_headers(section_body, r"\n###\s+([^\n#][^\n]*)\n")

        if len(h3_blocks) == 1 and h3_blocks[0][0] is None:
            # No H3 subsections — treat whole H2 section as one candidate chunk
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
                sub_pieces = split_long_text(content)
                for idx, piece in enumerate(sub_pieces, 1):
                    chunks.append({
                        "text": piece.strip(),
                        "section": f"{label} (part {idx})" if len(sub_pieces) > 1 else label,
                    })
            else:
                chunks.append({"text": content, "section": label})

    # Attach source metadata + stable chunk IDs
    result = []
    for i, c in enumerate(chunks, 1):
        chunk_id = f"{filename.replace('.md', '')}__chunk{i:02d}"
        result.append({
            "chunk_id": chunk_id,
            "source_file": filename,
            "chapter_title": chapter_title,
            "section": c["section"],
            "text": c["text"],
            "word_count": len(c["text"].split()),
        })
    return result


def main():
    # Resolve paths relative to this script's location, so it works regardless
    # of the OS or where the project folder lives. Assumes the structure:
    #   gradeops-plus/
    #     reference_material/*.md
    #     retrieval/chunk_reference_material.py   <- this script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    input_dir = os.path.join(script_dir, "..", "reference_material")
    output_path = os.path.join(script_dir, "chunks.json")

    if not os.path.isdir(input_dir):
        raise FileNotFoundError(
            f"Could not find reference_material folder at: {os.path.abspath(input_dir)}\n"
            f"Expected structure: gradeops-plus/reference_material/*.md and "
            f"gradeops-plus/retrieval/{os.path.basename(__file__)}\n"
            f"If your layout differs, edit 'input_dir' in main() to point to your .md files."
        )

    md_files = sorted(glob.glob(os.path.join(input_dir, "*.md")))
    if not md_files:
        raise FileNotFoundError(
            f"No .md files found in: {os.path.abspath(input_dir)}\n"
            f"Make sure your 11 chapter files are there."
        )

    all_chunks = []
    for path in md_files:
        file_chunks = chunk_file(path)
        all_chunks.extend(file_chunks)
        print(f"{os.path.basename(path)}: {len(file_chunks)} chunks")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_chunks, f, indent=2, ensure_ascii=False)

    word_counts = [c["word_count"] for c in all_chunks]
    print(f"\nTotal chunks: {len(all_chunks)}")
    print(f"Avg words/chunk: {sum(word_counts) / len(word_counts):.0f}")
    print(f"Min/Max words: {min(word_counts)} / {max(word_counts)}")
    print(f"Saved to {output_path}")


if __name__ == "__main__":
    main()