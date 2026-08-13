from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from app.domain.constants import Technology
from app.schemas.classification import FindingOut
from app.schemas.pdd import FinancialsIn, PowerUnitIn, ProjectEmissionsIn


class ESGEntryIn(BaseModel):
    category: str
    risk_id: str
    description: str = ""
    severity: int = Field(default=1, ge=1, le=5)
    likelihood: int = Field(default=1, ge=1, le=5)
    justification: str = ""
    mitigation: str = ""
    not_applicable: bool = False
    na_justification: str = ""


class AssessmentRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    proponent: str = Field(min_length=1, max_length=200)
    country_iso2: str = Field(min_length=2, max_length=2)
    technology: Technology
    installed_capacity_mw: float = Field(gt=0)
    expected_annual_generation_mwh: float = Field(gt=0)
    initial_crediting_period_start: date
    crediting_period_ordinal: int = Field(default=1, ge=1, le=10)
    grid_connected: bool = True
    has_bess: bool = False

    grid_units: list[PowerUnitIn] = Field(default_factory=list)
    project_emissions: ProjectEmissionsIn | None = None
    financials: FinancialsIn | None = None
    similar_projects_all: int = Field(default=0, ge=0)
    similar_projects_distinct: int = Field(default=0, ge=0)
    regulatory_surplus: bool = True
    esg_entries: list[ESGEntryIn] = Field(default_factory=list)


class ClassificationSummary(BaseModel):
    template_version: str
    methodology: str
    sectoral_scope: int
    project_category: str
    crediting_period_years: int
    crediting_period_end: date
    max_total_crediting_years: int
    pipeline_listing_deadline: date
    registration_deadline: date
    cm_weight_om: float
    cm_weight_bm: float


class QuantificationSummary(BaseModel):
    ef_grid_om: float | None = None
    ef_grid_bm: float | None = None
    ef_grid_cm: float | None = None
    om_method: str | None = None
    bm_sample_unit_ids: list[str] = []
    baseline_tco2e: float | None = None
    project_tco2e: float | None = None
    leakage_tco2e: float | None = None
    reductions_tco2e: float | None = None
    crediting_period_total_tco2e: float | None = None


class AdditionalitySummary(BaseModel):
    verdict: str
    irr_without_credits: float | None
    irr_with_credits: float | None
    benchmark_irr: float
    sensitivity_robust: bool
    meets_ccp_conditions: bool
    f_factor: float
    is_common_practice: bool


class RequirementOut(BaseModel):
    ref: str
    clause: str
    title: str
    status: str
    evidence_sources: list[str]
    note: str


class GapOut(BaseModel):
    priority: str
    area: str
    detail: str
    clause: str
    action: str


class AssessmentResponse(BaseModel):
    project_name: str
    ready_for_validation: bool
    compliance_summary: dict[str, int]
    classification: ClassificationSummary
    quantification: QuantificationSummary
    additionality: AdditionalitySummary | None
    requirements: list[RequirementOut]
    gaps: list[GapOut]
    findings: list[FindingOut]
    esg_complete: bool | None = None

    @classmethod
    def of(cls, intake, classification, ef, er, add, monitoring, esg,
           report, audit_result) -> "AssessmentResponse":
        quant = QuantificationSummary()
        if ef is not None:
            quant.ef_grid_om = ef.ef_grid_om
            quant.ef_grid_bm = ef.ef_grid_bm
            quant.ef_grid_cm = ef.ef_grid_cm
            quant.om_method = ef.om_method.value
            quant.bm_sample_unit_ids = ef.bm_sample_unit_ids
        if er is not None:
            quant.baseline_tco2e = er.baseline_emissions_tco2e
            quant.project_tco2e = er.project_emissions_tco2e
            quant.leakage_tco2e = er.leakage_emissions_tco2e
            quant.reductions_tco2e = er.emission_reductions_tco2e
            quant.crediting_period_total_tco2e = (
                er.emission_reductions_tco2e
                * classification.crediting_period_years)

        additionality = None
        if add is not None:
            additionality = AdditionalitySummary(
                verdict=add.verdict.value,
                irr_without_credits=add.investment.irr_without_credits,
                irr_with_credits=add.investment.irr_with_credits,
                benchmark_irr=add.investment.benchmark_irr,
                sensitivity_robust=add.sensitivity_robust,
                meets_ccp_conditions=add.investment.meets_ccp_conditions,
                f_factor=add.common_practice_result.f_factor,
                is_common_practice=add.common_practice_result.is_common_practice,
            )

        return cls(
            project_name=intake.name,
            ready_for_validation=audit_result.ready_for_validation,
            compliance_summary=audit_result.compliance_summary,
            classification=ClassificationSummary(
                template_version=classification.template_version.value,
                methodology=classification.methodology,
                sectoral_scope=classification.sectoral_scope,
                project_category=classification.project_category,
                crediting_period_years=classification.crediting_period_years,
                crediting_period_end=classification.crediting_period_end,
                max_total_crediting_years=classification.max_total_crediting_years,
                pipeline_listing_deadline=classification.pipeline_listing_deadline,
                registration_deadline=classification.registration_deadline,
                cm_weight_om=classification.cm_weights[0],
                cm_weight_bm=classification.cm_weights[1],
            ),
            quantification=quant,
            additionality=additionality,
            requirements=[
                RequirementOut(
                    ref=r.requirement.ref, clause=r.clause,
                    title=r.requirement.title, status=r.status.value,
                    evidence_sources=sorted({f.source for f in r.evidence}),
                    note=r.note,
                ) for r in report.results
            ],
            gaps=[
                GapOut(priority=g.priority.value, area=g.area, detail=g.detail,
                       clause=g.clause, action=g.action)
                for g in audit_result.gaps
            ],
            findings=[FindingOut.of(f) for f in (
                *classification.findings,
                *(ef.findings if ef else ()),
                *(er.findings if er else ()),
                *(add.findings if add else ()),
                *monitoring.findings,
                *(esg.findings if esg else ()),
            )],
            esg_complete=(not esg.missing_categories) if esg else None,
        )
