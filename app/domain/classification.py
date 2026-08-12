"""
Module 1 — Project Intake & Classification.

Pure functions, no database and no LLM. Everything here is deterministic and
unit-testable, which is the point: the numbers a VVB will scrutinise must never
depend on a model's mood. The RAG layer explains these results to the user; it
does not produce them.

Every finding carries a `source` citation that feeds the traceability matrix.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum

from app.data.countries import AS_OF as COUNTRY_DATA_AS_OF, income_group, is_ldc
from app.domain import constants as K


class Severity(str, Enum):
    PASS = "PASS"
    WARNING = "WARNING"   # proceed, but a human must confirm
    FAIL = "FAIL"         # blocks registration under VCS v5.0


@dataclass(frozen=True)
class Finding:
    check: str
    severity: Severity
    message: str
    source: str


@dataclass
class ProjectIntake:
    """Raw intake data. Mirrors the PDD front matter."""
    name: str
    proponent: str
    country_iso2: str
    technology: K.Technology
    installed_capacity_mw: float
    expected_annual_generation_mwh: float
    initial_crediting_period_start: date
    crediting_period_ordinal: int = 1  # 1 = initial, 2 = first renewal, ...
    authorised_capacity_mw: float | None = None  # hydro: regulator-approved
    grid_connected: bool = True
    applies_new_methodology: bool = False


@dataclass
class Classification:
    template_version: K.TemplateVersion
    sectoral_scope: int
    project_category: str
    methodology: str
    crediting_period_years: int
    crediting_period_end: date
    max_total_crediting_years: int
    pipeline_listing_deadline: date
    registration_deadline: date
    cm_weights: tuple[float, float]
    findings: list[Finding] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return any(f.severity is Severity.FAIL for f in self.findings)

    @property
    def needs_review(self) -> bool:
        return any(f.severity is Severity.WARNING for f in self.findings)


def _years(d: date, n: int) -> date:
    try:
        return d.replace(year=d.year + n)
    except ValueError:  # 29 Feb
        return d.replace(year=d.year + n, day=28)


def select_template_version(start: date) -> K.TemplateVersion:
    """VCS 5.0A before the cutover, 5.0B on/after it."""
    return (K.TemplateVersion.B if start >= K.TEMPLATE_B_CUTOVER
            else K.TemplateVersion.A)


def check_vmr0017_eligibility(intake: ProjectIntake) -> list[Finding]:
    """VMR0017 v1.0 Section 4, Table 1."""
    findings: list[Finding] = []
    rule = K.VMR0017_ELIGIBILITY[intake.technology]
    country = intake.country_iso2.upper()
    group = income_group(country)

    # --- geography ---
    if rule.geography is K.GeographyRule.GLOBAL:
        findings.append(Finding(
            "vmr0017.geography", Severity.PASS,
            f"{intake.technology.value} is globally applicable.", rule.source))
    elif rule.geography is K.GeographyRule.NON_HIGH_INCOME:
        if group is K.IncomeGroup.UNKNOWN:
            findings.append(Finding(
                "vmr0017.geography", Severity.WARNING,
                f"No World Bank income classification on file for {country}. "
                f"Confirm manually before validation.", rule.source))
        elif group is K.IncomeGroup.HIGH:
            findings.append(Finding(
                "vmr0017.geography", Severity.FAIL,
                f"{country} is a high-income economy. VMR0017 restricts "
                f"{intake.technology.value} to low, lower-middle and "
                f"upper-middle income countries.", rule.source))
        else:
            findings.append(Finding(
                "vmr0017.geography", Severity.PASS,
                f"{country} is classified {group.value}; eligible.",
                rule.source))
    elif rule.geography is K.GeographyRule.LDC_ONLY:
        if is_ldc(country):
            findings.append(Finding(
                "vmr0017.geography", Severity.PASS,
                f"{country} is on the UN LDC list; eligible.", rule.source))
        else:
            findings.append(Finding(
                "vmr0017.geography", Severity.FAIL,
                f"{country} is not on the UN LDC list. VMR0017 restricts "
                f"hydroelectric projects to LDCs.", rule.source))

    # --- capacity ---
    if rule.max_capacity_mw is not None:
        # Hydro: rated OR authorised capacity, whichever is HIGHER.
        governing = max(
            intake.installed_capacity_mw,
            intake.authorised_capacity_mw or 0.0,
        )
        if governing > rule.max_capacity_mw:
            findings.append(Finding(
                "vmr0017.capacity", Severity.FAIL,
                f"Governing capacity {governing:g} MW exceeds the "
                f"{rule.max_capacity_mw:g} MW ceiling. VMR0017 uses the higher "
                f"of rated and authorised capacity.", rule.source))
        else:
            findings.append(Finding(
                "vmr0017.capacity", Severity.PASS,
                f"Governing capacity {governing:g} MW is within the "
                f"{rule.max_capacity_mw:g} MW ceiling.", rule.source))

    # --- stale reference data ---
    if date.today() - COUNTRY_DATA_AS_OF > timedelta(days=365):
        findings.append(Finding(
            "vmr0017.reference_data", Severity.WARNING,
            f"Country classification table was last verified "
            f"{COUNTRY_DATA_AS_OF.isoformat()}. World Bank income groups are "
            f"revised each July — re-verify before submission.",
            "app/data/countries.py"))

    return findings


def select_cm_weights(intake: ProjectIntake) -> tuple[tuple[float, float], list[Finding]]:
    """VT0011 v1.0 Step 6, para 86 (Case 1) and para 90 (LDC option)."""
    findings: list[Finding] = []
    n = intake.crediting_period_ordinal

    if intake.technology in K.WIND_SOLAR_TECHNOLOGIES:
        if n in K.WIND_SOLAR_CM_WEIGHTS:
            weights = K.WIND_SOLAR_CM_WEIGHTS[n]
        else:
            weights = K.WIND_SOLAR_CM_WEIGHTS[3]
            findings.append(Finding(
                "vt0011.cm_weights", Severity.WARNING,
                f"Crediting period {n} exceeds the three tabulated in VT0011. "
                f"Third-period weights applied; confirm with the VVB.",
                K.CM_WEIGHTS_SOURCE))
    else:
        weights = (K.OTHER_CASE1_CM_WEIGHTS.get(n)
                   or K.OTHER_CASE1_CM_WEIGHTS_SUBSEQUENT)

    findings.append(Finding(
        "vt0011.cm_weights", Severity.PASS,
        f"Crediting period {n}: wOM={weights[0]}, wBM={weights[1]}.",
        K.CM_WEIGHTS_SOURCE))

    if is_ldc(intake.country_iso2):
        findings.append(Finding(
            "vt0011.cm_weights.ldc_option", Severity.WARNING,
            "Project is in an LDC. VT0011 para 90 permits wOM=1.0, wBM=0.0 as "
            "an alternative — usually more favourable. Confirm the election.",
            K.CM_WEIGHTS_SOURCE))

    return weights, findings


def validate_intake(intake: ProjectIntake) -> list[Finding]:
    """Data-quality rules from the client requirements mapping, Section 2."""
    findings: list[Finding] = []
    today = date.today()
    src = "App-Development-Requirements-Mapping.md s2 Data Validation Rules"

    if intake.installed_capacity_mw <= 0:
        findings.append(Finding("intake.capacity", Severity.FAIL,
                                "Installed capacity must be greater than 0 MW.", src))
    if intake.expected_annual_generation_mwh <= 0:
        findings.append(Finding("intake.generation", Severity.FAIL,
                                "Expected annual generation must be greater than 0 MWh.", src))

    # Sanity: implied capacity factor. Flags a unit mix-up (kW vs MW, kWh vs MWh)
    # before it propagates into the baseline calculation.
    if intake.installed_capacity_mw > 0:
        cf = intake.expected_annual_generation_mwh / (intake.installed_capacity_mw * 8760)
        if not 0.05 <= cf <= 0.65:
            findings.append(Finding(
                "intake.capacity_factor", Severity.WARNING,
                f"Implied capacity factor is {cf:.1%}, outside the plausible "
                f"5–65% band for grid-connected renewables. Check units.", src))

    if intake.initial_crediting_period_start < _years(today, -10):
        findings.append(Finding(
            "intake.start_date", Severity.FAIL,
            "Initial crediting period start date is more than 10 years in the "
            "past.", src))
    if intake.initial_crediting_period_start > _years(today, 2):
        findings.append(Finding(
            "intake.start_date", Severity.WARNING,
            "Initial crediting period start date is more than 2 years in the "
            "future.", src))

    if not intake.grid_connected:
        findings.append(Finding(
            "intake.grid_connection", Severity.FAIL,
            "VMR0017 covers grid-connected generation. An off-grid activity "
            "needs a different methodology.", "VMR0017 v1.0 s4"))

    return findings


def check_deadlines(intake: ProjectIntake) -> list[Finding]:
    """VCS Standard v5.0 s3.8.2 and Table 7."""
    findings: list[Finding] = []
    start = intake.initial_crediting_period_start
    today = date.today()
    src = "VCS Standard v5.0 s3.8.2, Table 7"

    listing_due = _years(start, K.PIPELINE_LISTING_DEADLINE_YEARS)
    reg_years = (K.EI_NEW_METHODOLOGY_REGISTRATION_YEARS
                 if intake.applies_new_methodology
                 else K.EI_REGISTRATION_DEADLINE_YEARS)
    reg_due = _years(start, reg_years)

    if today > listing_due:
        findings.append(Finding(
            "vcs.pipeline_listing_deadline", Severity.FAIL,
            f"Pipeline listing was due {listing_due.isoformat()} (1 year from "
            f"the crediting period start date) and has passed.", src))
    elif today > listing_due - timedelta(days=90):
        findings.append(Finding(
            "vcs.pipeline_listing_deadline", Severity.WARNING,
            f"Pipeline listing due {listing_due.isoformat()} — under 90 days "
            f"remaining.", src))
    else:
        findings.append(Finding(
            "vcs.pipeline_listing_deadline", Severity.PASS,
            f"Pipeline listing due {listing_due.isoformat()}.", src))

    if today > reg_due:
        findings.append(Finding(
            "vcs.registration_deadline", Severity.FAIL,
            f"Registration request was due {reg_due.isoformat()} "
            f"({reg_years} years from the crediting period start date, E&I).",
            src))
    else:
        findings.append(Finding(
            "vcs.registration_deadline", Severity.PASS,
            f"Registration request due {reg_due.isoformat()}.", src))

    return findings


def check_crediting_period(intake: ProjectIntake) -> list[Finding]:
    """VCS Standard v5.0 s3.8.4, Table 8 — E&I is 5 years, renewable twice."""
    findings: list[Finding] = []
    if intake.crediting_period_ordinal > K.EI_MAX_RENEWALS + 1:
        findings.append(Finding(
            "vcs.crediting_period", Severity.FAIL,
            f"Crediting period {intake.crediting_period_ordinal} exceeds the "
            f"E&I maximum of one initial period plus {K.EI_MAX_RENEWALS} "
            f"renewals ({K.EI_MAX_TOTAL_CREDITING_YEARS} years total).",
            K.CREDITING_PERIOD_SOURCE))
    else:
        findings.append(Finding(
            "vcs.crediting_period", Severity.PASS,
            f"E&I crediting period is {K.EI_CREDITING_PERIOD_YEARS} years, "
            f"renewable {K.EI_MAX_RENEWALS} times "
            f"({K.EI_MAX_TOTAL_CREDITING_YEARS} years maximum).",
            K.CREDITING_PERIOD_SOURCE))
    return findings


def classify(intake: ProjectIntake) -> Classification:
    """Run the full Module 1 pipeline."""
    cm_weights, cm_findings = select_cm_weights(intake)
    start = intake.initial_crediting_period_start

    findings = [
        *validate_intake(intake),
        *check_vmr0017_eligibility(intake),
        *check_crediting_period(intake),
        *check_deadlines(intake),
        *cm_findings,
    ]

    return Classification(
        template_version=select_template_version(start),
        sectoral_scope=K.SECTORAL_SCOPE_ENERGY_RENEWABLE,
        project_category=K.PROJECT_CATEGORY_EI,
        methodology="VMR0017 v1.0 (ACM0002 v22.0 revision)",
        crediting_period_years=K.EI_CREDITING_PERIOD_YEARS,
        crediting_period_end=_years(start, K.EI_CREDITING_PERIOD_YEARS),
        max_total_crediting_years=K.EI_MAX_TOTAL_CREDITING_YEARS,
        pipeline_listing_deadline=_years(start, K.PIPELINE_LISTING_DEADLINE_YEARS),
        registration_deadline=_years(
            start,
            K.EI_NEW_METHODOLOGY_REGISTRATION_YEARS
            if intake.applies_new_methodology
            else K.EI_REGISTRATION_DEADLINE_YEARS,
        ),
        cm_weights=cm_weights,
        findings=findings,
    )
