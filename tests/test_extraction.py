"""
Phase 3 tests — extraction.

The guard tests matter most. Extraction is where a number that nobody in this
system computed can enter a report, and the rule stopping that is easy to break
by accident in a schema edit six months from now.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from app.extraction.guards import (
    CALCULATED_FIELDS,
    CalculatedFieldInSchema,
    assert_extraction_safe,
)
from app.extraction.pipeline import (
    SYSTEM_PROMPT,
    Extractor,
    UnsupportedDocument,
    extract,
    load_text,
    parse_response,
)
from app.extraction.schema import (
    Confidence,
    ExtractionStatus,
    ProjectExtraction,
    band,
)


class FakeExtractor(Extractor):
    """Stands in for the model so the deterministic half is testable alone."""

    name = "fake"

    def __init__(self, response: str = "{}", raises: Exception | None = None):
        self.response = response
        self.raises = raises
        self.last_document = ""

    def complete(self, system: str, document_text: str) -> str:
        if self.raises:
            raise self.raises
        self.last_document = document_text
        return self.response


def _field(value, score=0.95, **kw) -> dict:
    return {"value": value, "score": score, "source_page": 1,
            "source_text": "as stated", **kw}


def _good_response(**overrides) -> str:
    payload = {
        "project_name": _field("Aligarh Solar One"),
        "proponent": _field("Bodhi Hub Client"),
        "country_iso2": _field("IN"),
        "technology": _field("solar PV"),
        "installed_capacity_mw": _field("50"),
        "expected_annual_generation_mwh": _field("87600"),
        "initial_crediting_period_start": _field("2026-03-01"),
    }
    payload.update(overrides)
    return json.dumps(payload)


@pytest.fixture
def doc(tmp_path) -> Path:
    path = tmp_path / "project.txt"
    path.write_text("Aligarh Solar One, 50 MW, Uttar Pradesh.")
    return path


# --- the calculated-field boundary ----------------------------------------

def test_the_shipped_schema_declares_no_calculated_field():
    """Importing the pipeline runs this check; asserting it here makes the
    failure legible rather than an import error."""
    assert_extraction_safe(ProjectExtraction.model_fields)


@pytest.mark.parametrize("name", [
    "emission_reductions", "ef_grid_cm", "irr", "baseline_emissions",
    "additionality_verdict", "template_version",
])
def test_adding_a_calculated_field_is_rejected(name):
    """A figure read off a document bypasses the engine entirely while every
    check we built quietly passes, because no calculation happened."""
    with pytest.raises(CalculatedFieldInSchema):
        assert_extraction_safe({"project_name", name})


def test_a_derived_looking_name_is_rejected_even_if_unlisted():
    with pytest.raises(CalculatedFieldInSchema, match="look like derived"):
        assert_extraction_safe({"total_emission_reduction_estimate"})


def test_ordinary_input_fields_pass():
    assert_extraction_safe({"project_name", "capex", "tariff_per_mwh"})


def test_the_blocklist_covers_every_engine_output_family():
    for marker in ("emission_reductions", "ef_grid_cm", "irr", "npv"):
        assert marker in CALCULATED_FIELDS


def test_the_prompt_forbids_computation():
    lowered = SYSTEM_PROMPT.lower()
    assert "you do not calculate" in lowered
    assert "never convert units" in lowered
    assert "never repair a value" in lowered


# --- confidence banding ----------------------------------------------------

@pytest.mark.parametrize("score,expected", [
    (1.0, Confidence.HIGH), (0.90, Confidence.HIGH),
    (0.89, Confidence.MEDIUM), (0.70, Confidence.MEDIUM),
    (0.69, Confidence.LOW), (0.0, Confidence.LOW),
])
def test_scores_band_correctly(score, expected):
    assert band(score) is expected


def test_anything_below_high_reaches_a_reviewer():
    data = parse_response(_good_response(
        country_iso2=_field("IN", score=0.5)))
    assert "country_iso2" in data.fields_needing_review()


def test_a_high_confidence_field_does_not_reach_a_reviewer():
    data = parse_response(_good_response())
    assert "project_name" not in data.fields_needing_review()


# --- response parsing ------------------------------------------------------

def test_a_good_response_parses():
    data = parse_response(_good_response())
    assert data.project_name.value == "Aligarh Solar One"
    assert data.installed_capacity_mw.value == "50"


def test_numbers_stay_strings():
    """They were strings in the document, and the engine parses them itself.
    Converting here would put a float between the document and the calculation."""
    data = parse_response(_good_response(installed_capacity_mw=_field(50)))
    assert data.installed_capacity_mw.value == "50"
    assert isinstance(data.installed_capacity_mw.value, str)


@pytest.mark.parametrize("raw,expected", [
    ("2026-03-01", date(2026, 3, 1)),
    ("01/03/2026", date(2026, 3, 1)),
    ("01-MAR-2026", date(2026, 3, 1)),
])
def test_common_date_formats_are_understood(raw, expected):
    data = parse_response(_good_response(
        initial_crediting_period_start=_field(raw)))
    assert data.initial_crediting_period_start.value == expected


def test_an_unparseable_date_is_dropped_not_guessed():
    data = parse_response(_good_response(
        initial_crediting_period_start=_field("sometime in spring")))
    assert data.initial_crediting_period_start.value is None
    assert data.initial_crediting_period_start.confidence is Confidence.NOT_FOUND


def test_a_fenced_code_block_response_is_handled():
    data = parse_response("```json\n" + _good_response() + "\n```")
    assert data.project_name.value == "Aligarh Solar One"


def test_unknown_keys_are_ignored():
    payload = json.loads(_good_response())
    payload["emission_reductions"] = _field("69672")
    data = parse_response(json.dumps(payload))
    assert not hasattr(data, "emission_reductions")


def test_an_absent_optional_field_does_not_trigger_review():
    """Absent is not uncertain. Sending a reviewer to verify a blank is how a
    targeted review queue turns back into a full manual check."""
    data = parse_response(_good_response())
    assert "capex" not in data.fields_needing_review()
    assert not data.missing_required()


def test_an_absent_required_field_is_reported_for_manual_entry():
    payload = json.loads(_good_response())
    del payload["technology"]
    data = parse_response(json.dumps(payload))
    assert data.missing_required() == ["technology"]
    assert "technology" not in data.fields_needing_review()


def test_the_review_queue_covers_both_kinds(doc):
    payload = json.loads(_good_response(country_iso2=_field("IN", score=0.4)))
    del payload["technology"]
    result = extract(doc, FakeExtractor(response=json.dumps(payload)))
    assert result.status is ExtractionStatus.PARTIAL
    assert set(result.review_queue) == {"country_iso2", "technology"}


def test_a_missing_field_is_not_found_rather_than_empty():
    data = parse_response(_good_response())
    assert data.capex.confidence is Confidence.NOT_FOUND
    assert data.capex.value is None


def test_scores_outside_zero_to_one_are_clamped():
    data = parse_response(_good_response(project_name=_field("X", score=9.9)))
    assert data.project_name.score == 1.0


def test_source_text_is_retained_for_review():
    data = parse_response(_good_response())
    assert data.project_name.source_text == "as stated"
    assert data.project_name.source_page == 1


# --- document loading ------------------------------------------------------

def test_a_text_document_loads(doc):
    text, pages = load_text(doc)
    assert "Aligarh" in text
    assert pages == 1


def test_an_empty_document_is_refused(tmp_path):
    path = tmp_path / "blank.txt"
    path.write_text("   ")
    with pytest.raises(UnsupportedDocument, match="empty"):
        load_text(path)


def test_an_unsupported_type_is_refused(tmp_path):
    path = tmp_path / "photo.heic"
    path.write_bytes(b"\x00")
    with pytest.raises(UnsupportedDocument, match="not a supported"):
        load_text(path)


# --- failures never disappear ---------------------------------------------

def test_an_unreadable_document_is_flagged_not_raised(tmp_path):
    path = tmp_path / "scan.heic"
    path.write_bytes(b"\x00")
    result = extract(path, FakeExtractor())
    assert result.status is ExtractionStatus.FAILED
    assert result.requires_manual_entry
    assert "not a supported" in result.error


def test_a_model_failure_is_flagged(doc):
    result = extract(doc, FakeExtractor(raises=RuntimeError("rate limited")))
    assert result.status is ExtractionStatus.FAILED
    assert "rate limited" in result.error


def test_an_unparseable_response_is_flagged(doc):
    result = extract(doc, FakeExtractor(response="not json at all"))
    assert result.status is ExtractionStatus.FAILED
    assert "could not be parsed" in result.error


def test_a_nearly_empty_extraction_is_flagged(doc):
    """Better to ask for manual entry than to proceed on two fields out of
    thirteen."""
    result = extract(doc, FakeExtractor(response=json.dumps({
        "project_name": _field("Something")})))
    assert result.status is ExtractionStatus.FAILED
    assert "below the minimum" in result.error


def test_a_failed_extraction_queues_every_field_for_review(doc):
    result = extract(doc, FakeExtractor(response="broken"))
    assert set(result.review_queue) == set(ProjectExtraction.model_fields)


# --- successful outcomes ---------------------------------------------------

def test_a_clean_extraction_is_marked_extracted(doc):
    result = extract(doc, FakeExtractor(response=_good_response()))
    assert result.status is ExtractionStatus.EXTRACTED
    assert not result.review_queue


def test_a_low_confidence_field_makes_it_partial(doc):
    result = extract(doc, FakeExtractor(response=_good_response(
        country_iso2=_field("IN", score=0.4))))
    assert result.status is ExtractionStatus.PARTIAL
    assert result.review_queue == ["country_iso2"]


def test_extracted_values_flatten_for_the_engine(doc):
    result = extract(doc, FakeExtractor(response=_good_response()))
    inputs = result.data.as_inputs()
    assert inputs["project_name"] == "Aligarh Solar One"
    assert inputs["installed_capacity_mw"] == "50"
    assert "capex" not in inputs


def test_the_document_text_reaches_the_model(doc):
    fake = FakeExtractor(response=_good_response())
    extract(doc, fake)
    assert "Aligarh" in fake.last_document
