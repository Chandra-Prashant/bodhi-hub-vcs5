"""
Module 1 API — Project Intake & Classification.

NOTE: every route here carries `Depends(get_current_user)`. The existing
/projects/process-boundary route does NOT, and must be fixed the same way.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user  # existing dependency
from app.domain.classification import ProjectIntake, classify
from app.schemas.classification import ClassificationOut, ProjectIntakeIn

router = APIRouter(prefix="/classification", tags=["Module 1 — Classification"])


@router.post("/evaluate", response_model=ClassificationOut)
def evaluate_intake(
    payload: ProjectIntakeIn,
    _user=Depends(get_current_user),
) -> ClassificationOut:
    """
    Deterministic eligibility and classification for a proposed project.

    Returns the applicable template version (5.0A/5.0B), methodology,
    crediting period, deadlines and combined-margin weights, plus a list of
    findings. `blocked` means the project cannot be registered as described;
    `needs_review` means a human must confirm something before submission.
    No LLM is involved — these results are reproducible.
    """
    intake = ProjectIntake(
        name=payload.name,
        proponent=payload.proponent,
        country_iso2=payload.country_iso2,
        technology=payload.technology,
        installed_capacity_mw=payload.installed_capacity_mw,
        expected_annual_generation_mwh=payload.expected_annual_generation_mwh,
        initial_crediting_period_start=payload.initial_crediting_period_start,
        crediting_period_ordinal=payload.crediting_period_ordinal,
        authorised_capacity_mw=payload.authorised_capacity_mw,
        grid_connected=payload.grid_connected,
        applies_new_methodology=payload.applies_new_methodology,
    )
    return ClassificationOut.of(classify(intake))
