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

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.deps import get_current_user
from app.domain.additionality import FinancialInputs, assess_additionality
from app.domain.baseline import ProjectEmissions, emission_reductions
from app.domain.classification import ProjectIntake, classify
from app.domain.compliance import build_compliance_report, traceability_csv
from app.domain.emission_factors import PowerUnit, grid_emission_factor
from app.domain.esg import RiskCategory, RiskEntry, assess_esg
from app.domain.monitoring import build_monitoring_parameters
from app.domain.regulatory import check_registry
from app.schemas.assessment import AssessmentRequest, AssessmentResponse
from app.services.auditor import audit

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
