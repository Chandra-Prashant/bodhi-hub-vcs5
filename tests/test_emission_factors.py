"""
Module 2 tests — grid emission factors (VT0011) and baseline (VMR0017/ACM0002).

Hand-checkable numbers throughout: if a test fails you should be able to
reproduce the expected value on paper from the clause named in the test.
"""

from __future__ import annotations

import pytest

from app.domain import constants as K
from app.domain.baseline import (
    ProjectEmissions,
    baseline_emissions,
    emission_reductions,
    leakage_emissions,
)
from app.domain.classification import Severity
from app.domain.emission_factors import (
    FuelInput,
    OMMethod,
    PowerUnit,
    ProjectCase,
    build_margin,
    combined_margin,
    grid_emission_factor,
    select_bm_sample,
    simple_om,
    unit_emission_factor,
)


def _coal(unit_id: str, gen: float, year: int, ef: float = 0.0946) -> PowerUnit:
    """Coal unit, Option A2. IPCC default EF for other bituminous coal is
    ~94.6 kg CO2/GJ; efficiency 35% gives ~0.973 t CO2/MWh."""
    return PowerUnit(unit_id=unit_id, generation_mwh=gen,
                     commissioning_year=year, efficiency=0.35,
                     efficiency_fuel_ef_t_per_gj=ef)


def _hydro(unit_id: str, gen: float, year: int) -> PowerUnit:
    return PowerUnit(unit_id=unit_id, generation_mwh=gen,
                     commissioning_year=year, low_cost_must_run=True,
                     generation_only=True)


def _finding(findings, check):
    return next(f for f in findings if f.check == check)


# --- per-unit emission factor ---------------------------------------------

def test_option_a2_efficiency_formula():
    """EF_EL = EF_CO2 * 3.6 / eta = 0.0946 * 3.6 / 0.35"""
    unit = _coal("C1", 1000.0, 2020)
    ef, _ = unit_emission_factor(unit, ProjectCase.SUPPLIES_GRID)
    assert ef == pytest.approx(0.0946 * 3.6 / 0.35, rel=1e-9)


def test_option_a1_fuel_formula():
    """EF_EL = sum(FC * NCV * EF_CO2) / EG"""
    unit = PowerUnit(
        unit_id="G1", generation_mwh=1_000.0, commissioning_year=2021,
        fuels=[FuelInput("natural_gas", quantity=200_000.0,
                         ncv_gj_per_unit=0.0383, ef_co2_t_per_gj=0.0561)],
    )
    ef, _ = unit_emission_factor(unit, ProjectCase.SUPPLIES_GRID)
    assert ef == pytest.approx(200_000 * 0.0383 * 0.0561 / 1_000, rel=1e-9)


def test_option_a3_defaults_by_case():
    """VT0011 para 50: 0 for Case 1, 1.3 for Case 2."""
    unit = PowerUnit("X", 500.0, 2022, generation_only=True)
    ef1, f1 = unit_emission_factor(unit, ProjectCase.SUPPLIES_GRID)
    ef2, _ = unit_emission_factor(unit, ProjectCase.INCREASES_CONSUMPTION)
    assert ef1 == 0.0
    assert ef2 == 1.3
    assert f1[0].severity is Severity.WARNING


def test_multifuel_case1_picks_lowest_emission_fuel():
    """VT0011 para 50 Option A.2.i."""
    unit = PowerUnit(
        unit_id="M1", generation_mwh=1_000.0, commissioning_year=2020,
        fuels=[
            FuelInput("coal", 100.0, 25.0, 0.0946),
            FuelInput("gas", 100.0, 25.0, 0.0561),
        ],
    )
    ef_low, _ = unit_emission_factor(unit, ProjectCase.SUPPLIES_GRID)
    ef_high, _ = unit_emission_factor(unit, ProjectCase.INCREASES_CONSUMPTION)
    assert ef_low < ef_high
    assert ef_low == pytest.approx(2 * 100.0 * 25.0 * 0.0561 / 1_000, rel=1e-9)


def test_efficiency_outside_range_is_blocked():
    unit = PowerUnit("B", 100.0, 2020, efficiency=1.4,
                     efficiency_fuel_ef_t_per_gj=0.09)
    _, findings = unit_emission_factor(unit, ProjectCase.SUPPLIES_GRID)
    assert findings[0].severity is Severity.FAIL


# --- simple OM applicability, TOOL07 para 40 ------------------------------

def test_simple_om_blocked_when_must_run_exceeds_half():
    units = [_coal("C1", 4_000.0, 2018), _hydro("H1", 6_000.0, 2015)]
    _, findings = simple_om(units, ProjectCase.SUPPLIES_GRID)
    f = _finding(findings, "vt0011.om.applicability")
    assert f.severity is Severity.FAIL
    assert "50%" in f.message


def test_simple_om_excludes_must_run_from_the_sample():
    """Hydro is excluded entirely, so the OM equals the coal unit's own EF."""
    units = [_coal("C1", 8_000.0, 2018), _hydro("H1", 2_000.0, 2015)]
    ef_om, findings = simple_om(units, ProjectCase.SUPPLIES_GRID)
    assert _finding(findings, "vt0011.om.applicability").severity is Severity.PASS
    assert ef_om == pytest.approx(0.0946 * 3.6 / 0.35, rel=1e-9)


def test_simple_om_is_generation_weighted():
    units = [
        _coal("C1", 9_000.0, 2018, ef=0.10),
        _coal("C2", 1_000.0, 2019, ef=0.05),
    ]
    ef_om, _ = simple_om(units, ProjectCase.SUPPLIES_GRID)
    expected = (9_000 * 0.10 * 3.6 / 0.35 + 1_000 * 0.05 * 3.6 / 0.35) / 10_000
    assert ef_om == pytest.approx(expected, rel=1e-9)


# --- build margin sample, VT0011 para 75 ----------------------------------

def test_bm_picks_the_larger_of_set5_and_set20():
    """Six small recent units vs one huge older one: SET_>=20% should win
    because the older unit alone exceeds the five newest combined."""
    units = [
        _coal("BIG", 100_000.0, 2010),
        *[_coal(f"S{i}", 1_000.0, 2020 + i) for i in range(6)],
    ]
    sample, findings = select_bm_sample(units)
    ids = {u.unit_id for u in sample}
    assert "BIG" in ids
    assert _finding(findings, "vt0011.bm.sample").severity is Severity.PASS


def test_bm_set5_wins_when_recent_units_dominate():
    units = [
        *[_coal(f"N{i}", 20_000.0, 2020 + i) for i in range(5)],
        _coal("OLD", 1_000.0, 2000),
    ]
    sample, _ = select_bm_sample(units)
    assert len(sample) == 5
    assert "OLD" not in {u.unit_id for u in sample}


def test_bm_flags_units_older_than_ten_years():
    """VT0011 para 79 restricts these to Option A2 with TOOL09 defaults."""
    units = [_coal("NEW", 1_000.0, 2024), _coal("OLD", 100_000.0, 2005)]
    _, findings = select_bm_sample(units)
    assert _finding(findings, "vt0011.bm.old_units").severity is Severity.WARNING


def test_build_margin_is_generation_weighted():
    units = [
        _coal("N1", 3_000.0, 2023, ef=0.10),
        _coal("N2", 1_000.0, 2024, ef=0.06),
    ]
    ef_bm, ids, _ = build_margin(units, ProjectCase.SUPPLIES_GRID)
    expected = (3_000 * 0.10 * 3.6 / 0.35 + 1_000 * 0.06 * 3.6 / 0.35) / 4_000
    assert ef_bm == pytest.approx(expected, rel=1e-9)
    assert set(ids) == {"N1", "N2"}


# --- combined margin, VT0011 para 86 --------------------------------------

@pytest.mark.parametrize("ordinal,w_om,w_bm", [
    (1, 0.50, 0.50),
    (2, 0.40, 0.60),
    (3, 0.30, 0.70),
])
def test_cm_weights_for_wind_and_solar(ordinal, w_om, w_bm):
    ef_cm, weights, _ = combined_margin(
        1.0, 0.5, K.Technology.SOLAR_PV_TERRESTRIAL, ordinal)
    assert weights == (w_om, w_bm)
    assert ef_cm == pytest.approx(1.0 * w_om + 0.5 * w_bm)


def test_case2_uses_operating_margin_only():
    _, weights, _ = combined_margin(
        1.0, 0.5, K.Technology.SOLAR_PV_TERRESTRIAL, 1,
        case=ProjectCase.INCREASES_CONSUMPTION)
    assert weights == (1.0, 0.0)


def test_unimplemented_om_methods_fail_loudly():
    """Better a hard stop than a plausible wrong number in a PDD."""
    units = [_coal("C1", 10_000.0, 2020)]
    result = grid_emission_factor(
        units, K.Technology.WIND_ONSHORE, 1,
        om_method=OMMethod.DISPATCH_DATA)
    assert result.blocked


def test_full_pipeline_produces_a_combined_margin():
    units = [
        _coal("C1", 50_000.0, 2012),
        _coal("C2", 30_000.0, 2021),
        _coal("C3", 10_000.0, 2023),
        _hydro("H1", 10_000.0, 2008),
    ]
    result = grid_emission_factor(units, K.Technology.WIND_ONSHORE, 1)
    assert not result.blocked
    assert result.ef_grid_cm == pytest.approx(
        result.ef_grid_om * 0.5 + result.ef_grid_bm * 0.5, rel=1e-9)
    assert all(f.source for f in result.findings)


# --- baseline and emission reductions -------------------------------------

def test_baseline_emissions_formula():
    be, _ = baseline_emissions(87_600.0, 0.82)
    assert be == pytest.approx(87_600 * 0.82)


def test_leakage_applies_the_kg_to_tonne_factor():
    """VMR0017 eq. 19 carries an explicit 10^-3."""
    le, _ = leakage_emissions(87_600.0, 25.0)
    assert le == pytest.approx(87_600 * 25.0 * 1e-3)


def test_missing_leakage_is_blocked_not_silently_zero():
    """ACM0002 had no embodied-emissions term; a migrated PDD will omit it."""
    result = emission_reductions(87_600.0, 0.82)
    assert result.blocked
    assert _finding(result.findings, "vmr0017.leakage").severity is Severity.FAIL


def test_zero_project_emissions_warns():
    result = emission_reductions(
        87_600.0, 0.82, eg_facility_mwh=87_600.0, ef_embodied_kg_per_mwh=25.0)
    assert _finding(
        result.findings, "vmr0017.project_emissions").severity is Severity.WARNING


def test_emission_reductions_equation():
    pe = ProjectEmissions(bess=120.0, fugitive_electrical=5.0)
    result = emission_reductions(
        87_600.0, 0.82, project_emissions=pe,
        eg_facility_mwh=87_600.0, ef_embodied_kg_per_mwh=25.0)
    expected = 87_600 * 0.82 - 125.0 - 87_600 * 25.0 * 1e-3
    assert result.emission_reductions_tco2e == pytest.approx(expected)
    assert not result.blocked


def test_negative_reductions_are_blocked():
    pe = ProjectEmissions(fossil_fuel_combustion=1_000_000.0)
    result = emission_reductions(
        87_600.0, 0.82, project_emissions=pe,
        eg_facility_mwh=87_600.0, ef_embodied_kg_per_mwh=25.0)
    assert result.blocked
