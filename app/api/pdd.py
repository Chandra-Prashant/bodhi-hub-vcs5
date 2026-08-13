"""Module 3 API — PDD generation."""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse

from app.api.deps import get_current_user
from app.domain.additionality import FinancialInputs, assess_additionality
from app.domain.baseline import ProjectEmissions, emission_reductions
from app.domain.classification import ProjectIntake, classify
from app.domain.emission_factors import PowerUnit, grid_emission_factor
from app.domain.monitoring import build_monitoring_parameters
from app.domain.pdd_content import ProjectIdentity, build_pdd_content
from app.schemas.pdd import PDDBuildRequest, PDDBuildResponse
from app.services.pdd_builder import build_pdd

router = APIRouter(prefix="/pdd", tags=["Module 3 — PDD Builder"])

DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document")


def _assemble(payload: PDDBuildRequest):
    intake = ProjectIntake(
        name=payload.project.name,
        proponent=payload.project.proponent,
        country_iso2=payload.project.country_iso2,
        technology=payload.project.technology,
        installed_capacity_mw=payload.project.installed_capacity_mw,
        expected_annual_generation_mwh=payload.project.expected_annual_generation_mwh,
        initial_crediting_period_start=payload.project.initial_crediting_period_start,
        crediting_period_ordinal=payload.project.crediting_period_ordinal,
        authorised_capacity_mw=payload.project.authorised_capacity_mw,
        grid_connected=payload.project.grid_connected,
        applies_new_methodology=payload.project.applies_new_methodology,
    )
    classification = classify(intake)

    units = [
        PowerUnit(
            unit_id=u.unit_id, generation_mwh=u.generation_mwh,
            commissioning_year=u.commissioning_year,
            low_cost_must_run=u.low_cost_must_run,
            efficiency=u.efficiency,
            efficiency_fuel_ef_t_per_gj=u.efficiency_fuel_ef_t_per_gj,
            generation_only=u.generation_only,
        )
        for u in payload.grid_units
    ]
    ef = grid_emission_factor(
        units, intake.technology, intake.crediting_period_ordinal,
        om_method=payload.om_method) if units else None

    monitoring = build_monitoring_parameters(
        intake.technology, has_bess=payload.has_bess)

    er = None
    if ef is not None:
        er = emission_reductions(
            intake.expected_annual_generation_mwh, ef.ef_grid_cm,
            project_emissions=ProjectEmissions(**payload.project_emissions.model_dump())
            if payload.project_emissions else None,
            eg_facility_mwh=payload.eg_facility_mwh
                or intake.expected_annual_generation_mwh,
            ef_embodied_kg_per_mwh=payload.ef_embodied_kg_per_mwh,
            technology=intake.technology,
        )

    add = None
    if payload.financials and er is not None:
        add = assess_additionality(
            FinancialInputs(
                **payload.financials.model_dump(),
                annual_credits_tco2e=er.emission_reductions_tco2e),
            n_all=payload.similar_projects_all,
            n_diff=payload.similar_projects_distinct,
            project_capacity_mw=intake.installed_capacity_mw,
            regulatory_surplus=payload.regulatory_surplus,
        )

    identity = ProjectIdentity(**payload.identity.model_dump()) if payload.identity \
        else ProjectIdentity()
    return build_pdd_content(intake, classification, identity, ef, er, add,
                             monitoring=monitoring)


@router.post("/preview", response_model=PDDBuildResponse)
def preview(
    payload: PDDBuildRequest,
    _user=Depends(get_current_user),
) -> PDDBuildResponse:
    """Assemble the PDD and report completeness without returning the file."""
    content = _assemble(payload)
    with tempfile.TemporaryDirectory() as tmp:
        result = build_pdd(content, Path(tmp) / "preview.docx",
                           strip_guidance=payload.strip_guidance)
        return PDDBuildResponse.of(content, result)


@router.post("/generate")
def generate(
    payload: PDDBuildRequest,
    _user=Depends(get_current_user),
):
    """Render and return the Project Description as a .docx.

    Refuses when the assembled content is blocked — a PDD asserting eligibility
    or additionality that the engine has rejected must not leave the system.
    """
    content = _assemble(payload)
    if content.blocked and not payload.allow_incomplete:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "PDD generation blocked by unresolved findings.",
                "findings": [
                    {"check": f.check, "severity": f.severity.value,
                     "message": f.message, "source": f.source}
                    for f in content.findings if f.severity.value == "FAIL"
                ],
            })

    out_dir = Path(tempfile.gettempdir()) / "bodhi-pdd" / str(uuid.uuid4())
    filename = (f"VCS_PD_{payload.project.name.replace(' ', '_')}_"
                f"{content.template_version.value}.docx")
    result = build_pdd(content, out_dir / filename,
                       strip_guidance=payload.strip_guidance)

    return FileResponse(
        path=str(result.output_path),
        media_type=DOCX_MEDIA_TYPE,
        filename=filename,
    )
