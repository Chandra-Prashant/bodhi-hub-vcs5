"""Module 5 tests — ESG risk assessment.

The matrix tests transcribe the table printed in the VCS ESG Risk Assessment
Template cell by cell. If Verra revises it, these fail loudly rather than the
system quietly assigning wrong risk levels.
"""

from __future__ import annotations

import pytest

from app.domain.classification import Severity as FindingSeverity
from app.domain.esg import (
    CATEGORY_TITLES,
    ELEVATED_LEVELS,
    RISK_MATRIX,
    Pillar,
    RiskCategory,
    RiskEntry,
    RiskLevel,
    assess_esg,
    esg_sections,
    risk_level,
)


def _entry(category=RiskCategory.E1, severity=2, likelihood=2, **kw) -> RiskEntry:
    base = dict(
        category=category,
        risk_id=f"{category.value}.1",
        description="Temporary habitat disturbance during construction.",
        severity=severity,
        likelihood=likelihood,
        justification="Site is degraded agricultural land with no protected "
                      "habitat within 5 km.",
        mitigation="Construction restricted to the fenced footprint; "
                   "pre-construction ecological survey completed.",
    )
    base.update(kw)
    return RiskEntry(**base)


def _full_set(**overrides) -> list[RiskEntry]:
    return [_entry(category=c, **overrides.get(c, {})) for c in RiskCategory]


def _finding(findings, check):
    return next(f for f in findings if f.check == check)


def _has(findings, check) -> bool:
    return any(f.check == check for f in findings)


# --- the risk matrix, cell by cell ----------------------------------------

@pytest.mark.parametrize("severity,row", [
    (1, ["Very low", "Very low", "Very low", "Low", "Medium"]),
    (2, ["Very low", "Very low", "Low", "Medium", "High"]),
    (3, ["Very low", "Low", "Medium", "High", "High"]),
    (4, ["Low", "Medium", "High", "High", "Very high"]),
    (5, ["Medium", "High", "High", "Very high", "Very high"]),
])
def test_matrix_matches_the_template(severity, row):
    for likelihood, expected in enumerate(row, start=1):
        assert risk_level(severity, likelihood).value == expected


def test_matrix_is_monotonic_in_both_directions():
    """Raising severity or likelihood can never lower the risk level."""
    order = list(RiskLevel)
    for s in range(1, 6):
        for l in range(1, 6):
            here = order.index(risk_level(s, l))
            if s < 5:
                assert order.index(risk_level(s + 1, l)) >= here
            if l < 5:
                assert order.index(risk_level(s, l + 1)) >= here


@pytest.mark.parametrize("severity,likelihood", [
    (0, 3), (6, 3), (3, 0), (3, 6), (-1, 1),
])
def test_out_of_range_scores_raise(severity, likelihood):
    with pytest.raises(ValueError):
        risk_level(severity, likelihood)


# --- category registry -----------------------------------------------------

def test_all_twelve_categories_are_registered():
    assert len(RiskCategory) == 12
    assert set(CATEGORY_TITLES) == set(RiskCategory)


def test_pillars_split_two_six_four():
    counts = {p: 0 for p in Pillar}
    for pillar, _, _ in CATEGORY_TITLES.values():
        counts[pillar] += 1
    assert counts[Pillar.ENVIRONMENTAL] == 2
    assert counts[Pillar.SOCIAL] == 6
    assert counts[Pillar.GOVERNANCE] == 4


def test_every_category_cites_its_standard_clause():
    for _, _, clause in CATEGORY_TITLES.values():
        assert clause.startswith("s3.18")


# --- completeness ----------------------------------------------------------

def test_empty_assessment_is_blocked():
    result = assess_esg([])
    assert result.blocked
    assert _finding(result.findings, "esg.assessment").severity is FindingSeverity.FAIL


def test_partial_assessment_names_the_missing_categories():
    result = assess_esg([_entry(RiskCategory.E1), _entry(RiskCategory.S1)])
    assert result.blocked
    message = _finding(result.findings, "esg.incomplete").message
    assert "10 of the twelve" in message
    assert "G3" in message


def test_full_assessment_passes_completeness():
    result = assess_esg(_full_set())
    assert _finding(result.findings, "esg.complete").severity is FindingSeverity.PASS
    assert result.missing_categories == []


def test_not_applicable_still_counts_as_addressed():
    entries = _full_set()
    entries[7] = _entry(RiskCategory.S6, not_applicable=True,
                        na_justification="No armed personnel are engaged in "
                                         "any project activity.")
    result = assess_esg(entries)
    assert result.missing_categories == []


def test_unjustified_not_applicable_is_blocked():
    entries = _full_set()
    entries[7] = _entry(RiskCategory.S6, not_applicable=True)
    result = assess_esg(entries)
    assert _finding(result.findings, "esg.na_unjustified").severity is FindingSeverity.FAIL


# --- mitigation commensurate with level, s3.18.1(2) -----------------------

def test_missing_mitigation_is_blocked():
    entries = _full_set()
    entries[0] = _entry(RiskCategory.E1, mitigation="")
    result = assess_esg(entries)
    assert _finding(result.findings, "esg.mitigation_missing").severity is FindingSeverity.FAIL


def test_thin_mitigation_on_a_high_risk_is_flagged():
    entries = _full_set()
    entries[2] = _entry(RiskCategory.S1, severity=4, likelihood=4,
                        mitigation="Will monitor.")
    result = assess_esg(entries)
    f = _finding(result.findings, "esg.mitigation_thin")
    assert f.severity is FindingSeverity.WARNING
    assert "3.18.1(2)" in f.source


def test_brief_mitigation_on_a_low_risk_is_not_flagged():
    """Proportionality cuts both ways — a very low risk needn't have an essay."""
    entries = _full_set()
    entries[0] = _entry(RiskCategory.E1, severity=1, likelihood=1,
                        mitigation="Standard site controls.")
    result = assess_esg(entries)
    assert not _has(result.findings, "esg.mitigation_thin")


def test_missing_justification_is_blocked():
    entries = _full_set()
    entries[0] = _entry(RiskCategory.E1, justification="")
    result = assess_esg(entries)
    assert _finding(result.findings, "esg.justification").severity is FindingSeverity.FAIL


# --- IDs -------------------------------------------------------------------

def test_duplicate_risk_ids_are_blocked():
    entries = _full_set()
    entries[1] = _entry(RiskCategory.E2, risk_id="E1.1")
    result = assess_esg(entries)
    assert _finding(result.findings, "esg.duplicate_id").severity is FindingSeverity.FAIL


def test_id_not_matching_its_category_is_flagged():
    entries = _full_set()
    entries[0] = _entry(RiskCategory.E1, risk_id="X9.1")
    result = assess_esg(entries)
    assert _finding(result.findings, "esg.id_format").severity is FindingSeverity.WARNING


# --- elevated risks and timing --------------------------------------------

def test_elevated_risks_are_listed():
    entries = _full_set()
    entries[3] = _entry(RiskCategory.S2, severity=5, likelihood=4,
                        mitigation="x" * 200)
    result = assess_esg(entries)
    assert [e.risk_id for e in result.elevated_risks] == ["S2.1"]
    assert _finding(result.findings, "esg.elevated").severity is FindingSeverity.WARNING


def test_all_elevated_levels_are_high_or_very_high():
    assert ELEVATED_LEVELS == {RiskLevel.HIGH, RiskLevel.VERY_HIGH}


def test_pre_start_date_timing_is_always_raised():
    """s3.18.1 — the assessment must predate the project start date."""
    result = assess_esg(_full_set())
    assert _finding(result.findings, "esg.timing").severity is FindingSeverity.WARNING


def test_every_finding_carries_a_source():
    result = assess_esg(_full_set())
    assert all(f.source for f in result.findings)


# --- prose -----------------------------------------------------------------

def test_prose_reports_the_assessment_not_an_invention():
    result = assess_esg(_full_set())
    text = " ".join(esg_sections(result)[
        "Environmental, Social, and Governance Risks"])
    assert "3.18.1" in text
    assert "twelve safeguard categories" in text


def test_prose_names_elevated_risks_when_present():
    entries = _full_set()
    entries[3] = _entry(RiskCategory.S2, severity=5, likelihood=5,
                        mitigation="y" * 200)
    text = " ".join(esg_sections(assess_esg(entries))[
        "Environmental, Social, and Governance Risks"])
    assert "S2.1" in text
    assert "very high" in text.lower()


def test_prose_states_plainly_when_nothing_is_elevated():
    text = " ".join(esg_sections(assess_esg(_full_set()))[
        "Environmental, Social, and Governance Risks"])
    assert "no risk has been assessed as high" in text.lower()


def test_no_prose_without_an_assessment():
    assert esg_sections(assess_esg([])) == {}
