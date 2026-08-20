"""Request and response shapes for projects."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.project import Project, ProjectStatus


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    note: str = ""


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=300)
    note: str | None = None
    status: ProjectStatus | None = None


class ProjectOut(BaseModel):
    id: uuid.UUID
    name: str
    status: str
    note: str
    document_count: int
    # The saved working state. Returned with the project so switching does not
    # need a second round trip.
    state: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, project: Project, document_count: int) -> "ProjectOut":
        return cls(
            id=project.id,
            name=project.name,
            status=project.status.value,
            note=project.note,
            document_count=document_count,
            state=project.state or None,
            created_at=project.created_at,
            updated_at=project.updated_at,
        )
