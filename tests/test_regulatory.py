"""Module 8 tests — regulatory tracking."""

from __future__ import annotations

import shutil

import pytest

from app.domain.classification import Severity
from app.domain.regulatory import (
    REGISTRY,
    TEMPLATE_DIR,
    assess_update,
    check_integrity,
    check_registry,
    content_hash,
    dependency_index,
    document_hashes,
)


def _finding(findings, check):
    return next(f for f in findings if f.check == check)


def _has(findings, check) -> bool:
    return any(f.check == check for f in findings)


@pytest.fixture
def template_copy(tmp_path):
    """A writable copy so integrity tests can mutate files safely."""
    destination = tmp_path / "templates"
    shutil.copytree(TEMPLATE_DIR, destination)
    return destination


# --- registry shape --------------------------------------------------------

def test_document_ids_are_unique():
    ids = [d.doc_id for d in REGISTRY]
    assert len(ids) == len(set(ids))


def test_every_document_declares_at_least_one_dependency():
    """A tracked document with no code behind it is a note, not a dependency."""
    assert all(d.dependencies for d in REGISTRY)


def test_every_dependency_describes_what_it_implements():
    for doc in REGISTRY:
        for dependency in doc.dependencies:
            assert dependency.module and dependency.symbol
            assert len(dependency.description) > 10


def test_the_documents_that_drive_the_numbers_are_tracked():
    ids = {d.doc_id for d in REGISTRY}
    assert {"VCS-STANDARD", "VMR0017", "VT0008", "VT0011", "ACM0002",
            "TOOL07"} <= ids


# --- the TOOL07 gap surfaces here -----------------------------------------

def test_tool07_is_recorded_as_unverified():
    """The one known gap that code cannot close must be visible in the
    tracking module, not only in the README."""
    tool07 = next(d for d in REGISTRY if d.doc_id == "TOOL07")
    assert not tool07.verified
    assert "UNVERIFIED" in tool07.notes


def test_unverified_documents_produce_a_blocking_finding():
    findings = check_registry()
    f = _finding(findings, "regulatory.unverified")
    assert f.severity is Severity.FAIL
    assert "TOOL07" in f.source


def test_the_unverified_finding_names_the_affected_code():
    f = _finding(check_registry(), "regulatory.unverified")
    for symbol in ("simple_om", "build_margin", "average_om"):
        assert symbol in f.message


def test_missing_effective_dates_are_flagged():
    assert _has(check_registry(), "regulatory.no_effective_date")


def test_coverage_is_reported():
    f = _finding(check_registry(), "regulatory.coverage")
    assert f.severity is Severity.PASS
    assert "verified" in f.message


# --- integrity -------------------------------------------------------------

def test_vendored_documents_are_hashed(template_copy):
    hashes = document_hashes(template_copy)
    assert "PD-TEMPLATE-A" in hashes
    assert "ESG-TEMPLATE" in hashes
    assert all(len(h) == 64 for h in hashes.values())


def test_hashing_is_stable(template_copy):
    assert document_hashes(template_copy) == document_hashes(template_copy)


def test_unchanged_documents_pass_integrity(template_copy):
    baseline = document_hashes(template_copy)
    findings = check_integrity(baseline, template_copy)
    assert _finding(findings, "regulatory.integrity").severity is Severity.PASS


def test_an_edited_document_is_detected(template_copy):
    """Someone hand-edits a template; the code that reads its labels is now
    working against a document nobody re-checked."""
    baseline = document_hashes(template_copy)
    target = template_copy / "VCS-Project-Description-Template-v5.0A.docx"
    target.write_bytes(target.read_bytes() + b"\x00")
    f = _finding(check_integrity(baseline, template_copy),
                 "regulatory.document_changed")
    assert f.severity is Severity.FAIL


def test_a_changed_document_names_what_to_reverify(template_copy):
    baseline = document_hashes(template_copy)
    target = template_copy / "VCS-ESG-Risk-Assessment-Template-v5.0.docx"
    target.write_bytes(target.read_bytes() + b"\x00")
    f = _finding(check_integrity(baseline, template_copy),
                 "regulatory.document_changed")
    assert "RISK_MATRIX" in f.message


def test_a_deleted_document_is_detected(template_copy):
    baseline = document_hashes(template_copy)
    (template_copy / "VCS-Monitoring-Report-Template-V5.0A.docx").unlink()
    f = _finding(check_integrity(baseline, template_copy),
                 "regulatory.document_missing")
    assert f.severity is Severity.FAIL


def test_an_unrecorded_document_is_flagged(template_copy):
    baseline = document_hashes(template_copy)
    baseline.pop("PD-TEMPLATE-B")
    f = _finding(check_integrity(baseline, template_copy),
                 "regulatory.document_new")
    assert f.severity is Severity.WARNING


def test_content_hash_distinguishes_files(template_copy):
    a = content_hash(template_copy / "VCS-Project-Description-Template-v5.0A.docx")
    b = content_hash(template_copy / "VCS-Monitoring-Report-Template-V5.0A.docx")
    assert a != b


# --- update impact ---------------------------------------------------------

def test_the_current_version_reports_up_to_date():
    impact = assess_update("VT0011", "v1.0")
    assert not impact.is_newer
    assert _finding(impact.findings, "regulatory.up_to_date").severity is Severity.PASS


def test_a_new_version_lists_every_affected_symbol():
    impact = assess_update("VT0011", "v1.1")
    assert impact.is_newer
    symbols = {d.symbol for d in impact.dependencies}
    assert {"WIND_SOLAR_CM_WEIGHTS", "select_bm_sample",
            "unit_emission_factor"} <= symbols


def test_a_new_version_produces_one_reverify_finding_per_dependency():
    impact = assess_update("VMR0017", "v1.1")
    reverify = [f for f in impact.findings if f.check == "regulatory.reverify"]
    assert len(reverify) == len(impact.document.dependencies)


def test_a_standard_revision_reaches_the_crediting_period_constants():
    """The 15-year cap is the figure most likely to move, and it silently
    changes every financial model."""
    impact = assess_update("VCS-STANDARD", "v5.1")
    checklist = " ".join(impact.as_checklist())
    assert "EI_MAX_TOTAL_CREDITING_YEARS" in checklist
    assert "EI_CREDITING_PERIOD_YEARS" in checklist


def test_a_vmr0017_revision_reaches_the_embodied_defaults():
    impact = assess_update("VMR0017", "v1.1")
    checklist = " ".join(impact.as_checklist())
    assert "EMBODIED_EF_G_CO2E_PER_KWH" in checklist


def test_a_vt0008_revision_reaches_the_common_practice_thresholds():
    impact = assess_update("VT0008", "v1.1")
    checklist = " ".join(impact.as_checklist())
    assert "COMMON_PRACTICE_F_THRESHOLD" in checklist


def test_an_unknown_document_raises():
    with pytest.raises(KeyError):
        assess_update("NOT-A-DOCUMENT", "v1.0")


def test_the_checklist_explains_each_item():
    impact = assess_update("VT0011", "v1.1")
    assert all("—" in line for line in impact.as_checklist())


# --- inverse index ---------------------------------------------------------

def test_dependency_index_maps_symbols_back_to_documents():
    index = dependency_index()
    assert "domain.constants.WIND_SOLAR_CM_WEIGHTS" in index
    assert any("VT0011" in entry
               for entry in index["domain.constants.WIND_SOLAR_CM_WEIGHTS"])


def test_the_crediting_period_constants_answer_to_the_standard():
    index = dependency_index()
    entries = index["domain.constants.EI_MAX_TOTAL_CREDITING_YEARS"]
    assert any("VCS-STANDARD" in entry for entry in entries)


def test_the_operating_margin_answers_to_tool07():
    """simple_om implements TOOL07, not VT0011 — which is precisely why it is
    unverified."""
    index = dependency_index()
    assert any("TOOL07" in entry
               for entry in index["domain.emission_factors.simple_om"])


def test_every_finding_carries_a_source():
    assert all(f.source for f in check_registry())
    assert all(f.source for f in assess_update("VT0011", "v1.1").findings)
