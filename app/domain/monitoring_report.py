"""
Module 6 — Monitoring report.

Ex-post quantification for a completed monitoring period, using metered
generation rather than the ex-ante estimate, plus the checks a verifier will
run first.

The distinction from Module 2 matters. Module 2 answers "what do we expect this
project to reduce?" using an estimated generation figure. This module answers
"what did it actually reduce?" using EGfacility,y read off the meter. Same
equations, different inputs, and a variance between the two that a verifier
will ask about.

Period continuity is checked because it is the cheapest way to lose credits: a
gap between monitoring periods is unclaimed generation, and an overlap is
double issuance. Neither is recoverable after the fact.

The variance threshold used to flag ex-ante/ex-post divergence is OURS, not
Verra's. VCS sets no numeric trigger. It is a review heuristic, configurable,
and labelled as such wherever it surfaces so nobody cites it as a requirement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from app.domain import constants as K
from app.domain.baseline import ProjectEmissions, emission_reductions
from app.domain.classification import Classification, Finding, Severity

VMR0017_MON = "VMR0017 v1.0 s9.2"
VCS5_MON = "VCS Standard v5.0 s3.15"

# House review heuristic, NOT a VCS requirement. See module docstring.
VARIANCE_REVIEW_THRESHOLD = 0.10
VARIANCE_SOURCE = "Bodhi Hub review heuristic (not a VCS requirement)"


@dataclass
class MeterCalibration:
    meter_id: str
    last_calibration: date
    uncertainty_pct: float | None = None
    interval_months: int = 12


@dataclass
class MonitoringPeriod:
    """One completed monitoring period."""
    start: date
    end: date
    eg_facility_mwh: float                 # metered net export
    eg_pj_add_mwh: float | None = None     # added capacity portion, if grouped
    ef_grid_cm: float = 0.0                # from VT0011, ex-ante or updated
    project_emissions: ProjectEmissions | None = None
    data_gap_days: int = 0
    meters: list[MeterCalibration] = field(default_factory=list)
    notes: str = ""

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


@dataclass
class MonitoringReportResult:
    period: MonitoringPeriod
    baseline_tco2e: float
    project_tco2e: float
    leakage_tco2e: float
    reductions_tco2e: float
    ex_ante_reductions_tco2e: float | None
    variance_fraction: float | None
    findings: list[Finding] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return any(f.severity is Severity.FAIL for f in self.findings)

    @property
    def annualised_reductions_tco2e(self) -> float:
        if self.period.days == 0:
            return 0.0
        return self.reductions_tco2e * 365.0 / self.period.days


def check_period_within_crediting_period(
    period: MonitoringPeriod,
    classification: Classification,
    crediting_start: date,
) -> list[Finding]:
    findings: list[Finding] = []
    crediting_end = classification.crediting_period_end

    if period.start < crediting_start:
        findings.append(Finding(
            "mr.period_start", Severity.FAIL,
            f"Monitoring period starts {period.start.isoformat()}, before the "
            f"crediting period begins on {crediting_start.isoformat()}. "
            f"Reductions before that date are not creditable.",
            K.CREDITING_PERIOD_SOURCE))
    if period.end > crediting_end:
        findings.append(Finding(
            "mr.period_end", Severity.FAIL,
            f"Monitoring period ends {period.end.isoformat()}, after the "
            f"crediting period ends on {crediting_end.isoformat()}. Split the "
            f"period at the crediting period boundary.",
            K.CREDITING_PERIOD_SOURCE))
    if period.end < period.start:
        findings.append(Finding(
            "mr.period_order", Severity.FAIL,
            "Monitoring period end precedes its start.", VCS5_MON))

    if not findings:
        findings.append(Finding(
            "mr.period", Severity.PASS,
            f"Monitoring period {period.start.isoformat()} to "
            f"{period.end.isoformat()} ({period.days} days) falls within the "
            f"crediting period.", K.CREDITING_PERIOD_SOURCE))
    return findings


def check_period_continuity(
    periods: list[MonitoringPeriod],
) -> list[Finding]:
    """Gaps forfeit credits; overlaps are double issuance. Neither is
    recoverable after verification."""
    findings: list[Finding] = []
    ordered = sorted(periods, key=lambda p: p.start)

    for previous, current in zip(ordered, ordered[1:]):
        expected = previous.end + timedelta(days=1)
        if current.start > expected:
            missing = (current.start - expected).days
            findings.append(Finding(
                "mr.continuity_gap", Severity.WARNING,
                f"{missing} day(s) between {previous.end.isoformat()} and "
                f"{current.start.isoformat()} are covered by no monitoring "
                f"period. Generation in that window cannot be claimed.",
                VCS5_MON))
        elif current.start < expected:
            overlap = (expected - current.start).days
            findings.append(Finding(
                "mr.continuity_overlap", Severity.FAIL,
                f"Monitoring periods overlap by {overlap} day(s) at "
                f"{current.start.isoformat()}. Overlapping periods would issue "
                f"credits twice for the same generation.", VCS5_MON))

    if periods and not findings:
        findings.append(Finding(
            "mr.continuity", Severity.PASS,
            f"{len(periods)} monitoring period(s) are contiguous with no gaps "
            f"or overlaps.", VCS5_MON))
    return findings


def check_metering(period: MonitoringPeriod) -> list[Finding]:
    """VMR0017 s9.2 requires meters tested and calibrated per utility or
    national requirements and manufacturer specifications."""
    findings: list[Finding] = []

    if not period.meters:
        findings.append(Finding(
            "mr.metering", Severity.FAIL,
            "No meter calibration records supplied. VMR0017 s9.2 requires "
            "calibration evidence, and measurement uncertainty is taken from "
            "the last calibration event.", VMR0017_MON))
        return findings

    for meter in period.meters:
        due = meter.last_calibration + timedelta(days=meter.interval_months * 30)
        if due < period.end:
            findings.append(Finding(
                "mr.calibration_overdue", Severity.FAIL,
                f"Meter {meter.meter_id} was last calibrated "
                f"{meter.last_calibration.isoformat()}; calibration was due "
                f"{due.isoformat()}, within the monitoring period. Readings "
                f"after that date are not supported by a calibration record.",
                VMR0017_MON))
        elif meter.last_calibration > period.end:
            findings.append(Finding(
                "mr.calibration_after_period", Severity.WARNING,
                f"Meter {meter.meter_id} was calibrated "
                f"{meter.last_calibration.isoformat()}, after the monitoring "
                f"period ended. Confirm which calibration event governs the "
                f"uncertainty for this period.", VMR0017_MON))
        else:
            findings.append(Finding(
                "mr.calibration", Severity.PASS,
                f"Meter {meter.meter_id} calibration of "
                f"{meter.last_calibration.isoformat()} covers the monitoring "
                f"period.", VMR0017_MON))

        if meter.uncertainty_pct is None:
            findings.append(Finding(
                "mr.uncertainty", Severity.WARNING,
                f"No measurement uncertainty recorded for meter "
                f"{meter.meter_id}. VMR0017 s9.2 requires the error from the "
                f"last calibration event, or the manufacturer's figure where "
                f"no record exists.", VMR0017_MON))

    return findings


def check_data_completeness(period: MonitoringPeriod) -> list[Finding]:
    findings: list[Finding] = []

    if period.eg_facility_mwh <= 0:
        findings.append(Finding(
            "mr.generation", Severity.FAIL,
            "Metered net export must be greater than zero.", VMR0017_MON))

    if period.data_gap_days > 0:
        share = period.data_gap_days / period.days if period.days else 1.0
        findings.append(Finding(
            "mr.data_gap", Severity.WARNING,
            f"{period.data_gap_days} day(s) ({share:.1%}) of the monitoring "
            f"period have no direct measurement. VMR0017 s9.2 permits VT0010 "
            f"estimation where direct measurement is temporarily infeasible, "
            f"with justification and a demonstration that the method is "
            f"conservative.", VMR0017_MON))

    return findings


def build_monitoring_report(
    period: MonitoringPeriod,
    classification: Classification,
    crediting_start: date,
    technology: K.Technology,
    ex_ante_annual_reductions: float | None = None,
    prior_periods: list[MonitoringPeriod] | None = None,
    variance_threshold: float = VARIANCE_REVIEW_THRESHOLD,
) -> MonitoringReportResult:
    """Quantify a completed monitoring period ex-post and validate it."""
    findings: list[Finding] = [
        *check_period_within_crediting_period(period, classification, crediting_start),
        *check_period_continuity([*(prior_periods or []), period]),
        *check_metering(period),
        *check_data_completeness(period),
    ]

    if period.ef_grid_cm <= 0:
        findings.append(Finding(
            "mr.emission_factor", Severity.FAIL,
            "No combined margin emission factor supplied for the monitoring "
            "period.", "VT0011 v1.0"))
        er = None
    else:
        er = emission_reductions(
            period.eg_facility_mwh, period.ef_grid_cm,
            project_emissions=period.project_emissions,
            eg_facility_mwh=period.eg_facility_mwh,
            technology=technology)
        findings.extend(er.findings)

    baseline = er.baseline_emissions_tco2e if er else 0.0
    project = er.project_emissions_tco2e if er else 0.0
    leakage = er.leakage_emissions_tco2e if er else 0.0
    reductions = er.emission_reductions_tco2e if er else 0.0

    # Ex-ante comparison, pro-rated to the length of this period.
    variance: float | None = None
    if ex_ante_annual_reductions and period.days and er:
        expected = ex_ante_annual_reductions * period.days / 365.0
        if expected > 0:
            variance = (reductions - expected) / expected
            direction = "above" if variance > 0 else "below"
            if abs(variance) >= variance_threshold:
                findings.append(Finding(
                    "mr.ex_ante_variance", Severity.WARNING,
                    f"Ex-post reductions of {reductions:,.0f} tCO2e are "
                    f"{abs(variance):.1%} {direction} the pro-rated ex-ante "
                    f"estimate of {expected:,.0f} tCO2e. Expect a verifier to "
                    f"ask for an explanation. (Threshold is a review "
                    f"heuristic, not a VCS requirement.)", VARIANCE_SOURCE))
            else:
                findings.append(Finding(
                    "mr.ex_ante_variance", Severity.PASS,
                    f"Ex-post reductions are within {variance_threshold:.0%} "
                    f"of the pro-rated ex-ante estimate "
                    f"({variance:+.1%}).", VARIANCE_SOURCE))

    return MonitoringReportResult(
        period=period,
        baseline_tco2e=baseline,
        project_tco2e=project,
        leakage_tco2e=leakage,
        reductions_tco2e=reductions,
        ex_ante_reductions_tco2e=ex_ante_annual_reductions,
        variance_fraction=variance,
        findings=findings,
    )


# ---------------------------------------------------------------------------
# Prose
# ---------------------------------------------------------------------------

def monitoring_report_sections(
    result: MonitoringReportResult,
) -> dict[str, list[str]]:
    period = result.period
    sections: dict[str, list[str]] = {
        "Quantification of Reductions and Removals": [
            f"Emission reductions for the monitoring period "
            f"{period.start.isoformat()} to {period.end.isoformat()} "
            f"({period.days} days) are quantified in accordance with VMR0017 "
            f"v1.0, equation (17), using metered net electricity export.",
            f"ER = BE − PE − LE = {result.baseline_tco2e:,.1f} − "
            f"{result.project_tco2e:,.1f} − {result.leakage_tco2e:,.1f} = "
            f"{result.reductions_tco2e:,.1f} tCO2e.",
        ],
        "Baseline Emissions": [
            f"BE = EG_facility × EF_grid,CM = "
            f"{period.eg_facility_mwh:,.0f} MWh × "
            f"{period.ef_grid_cm:.4f} tCO2/MWh = "
            f"{result.baseline_tco2e:,.1f} tCO2e, where EG_facility is the net "
            f"electricity supplied to the grid as measured at the grid "
            f"interface in accordance with VMR0017 v1.0 Section 9.2.",
        ],
        "Summary of Reductions and Removals": [
            f"Total emission reductions for the monitoring period: "
            f"{result.reductions_tco2e:,.1f} tCO2e "
            f"({result.annualised_reductions_tco2e:,.0f} tCO2e annualised).",
        ],
    }

    if result.variance_fraction is not None:
        expected = (result.ex_ante_reductions_tco2e or 0) * period.days / 365.0
        direction = "higher" if result.variance_fraction > 0 else "lower"
        sections["Ex-Ante vs Ex-Post Comparison"] = [
            f"The ex-ante estimate for a period of this length was "
            f"{expected:,.0f} tCO2e. Ex-post reductions of "
            f"{result.reductions_tco2e:,.0f} tCO2e are "
            f"{abs(result.variance_fraction):.1%} {direction}. The difference "
            f"arises from the variance between estimated and actual "
            f"electricity generation over the period; the emission factor and "
            f"quantification approach are unchanged from those applied at "
            f"validation.",
        ]

    if period.data_gap_days:
        sections["Procedures for Handling Non-Conformances"] = [
            f"Direct measurement was unavailable for {period.data_gap_days} "
            f"day(s) of the monitoring period. Generation for that interval "
            f"was determined using an estimation method in line with VT0010, "
            f"as permitted by VMR0017 v1.0 Section 9.2 where direct "
            f"measurement is temporarily infeasible. The justification and the "
            f"demonstration that the method is conservative are to be recorded "
            f"by the project proponent.",
        ]

    return sections
