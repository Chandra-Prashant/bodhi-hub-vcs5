"""
Chunking for the historical report index.

The usual approach — fixed-size overlapping windows — is wrong for this corpus.
We are retrieving *structure and style*, so the useful unit of retrieval is a
section: how Bodhi-hub opens a findings section, how long it runs, what order
the points come in. A 500-character window sliced across a heading gives a
model half a sentence from one section and half from another, which teaches it
nothing about either.

So chunks follow the document's own headings, and carry the heading with them.
Oversized sections are split at paragraph boundaries rather than mid-sentence,
because a truncated clause is worse than a slightly short chunk.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

MAX_CHARS = 2400
MIN_CHARS = 120

# A heading in these documents: numbered, all-caps, or short and title-cased on
# its own line.
_HEADING = re.compile(
    r"^\s*(?:"
    r"\d+(?:\.\d+)*\.?\s+\S.{0,80}"          # 3.2 Findings
    r"|[A-Z][A-Z \d&/,'()-]{4,80}"           # FINDINGS AND RECOMMENDATIONS
    r"|(?:[A-Z][a-z]+\s+){0,6}[A-Z][a-z]+"   # Findings and Recommendations
    r")\s*$"
)


@dataclass(frozen=True)
class Chunk:
    text: str
    heading: str
    ordinal: int
    source: str

    @property
    def char_count(self) -> int:
        return len(self.text)


def _looks_like_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped or len(stripped) > 100:
        return False
    if stripped.endswith((".", ",", ";", ":")) and not re.match(r"^\d", stripped):
        # A sentence, not a heading — except numbered headings often end in a
        # full stop ("3.2. Findings").
        return False
    return bool(_HEADING.match(stripped))


def _split_oversized(text: str, limit: int = MAX_CHARS) -> list[str]:
    """Split at paragraph boundaries, never mid-sentence."""
    if len(text) <= limit:
        return [text]

    parts: list[str] = []
    current = ""
    for paragraph in re.split(r"\n\s*\n", text):
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) > limit and current:
            parts.append(current.strip())
            current = paragraph
        else:
            current = candidate
    if current.strip():
        parts.append(current.strip())

    # A single paragraph longer than the limit: split on sentence ends.
    final: list[str] = []
    for part in parts:
        if len(part) <= limit:
            final.append(part)
            continue
        sentences = re.split(r"(?<=[.!?])\s+", part)
        buffer = ""
        for sentence in sentences:
            if len(buffer) + len(sentence) > limit and buffer:
                final.append(buffer.strip())
                buffer = sentence
            else:
                buffer = f"{buffer} {sentence}".strip()
        if buffer.strip():
            final.append(buffer.strip())
    return final


def chunk_text(text: str, source: str = "") -> list[Chunk]:
    """Split a document into section-level chunks, each carrying its heading."""
    lines = text.splitlines()
    sections: list[tuple[str, list[str]]] = []
    heading = ""
    body: list[str] = []

    for line in lines:
        if _looks_like_heading(line):
            if body and any(l.strip() for l in body):
                sections.append((heading, body))
            heading = line.strip()
            body = []
        else:
            body.append(line)
    if body and any(l.strip() for l in body):
        sections.append((heading, body))

    chunks: list[Chunk] = []
    ordinal = 0
    for section_heading, section_body in sections:
        content = "\n".join(section_body).strip()
        if len(content) < MIN_CHARS:
            # Too short to teach anything about style on its own; fold it into
            # the previous chunk rather than indexing a fragment.
            if chunks and content:
                previous = chunks[-1]
                merged = f"{previous.text}\n\n{section_heading}\n{content}".strip()
                chunks[-1] = Chunk(merged, previous.heading, previous.ordinal,
                                   previous.source)
            continue

        for part in _split_oversized(content):
            chunks.append(Chunk(
                text=part,
                heading=section_heading,
                ordinal=ordinal,
                source=source,
            ))
            ordinal += 1

    if not chunks and text.strip():
        # No headings found at all — fall back to paragraph splitting so a
        # flat document still indexes rather than being silently skipped.
        for part in _split_oversized(text.strip()):
            chunks.append(Chunk(part, "", ordinal, source))
            ordinal += 1

    return chunks


def chunk_file(path: Path) -> list[Chunk]:
    from app.extraction.pipeline import load_text

    text, _pages = load_text(path)
    return chunk_text(text, source=path.name)
