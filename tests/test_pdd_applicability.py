"""Module 3d tests — not-applicable sections.

The risk here is over-reach: auto-writing "not applicable" into a section that
a validator expects a real answer for. Most of these tests assert what the pass
must NOT touch.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.domain import constants as K
from app.domain.classification import ProjectIntake, Severity, classify
from app.domain.pdd_applicability import not_applicable_sections
from app.domain.pdd_content import ProjectIdentity, build_pdd_content


def _intake(**overrides) -> ProjectIntake:
    base = dict(
        name="Aligarh Solar One",
        proponent="Bodhi Hub Client",
        country_iso2="IN",
        technology=K.Technology.SOLAR_PV_TERRESTRIAL,
        installed_capacity_mw=50.0,
        expected_annual_generation_mwh=87_600.0,
        initial_crediting_period_start=date(2026, 3, 1),
    )
    base.update(overrides)
    return ProjectIntake(**base)


def _na(intake):
    return not_applicable_sections(intake, classify(intake))


def _finding(findings, check):
    return next(f for f in findings if f.check == check)


# --- AFOLU sections --------------------------------------------------------

@pytest.mark.parametrize("heading", [
    "AFOLU Project Eligibility",
    "Non-Permanence Risk Analysis",
    "Buffer Pool Allocation Calculation",
    "Long-Term Average",
])
def test_afolu_sections_marked_not_applicable_for_ei(heading):
    sections, _ = _na(_intake())
    assert heading in sections
    assert "not applicable" in sections[heading][0].lower()


def test_non_permanence_justification_cites_the_governing_clause():
    """VCS Standard v5.0 s3.2.8 — sinks only; fossil CO2 displacement exempt."""
    sections, _ = _na(_intake())
    text = sections["Non-Permanence Risk Analysis"][0]
    assert "3.2.8" in text
    assert "carbon sink" in text.lower()


# --- capacity limit is technology-dependent -------------------------------

@pytest.mark.parametrize("technology", [
    K.Technology.SOLAR_PV_TERRESTRIAL,
    K.Technology.WIND_ONSHORE,
    K.Technology.SOLAR_PV_FLOATING,
])
def test_no_capacity_limit_technologies_get_the_section_filled(technology):
    sections, findings = _na(_intake(technology=technology))
    assert "Capacity Limit Eligibility" in sections
    assert _finding(
        findings, "pdd.not_applicable.capacity_limit").severity is Severity.PASS


def test_hydro_keeps_capacity_limit_for_the_author():
    """VMR0017 caps hydro at 15 MW, so s3.5.13 fragmentation rules DO apply.
    Auto-writing 'not applicable' here would be a false statement."""
    sections, findings = _na(_intake(
        country_iso2="NP", technology=K.Technology.HYDRO,
        installed_capacity_mw=12.0, expected_annual_generation_mwh=40_000.0))
    assert "Capacity Limit Eligibility" not in sections
    f = _finding(findings, "pdd.not_applicable.capacity_limit")
    assert f.severity is Severity.WARNING
    assert "3.5.13" in f.source or "3.5.13" in f.message


# --- what must never be auto-filled ---------------------------------------

@pytest.mark.parametrize("heading", [
    "Stakeholder Identification",
    "Free, Prior, and Informed Consent",
    "Grievance Redress Procedure",
    "Indigenous Peoples and Cultural Heritage",
    "Property Rights",
    "Benefit Sharing",
    "Rare, Threatened, and Endangered Species",
    "Introduction of Species",
    "Ecosystem Conversion",
    "Labor and Work",
    "Human Rights",
])
def test_safeguards_sections_are_never_auto_completed(heading):
    """Site-specific, and where a validator looks hardest. An auto-generated
    'not applicable' here is a liability."""
    sections, _ = _na(_intake())
    assert heading not in sections


@pytest.mark.parametrize("heading", [
    "Grouped Project Design",
    "Registration with Other GHG Programs",
    "Projects Rejected by Other GHG Programs",
    "Eligibility of Projects Registered with Other GHG Programs",
    "Methodology Deviations",
    "Sensitive Information",
])
def test_proponent_specific_sections_are_left_for_the_author(heading):
    sections, _ = _na(_intake())
    assert heading not in sections


def test_the_scope_limitation_is_reported_not_silent():
    _, findings = _na(_intake())
    f = _finding(findings, "pdd.not_applicable.scope")
    assert f.severity is Severity.WARNING
    assert "safeguards" in f.message.lower()


# --- integration with the content model -----------------------------------

def test_drafted_content_is_never_overwritten_by_the_na_pass():
    """Order matters: a real draft must win over a 'not applicable' default."""
    intake = _intake()
    content = build_pdd_content(intake, classify(intake), ProjectIdentity())
    assert "not applicable" not in content.sections[
        "Summary Description of the Project"][0].lower()


def test_na_sections_reach_the_content_model():
    intake = _intake()
    content = build_pdd_content(intake, classify(intake), ProjectIdentity())
    assert "AFOLU Project Eligibility" in content.sections
    assert _finding(
        content.findings, "pdd.not_applicable.afolu").severity is Severity.PASS


def test_na_pass_reduces_the_author_workload(tmp_path):
    from app.services.pdd_builder import build_pdd
    intake = _intake()
    content = build_pdd_content(intake, classify(intake), ProjectIdentity())
    result = build_pdd(content, tmp_path / "PDD.docx")
    remaining = result.report.instructions_remaining
    for heading in ("AFOLU Project Eligibility", "Non-Permanence Risk Analysis",
                    "Capacity Limit Eligibility"):
        assert remaining.get(heading, 0) == 0
