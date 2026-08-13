"""
Assessment API — one call that runs every engine and returns what a project
manager needs to see on one screen.

The dashboard shouldn't have to orchestrate seven modules and stitch their
findings together; that ordering is domain knowledge and belongs here. It also
means the UI cannot accidentally show a compliance verdict computed from a
different set of inputs than the reductions figure beside it.
"""

from __future__ import annotations

import io
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse, StreamingResponse

from app.api.deps import get_current_user
from app.domain.additionality import FinancialInputs, assess_additionality
from app.domain.baseline import ProjectEmissions, emission_reductions
from app.domain.classification import ProjectIntake, classify
from app.domain.compliance import build_compliance_report, traceability_csv
from app.domain.emission_factors import PowerUnit, grid_emission_factor
from app.domain.esg import (
    CATEGORY_TITLES,
    LIKELIHOOD_LABELS,
    RISK_MATRIX,
    SEVERITY_LABELS,
    RiskCategory,
    RiskEntry,
    assess_esg,
)
from app.domain.monitoring import build_monitoring_parameters
from app.domain.pdd_content import ProjectIdentity, build_pdd_content
from app.domain.regulatory import check_registry
from app.schemas.assessment import AssessmentRequest, AssessmentResponse
from app.services.auditor import audit
from app.services.pdd_builder import build_pdd

router = APIRouter(prefix="/assessment", tags=["Assessment"])


def _run(payload: AssessmentRequest):
    intake = ProjectIntake(
        name=payload.name,
        proponent=payload.proponent,
        country_iso2=payload.country_iso2,
        technology=payload.technology,
        installed_capacity_mw=payload.installed_capacity_mw,
        expected_annual_generation_mwh=payload.expected_annual_generation_mwh,
        initial_crediting_period_start=payload.initial_crediting_period_start,
        crediting_period_ordinal=payload.crediting_period_ordinal,
        grid_connected=payload.grid_connected,
    )
    classification = classify(intake)
    findings = list(classification.findings)

    units = [
        PowerUnit(
            unit_id=u.unit_id, generation_mwh=u.generation_mwh,
            commissioning_year=u.commissioning_year,
            low_cost_must_run=u.low_cost_must_run,
            efficiency=u.efficiency,
            efficiency_fuel_ef_t_per_gj=u.efficiency_fuel_ef_t_per_gj,
            generation_only=u.generation_only,
        ) for u in payload.grid_units
    ]

    ef = er = add = None
    if units:
        ef = grid_emission_factor(units, intake.technology,
                                  intake.crediting_period_ordinal)
        findings.extend(ef.findings)

        er = emission_reductions(
            intake.expected_annual_generation_mwh, ef.ef_grid_cm,
            project_emissions=ProjectEmissions(
                **payload.project_emissions.model_dump())
            if payload.project_emissions else None,
            eg_facility_mwh=intake.expected_annual_generation_mwh,
            technology=intake.technology,
        )
        findings.extend(er.findings)

        if payload.financials:
            add = assess_additionality(
                FinancialInputs(**payload.financials.model_dump(),
                                annual_credits_tco2e=er.emission_reductions_tco2e),
                n_all=payload.similar_projects_all,
                n_diff=payload.similar_projects_distinct,
                project_capacity_mw=intake.installed_capacity_mw,
                regulatory_surplus=payload.regulatory_surplus,
            )
            findings.extend(add.findings)

    monitoring = build_monitoring_parameters(
        intake.technology, has_bess=payload.has_bess)
    findings.extend(monitoring.findings)

    esg = None
    if payload.esg_entries:
        esg = assess_esg([
            RiskEntry(
                category=RiskCategory(e.category), risk_id=e.risk_id,
                description=e.description, severity=e.severity,
                likelihood=e.likelihood, justification=e.justification,
                mitigation=e.mitigation, not_applicable=e.not_applicable,
                na_justification=e.na_justification,
            ) for e in payload.esg_entries
        ])
        findings.extend(esg.findings)

    report = build_compliance_report(findings, intake.technology)
    audit_result = audit(report, findings)

    return intake, classification, ef, er, add, monitoring, esg, report, audit_result


@router.post("/run", response_model=AssessmentResponse)
def run_assessment(
    payload: AssessmentRequest,
    _user=Depends(get_current_user),
) -> AssessmentResponse:
    """Run every engine over one project and return a single consolidated view."""
    return AssessmentResponse.of(*_run(payload))


@router.post("/traceability.csv")
def traceability_export(
    payload: AssessmentRequest,
    _user=Depends(get_current_user),
):
    """The register a validation/verification body works from."""
    *_, report, _audit = _run(payload)
    csv_text = traceability_csv(report)
    return StreamingResponse(
        io.StringIO(csv_text),
        media_type="text/csv",
        headers={"Content-Disposition":
                 'attachment; filename="traceability-matrix.csv"'},
    )


@router.get("/regulatory-status")
def regulatory_status(_user=Depends(get_current_user)) -> dict:
    """Which regulatory documents are verified, and what is outstanding."""
    findings = check_registry()
    return {
        "findings": [
            {"check": f.check, "severity": f.severity.value,
             "message": f.message, "source": f.source}
            for f in findings
        ]
    }


# ---------------------------------------------------------------------------
# Project Description
# ---------------------------------------------------------------------------
#
# The document is the deliverable; everything above it is the evidence that the
# document can be defended. Both are produced from the same inputs in the same
# request, so the figures in the .docx cannot drift from the figures on screen.

DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document")


def _pdd_content(payload: AssessmentRequest):
    intake, classification, ef, er, add, monitoring, esg, _report, _audit = _run(payload)
    return build_pdd_content(
        intake, classification,
        ProjectIdentity(prepared_by=payload.proponent),
        ef, er, add, monitoring=monitoring)


@router.post("/document-status")
def document_status(
    payload: AssessmentRequest,
    _user=Depends(get_current_user),
) -> dict:
    """What the generated Project Description would contain, and what a person
    still has to write into it."""
    content = _pdd_content(payload)
    with tempfile.TemporaryDirectory() as tmp:
        result = build_pdd(content, Path(tmp) / "preview.docx")
    return {
        "template_used": result.template_used,
        "blocked": content.blocked,
        "fields_written": len(result.report.fields_written),
        "sections_drafted": result.report.sections_written,
        "sections_needing_input": result.sections_needing_input,
        "total_guidance_blocks_remaining": sum(
            result.report.instructions_remaining.values()),
        "findings": [
            {"check": f.check, "severity": f.severity.value,
             "message": f.message, "source": f.source}
            for f in result.findings
        ],
    }


@router.post("/project-description")
def project_description(
    payload: AssessmentRequest,
    strip_guidance: bool = False,
    allow_incomplete: bool = False,
    _user=Depends(get_current_user),
):
    """Render the Project Description as a .docx.

    Refuses when the assembled content is blocked. A document asserting
    eligibility or additionality that the engine has rejected must not leave
    the system, whatever the caller asks for.
    """
    content = _pdd_content(payload)
    if content.blocked and not allow_incomplete:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "Project Description blocked by unresolved findings.",
                "findings": [
                    {"check": f.check, "message": f.message, "source": f.source}
                    for f in content.findings if f.severity.value == "FAIL"
                ],
            })

    out_dir = Path(tempfile.gettempdir()) / "bodhi-pdd" / str(uuid.uuid4())
    filename = (f"VCS_PD_{payload.name.replace(' ', '_')}_"
                f"{content.template_version.value}.docx")
    result = build_pdd(content, out_dir / filename, strip_guidance=strip_guidance)
    return FileResponse(path=str(result.output_path),
                        media_type=DOCX_MEDIA_TYPE, filename=filename)


@router.get("/esg-schema")
def esg_schema(_user=Depends(get_current_user)) -> dict:
    """The twelve safeguard categories and the risk matrix, served from the
    engine's own copy.

    The matrix is a regulatory constant transcribed from the VCS ESG Risk
    Assessment Template. Duplicating it in the frontend would put the same
    table in two places and let them drift, so the client renders from this.
    """
    return {
        "categories": [
            {
                "code": category.value,
                "pillar": pillar.value,
                "title": title,
                "clause": clause,
            }
            for category, (pillar, title, clause) in CATEGORY_TITLES.items()
        ],
        "severity_labels": SEVERITY_LABELS,
        "likelihood_labels": LIKELIHOOD_LABELS,
        "matrix": {
            str(severity): {str(likelihood): level.value
                            for likelihood, level in row.items()}
            for severity, row in RISK_MATRIX.items()
        },
    }


@router.post("/esg-review")
def esg_review(
    payload: AssessmentRequest,
    _user=Depends(get_current_user),
) -> dict:
    """Validate a supplied ESG risk assessment without running everything else."""
    if not payload.esg_entries:
        result = assess_esg([])
    else:
        result = assess_esg([
            RiskEntry(
                category=RiskCategory(e.category), risk_id=e.risk_id,
                description=e.description, severity=e.severity,
                likelihood=e.likelihood, justification=e.justification,
                mitigation=e.mitigation, not_applicable=e.not_applicable,
                na_justification=e.na_justification,
            ) for e in payload.esg_entries
        ])
    return {
        "blocked": result.blocked,
        "missing_categories": [c.value for c in result.missing_categories],
        "elevated_risk_ids": [e.risk_id for e in result.elevated_risks],
        "findings": [
            {"check": f.check, "severity": f.severity.value,
             "message": f.message, "source": f.source}
            for f in result.findings
        ],
    }
