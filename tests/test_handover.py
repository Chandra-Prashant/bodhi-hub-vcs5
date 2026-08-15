"""
Tests for the join between ingestion and assessment.

Each of these defends a way the handover could silently lose something a
reviewer did.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.domain.constants import Technology
from app.services.handover import (
    HandoverRefused,
    Handover,
    build_assessment_payload,
    map_technology,
)


# --- technology mapping ----------------------------------------------------

@pytest.mark.parametrize("stated,expected", [
    ("solar PV", Technology.SOLAR_PV_TERRESTRIAL),
    ("terrestrial solar photovoltaic", Technology.SOLAR_PV_TERRESTRIAL),
    ("Solar Photovoltaic Power Plant", Technology.SOLAR_PV_TERRESTRIAL),
    ("floating solar", Technology.SOLAR_PV_FLOATING),
    ("solar floating array", Technology.SOLAR_PV_FLOATING),
    ("onshore wind farm", Technology.WIND_ONSHORE),
    ("wind", Technology.WIND_ONSHORE),
    ("offshore wind", Technology.WIND_OFFSHORE),
    ("geothermal plant", Technology.GEOTHERMAL),
    ("small hydro", Technology.HYDRO),
    ("tidal barrage", Technology.TIDAL),
])
def test_common_wordings_map(stated, expected):
    assert map_technology(stated) is expected


def test_the_more_specific_pattern_wins():
    """'floating solar' also contains 'solar'; order decides, and getting it
    wrong picks a different row of VMR0017 Table 1."""
    assert map_technology("floating solar pv") is Technology.SOLAR_PV_FLOATING
    assert map_technology("offshore wind") is Technology.WIND_OFFSHORE


def test_an_enum_name_typed_by_a_reviewer_is_accepted():
    assert map_technology("SOLAR_PV_FLOATING") is Technology.SOLAR_PV_FLOATING


@pytest.mark.parametrize("stated", [
    "biomass", "waste heat recovery", "", "   ", "nuclear", "CSP plant",
])
def test_an_unknown_technology_is_refused_not_guessed(stated):
    """'Solar thermal' is not solar PV. A fuzzy match would silently select the
    wrong methodology rules."""
    with pytest.raises(HandoverRefused):
        map_technology(stated)


def test_the_refusal_lists_the_valid_types():
    with pytest.raises(HandoverRefused, match="SOLAR_PV_TERRESTRIAL"):
        map_technology("something unrecognised")


@pytest.mark.parametrize("stated", [
    "solar thermal", "concentrated solar power",
    "solar-biomass hybrid", "wind-diesel hybrid",
])
def test_a_disqualifying_word_blocks_a_partial_match(stated):
    """These contain 'solar' or 'wind' but are not VMR0017 Table 1 types.
    Matching them would select the wrong eligibility rules and the wrong
    embodied emission factor while looking entirely correct."""
    with pytest.raises(HandoverRefused, match="not a VMR0017 Table 1"):
        map_technology(stated)


def test_geothermal_is_not_blocked_by_its_own_substring():
    """'geothermal' contains 'thermal'. The disqualifier applies to the text a
    match did not account for, not to the matched word itself."""
    assert map_technology("geothermal plant") is Technology.GEOTHERMAL
    assert map_technology("geothermal") is Technology.GEOTHERMAL


# --- payload construction --------------------------------------------------

def _handover(**overrides) -> Handover:
    values = {
        "project_name": "Aligarh Solar One",
        "proponent": "Bodhi Hub Client",
        "country_iso2": "in",
        "technology": "terrestrial solar photovoltaic",
        "installed_capacity_mw": "50",
        "expected_annual_generation_mwh": "87,600",
        "initial_crediting_period_start": "01-MAR-2026",
    }
    values.update(overrides)
    return Handover(values=values)


def test_a_complete_handover_builds_a_payload():
    payload = build_assessment_payload(_handover())
    assert payload["name"] == "Aligarh Solar One"
    assert payload["technology"] == "SOLAR_PV_TERRESTRIAL"
    assert payload["installed_capacity_mw"] == 50.0
    assert payload["expected_annual_generation_mwh"] == 87600.0


def test_country_codes_are_upper_cased():
    assert build_assessment_payload(_handover())["country_iso2"] == "IN"


def test_thousands_separators_are_handled():
    payload = build_assessment_payload(
        _handover(expected_annual_generation_mwh="87,600"))
    assert payload["expected_annual_generation_mwh"] == 87600.0


@pytest.mark.parametrize("stated", [
    "01-MAR-2026", "2026-03-01", "01/03/2026",
])
def test_common_date_formats_are_understood(stated):
    payload = build_assessment_payload(
        _handover(initial_crediting_period_start=stated))
    assert payload["initial_crediting_period_start"] == "2026-03-01"


def test_a_missing_required_field_refuses():
    handover = _handover()
    del handover.values["technology"]
    with pytest.raises(HandoverRefused, match="technology"):
        build_assessment_payload(handover)


def test_a_non_numeric_capacity_refuses():
    with pytest.raises(HandoverRefused, match="not a number"):
        build_assessment_payload(_handover(installed_capacity_mw="fifty"))


def test_an_unparseable_date_refuses():
    with pytest.raises(HandoverRefused, match="not a recognisable date"):
        build_assessment_payload(
            _handover(initial_crediting_period_start="next spring"))


# --- grid units and financials --------------------------------------------

def test_no_grid_units_are_invented():
    """A project document states its own capacity; it does not describe the
    power units of the national grid. Quantification is reported unavailable
    rather than a factor being conjured."""
    assert build_assessment_payload(_handover())["grid_units"] == []


def test_financials_are_omitted_when_incomplete_and_the_reason_is_recorded():
    handover = _handover(capex="40000")
    payload = build_assessment_payload(handover)
    assert "financials" not in payload
    assert any("Additionality was not assessed" in n for n in handover.notes)


def test_complete_financials_are_carried_through():
    handover = _handover(capex="40000", annual_opex="500",
                         tariff_per_mwh="0.03", project_lifetime_years="25",
                         benchmark_irr="0.14")
    payload = build_assessment_payload(handover)
    assert payload["financials"]["benchmark_irr"] == 0.14


def test_a_percentage_benchmark_is_converted_and_noted():
    """Documents state 14%, the engine expects 0.14. Reading 14 as 1400% would
    make every project additional."""
    handover = _handover(capex="40000", annual_opex="500",
                         tariff_per_mwh="0.03", project_lifetime_years="25",
                         benchmark_irr="14")
    payload = build_assessment_payload(handover)
    assert payload["financials"]["benchmark_irr"] == pytest.approx(0.14)
    assert any("percentage" in n for n in handover.notes)
