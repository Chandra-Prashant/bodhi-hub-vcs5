"""
Document ingestion and review API — Phases 3, 4 and 7.

Every route is organization-scoped. A reviewer at one firm must never see
another firm's farm data, and that is enforced on each query rather than
assumed from the token.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from sqlalchemy import case, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.config import settings
from app.core.database import get_db
from app.extraction.pipeline import GeminiExtractor
from app.models.ingestion import (
    Document,
    DocumentStatus,
    Extraction,
    ReviewItem,
    ReviewState,
)
from app.models.user import Role, User
from app.schemas.ingestion import (
    DocumentOut,
    ExtractionOut,
    ResolveReviewIn,
    ReviewItemOut,
    UploadResponse,
)
from app.services.ingestion import (
    UploadRejected,
    ingest,
    resolve_review_item,
)

router = APIRouter(prefix="/documents", tags=["Documents & Review"])

# Blocking items first. Sorted in the database rather than in Python so the
# ordering survives pagination — sorting a page after fetching it would put
# the wrong items on page one.
_SEVERITY_ORDER = case(
    {"ERROR": 0, "WARNING": 1, "INFO": 2},
    value=ReviewItem.severity,
    else_=3,
)


def _extractor():
    if not settings.GEMINI_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No extraction model configured. Set GEMINI_API_KEY.")
    return GeminiExtractor(settings.GEMINI_API_KEY, settings.GEMINI_MODEL)


@router.post("/upload", response_model=UploadResponse,
             status_code=status.HTTP_201_CREATED)
async def upload(
    request: Request,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UploadResponse:
    """Upload a document, extract it, validate it, and queue what needs review."""
    content = await file.read()
    try:
        outcome = ingest(db, user, file.filename or "document", content,
                         _extractor(), request)
    except UploadRejected as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=str(exc))
    return UploadResponse.of(outcome)


@router.get("", response_model=list[DocumentOut])
def list_documents(
    document_status: DocumentStatus | None = None,
    limit: int = 50,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Document]:
    stmt = select(Document).where(Document.organization == user.organization)
    if document_status is not None:
        stmt = stmt.where(Document.status == document_status)
    return list(db.scalars(
        stmt.order_by(Document.created_at.desc()).limit(min(limit, 200))))


@router.get("/queue", response_model=list[ReviewItemOut])
def review_queue(
    limit: int = 100,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ReviewItem]:
    """Everything awaiting a reviewer, blocking items first.

    PRD.md: "only flagged items require manual review". This is that queue —
    it holds fields, not documents, so a reviewer touches the three uncertain
    values rather than re-checking a whole report.
    """
    return list(db.scalars(
        select(ReviewItem)
        .where(
            ReviewItem.organization == user.organization,
            ReviewItem.state == ReviewState.PENDING,
        )
        .order_by(_SEVERITY_ORDER, ReviewItem.created_at)
        .limit(min(limit, 500))))


@router.get("/{document_id}/extraction", response_model=ExtractionOut)
def latest_extraction(
    document_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Extraction:
    extraction = db.scalars(
        select(Extraction)
        .where(
            Extraction.document_id == document_id,
            Extraction.organization == user.organization,
        )
        .order_by(Extraction.created_at.desc())
    ).first()
    if extraction is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="No extraction found for that document.")
    return extraction


@router.post("/review/{item_id}", response_model=ReviewItemOut)
def resolve(
    item_id: uuid.UUID,
    payload: ResolveReviewIn,
    request: Request,
    user: User = Depends(require_roles(Role.ADMIN, Role.AUDITOR)),
    db: Session = Depends(get_db),
) -> ReviewItem:
    """Approve, edit or reject one flagged field."""
    item = db.get(ReviewItem, item_id)
    if item is None or item.organization != user.organization:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Review item not found.")
    if item.state is not ReviewState.PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Already resolved as {item.state.value} — reopening is not "
                   f"supported, since the decision is part of the audit trail.")

    try:
        resolved = resolve_review_item(
            db, user, item, payload.state, payload.corrected_value,
            payload.note, request)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=str(exc))
    return resolved
