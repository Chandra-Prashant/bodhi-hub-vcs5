"""Module 4a tests — monitoring parameters and VMR0017 s9.1 defaults."""

from __future__ import annotations

import pytest

from app.domain import constants as K
from app.domain.baseline import emission_reductions
from app.domain.classification import Severity
from app.domain.monitoring import (
    EMBODIED_EF_G_CO2E_PER_KWH,
    RESERVOIR_EF_KG_CO2E_PER_MWH,
    ParameterKind,
    build_monitoring_parameters,
    embodied_emission_factor,
)


def _names(params) -> set[str]:
    return {p.name for p in params}


def _finding(findings, check):
    return next(f for f in findings if f.check == check)


# --- VMR0017 s9.1 defaults table ------------------------------------------

@pytest.mark.parametrize("technology,expected", [
    (K.Technology.SOLAR_PV_TERRESTRIAL, 43.0),
    (K.Technology.SOLAR_PV_FLOATING, 43.0),
    (K.Technology.WIND_ONSHORE, 13.0),
    (K.Technology.WIND_OFFSHORE, 13.0),
    (K.Technology.GEOTHERMAL, 37.0),
    (K.Technology.HYDRO, 21.0),
    (K.Technology.WAVE, 8.0),
    (K.Technology.TIDAL, 8.0),
])
def test_embodied_defaults_match_the_methodology_table(technology, expected):
    ef, findings = embodied_emission_factor(technology)
    assert ef == expected
    assert findings[0].severity is Severity.PASS
    assert "s9.1" in findings[0].source


def test_every_eligible_technology_has_a_default():
    assert set(EMBODIED_EF_G_CO2E_PER_KWH) == set(K.Technology)


def test_reservoir_default_is_one_hundred():
    """VMR0017 s9.1 replaces ACM0002 Data/Parameter table 6."""
    assert RESERVOIR_EF_KG_CO2E_PER_MWH == 100.0


# --- the correction this catches ------------------------------------------

def test_methodology_default_is_used_when_none_supplied():
    result = emission_reductions(
        87_600, 0.8383, eg_facility_mwh=87_600,
        technology=K.Technology.SOLAR_PV_TERRESTRIAL)
    assert result.leakage_emissions_tco2e == pytest.approx(87_600 * 43.0 * 1e-3)


def test_a_lower_guess_overstates_reductions():
    """43 g CO2e/kWh is mandatory for solar PV. Substituting a lower figure
    inflates ER_y — here by over 1,500 tCO2e a year on a 50 MW plant."""
    guessed = emission_reductions(87_600, 0.8383, eg_facility_mwh=87_600,
                                  ef_embodied_kg_per_mwh=25.0)
    correct = emission_reductions(87_600, 0.8383, eg_facility_mwh=87_600,
                                  technology=K.Technology.SOLAR_PV_TERRESTRIAL)
    assert guessed.emission_reductions_tco2e > correct.emission_reductions_tco2e
    assert (guessed.emission_reductions_tco2e
            - correct.emission_reductions_tco2e) == pytest.approx(
                87_600 * (43.0 - 25.0) * 1e-3)


def test_wind_leaks_less_than_solar():
    """13 vs 43 g CO2e/kWh — the technology difference is material."""
    wind = emission_reductions(87_600, 0.8383, eg_facility_mwh=87_600,
                               technology=K.Technology.WIND_ONSHORE)
    solar = emission_reductions(87_600, 0.8383, eg_facility_mwh=87_600,
                                technology=K.Technology.SOLAR_PV_TERRESTRIAL)
    assert wind.leakage_emissions_tco2e < solar.leakage_emissions_tco2e


def test_explicit_value_still_overrides_the_default():
    """The default applies when nothing is supplied; an author who justifies a
    different figure per s9.1 comments must still be able to use it."""
    result = emission_reductions(
        87_600, 0.8383, eg_facility_mwh=87_600, ef_embodied_kg_per_mwh=50.0,
        technology=K.Technology.SOLAR_PV_TERRESTRIAL)
    assert result.leakage_emissions_tco2e == pytest.approx(87_600 * 50.0 * 1e-3)


# --- parameter registry ----------------------------------------------------

def test_core_parameters_present_for_a_solar_project():
    mp = build_monitoring_parameters(K.Technology.SOLAR_PV_TERRESTRIAL)
    assert {"EFembodied", "EFgrid,CM,y"} <= _names(mp.at_validation)
    assert {"EGfacility,y", "EGPJ_Add,y"} <= _names(mp.monitored)


def test_solar_has_no_reservoir_or_fire_suppression_parameters():
    mp = build_monitoring_parameters(K.Technology.SOLAR_PV_TERRESTRIAL)
    assert "EFRes" not in _names(mp.at_validation)
    assert "Me,released,y" not in _names(mp.monitored)


def test_hydro_adds_the_reservoir_parameter():
    mp = build_monitoring_parameters(K.Technology.HYDRO)
    assert "EFRes" in _names(mp.at_validation)


def test_bess_adds_fire_suppression_parameters():
    mp = build_monitoring_parameters(
        K.Technology.SOLAR_PV_TERRESTRIAL, has_bess=True)
    assert "GWPagent" in _names(mp.at_validation)
    assert "Me,released,y" in _names(mp.monitored)
    assert _finding(mp.findings, "vmr0017.bess").severity is Severity.WARNING


def test_monitored_parameters_carry_frequency_and_qa_qc():
    """A Data/Parameter table without these is incomplete at validation."""
    mp = build_monitoring_parameters(K.Technology.WIND_ONSHORE)
    for p in mp.monitored:
        assert p.monitoring_frequency
        assert p.qa_qc
        assert p.kind is ParameterKind.MONITORED


def test_generation_monitoring_requires_direct_measurement():
    mp = build_monitoring_parameters(K.Technology.SOLAR_PV_TERRESTRIAL)
    eg = next(p for p in mp.monitored if p.name == "EGfacility,y")
    assert "direct measurement" in eg.measurement_methods.lower()
    assert "monthly" in eg.monitoring_frequency.lower()
    assert "calibrat" in eg.qa_qc.lower()


def test_every_parameter_carries_a_citation():
    for tech in K.Technology:
        mp = build_monitoring_parameters(tech, has_bess=True)
        assert all(p.citation for p in mp.all())
