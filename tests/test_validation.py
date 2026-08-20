"""
Phase 4 tests — validation and confidence scoring.

Phases.md exit criterion: "flagging correctly catches injected test errors in
sample data." The injection suite at the bottom of this file IS that criterion,
written so a rule that stops working fails loudly rather than quietly letting a
bad value through.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from app.extraction.pipeline import parse_response
from app.extraction.schema import (
    Confidence,
    ExtractionResult,
    ExtractionStatus,
    ProjectExtraction,
)
from app.validation.rules import RULES, Severity
from app.validation.validator import validate, validate_extraction


def _f(value, score=0.95, **kw) -> dict:
    return {"value": value, "score": score, "source_page": 1,
            "source_text": f"document states {value}", **kw}


CLEAN = {
    "project_name": _f("Aligarh Solar One"),
    "proponent": _f("Bodhi Hub Client"),
    "country_iso2": _f("IN"),
    "technology": _f("terrestrial solar photovoltaic"),
    "installed_capacity_mw": _f("50"),
    "expected_annual_generation_mwh": _f("87600"),
    "initial_crediting_period_start": _f("2026-03-01"),
    # Both in lakh. The clean baseline previously mixed a lakh capital cost
    # with a rupee tariff — the very error the payback rule now catches — so
    # every test built on it was measuring against a faulty baseline.
    "capex": _f("40000"),
    "annual_opex": _f("500"),
    "tariff_per_mwh": _f("0.045"),
    "project_lifetime_years": _f("25"),
    "benchmark_irr": _f("0.14"),
}


def _data(**overrides) -> ProjectExtraction:
    payload = {**CLEAN, **overrides}
    return parse_response(json.dumps(payload))


def _rule_ids(result) -> set[str]:
    return {f.rule_id for f in result.flags}


# --- the clean baseline ----------------------------------------------------

def test_clean_data_raises_nothing():
    """If this fails, every injection test below is meaningless — they would
    be passing on noise rather than on the injected error."""
    result = validate(_data())
    assert result.flags == []
    assert result.auto_approvable
    assert result.can_calculate


def test_clean_high_confidence_data_needs_no_reviewer():
    """The PRD's whole objective: only flagged items reach a human."""
    assert validate(_data()).auto_approvable


# --- injected errors — the Phase 4 exit criterion --------------------------

@pytest.mark.parametrize("label,override,expected_rule", [
    (
        "capacity in kW rather than MW",
        {"installed_capacity_mw": _f("50000")},
        "consistency.capacity_factor",
    ),
    (
        "generation off by 1000x",
        {"expected_annual_generation_mwh": _f("87600000")},
        "consistency.capacity_factor",
    ),
    (
        "capacity zero",
        {"installed_capacity_mw": _f("0")},
        "range.capacity_positive",
    ),
    (
        "generation zero",
        {"expected_annual_generation_mwh": _f("0")},
        "range.generation_positive",
    ),
    (
        "country written as a name",
        {"country_iso2": _f("India")},
        "format.country_code",
    ),
    (
        "capacity is text",
        {"installed_capacity_mw": _f("fifty")},
        "type.numeric",
    ),
    (
        "benchmark stated as a percent",
        {"benchmark_irr": _f("14")},
        "range.benchmark_irr",
    ),
    (
        "benchmark negative",
        {"benchmark_irr": _f("-0.05")},
        "range.benchmark_irr",
    ),
    (
        "project life of 200 years",
        {"project_lifetime_years": _f("200")},
        "range.lifetime_plausible",
    ),
    (
        "crediting period starts in 1990",
        {"initial_crediting_period_start": _f("1990-01-01")},
        "range.crediting_start",
    ),
    (
        "opex exceeds revenue",
        {"annual_opex": _f("999999999")},
        "consistency.revenue_vs_cost",
    ),
])
def test_injected_error_is_caught(label, override, expected_rule):
    result = validate(_data(**override))
    assert expected_rule in _rule_ids(result), (
        f"{label}: expected rule {expected_rule} to fire, got "
        f"{_rule_ids(result) or 'nothing'}")


def test_a_unit_error_blocks_the_calculation_engine():
    """The 1000x case is the one that would otherwise reach the baseline
    calculation and produce a confidently wrong tonnage."""
    result = validate(_data(expected_annual_generation_mwh=_f("87600000")))
    assert not result.can_calculate


def test_the_capacity_factor_rule_reports_the_conflicting_pair():
    """Capacity and generation are extracted from different parts of a
    document, so the reviewer needs both to see which one is wrong."""
    result = validate(_data(installed_capacity_mw=_f("50000")))
    flag = next(f for f in result.flags
                if f.rule_id == "consistency.capacity_factor")
    assert "50000" in flag.observed and "87600" in flag.observed


def test_a_percentage_benchmark_explains_the_consequence():
    flag = next(f for f in validate(_data(benchmark_irr=_f("14"))).flags
                if f.rule_id == "range.benchmark_irr")
    assert "1400%" in flag.message


# --- rules are independent of confidence ----------------------------------

def test_a_rule_fires_even_at_maximum_confidence():
    """A model can read a typo perfectly. Confidence describes the reading,
    not the value."""
    result = validate(_data(
        installed_capacity_mw={"value": "0", "score": 1.0, "source_page": 1,
                               "source_text": "0 MW"}))
    assert "range.capacity_positive" in _rule_ids(result)


def test_low_confidence_alone_queues_a_field_for_review():
    result = validate(_data(country_iso2=_f("IN", score=0.55)))
    assert not result.auto_approvable
    assert any(i.field_name == "country_iso2" for i in result.review_items)


def test_medium_confidence_warns_but_does_not_block():
    result = validate(_data(capex=_f("40000", score=0.80)))
    assert result.can_calculate
    assert not result.auto_approvable


def test_low_confidence_blocks():
    result = validate(_data(capex=_f("40000", score=0.30)))
    assert not result.can_calculate


def test_a_field_is_not_queued_twice():
    """A field that both fails a rule and was read uncertainly appears once —
    a duplicated queue teaches reviewers to skim."""
    result = validate(_data(installed_capacity_mw=_f("0", score=0.4)))
    names = [i.field_name for i in result.review_items]
    assert names.count("installed_capacity_mw") == 1


# --- review items carry what a reviewer needs -----------------------------

def test_review_items_carry_the_source_text():
    """Without it the reviewer reopens the PDF and searches, which is the
    manual effort this is meant to remove."""
    result = validate(_data(installed_capacity_mw=_f("0")))
    item = next(i for i in result.review_items
                if i.field_name == "installed_capacity_mw")
    assert item.source_text
    assert item.source_page == 1


def test_blocking_items_are_marked():
    result = validate(_data(installed_capacity_mw=_f("0")))
    assert any(i.blocking for i in result.review_items)


def test_the_text_report_lists_blocking_items_first():
    text = validate(_data(
        installed_capacity_mw=_f("0"),
        capex=_f("40000", score=0.8))).as_text()
    assert text.index("ERROR") < text.index("WARNING")


# --- whole-extraction validation ------------------------------------------

def _extraction(status=ExtractionStatus.EXTRACTED, error="", **overrides):
    return ExtractionResult(document_name="doc.pdf", status=status,
                            data=_data(**overrides), error=error)


def test_a_failed_extraction_blocks_and_asks_for_manual_entry():
    result = validate_extraction(_extraction(
        status=ExtractionStatus.FAILED, error="No text layer; needs OCR."))
    assert not result.can_calculate
    assert "manual entry" in result.as_text().lower() or "OCR" in result.as_text()


def test_a_missing_required_field_blocks():
    payload = {k: v for k, v in CLEAN.items() if k != "technology"}
    extraction = ExtractionResult(
        document_name="doc.pdf", status=ExtractionStatus.PARTIAL,
        data=parse_response(json.dumps(payload)))
    result = validate_extraction(extraction)
    assert not result.can_calculate
    assert any(f.rule_id == "required.missing" for f in result.flags)


def test_a_missing_optional_field_does_not_block():
    payload = {k: v for k, v in CLEAN.items() if k != "capex"}
    extraction = ExtractionResult(
        document_name="doc.pdf", status=ExtractionStatus.EXTRACTED,
        data=parse_response(json.dumps(payload)))
    assert validate_extraction(extraction).can_calculate


def test_a_clean_extraction_is_auto_approvable():
    assert validate_extraction(_extraction()).auto_approvable


# --- the rule set itself ---------------------------------------------------

def test_rule_ids_are_unique():
    ids = [r.id for r in RULES]
    assert len(ids) == len(set(ids))


def test_every_rule_describes_itself():
    for r in RULES:
        assert r.description.strip()
        assert r.id.strip()


def test_rules_are_deterministic():
    """A flag that appears on one run and not the next is worse than no flag —
    a reviewer stops trusting the queue."""
    data = _data(installed_capacity_mw=_f("50000"))
    runs = {tuple(sorted(_rule_ids(validate(data)))) for _ in range(20)}
    assert len(runs) == 1


def test_rules_never_mutate_the_data():
    data = _data()
    before = data.model_dump_json()
    validate(data)
    assert data.model_dump_json() == before


# --- mixed currency scales (found on a real document) ---------------------

def test_a_lakh_capex_against_a_rupee_tariff_is_caught():
    """The Aligarh memorandum states "INR 40,000 lakh" and "INR 3,000 per MWh".
    Neither figure is wrong alone; divided, the implied payback is days."""
    result = validate(_data(capex=_f("40000"), tariff_per_mwh=_f("3000"),
                            annual_opex=_f("500")))
    assert "consistency.payback_period" in _rule_ids(result)
    assert not result.can_calculate


def test_the_message_names_the_likely_cause():
    result = validate(_data(capex=_f("40000"), tariff_per_mwh=_f("3000")))
    flag = next(f for f in result.flags
                if f.rule_id == "consistency.payback_period")
    assert "different scales" in flag.message
    assert "lakh" in flag.message


def test_consistent_units_pass():
    """40,000 lakh capital cost against a 0.03 lakh/MWh tariff — payback about
    eleven years, which is normal for utility-scale solar."""
    result = validate(_data(capex=_f("40000"), tariff_per_mwh=_f("0.045"),
                            annual_opex=_f("500")))
    assert "consistency.payback_period" not in _rule_ids(result)


def test_an_implausibly_long_payback_warns_but_does_not_block():
    result = validate(_data(capex=_f("40000"), tariff_per_mwh=_f("0.005"),
                            annual_opex=_f("100")))
    flag = next((f for f in result.flags
                 if f.rule_id == "consistency.payback_period"), None)
    assert flag is not None and flag.severity is Severity.WARNING


# --- a consistency finding implicates both sides --------------------------

def test_both_sides_of_a_unit_mismatch_reach_the_queue():
    """The rule is registered against capex, but the fault is as likely to be
    in the tariff. Queuing only capex leaves the real correction unreachable."""
    result = validate(_data(capex=_f("40000"), tariff_per_mwh=_f("3000"),
                            annual_opex=_f("500")))
    queued = {i.field_name for i in result.review_items}
    assert "capex" in queued
    assert "tariff_per_mwh" in queued


def test_the_secondary_field_says_why_it_is_queued():
    result = validate(_data(capex=_f("40000"), tariff_per_mwh=_f("3000")))
    item = next(i for i in result.review_items
                if i.field_name == "tariff_per_mwh")
    assert "same finding as capex" in item.reason


def test_a_capacity_factor_error_queues_the_capacity_too():
    result = validate(_data(installed_capacity_mw=_f("50000")))
    queued = {i.field_name for i in result.review_items}
    assert "expected_annual_generation_mwh" in queued
    assert "installed_capacity_mw" in queued


def test_a_field_is_still_never_queued_twice():
    result = validate(_data(capex=_f("40000"), tariff_per_mwh=_f("3000"),
                            annual_opex=_f("999999999")))
    names = [i.field_name for i in result.review_items]
    assert len(names) == len(set(names))


def test_a_secondary_item_shows_its_own_value_not_the_comparison():
    """The flag's observed string describes the failed comparison, which is
    right on the field the rule is registered under and useless on the others.
    A reviewer correcting the tariff needs to see the tariff."""
    result = validate(_data(capex=_f("40000"), tariff_per_mwh=_f("3000"),
                            annual_opex=_f("500")))
    primary = next(i for i in result.review_items if i.field_name == "capex")
    tariff = next(i for i in result.review_items
                  if i.field_name == "tariff_per_mwh")
    assert "vs net revenue" in primary.observed
    assert tariff.observed == "3000"


def test_a_secondary_item_keeps_its_own_source_text():
    result = validate(_data(capex=_f("40000"), tariff_per_mwh=_f("3000")))
    tariff = next(i for i in result.review_items
                  if i.field_name == "tariff_per_mwh")
    assert "3000" in tariff.source_text
