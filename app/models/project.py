"""
Projects.

Until now a document belonged to an organisation and there was one working
draft per organisation, which assumed one project at a time. Real use is a
carbon advisory carrying several projects at once, each with its own bundle of
source documents — a project information memorandum, a technical report, a
financial model, a land schedule.

A project is the unit everything else hangs from: documents, the working state,
and the assessment produced from them. Nothing crosses between projects. Two
projects in the same organisation are as separate as two organisations, because
mixing a capacity figure from one project into another's Project Description
would be the worst failure this system could produce.

Deleting a project takes its documents and draft with it. That is intentional:
a document has no meaning outside the project it describes, and leaving orphans
would give the next assessment a source nobody can place.
"""

from __future__ import annotations

import enum
import uuid
from typing import Any

from sqlalchemy import Enum, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ProjectStatus(str, enum.Enum):
    DRAFT = "DRAFT"           # being assembled
    IN_REVIEW = "IN_REVIEW"   # under internal review
    SUBMITTED = "SUBMITTED"   # sent to a validation body
    ARCHIVED = "ARCHIVED"     # closed, kept for the record


class Project(Base):
    """One carbon project under assessment."""

    __tablename__ = "projects"
    __table_args__ = (
        Index("ix_projects_org_created", "organization", "created_at"),
        # Two projects with the same name in one organisation would be
        # indistinguishable in a selector, and picking the wrong one is exactly
        # the mistake that must not be easy to make.
        Index("ix_projects_org_name", "organization", "name", unique=True),
    )

    name: Mapped[str] = mapped_column(String(300), nullable=False)
    organization: Mapped[str] = mapped_column(String(200), index=True,
                                              nullable=False)
    status: Mapped[ProjectStatus] = mapped_column(
        Enum(ProjectStatus, native_enum=False, length=20),
        default=ProjectStatus.DRAFT, nullable=False)

    # Free text for whoever picks this up in six months.
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True)

    # The working state — the assessment request payload including ESG
    # entries. Stored on the project itself rather than in a separate table:
    # it is one row per project, always loaded with it, and never queried
    # independently.
    state: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict,
                                                  nullable=False)
