from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from app.domain.constants import Technology
from app.domain.emission_factors import OMMethod
from app.schemas.classification import FindingOut


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    proponent: str = Field(min_length=1, max_length=200)
    country_iso2: str = Field(min_length=2, max_length=2)
    technology: Technology
    installed_capacity_mw: float = Field(gt=0)
    expected_annual_generation_mwh: float = Field(gt=0)
    initial_crediting_period_start: date
    crediting_period_ordinal: int = Field(default=1, ge=1, le=10)
    authorised_capacity_mw: float | None = Field(default=None, gt=0)
    grid_connected: bool = True
    applies_new_methodology: bool = False


class IdentityIn(BaseModel):
    verra_project_id: str = ""
    location_description: str = ""
    project_start_date: date | None = None
    proponent_contact: str = ""
    prepared_by: str = ""
    other_entities: str = ""
    ownership_basis: str = ""


class PowerUnitIn(BaseModel):
    unit_id: str
    generation_mwh: float = Field(gt=0)
    commissioning_year: int = Field(ge=1900, le=2100)
    low_cost_must_run: bool = False
    efficiency: float | None = Field(default=None, gt=0, le=1)
    efficiency_fuel_ef_t_per_gj: float | None = Field(default=None, ge=0)
    generation_only: bool = False


class ProjectEmissionsIn(BaseModel):
    fossil_fuel_combustion: float = 0.0
    geothermal: float = 0.0
    hydro_reservoir: float = 0.0
    bess: float = 0.0
    pv_specific: float = 0.0
    fugitive_electrical: float = 0.0


class FinancialsIn(BaseModel):
    capex: float = Field(gt=0)
    annual_opex: float = Field(ge=0)
    annual_generation_mwh: float = Field(gt=0)
    tariff_per_mwh: float = Field(gt=0)
    project_lifetime_years: int = Field(gt=0, le=60)
    discount_rate: float = Field(gt=0, lt=1)
    benchmark_irr: float = Field(gt=0, lt=1)
    credit_price_per_tco2e: float = Field(default=0.0, ge=0)
    residual_value: float = 0.0


class PDDBuildRequest(BaseModel):
    project: ProjectIn
    identity: IdentityIn | None = None
    grid_units: list[PowerUnitIn] = Field(default_factory=list)
    om_method: OMMethod = OMMethod.SIMPLE
    project_emissions: ProjectEmissionsIn | None = None
    eg_facility_mwh: float | None = None
    ef_embodied_kg_per_mwh: float | None = None
    financials: FinancialsIn | None = None
    similar_projects_all: int = Field(default=0, ge=0)
    similar_projects_distinct: int = Field(default=0, ge=0)
    regulatory_surplus: bool = True
    strip_guidance: bool = False
    allow_incomplete: bool = False


class AnnualEstimateOut(BaseModel):
    year: int
    period_label: str
    baseline_tco2e: float
    project_tco2e: float
    leakage_tco2e: float
    reductions_tco2e: float


class PDDBuildResponse(BaseModel):
    template_version: str
    template_used: str
    blocked: bool
    fields_written: list[str]
    fields_not_found: list[str]
    sections_written: list[str]
    sections_not_found: list[str]
    sections_needing_input: list[tuple[str, int]]
    total_guidance_blocks_remaining: int
    annual_estimates: list[AnnualEstimateOut]
    total_estimated_reductions_tco2e: float
    findings: list[FindingOut]

    @classmethod
    def of(cls, content, result) -> "PDDBuildResponse":
        return cls(
            template_version=content.template_version.value,
            template_used=result.template_used,
            blocked=content.blocked,
            fields_written=result.report.fields_written,
            fields_not_found=result.report.fields_not_found,
            sections_written=result.report.sections_written,
            sections_not_found=result.report.sections_not_found,
            sections_needing_input=result.sections_needing_input,
            total_guidance_blocks_remaining=sum(
                result.report.instructions_remaining.values()),
            annual_estimates=[
                AnnualEstimateOut(**a.__dict__) for a in content.annual_estimates],
            total_estimated_reductions_tco2e=content.total_estimated_reductions,
            findings=[FindingOut.of(f) for f in result.findings],
        )
