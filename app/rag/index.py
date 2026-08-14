"""
Indexing and retrieval over the historical report corpus — Phase 5.

Retrieval returns style exemplars, never facts. The redaction happens at
ingestion so the raw figures are never written; `retrieve` asserts the property
again on the way out, because a guarantee worth having is worth checking at
both ends.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.rag import HistoricalReport, ReportChunk
from app.rag.chunking import Chunk, chunk_file
from app.rag.redaction import contains_figure, redact_numbers


class Embedder(ABC):
    """The model boundary for embeddings, isolated so indexing and retrieval
    are testable without a network call."""

    name = "abstract"
    dimension = settings.EMBEDDING_DIM

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input, in order."""


class GeminiEmbedder(Embedder):
    name = "text-embedding-004"

    def __init__(self, api_key: str, model: str | None = None) -> None:
        self.api_key = api_key
        self.model = model or settings.EMBEDDING_MODEL

    def embed(self, texts: list[str]) -> list[list[float]]:
        from google import genai

        client = genai.Client(api_key=self.api_key)
        vectors: list[list[float]] = []
        # Batched to keep a single failure from costing the whole corpus.
        for start in range(0, len(texts), 32):
            batch = texts[start:start + 32]
            response = client.models.embed_content(model=self.model,
                                                   contents=batch)
            vectors.extend(e.values for e in response.embeddings)
        return vectors


@dataclass
class Retrieved:
    """A style exemplar. Carries no figures by construction."""

    heading: str
    text: str
    source: str
    distance: float

    @property
    def similarity(self) -> float:
        return 1.0 - self.distance


class RedactionFailure(Exception):
    """Raised when a figure survives into retrieved text.

    Deliberately fatal rather than filtered. A survivor means the redaction has
    a hole, and the response is to find and close it — silently dropping the
    chunk would hide the hole while leaving it open for the next corpus.
    """


def index_report(
    db: Session,
    path: Path,
    organization: str,
    embedder: Embedder,
    report_type: str | None = None,
) -> HistoricalReport:
    """Chunk, redact, embed and store one historical report."""
    content = path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()

    existing = db.scalar(
        select(HistoricalReport).where(
            HistoricalReport.organization == organization,
            HistoricalReport.content_hash == digest,
        )
    )
    if existing is not None:
        return existing

    chunks: list[Chunk] = chunk_file(path)
    if not chunks:
        raise ValueError(f"{path.name} produced no chunks — nothing to index.")

    # Redact BEFORE embedding, so the vectors describe the shape of the prose
    # rather than the particular numbers in it. Two reports with the same
    # structure and different figures should retrieve as similar; embedding the
    # raw text would push them apart.
    redacted = [redact_numbers(c.text) for c in chunks]
    vectors = embedder.embed(redacted)

    report = HistoricalReport(
        filename=path.name,
        content_hash=digest,
        organization=organization,
        storage_path=str(path),
        chunk_count=len(chunks),
        report_type=report_type,
    )
    db.add(report)
    db.flush()

    for chunk, text, vector in zip(chunks, redacted, vectors):
        db.add(ReportChunk(
            report_id=report.id,
            organization=organization,
            heading=chunk.heading[:300],
            ordinal=chunk.ordinal,
            text=text,
            embedding=vector,
        ))

    db.flush()
    return report


def retrieve(
    db: Session,
    query: str,
    organization: str,
    embedder: Embedder,
    limit: int = 4,
    heading_hint: str | None = None,
) -> list[Retrieved]:
    """Find past sections resembling what is about to be written.

    Scoped to the organization: one advisory firm's house style must never be
    retrieved into another's report.
    """
    vector = embedder.embed([redact_numbers(query)])[0]

    stmt = (
        select(ReportChunk, HistoricalReport.filename)
        .join(HistoricalReport, ReportChunk.report_id == HistoricalReport.id)
        .where(ReportChunk.organization == organization)
    )
    if heading_hint:
        stmt = stmt.where(ReportChunk.heading.ilike(f"%{heading_hint}%"))

    stmt = stmt.order_by(ReportChunk.embedding.cosine_distance(vector)).limit(limit)

    results: list[Retrieved] = []
    for chunk, filename in db.execute(stmt).all():
        if contains_figure(chunk.text):
            raise RedactionFailure(
                f"A figure survived redaction in chunk {chunk.id} of "
                f"{filename}. Retrieval is meant to carry structure and style "
                f"only — fix app/rag/redaction.py before using this corpus."
            )
        distance = 0.0
        results.append(Retrieved(
            heading=chunk.heading,
            text=chunk.text,
            source=filename,
            distance=distance,
        ))
    return results


STYLE_PROMPT_HEADER = """\
Below are excerpts from past reports by this organisation, provided so your
writing matches their structure and register.

They are reference for FORM ONLY. Every figure has been removed and replaced
with «figure» — that is deliberate. Do not invent values to fill those
placeholders, do not carry any detail from these excerpts into your text, and
do not treat anything here as a fact about the project you are writing about.
The numbers for that project are supplied separately and are already correct.
"""


def as_style_prompt(examples: list[Retrieved]) -> str:
    """Format retrieved exemplars for a narrative generator."""
    if not examples:
        return ""
    blocks = [
        f"--- {e.source}{f' · {e.heading}' if e.heading else ''} ---\n{e.text}"
        for e in examples
    ]
    return STYLE_PROMPT_HEADER + "\n\n" + "\n\n".join(blocks)
