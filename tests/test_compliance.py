"""Module 7 tests — compliance engine, traceability, auditor."""

from __future__ import annotations

import csv
import io
from datetime import date

import pytest

from app.domain import constants as K
from app.domain.additionality import FinancialInputs, assess_additionality
from app.domain.baseline import emission_reductions
from app.domain.classification import Finding, ProjectIntake, Severity, classify
from app.domain.compliance import (
    REGISTRY,
    Status,
    build_compliance_report,
    traceability_csv,
    traceability_rows,
)
from app.domain.emission_factors import PowerUnit, grid_emission_factor
from app.domain.esg import RiskCategory, RiskEntry, assess_esg
from app.domain.monitoring import build_monitoring_parameters
from app.services.auditor import AUDITOR_SYSTEM_PROMPT, Priority, audit, narrative_prompt


def _intake(**overrides) -> ProjectIntake:
    base = dict(
        name="Aligarh Solar One", proponent="Bodhi Hub Client",
        country_iso2="IN", technology=K.Technology.SOLAR_PV_TERRESTRIAL,
        installed_capacity_mw=50.0, expected_annual_generation_mwh=87_600.0,
        initial_crediting_period_start=date(2026, 3, 1),
    )
    base.update(overrides)
    return ProjectIntake(**base)


def _esg_entries():
    return [
        RiskEntry(
            category=c, risk_id=f"{c.value}.1",
            description="Assessed risk.", severity=2, likelihood=2,
            justification="Site survey and stakeholder consultation.",
            mitigation="Controls documented in the management plan.")
        for c in RiskCategory
    ]


def _all_findings(intake=None, with_esg=True):
    intake = intake or _intake()
    cls = classify(intake)
    grid = [
        PowerUnit("COAL-1", 50_000, 2012, efficiency=0.35,
                  efficiency_fuel_ef_t_per_gj=0.0946),
        PowerUnit("COAL-2", 30_000, 2021, efficiency=0.38,
                  efficiency_fuel_ef_t_per_gj=0.0946),
        PowerUnit("GAS-1", 10_000, 2023, efficiency=0.52,
                  efficiency_fuel_ef_t_per_gj=0.0561),
    ]
    ef = grid_emission_factor(grid, intake.technology, 1)
    er = emission_reductions(
        intake.expected_annual_generation_mwh, ef.ef_grid_cm,
        eg_facility_mwh=intake.expected_annual_generation_mwh,
        technology=intake.technology)
    add = assess_additionality(
        FinancialInputs(
            capex=40_000, annual_opex=500, annual_generation_mwh=87_600,
            tariff_per_mwh=0.0300, project_lifetime_years=25,
            discount_rate=0.10, benchmark_irr=0.14,
            credit_price_per_tco2e=0.0080,
            annual_credits_tco2e=er.emission_reductions_tco2e),
        n_all=10, n_diff=9, project_capacity_mw=intake.installed_capacity_mw,
        regulatory_surplus=True)
    mp = build_monitoring_parameters(intake.technology)

    findings = [*cls.findings, *ef.findings, *er.findings, *add.findings,
                *mp.findings]
    if with_esg:
        findings.extend(assess_esg(_esg_entries()).findings)
    return intake, findings


def _result(report, ref):
    return next(r for r in report.results if r.requirement.ref == ref)


# --- registry --------------------------------------------------------------

def test_every_requirement_cites_a_clause():
    assert all(r.clause for r in REGISTRY)


def test_requirement_refs_are_unique():
    refs = [r.ref for r in REGISTRY]
    assert len(refs) == len(set(refs))


def test_requirements_the_engine_cannot_evidence_are_still_listed():
    """A report listing only what the software knows is worse than none."""
    author_refs = {r.ref for r in REGISTRY if r.author_supplied}
    assert {"right_to_operate", "stakeholder_engagement", "project_location",
            "double_counting", "records"} <= author_refs


# --- status mapping --------------------------------------------------------

def test_evidenced_requirements_are_satisfied():
    intake, findings = _all_findings()
    report = build_compliance_report(findings, intake.technology)
    assert _result(report, "crediting_period").status is Status.SATISFIED
    assert _result(report, "additionality").status is Status.SATISFIED


def test_author_supplied_requirements_need_input():
    intake, findings = _all_findings()
    report = build_compliance_report(findings, intake.technology)
    assert _result(report, "right_to_operate").status is Status.NEEDS_INPUT
    assert _result(report, "stakeholder_engagement").status is Status.NEEDS_INPUT


def test_a_blocking_finding_fails_its_requirement():
    """A high-income country fails VMR0017 Table 1."""
    intake = _intake(country_iso2="DE")
    report = build_compliance_report(classify(intake).findings, intake.technology)
    assert _result(report, "methodology_applicability").status is Status.FAILED


def test_capacity_limit_is_not_applicable_for_solar():
    report = build_compliance_report([], K.Technology.SOLAR_PV_TERRESTRIAL)
    result = _result(report, "capacity_limit")
    assert result.status is Status.NOT_APPLICABLE
    assert "3.5.13" in result.note


def test_capacity_limit_still_applies_to_hydro():
    report = build_compliance_report([], K.Technology.HYDRO)
    assert _result(report, "capacity_limit").status is not Status.NOT_APPLICABLE


def test_missing_esg_assessment_fails_the_safeguards_requirement():
    intake, findings = _all_findings(with_esg=False)
    findings.extend(assess_esg([]).findings)
    report = build_compliance_report(findings, intake.technology)
    assert _result(report, "esg_safeguards").status is Status.FAILED


def test_warnings_satisfy_but_are_noted():
    intake, findings = _all_findings()
    report = build_compliance_report(findings, intake.technology)
    result = _result(report, "monitoring")
    assert result.status is Status.SATISFIED


def test_no_evidence_reads_as_needs_input_not_satisfied():
    report = build_compliance_report([], K.Technology.WIND_ONSHORE)
    assert _result(report, "additionality").status is Status.NEEDS_INPUT


# --- readiness -------------------------------------------------------------

def test_a_project_with_outstanding_items_is_not_ready():
    intake, findings = _all_findings()
    report = build_compliance_report(findings, intake.technology)
    assert not report.ready_for_validation
    assert report.needs_input


def test_summary_counts_cover_every_requirement():
    intake, findings = _all_findings()
    report = build_compliance_report(findings, intake.technology)
    assert sum(report.summary.values()) == len(REGISTRY)


# --- traceability ----------------------------------------------------------

def test_traceability_has_one_row_per_requirement():
    intake, findings = _all_findings()
    rows = traceability_rows(build_compliance_report(findings, intake.technology))
    assert len(rows) == len(REGISTRY)


def test_traceability_rows_name_their_evidence_sources():
    intake, findings = _all_findings()
    rows = traceability_rows(build_compliance_report(findings, intake.technology))
    row = next(r for r in rows if r["requirement"] == "crediting_period")
    assert "VCS Standard v5.0" in row["evidence_sources"]


def test_traceability_csv_parses_and_keeps_its_header():
    intake, findings = _all_findings()
    csv_text = traceability_csv(
        build_compliance_report(findings, intake.technology))
    rows = list(csv.DictReader(io.StringIO(csv_text)))
    assert len(rows) == len(REGISTRY)
    assert "clause" in rows[0]


# --- auditor ---------------------------------------------------------------

def test_blockers_sort_before_required_and_review():
    intake = _intake(country_iso2="DE")
    findings = classify(intake).findings
    result = audit(build_compliance_report(findings, intake.technology), findings)
    priorities = [g.priority for g in result.gaps]
    assert priorities == sorted(priorities, key=lambda p: list(Priority).index(p))


def test_a_failed_requirement_produces_a_blocker():
    intake = _intake(country_iso2="DE")
    findings = classify(intake).findings
    result = audit(build_compliance_report(findings, intake.technology), findings)
    assert result.blockers
    assert not result.ready_for_validation


def test_unfilled_document_sections_become_required_gaps():
    intake, findings = _all_findings()
    result = audit(
        build_compliance_report(findings, intake.technology), findings,
        instructions_remaining={"Project Location": 10, "Project Start Date": 4})
    areas = [g.area for g in result.required]
    assert "Document section: Project Location" in areas


def test_document_gaps_are_ranked_by_size():
    """Names chosen so alphabetical order would give the WRONG answer — the
    first version of this test passed by luck on 'Large' vs 'Small'."""
    intake, findings = _all_findings()
    result = audit(
        build_compliance_report(findings, intake.technology), findings,
        instructions_remaining={"Aaa tiny section": 1, "Zzz huge section": 20})
    doc_gaps = [g for g in result.gaps if g.area.startswith("Document section")]
    assert doc_gaps[0].area.endswith("Zzz huge section")
    assert [g.weight for g in doc_gaps] == sorted(
        (g.weight for g in doc_gaps), reverse=True)


def test_every_gap_carries_a_clause():
    intake, findings = _all_findings()
    result = audit(build_compliance_report(findings, intake.technology), findings)
    assert all(g.clause for g in result.gaps)


def test_text_report_needs_no_model():
    intake, findings = _all_findings()
    text = audit(
        build_compliance_report(findings, intake.technology), findings).as_text()
    assert "Readiness:" in text
    assert "BLOCKER" in text or "REQUIRED" in text


# --- the narrative layer's guardrails -------------------------------------

def test_system_prompt_forbids_adding_or_removing_gaps():
    lowered = AUDITOR_SYSTEM_PROMPT.lower()
    assert "do not add gaps" in lowered
    assert "do not remove gaps" in lowered


def test_system_prompt_forbids_producing_numbers():
    lowered = AUDITOR_SYSTEM_PROMPT.lower()
    assert "recalculate" in lowered
    assert "do not invent clause references" in lowered


def test_narrative_prompt_ships_the_closed_gap_list():
    intake, findings = _all_findings()
    result = audit(build_compliance_report(findings, intake.technology), findings)
    system, content = narrative_prompt(result)
    assert system == AUDITOR_SYSTEM_PROMPT
    assert content.count("- [") == len(result.gaps)


def test_narrative_prompt_states_the_readiness_as_fixed():
    intake, findings = _all_findings()
    result = audit(build_compliance_report(findings, intake.technology), findings)
    _, content = narrative_prompt(result)
    assert "do not revise" in content.lower()


def test_audit_is_reproducible():
    """Two runs on the same inputs must agree — that is the point of keeping
    detection deterministic and the model out of it."""
    intake, findings = _all_findings()
    report = build_compliance_report(findings, intake.technology)
    a, b = audit(report, findings), audit(report, findings)
    assert [(g.priority, g.area, g.detail) for g in a.gaps] == \
           [(g.priority, g.area, g.detail) for g in b.gaps]
    assert a.ready_for_validation == b.ready_for_validation
