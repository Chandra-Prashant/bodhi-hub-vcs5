"""
Ingestion and review records — Phases 3, 4, 7 and 8.

Architecture.md puts versioning and history in `audit_log/`; PRD.md requires
"audit log / version history for every extraction, calculation, edit, and
approval". These tables are that history.

A note on what is NOT stored here. Rules.md: "Never log raw farm/client
financial data in plaintext logs." The audit trail records that a field was
edited, by whom and when — it does not record the value. The values live in the
extraction record, which is scoped to an organization and reachable only
through an authenticated route; the log is a different artefact with different
retention and a wider readership.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DocumentStatus(str, enum.Enum):
    UPLOADED = "UPLOADED"
    EXTRACTED = "EXTRACTED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    MANUAL_ENTRY = "MANUAL_ENTRY"   # extraction failed; a person types it in
    APPROVED = "APPROVED"


class Document(Base):
    """An uploaded source document."""

    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_documents_org_created", "organization", "created_at"),
        Index("ix_documents_project_created", "project_id", "created_at"),
        # Same file uploaded twice into the SAME PROJECT is the same document.
        # Deliberately scoped to the project, not the organisation: the same
        # grid study can legitimately support two projects, and refusing the
        # second upload would force a rename to work around it.
        Index("ix_documents_project_hash", "project_id", "content_hash",
              unique=True),
    )

    # Nullable only so the migration can run against existing rows. Every new
    # document has one; the upload route requires it.
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=True, index=True)

    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    organization: Mapped[str] = mapped_column(String(200), index=True,
                                              nullable=False)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus, name="document_status"),
        default=DocumentStatus.UPLOADED, nullable=False)


class Extraction(Base):
    """One extraction attempt over one document.

    Attempts are kept rather than overwritten. Re-running extraction after a
    model change produces a new row, so a report issued last month can still be
    traced to the extraction it was actually built from.
    """

    __tablename__ = "extractions"

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"),
        index=True, nullable=False)
    organization: Mapped[str] = mapped_column(String(200), index=True,
                                              nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    pages_read: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)

    # The full ProjectExtraction, fields and provenance together.
    data: Mapped[dict | None] = mapped_column(JSONB)
    # Rule flags at the time of extraction.
    flags: Mapped[list | None] = mapped_column(JSONB)
    can_calculate: Mapped[bool] = mapped_column(default=False, nullable=False)


class ReviewState(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    EDITED = "EDITED"
    REJECTED = "REJECTED"


class ReviewItem(Base):
    """One thing a reviewer has to act on, and what they did about it.

    PRD.md: "Human review dashboard — only flagged items require manual
    review." One row per flagged field, not per document.
    """

    __tablename__ = "review_items"
    __table_args__ = (
        Index("ix_review_items_org_state", "organization", "state"),
    )

    extraction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("extractions.id", ondelete="CASCADE"),
        index=True, nullable=False)
    organization: Mapped[str] = mapped_column(String(200), index=True,
                                              nullable=False)

    field_name: Mapped[str] = mapped_column(String(100), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    rule_id: Mapped[str | None] = mapped_column(String(100))
    observed: Mapped[str | None] = mapped_column(Text)
    source_text: Mapped[str | None] = mapped_column(Text)
    source_page: Mapped[int | None] = mapped_column(Integer)

    state: Mapped[ReviewState] = mapped_column(
        Enum(ReviewState, name="review_state"),
        default=ReviewState.PENDING, nullable=False)
    corrected_value: Mapped[str | None] = mapped_column(Text)
    reviewer_note: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
