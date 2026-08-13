"""Module 6 tests — monitoring report."""

from __future__ import annotations

from datetime import date, timedelta

import docx
import pytest

from app.domain import constants as K
from app.domain.baseline import ProjectEmissions
from app.domain.classification import ProjectIntake, Severity, classify
from app.domain.monitoring import build_monitoring_parameters
from app.domain.monitoring_report import (
    MeterCalibration,
    MonitoringPeriod,
    build_monitoring_report,
    check_period_continuity,
    monitoring_report_sections,
)
from app.services.monitoring_report_builder import (
    build_monitoring_report as render_report,
)
from app.services.pdd_builder import monitoring_report_template_path

CREDITING_START = date(2026, 3, 1)
EF_CM = 0.8383


def _classification(**overrides):
    base = dict(
        name="Aligarh Solar One", proponent="Bodhi Hub Client",
        country_iso2="IN", technology=K.Technology.SOLAR_PV_TERRESTRIAL,
        installed_capacity_mw=50.0, expected_annual_generation_mwh=87_600.0,
        initial_crediting_period_start=CREDITING_START,
    )
    base.update(overrides)
    return classify(ProjectIntake(**base))


def _meter(last=date(2026, 6, 1), **kw) -> MeterCalibration:
    return MeterCalibration(meter_id="M-1", last_calibration=last,
                            uncertainty_pct=0.5, **kw)


def _period(**overrides) -> MonitoringPeriod:
    base = dict(
        start=date(2026, 3, 1), end=date(2027, 2, 28),
        eg_facility_mwh=85_000.0, ef_grid_cm=EF_CM,
        meters=[_meter()],
    )
    base.update(overrides)
    return MonitoringPeriod(**base)


def _run(period=None, **kw):
    return build_monitoring_report(
        period or _period(), _classification(), CREDITING_START,
        K.Technology.SOLAR_PV_TERRESTRIAL, **kw)


def _finding(findings, check):
    return next(f for f in findings if f.check == check)


def _has(findings, check) -> bool:
    return any(f.check == check for f in findings)


# --- ex-post quantification ------------------------------------------------

def test_uses_metered_generation_not_the_estimate():
    """The whole point of a monitoring report: 85,000 MWh metered, not the
    87,600 MWh estimated at validation."""
    result = _run()
    assert result.baseline_tco2e == pytest.approx(85_000 * EF_CM)


def test_leakage_uses_the_methodology_default():
    result = _run()
    assert result.leakage_tco2e == pytest.approx(85_000 * 43.0 * 1e-3)


def test_reductions_follow_equation_17():
    result = _run(period=_period(
        project_emissions=ProjectEmissions(bess=50.0)))
    assert result.reductions_tco2e == pytest.approx(
        result.baseline_tco2e - 50.0 - result.leakage_tco2e)


def test_annualisation_scales_a_short_period():
    result = _run(period=_period(start=date(2026, 3, 1), end=date(2026, 8, 28),
                                 eg_facility_mwh=42_500.0))
    assert result.annualised_reductions_tco2e > result.reductions_tco2e


def test_missing_emission_factor_is_blocked():
    result = _run(period=_period(ef_grid_cm=0.0))
    assert result.blocked
    assert _finding(result.findings, "mr.emission_factor").severity is Severity.FAIL


def test_zero_generation_is_blocked():
    result = _run(period=_period(eg_facility_mwh=0.0))
    assert result.blocked


# --- period bounds ---------------------------------------------------------

def test_period_before_the_crediting_period_is_blocked():
    result = _run(period=_period(start=date(2026, 1, 1), end=date(2026, 12, 31)))
    assert _finding(result.findings, "mr.period_start").severity is Severity.FAIL


def test_period_past_the_crediting_period_end_is_blocked():
    """Crediting period ends 01-MAR-2031 under the 5-year E&I rule."""
    result = _run(period=_period(start=date(2031, 1, 1), end=date(2031, 12, 31)))
    assert _finding(result.findings, "mr.period_end").severity is Severity.FAIL


def test_reversed_period_is_blocked():
    result = _run(period=_period(start=date(2027, 1, 1), end=date(2026, 1, 1)))
    assert _finding(result.findings, "mr.period_order").severity is Severity.FAIL


def test_a_valid_period_passes():
    result = _run()
    assert _finding(result.findings, "mr.period").severity is Severity.PASS


# --- continuity: gaps forfeit credits, overlaps double-issue --------------

def test_contiguous_periods_pass():
    a = _period(start=date(2026, 3, 1), end=date(2026, 8, 31))
    b = _period(start=date(2026, 9, 1), end=date(2027, 2, 28))
    findings = check_period_continuity([a, b])
    assert _finding(findings, "mr.continuity").severity is Severity.PASS


def test_a_gap_between_periods_is_flagged():
    a = _period(start=date(2026, 3, 1), end=date(2026, 8, 31))
    b = _period(start=date(2026, 9, 15), end=date(2027, 2, 28))
    f = _finding(check_period_continuity([a, b]), "mr.continuity_gap")
    assert f.severity is Severity.WARNING
    assert "14 day" in f.message


def test_overlapping_periods_are_blocked():
    """Overlap means the same generation is credited twice."""
    a = _period(start=date(2026, 3, 1), end=date(2026, 9, 30))
    b = _period(start=date(2026, 9, 1), end=date(2027, 2, 28))
    f = _finding(check_period_continuity([a, b]), "mr.continuity_overlap")
    assert f.severity is Severity.FAIL
    assert "30 day" in f.message


def test_continuity_is_checked_against_prior_periods():
    prior = _period(start=date(2026, 3, 1), end=date(2026, 8, 31))
    current = _period(start=date(2026, 10, 1), end=date(2027, 2, 28))
    result = _run(period=current, prior_periods=[prior])
    assert _has(result.findings, "mr.continuity_gap")


# --- metering --------------------------------------------------------------

def test_no_calibration_record_is_blocked():
    result = _run(period=_period(meters=[]))
    assert _finding(result.findings, "mr.metering").severity is Severity.FAIL


def test_calibration_expiring_mid_period_is_blocked():
    result = _run(period=_period(meters=[_meter(last=date(2025, 1, 1))]))
    assert _finding(
        result.findings, "mr.calibration_overdue").severity is Severity.FAIL


def test_calibration_after_the_period_is_flagged_for_review():
    result = _run(period=_period(
        start=date(2026, 3, 1), end=date(2026, 6, 30),
        meters=[_meter(last=date(2026, 9, 1))]))
    assert _finding(
        result.findings, "mr.calibration_after_period").severity is Severity.WARNING


def test_missing_uncertainty_is_flagged():
    meter = MeterCalibration(meter_id="M-1", last_calibration=date(2026, 6, 1))
    result = _run(period=_period(meters=[meter]))
    assert _finding(result.findings, "mr.uncertainty").severity is Severity.WARNING


def test_valid_calibration_passes():
    result = _run()
    assert _finding(result.findings, "mr.calibration").severity is Severity.PASS


# --- data gaps -------------------------------------------------------------

def test_data_gaps_are_flagged_with_the_vt0010_route():
    result = _run(period=_period(data_gap_days=12))
    f = _finding(result.findings, "mr.data_gap")
    assert f.severity is Severity.WARNING
    assert "VT0010" in f.message


def test_data_gaps_reach_the_non_conformance_section():
    result = _run(period=_period(data_gap_days=12))
    sections = monitoring_report_sections(result)
    assert "Procedures for Handling Non-Conformances" in sections


# --- ex-ante comparison ----------------------------------------------------

def test_close_agreement_with_the_estimate_passes():
    result = _run(ex_ante_annual_reductions=69_672.0)
    assert _finding(
        result.findings, "mr.ex_ante_variance").severity is Severity.PASS


def test_large_shortfall_is_flagged_for_the_verifier():
    result = _run(period=_period(eg_facility_mwh=50_000.0),
                  ex_ante_annual_reductions=69_672.0)
    f = _finding(result.findings, "mr.ex_ante_variance")
    assert f.severity is Severity.WARNING
    assert "below" in f.message


def test_the_variance_threshold_is_labelled_as_ours_not_verras():
    """It must never be cited to a client as a VCS requirement."""
    result = _run(period=_period(eg_facility_mwh=50_000.0),
                  ex_ante_annual_reductions=69_672.0)
    f = _finding(result.findings, "mr.ex_ante_variance")
    assert "not a VCS requirement" in f.source
    assert "not a VCS requirement" in f.message


def test_the_threshold_is_configurable():
    strict = _run(period=_period(eg_facility_mwh=83_000.0),
                  ex_ante_annual_reductions=69_672.0, variance_threshold=0.01)
    assert _finding(
        strict.findings, "mr.ex_ante_variance").severity is Severity.WARNING


def test_variance_is_prorated_for_a_short_period():
    """A half-year period must be compared against half the annual estimate,
    not the whole of it."""
    result = _run(period=_period(start=date(2026, 3, 1), end=date(2026, 8, 28),
                                 eg_facility_mwh=42_500.0),
                  ex_ante_annual_reductions=69_672.0)
    assert abs(result.variance_fraction) < 0.10


def test_no_comparison_without_an_ex_ante_figure():
    result = _run()
    assert result.variance_fraction is None
    assert not _has(result.findings, "mr.ex_ante_variance")


# --- rendering -------------------------------------------------------------

def test_both_monitoring_report_templates_resolve():
    """Verra ships these as 'V5.0A' while the PD template is 'v5.0A'. Case
    matters on Linux even though it does not on macOS."""
    for version in (K.TemplateVersion.A, K.TemplateVersion.B):
        assert monitoring_report_template_path(version).exists()


def test_report_renders_to_docx(tmp_path):
    result = _run(ex_ante_annual_reductions=69_672.0)
    built = render_report(
        result, _classification(), "Aligarh Solar One", "Bodhi Hub Client",
        tmp_path / "MR.docx",
        monitoring=build_monitoring_parameters(K.Technology.SOLAR_PV_TERRESTRIAL))
    assert built.output_path.exists()
    assert built.report.fields_not_found == []


def test_monitoring_period_dates_appear_in_the_document(tmp_path):
    result = _run()
    built = render_report(result, _classification(), "Aligarh Solar One",
                          "Bodhi Hub Client", tmp_path / "MR.docx")
    doc = docx.Document(str(built.output_path))
    text = " ".join(c.text for t in doc.tables for r in t.rows for c in r.cells)
    assert "01-MAR-2026" in text


def test_quantification_sections_are_drafted(tmp_path):
    result = _run(ex_ante_annual_reductions=69_672.0)
    built = render_report(result, _classification(), "Aligarh Solar One",
                          "Bodhi Hub Client", tmp_path / "MR.docx")
    assert "Quantification of Reductions and Removals" in built.report.sections_written
    assert "Ex-Ante vs Ex-Post Comparison" in built.report.sections_written


def test_a_blocked_period_blocks_the_report(tmp_path):
    result = _run(period=_period(meters=[]))
    built = render_report(result, _classification(), "Aligarh Solar One",
                          "Bodhi Hub Client", tmp_path / "MR.docx")
    assert built.blocked
    assert _finding(built.findings, "mr.build").severity is Severity.FAIL


def test_remaining_guidance_is_reported(tmp_path):
    result = _run()
    built = render_report(result, _classification(), "Aligarh Solar One",
                          "Bodhi Hub Client", tmp_path / "MR.docx")
    assert sum(built.report.instructions_remaining.values()) > 0
    assert built.sections_needing_input[0][1] >= built.sections_needing_input[-1][1]


def test_the_source_template_is_never_modified(tmp_path):
    source = monitoring_report_template_path(K.TemplateVersion.A)
    before = source.read_bytes()
    render_report(_run(), _classification(), "X", "Y", tmp_path / "MR.docx",
                  strip_guidance=True)
    assert source.read_bytes() == before


def test_every_finding_carries_a_source():
    result = _run(ex_ante_annual_reductions=69_672.0)
    assert all(f.source for f in result.findings)
