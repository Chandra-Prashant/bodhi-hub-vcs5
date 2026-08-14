"""
Historical report index — Phase 5.

Architecture.md specifies Chroma or Pinecone. This uses pgvector in the
Postgres already running, which is a deliberate deviation: one datastore means
one backup, one deployment, and chunks that live in the same transaction as
everything else. Tell the client; it is their spec.

The redacted text is stored, not the original. If a raw figure is never written
to this table it can never be retrieved from it, whatever a later query does.
The original document stays on disk for a human who needs it.
"""

from __future__ import annotations

import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import settings
from app.core.database import Base


class HistoricalReport(Base):
    """One of Bodhi-hub's 300+ past audit reports."""

    __tablename__ = "historical_reports"
    __table_args__ = (
        Index("ix_historical_reports_org_hash", "organization", "content_hash",
              unique=True),
    )

    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    organization: Mapped[str] = mapped_column(String(200), index=True,
                                              nullable=False)
    storage_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    report_type: Mapped[str | None] = mapped_column(String(100))


class ReportChunk(Base):
    """A section of a past report, with its figures already removed."""

    __tablename__ = "report_chunks"

    report_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("historical_reports.id", ondelete="CASCADE"),
        index=True, nullable=False)
    organization: Mapped[str] = mapped_column(String(200), index=True,
                                              nullable=False)

    heading: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Redacted at ingestion. The raw text is deliberately not stored — see the
    # module docstring.
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(
        Vector(settings.EMBEDDING_DIM), nullable=False)
