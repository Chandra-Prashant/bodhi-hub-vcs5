from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.domain.classification import Classification, Finding
from app.domain.constants import Technology


class ProjectIntakeIn(BaseModel):
    model_config = ConfigDict(use_enum_values=False)

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


class FindingOut(BaseModel):
    check: str
    severity: str
    message: str
    source: str

    @classmethod
    def of(cls, f: Finding) -> "FindingOut":
        return cls(check=f.check, severity=f.severity.value,
                   message=f.message, source=f.source)


class ClassificationOut(BaseModel):
    template_version: str
    sectoral_scope: int
    project_category: str
    methodology: str
    crediting_period_years: int
    crediting_period_end: date
    max_total_crediting_years: int
    pipeline_listing_deadline: date
    registration_deadline: date
    cm_weight_om: float
    cm_weight_bm: float
    blocked: bool
    needs_review: bool
    findings: list[FindingOut]

    @classmethod
    def of(cls, c: Classification) -> "ClassificationOut":
        return cls(
            template_version=c.template_version.value,
            sectoral_scope=c.sectoral_scope,
            project_category=c.project_category,
            methodology=c.methodology,
            crediting_period_years=c.crediting_period_years,
            crediting_period_end=c.crediting_period_end,
            max_total_crediting_years=c.max_total_crediting_years,
            pipeline_listing_deadline=c.pipeline_listing_deadline,
            registration_deadline=c.registration_deadline,
            cm_weight_om=c.cm_weights[0],
            cm_weight_bm=c.cm_weights[1],
            blocked=c.blocked,
            needs_review=c.needs_review,
            findings=[FindingOut.of(f) for f in c.findings],
        )
