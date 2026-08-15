"""
Ingestion service — the pipeline from Architecture.md, steps 1 to 4 and 7.

    upload → extract → validate → persist → route flagged items to review

Everything here is orchestration. The extraction, the rules and the
calculations each live in their own module and none of them know about the
database.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.extraction.documents import SUPPORTED_SUFFIXES
from app.extraction.pipeline import Extractor, extract
from app.extraction.schema import ExtractionStatus
from app.models.ingestion import (
    Document,
    DocumentStatus,
    Extraction,
    ReviewItem,
    ReviewState,
)
from app.models.user import User
from app.services import audit
from app.validation.validator import validate_extraction

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
# Kept in step with what the extractor can actually read, so the gate and the
# pipeline cannot disagree about what is accepted.
ALLOWED_SUFFIXES = SUPPORTED_SUFFIXES

# Rules.md: "Always validate and sanitize uploaded file contents before
# processing." A filename arrives from a browser and is used to build a path.
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]")


class UploadRejected(Exception):
    pass


def safe_filename(name: str) -> str:
    """Reduce an uploaded filename to something safe to put on disk.

    Path separators and traversal sequences are stripped rather than escaped,
    and the result is never trusted as a directory — every stored file lands
    under a generated UUID directory regardless of what it is called.
    """
    cleaned = _SAFE_NAME.sub("_", Path(name).name).strip("._")
    return cleaned[:200] or "document"


def check_upload(filename: str, content: bytes) -> None:
    if not content:
        raise UploadRejected("The uploaded file is empty.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise UploadRejected(
            f"File is {len(content) / 1_048_576:.1f} MB; the limit is "
            f"{MAX_UPLOAD_BYTES // 1_048_576} MB.")
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise UploadRejected(
            f"{suffix or 'This file type'} is not accepted. Supported: "
            f"{', '.join(sorted(ALLOWED_SUFFIXES))}.")


def storage_root() -> Path:
    """Where uploads land.

    Architecture.md specifies S3-compatible object storage. This is local disk
    behind a single function so swapping it is one change, not a search across
    the codebase. Until that swap, uploads live on the application volume and
    are not replicated.
    """
    root = Path(getattr(settings, "UPLOAD_DIR", "uploads"))
    root.mkdir(parents=True, exist_ok=True)
    return root


@dataclass
class IngestionOutcome:
    document: Document
    extraction: Extraction
    review_items: list[ReviewItem]
    auto_approved: bool

    @property
    def needs_review(self) -> bool:
        return bool(self.review_items)


def ingest(
    db: Session,
    user: User,
    filename: str,
    content: bytes,
    extractor: Extractor,
    request: Request | None = None,
) -> IngestionOutcome:
    """Run one document through the pipeline and persist the result."""
    check_upload(filename, content)

    digest = hashlib.sha256(content).hexdigest()
    existing = db.scalar(
        select(Document).where(
            Document.organization == user.organization,
            Document.content_hash == digest,
        )
    )
    if existing is not None:
        raise UploadRejected(
            f"This file has already been uploaded as {existing.filename!r}. "
            f"Re-running extraction on it is a separate action.")

    stored_name = safe_filename(filename)
    directory = storage_root() / str(uuid.uuid4())
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / stored_name
    path.write_bytes(content)

    document = Document(
        filename=stored_name,
        content_hash=digest,
        byte_size=len(content),
        storage_path=str(path),
        organization=user.organization,
        uploaded_by=user.id,
        status=DocumentStatus.UPLOADED,
    )
    db.add(document)
    db.flush()

    audit.record(
        db, action="ingest.document_uploaded", outcome=audit.SUCCESS,
        actor_email=user.email, organization=user.organization,
        user_id=user.id, resource_type="document", resource_id=str(document.id),
        request=request,
        # Filename and size only. Rules.md forbids raw client financial data in
        # logs, and the extracted values are exactly that.
        detail={"filename": stored_name, "bytes": len(content)},
    )

    result = extract(path, extractor)
    validation = validate_extraction(result)

    extraction = Extraction(
        document_id=document.id,
        organization=user.organization,
        model=result.model,
        status=result.status.value,
        pages_read=result.pages_read,
        error=result.error or None,
        data=result.data.model_dump(mode="json"),
        flags=[
            {"rule_id": f.rule_id, "field": f.field_name,
             "severity": f.severity.value, "message": f.message}
            for f in validation.flags
        ],
        can_calculate=validation.can_calculate,
    )
    db.add(extraction)
    db.flush()

    items = [
        ReviewItem(
            extraction_id=extraction.id,
            organization=user.organization,
            field_name=item.field_name,
            reason=item.reason,
            severity=item.severity.value,
            rule_id=item.rule_id or None,
            observed=item.observed or None,
            source_text=item.source_text or None,
            source_page=item.source_page,
            state=ReviewState.PENDING,
        )
        for item in validation.review_items
    ]
    for item in items:
        db.add(item)

    if result.status is ExtractionStatus.FAILED:
        document.status = DocumentStatus.MANUAL_ENTRY
    elif items:
        document.status = DocumentStatus.NEEDS_REVIEW
    else:
        # PRD.md: "non-flagged items auto-approved".
        document.status = DocumentStatus.APPROVED

    audit.record(
        db, action="ingest.extraction_completed",
        outcome=audit.SUCCESS if result.status is not ExtractionStatus.FAILED
        else audit.FAILURE,
        actor_email=user.email, organization=user.organization,
        user_id=user.id, resource_type="extraction",
        resource_id=str(extraction.id), request=request,
        detail={
            "status": result.status.value,
            "model": result.model,
            "fields_found": len(result.data.fields_found()),
            "flagged": len(items),
            "can_calculate": validation.can_calculate,
        },
        note=result.error or None,
    )

    db.flush()
    return IngestionOutcome(
        document=document, extraction=extraction, review_items=items,
        auto_approved=not items and result.status is not ExtractionStatus.FAILED,
    )


def resolve_review_item(
    db: Session,
    user: User,
    item: ReviewItem,
    state: ReviewState,
    corrected_value: str | None = None,
    note: str | None = None,
    request: Request | None = None,
) -> ReviewItem:
    """Record a reviewer's decision on one flagged field."""
    if state is ReviewState.EDITED and not (corrected_value or "").strip():
        raise ValueError("An edit needs a corrected value.")

    item.state = state
    item.corrected_value = corrected_value if state is ReviewState.EDITED else None
    item.reviewer_note = note
    item.resolved_by = user.id
    item.resolved_at = datetime.now(timezone.utc)

    audit.record(
        db, action=f"review.{state.value.lower()}", outcome=audit.SUCCESS,
        actor_email=user.email, organization=user.organization,
        user_id=user.id, resource_type="review_item", resource_id=str(item.id),
        request=request,
        # Which field, and what was decided — never the value itself.
        detail={"field": item.field_name, "state": state.value,
                "rule_id": item.rule_id},
        note=note,
    )

    outstanding = db.scalars(
        select(ReviewItem).where(
            ReviewItem.extraction_id == item.extraction_id,
            ReviewItem.state == ReviewState.PENDING,
        )
    ).first()

    if outstanding is None:
        extraction = db.get(Extraction, item.extraction_id)
        if extraction is not None:
            document = db.get(Document, extraction.document_id)
            if document is not None:
                document.status = DocumentStatus.APPROVED
                audit.record(
                    db, action="review.document_cleared",
                    outcome=audit.SUCCESS, actor_email=user.email,
                    organization=user.organization, user_id=user.id,
                    resource_type="document", resource_id=str(document.id),
                    request=request)

    db.flush()
    return item
