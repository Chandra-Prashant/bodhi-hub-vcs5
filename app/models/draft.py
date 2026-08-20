"""
Working state that survives a session.

Until now the only things written to the database were documents, extractions
and review items. Everything a person typed — the project details, and the
twelve categories of ESG judgement — lived in the browser tab and nowhere else.
Sign out, refresh, or let an access token expire and an hour of work was gone
with no warning, because the screen went on showing it as saved.

That is worse than losing the work. A save that reports success and stores
nothing is the same failure this system exists to prevent, applied to the user
rather than to a figure: an absence presented as a result.

One row per organisation. The application is single-project at a time by
design — the header says "No project loaded" until one is — so a draft per
organisation matches how it is actually used, and avoids inventing a project
list nobody asked for. When that changes, add a name column and drop the
unique constraint.

The whole working state is stored as one JSON document rather than a column
per field. The shape is the assessment request schema, which is already
versioned and validated on the way in and out; splitting it across columns
would mean a migration every time a field is added to the intake form.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ProjectDraft(Base):
    """The in-progress project for an organisation.

    Not an assessment result. Results are recomputed from this on demand — the
    engine is deterministic, so storing them would create a second source of
    truth that could drift from the inputs.
    """

    __tablename__ = "project_drafts"
    __table_args__ = (
        UniqueConstraint("organization", name="uq_project_drafts_organization"),
    )

    organization: Mapped[str] = mapped_column(String(200), index=True,
                                              nullable=False)

    # Free-text label so a draft is recognisable in a list later. Taken from
    # the project name when there is one.
    label: Mapped[str] = mapped_column(String(500), nullable=False, default="")

    # The assessment request payload, including esg_entries. Validated against
    # AssessmentRequest before it is written, so a malformed draft cannot be
    # stored and then fail on load.
    state: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False,
                                                  default=dict)

    # Who last wrote it. With one draft per organisation two people can
    # overwrite each other, and the record of who did is the minimum needed to
    # untangle that.
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True)
