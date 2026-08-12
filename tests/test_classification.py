"""
Module 1 tests. Each test names the clause it defends so a failure tells you
which regulation you broke, not just which assertion tripped.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.domain import constants as K
from app.domain.classification import (
    ProjectIntake,
    Severity,
    classify,
    select_template_version,
)


def _intake(**overrides) -> ProjectIntake:
    base = dict(
        name="Aligarh Solar One",
        proponent="Bodhi Hub Client",
        country_iso2="IN",
        technology=K.Technology.SOLAR_PV_TERRESTRIAL,
        installed_capacity_mw=50.0,
        expected_annual_generation_mwh=87_600.0,  # 20% capacity factor
        initial_crediting_period_start=date.today() - timedelta(days=180),
    )
    base.update(overrides)
    return ProjectIntake(**base)


def _finding(result, check):
    return next(f for f in result.findings if f.check == check)


# --- template routing: VCS v5 cutover -------------------------------------

@pytest.mark.parametrize("start,expected", [
    (date(2026, 12, 31), K.TemplateVersion.A),
    (date(2027, 1, 1), K.TemplateVersion.B),
    (date(2027, 6, 15), K.TemplateVersion.B),
])
def test_template_version_routes_on_cutover(start, expected):
    assert select_template_version(start) is expected


# --- VMR0017 Table 1: geography -------------------------------------------

def test_solar_in_lower_middle_income_country_is_eligible():
    result = classify(_intake(country_iso2="IN"))
    assert _finding(result, "vmr0017.geography").severity is Severity.PASS
    assert not result.blocked


def test_solar_in_high_income_country_is_blocked():
    """VMR0017 Table 1 restricts solar/wind to non-high-income economies."""
    result = classify(_intake(country_iso2="DE"))
    assert _finding(result, "vmr0017.geography").severity is Severity.FAIL
    assert result.blocked


def test_unknown_country_warns_rather_than_passing():
    """A wrong PASS invalidates the PDD, so unknown must route to review."""
    result = classify(_intake(country_iso2="ZZ"))
    assert _finding(result, "vmr0017.geography").severity is Severity.WARNING
    assert result.needs_review
    assert not result.blocked


def test_wave_is_globally_applicable():
    result = classify(_intake(country_iso2="US", technology=K.Technology.WAVE))
    assert _finding(result, "vmr0017.geography").severity is Severity.PASS


# --- VMR0017 Table 1: hydro capacity + LDC --------------------------------

def test_hydro_outside_ldc_is_blocked():
    result = classify(_intake(
        country_iso2="IN", technology=K.Technology.HYDRO,
        installed_capacity_mw=10.0, expected_annual_generation_mwh=35_000.0))
    assert _finding(result, "vmr0017.geography").severity is Severity.FAIL


def test_hydro_uses_higher_of_rated_and_authorised_capacity():
    """VMR0017 Table 1: 15 MW ceiling, whichever of the two is higher."""
    result = classify(_intake(
        country_iso2="NP", technology=K.Technology.HYDRO,
        installed_capacity_mw=12.0,
        authorised_capacity_mw=18.0,          # higher -> governs -> over ceiling
        expected_annual_generation_mwh=40_000.0))
    assert _finding(result, "vmr0017.capacity").severity is Severity.FAIL


def test_hydro_within_ceiling_in_ldc_passes():
    result = classify(_intake(
        country_iso2="NP", technology=K.Technology.HYDRO,
        installed_capacity_mw=12.0, authorised_capacity_mw=14.0,
        expected_annual_generation_mwh=40_000.0))
    assert _finding(result, "vmr0017.capacity").severity is Severity.PASS
    assert _finding(result, "vmr0017.geography").severity is Severity.PASS


# --- VT0011 Step 6 para 86: combined margin weights -----------------------

@pytest.mark.parametrize("ordinal,expected", [
    (1, (0.50, 0.50)),
    (2, (0.40, 0.60)),
    (3, (0.30, 0.70)),
])
def test_wind_solar_cm_weights_by_crediting_period(ordinal, expected):
    result = classify(_intake(crediting_period_ordinal=ordinal))
    assert result.cm_weights == expected


def test_ldc_projects_are_offered_the_wom_1_election():
    """VT0011 para 90 — usually more favourable; must not be silently skipped."""
    result = classify(_intake(
        country_iso2="NP", technology=K.Technology.WIND_ONSHORE,
        expected_annual_generation_mwh=131_400.0))
    assert _finding(result, "vt0011.cm_weights.ldc_option").severity is Severity.WARNING


# --- VCS Standard v5.0 Table 8: crediting period --------------------------

def test_ei_crediting_period_is_five_years_not_seven():
    """v5.0 shortened E&I to 5 years x 3 = 15. Financial models must follow."""
    result = classify(_intake())
    assert result.crediting_period_years == 5
    assert result.max_total_crediting_years == 15


def test_fourth_crediting_period_is_blocked():
    result = classify(_intake(crediting_period_ordinal=4))
    assert _finding(result, "vcs.crediting_period").severity is Severity.FAIL


# --- data quality ----------------------------------------------------------

def test_zero_capacity_is_blocked():
    result = classify(_intake(installed_capacity_mw=0.0))
    assert _finding(result, "intake.capacity").severity is Severity.FAIL


def test_implausible_capacity_factor_is_flagged():
    """Catches a kW/MW or kWh/MWh mix-up before it reaches the baseline calc."""
    result = classify(_intake(
        installed_capacity_mw=50.0,
        expected_annual_generation_mwh=87_600_000.0))  # 1000x too large
    assert _finding(result, "intake.capacity_factor").severity is Severity.WARNING


def test_offgrid_project_is_blocked():
    result = classify(_intake(grid_connected=False))
    assert _finding(result, "intake.grid_connection").severity is Severity.FAIL


# --- VCS Standard v5.0 s3.8.2 / Table 7: deadlines ------------------------

def test_missed_pipeline_listing_deadline_is_blocked():
    result = classify(_intake(
        initial_crediting_period_start=date.today() - timedelta(days=500)))
    assert _finding(result, "vcs.pipeline_listing_deadline").severity is Severity.FAIL


def test_registration_deadline_is_two_years_for_ei():
    start = date.today() - timedelta(days=30)
    result = classify(_intake(initial_crediting_period_start=start))
    assert result.registration_deadline.year == start.year + 2


def test_new_methodology_extends_registration_to_four_years():
    start = date.today() - timedelta(days=30)
    result = classify(_intake(
        initial_crediting_period_start=start, applies_new_methodology=True))
    assert result.registration_deadline.year == start.year + 4


# --- every finding must be traceable --------------------------------------

def test_all_findings_carry_a_source_citation():
    result = classify(_intake())
    assert all(f.source for f in result.findings)
