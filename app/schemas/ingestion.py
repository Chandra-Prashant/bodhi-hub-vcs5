from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.ingestion import DocumentStatus, ReviewState


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    byte_size: int
    status: DocumentStatus
    created_at: datetime


class ReviewItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    extraction_id: uuid.UUID
    field_name: str
    reason: str
    severity: str
    rule_id: str | None
    observed: str | None
    source_text: str | None
    source_page: int | None
    state: ReviewState
    corrected_value: str | None
    created_at: datetime


class ExtractionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    model: str
    status: str
    pages_read: int
    error: str | None
    data: dict | None
    flags: list | None
    can_calculate: bool


class UploadResponse(BaseModel):
    document: DocumentOut
    extraction: ExtractionOut
    review_items: list[ReviewItemOut]
    auto_approved: bool

    @classmethod
    def of(cls, outcome) -> "UploadResponse":
        return cls(
            document=DocumentOut.model_validate(outcome.document),
            extraction=ExtractionOut.model_validate(outcome.extraction),
            review_items=[ReviewItemOut.model_validate(i)
                          for i in outcome.review_items],
            auto_approved=outcome.auto_approved,
        )


class ResolveReviewIn(BaseModel):
    state: ReviewState
    corrected_value: str | None = Field(default=None, max_length=2000)
    note: str | None = Field(default=None, max_length=2000)
