"""
Merging several documents into one set of values.

A project is described by a bundle of documents — an information memorandum, a
technical report, a financial model, a land schedule. Each is extracted
separately, and each may state some of the same fields.

Two questions follow, and only one of them is technical.

**Where did this value come from?** Recorded per field: the document, the page
and the sentence. Without it a reviewer looking at a corrected capacity across
ten uploads has no way to know which file to open.

**What happens when two documents disagree?** The memorandum says 50 MW and the
technical report says 49.5 MW. Three answers were available:

- take the most recent document, which is silently wrong the day somebody
  uploads an old file last;
- take the highest confidence, which sounds principled and is not — confidence
  measures how clearly the value was *read*, not whether it is *right*;
- treat the disagreement as a finding for a person.

The third is the only one that does not invent an answer, and it is the same
rule the rest of this system follows: where the evidence conflicts, say so.
A conflict blocks calculation until a reviewer picks a value, and the review
item shows both figures with the filename each came from.

The cost is real — a reviewer has to resolve conflicts that a silent rule would
have hidden. That is the point. A capacity that differs between two source
documents is a fact about the project, not noise, and a Project Description
built on the wrong one is exactly the failure this system exists to prevent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ingestion import Document, Extraction


@dataclass(frozen=True)
class Provenance:
    """Where one value came from."""

    document_id: str
    filename: str
    page: int | None
    source_text: str
    score: float


def _normalise(value: Any) -> str:
    """A comparable form. Numbers that differ only in formatting are equal."""
    text = str(value).strip().lower().replace(",", "")
    try:
        return f"{float(text):.6g}"
    except (TypeError, ValueError):
        return text


@dataclass
class MergeResult:
    """Values merged across a project's documents."""

    values: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, list[Provenance]] = field(default_factory=dict)
    # field name -> [(value, provenance), ...] for fields where documents
    # disagree. These block calculation until a reviewer chooses.
    conflicts: dict[str, list[tuple[Any, Provenance]]] = field(
        default_factory=dict)

    @property
    def blocked(self) -> bool:
        return bool(self.conflicts)

    def describe_conflicts(self) -> list[str]:
        lines = []
        for name, options in sorted(self.conflicts.items()):
            rendered = "; ".join(
                f"{value!r} in {p.filename}"
                + (f" p{p.page}" if p.page else "")
                for value, p in options)
            lines.append(f"{name}: {rendered}")
        return lines


def merge_project_extractions(db: Session, project_id, organization: str
                              ) -> MergeResult:
    """Combine the latest extraction from every document in a project.

    Documents are read oldest first so that, where there is no conflict, the
    provenance list reads in upload order — which is the order a person
    remembers adding them in.
    """
    result = MergeResult()
    collected: dict[str, list[tuple[Any, Provenance]]] = {}

    documents = db.scalars(
        select(Document)
        .where(Document.project_id == project_id,
               Document.organization == organization)
        .order_by(Document.created_at)
    ).all()

    for document in documents:
        extraction = db.scalar(
            select(Extraction)
            .where(Extraction.document_id == document.id)
            .order_by(Extraction.created_at.desc())
            .limit(1))
        if extraction is None or not extraction.data:
            continue

        for name, entry in extraction.data.items():
            if not isinstance(entry, dict):
                continue
            value = entry.get("value")
            if value is None:
                continue
            collected.setdefault(name, []).append((
                value,
                Provenance(
                    document_id=str(document.id),
                    filename=document.filename,
                    page=entry.get("source_page"),
                    source_text=entry.get("source_text", ""),
                    score=float(entry.get("score") or 0.0),
                ),
            ))

    for name, options in collected.items():
        distinct = {_normalise(value) for value, _ in options}
        result.provenance[name] = [p for _, p in options]
        if len(distinct) > 1:
            # Deliberately NOT resolved here. See the module docstring.
            result.conflicts[name] = options
        else:
            result.values[name] = options[0][0]

    return result
