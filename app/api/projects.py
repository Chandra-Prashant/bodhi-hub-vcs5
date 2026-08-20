"""
Project routes.

The working state lives on the project rather than on the organisation, so
switching project switches everything: documents, review queue, ESG entries and
the assessment built from them.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.database import get_db
from app.models.ingestion import Document
from app.models.project import Project, ProjectStatus
from app.models.user import Role, User
from app.schemas.assessment import AssessmentRequest
from app.schemas.project import ProjectCreate, ProjectOut, ProjectUpdate
from app.services import audit

router = APIRouter(prefix="/projects", tags=["projects"])


def _get(db: Session, project_id: uuid.UUID, user: User) -> Project:
    """Fetch a project, or 404.

    Scoped to the caller's organisation, and 404 rather than 403 for another
    organisation's id: whether a project exists elsewhere is not something a
    stranger should be able to learn.
    """
    project = db.get(Project, project_id)
    if project is None or project.organization != user.organization:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Project not found.")
    return project


@router.get("", response_model=list[ProjectOut])
def list_projects(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ProjectOut]:
    """Every project in the organisation, newest first, with document counts."""
    counts = dict(
        db.execute(
            select(Document.project_id, func.count(Document.id))
            .where(Document.organization == user.organization)
            .group_by(Document.project_id)
        ).all()
    )
    projects = db.scalars(
        select(Project)
        .where(Project.organization == user.organization)
        .order_by(Project.created_at.desc())
    ).all()
    return [ProjectOut.of(p, counts.get(p.id, 0)) for p in projects]


@router.post("", response_model=ProjectOut,
             status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProjectOut:
    project = Project(
        name=payload.name.strip(),
        organization=user.organization,
        note=payload.note or "",
        created_by=user.id,
        state={},
    )
    db.add(project)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A project named {payload.name.strip()!r} already exists. "
                   f"Two projects with the same name are indistinguishable in "
                   f"the selector, and picking the wrong one is the mistake "
                   f"this prevents.")

    audit.record(
        db, action="project.created", outcome=audit.SUCCESS,
        actor_email=user.email, organization=user.organization,
        user_id=user.id, resource_type="project", resource_id=str(project.id),
        request=request, detail={"name": project.name})
    db.flush()
    return ProjectOut.of(project, 0)


@router.get("/{project_id}", response_model=ProjectOut)
def read_project(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProjectOut:
    project = _get(db, project_id, user)
    count = db.scalar(
        select(func.count(Document.id))
        .where(Document.project_id == project.id)) or 0
    return ProjectOut.of(project, count)


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: uuid.UUID,
    payload: ProjectUpdate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProjectOut:
    project = _get(db, project_id, user)
    changed: list[str] = []

    if payload.name is not None and payload.name.strip() != project.name:
        project.name = payload.name.strip()
        changed.append("name")
    if payload.note is not None and payload.note != project.note:
        project.note = payload.note
        changed.append("note")
    if payload.status is not None and payload.status != project.status:
        project.status = ProjectStatus(payload.status)
        changed.append("status")

    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="A project with that name already exists.")

    if changed:
        audit.record(
            db, action="project.updated", outcome=audit.SUCCESS,
            actor_email=user.email, organization=user.organization,
            user_id=user.id, resource_type="project",
            resource_id=str(project.id), request=request,
            detail={"changed": changed})
        db.flush()

    count = db.scalar(
        select(func.count(Document.id))
        .where(Document.project_id == project.id)) or 0
    return ProjectOut.of(project, count)


@router.put("/{project_id}/state")
def write_state(
    project_id: uuid.UUID,
    payload: AssessmentRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Save the working state for this project.

    Validated as a full AssessmentRequest before storage, so state that cannot
    be loaded can never be written.
    """
    project = _get(db, project_id, user)
    project.state = payload.model_dump(mode="json")
    db.flush()

    audit.record(
        db, action="project.state_saved", outcome=audit.SUCCESS,
        actor_email=user.email, organization=user.organization,
        user_id=user.id, resource_type="project", resource_id=str(project.id),
        request=request,
        detail={"esg_entries": len(payload.esg_entries)})
    db.flush()
    return {"saved": True, "updated_at": project.updated_at.isoformat()}


@router.post("/{project_id}/assess")
def assess_project(
    project_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Run the assessment across every document in the project.

    Values are merged from all of them. Where two documents state different
    values for the same field the merge refuses rather than choosing — see
    app/services/merge.py for why — and the response names both figures with
    the file each came from.
    """
    from app.api.assessment import _run
    from app.schemas.assessment import AssessmentResponse
    from app.services.handover import HandoverRefused, build_assessment_payload
    from app.services.merge import merge_project_extractions

    project = _get(db, project_id, user)
    merged = merge_project_extractions(db, project.id, user.organization)

    if merged.blocked:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "Documents disagree. Choose a value before "
                           "calculating.",
                "conflicts": [
                    {
                        "field": name,
                        "options": [
                            {"value": value, "filename": p.filename,
                             "page": p.page, "source_text": p.source_text}
                            for value, p in options
                        ],
                    }
                    for name, options in sorted(merged.conflicts.items())
                ],
            })

    # Saved state wins over extraction: it carries reviewer corrections and
    # everything typed by hand, including the ESG entries no document holds.
    from app.services.handover import Handover

    handover = Handover(values=dict(merged.values))
    try:
        payload = build_assessment_payload(handover)
    except HandoverRefused as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail=str(exc))

    saved = project.state or {}
    payload = {**payload, **{k: v for k, v in saved.items()
                             if v not in (None, [], {})}}

    result = AssessmentResponse.of(*_run(AssessmentRequest(**payload)))

    audit_detail = {"documents": len(merged.provenance)}
    audit.record(
        db, action="project.assessed", outcome=audit.SUCCESS,
        actor_email=user.email, organization=user.organization,
        user_id=user.id, resource_type="project", resource_id=str(project.id),
        request=request, detail=audit_detail)
    db.flush()

    return {
        "assessment": result.model_dump(mode="json"),
        "project": payload,
        # Which file each value came from, so the interface can show it
        # beside the figure.
        "provenance": {
            name: [{"filename": p.filename, "page": p.page,
                    "source_text": p.source_text, "score": p.score}
                   for p in sources]
            for name, sources in merged.provenance.items()
        },
    }


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    project_id: uuid.UUID,
    request: Request,
    user: User = Depends(require_roles(Role.ADMIN, Role.AUDITOR)),
    db: Session = Depends(get_db),
) -> Response:
    """Remove a project, its documents and its working state.

    The audit trail survives, as it does for a document: the record that the
    project existed and was deleted, by whom and when, outlives the project.
    """
    from app.services.storage import StorageError, get_storage

    project = _get(db, project_id, user)
    storage = get_storage()

    # Remove the stored objects before the rows. An orphaned object costs
    # storage; a row pointing at a file that is gone breaks every later read.
    for document in db.scalars(
            select(Document).where(Document.project_id == project.id)).all():
        try:
            storage.delete(document.storage_path)
        except StorageError:
            pass

    name = project.name
    db.delete(project)          # documents cascade

    audit.record(
        db, action="project.deleted", outcome=audit.SUCCESS,
        actor_email=user.email, organization=user.organization,
        user_id=user.id, resource_type="project", resource_id=str(project_id),
        request=request, detail={"name": name})
    db.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
