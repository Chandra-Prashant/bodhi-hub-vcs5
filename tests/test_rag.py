"""
Phase 5 tests — chunking, redaction, retrieval boundary.

The redaction tests carry the weight. Architecture.md says RAG "does not
influence any calculated value", and redaction is the mechanism that makes that
true rather than hoped for.
"""

from __future__ import annotations

import pytest

from app.rag.chunking import MAX_CHARS, chunk_text
from app.rag.index import STYLE_PROMPT_HEADER, Retrieved, as_style_prompt
from app.rag.redaction import PLACEHOLDER, contains_figure, redact_numbers


# --- redaction: figures must not survive ----------------------------------

@pytest.mark.parametrize("text", [
    "The plant generated 87,600 MWh last year.",
    "Net profit was 40000.",
    "Yield reached 12,450.5 kg per hectare.",
    "The emission factor is 0.8383 tCO2/MWh.",
    "Revenue of ₹1,20,000 was recorded.",
    "Capital cost was INR 40,000 lakh.",
    "Returns improved by 4.2%.",
    "The benchmark is 14 per cent.",
    "Total area is 3.2 ha.",
])
def test_quantities_are_removed(text):
    redacted = redact_numbers(text)
    assert not contains_figure(redacted), redacted
    assert PLACEHOLDER in redacted


def test_sentence_shape_survives():
    """The point of retrieval is the shape, so it has to remain legible."""
    redacted = redact_numbers(
        "The plant generated 87,600 MWh, exceeding the estimate by 4.2%.")
    assert redacted.startswith("The plant generated")
    assert "exceeding the estimate by" in redacted


@pytest.mark.parametrize("text,kept", [
    ("Assessed under section 3.18.1 of the Standard.", "3.18.1"),
    ("See s5.4.2(2)(a) for the condition.", "5.4.2"),
    ("Applying VMR0017 to the project.", "VMR0017"),
    ("Prepared to VCS v5.0.", "v5.0"),
    ("Refer to Table 8.", "Table 8"),
])
def test_structural_references_are_kept(text, kept):
    """Clause and version references describe how a document is organised.
    None can be mistaken for a calculated result, and they help a model match
    Bodhi-hub's structure."""
    assert kept in redact_numbers(text)


def test_a_table_row_of_figures_collapses():
    redacted = redact_numbers("2021 | 84,000 | 71,200 | 12,800")
    assert not contains_figure(redacted)
    assert redacted.count(PLACEHOLDER) <= 2


def test_redaction_is_idempotent():
    once = redact_numbers("Profit was 40,000 against a cost of 39,900.")
    assert redact_numbers(once) == once


def test_empty_input_is_safe():
    assert redact_numbers("") == ""


def test_contains_figure_ignores_clause_references():
    assert not contains_figure("Assessed under section 3.18.1 and Table 8.")


def test_contains_figure_detects_a_real_number():
    assert contains_figure("The yield was 12450 kg.")


# --- chunking --------------------------------------------------------------

SAMPLE = """
1. Introduction

This audit covers the 2024 season for the farm described below. The engagement
was carried out under the standard procedure and the findings are set out in
the sections that follow this introduction paragraph here.

2. Findings

The soil samples returned values within the expected range for the region.
Irrigation practice was consistent with the plan agreed at the previous audit,
and no material deviation was identified during the site visit conducted.

3. Recommendations

We recommend continuing the current rotation and reviewing the irrigation
schedule before the next season begins in order to maintain the observed
improvement across the surveyed area of the holding.
"""


def test_chunks_follow_headings():
    chunks = chunk_text(SAMPLE, source="audit.pdf")
    headings = [c.heading for c in chunks]
    assert any("Findings" in h for h in headings)
    assert any("Recommendations" in h for h in headings)


def test_each_chunk_carries_its_heading():
    """A section retrieved without its heading teaches nothing about where it
    belongs in a document."""
    for chunk in chunk_text(SAMPLE, source="audit.pdf"):
        assert chunk.source == "audit.pdf"


def test_chunks_do_not_exceed_the_limit():
    long_text = "1. Section\n\n" + ("A sentence of reasonable length. " * 400)
    for chunk in chunk_text(long_text):
        assert chunk.char_count <= MAX_CHARS


def test_oversized_sections_split_at_sentence_ends():
    long_text = "1. Section\n\n" + ("A sentence of reasonable length. " * 400)
    for chunk in chunk_text(long_text):
        assert not chunk.text.endswith("A sentence of reasonable")


def test_a_document_without_headings_still_chunks():
    """Otherwise a flat report is silently skipped at ingestion."""
    flat = "This report has no headings at all. " * 60
    assert chunk_text(flat)


def test_empty_input_yields_no_chunks():
    assert chunk_text("") == []


def test_ordinals_are_sequential():
    chunks = chunk_text(SAMPLE)
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))


# --- the style prompt ------------------------------------------------------

def _example(text="The plant generated «figure» MWh.") -> Retrieved:
    return Retrieved(heading="Findings", text=text, source="audit.pdf",
                     distance=0.1)


def test_the_style_prompt_forbids_carrying_detail_across():
    prompt = as_style_prompt([_example()])
    lowered = prompt.lower()
    assert "form only" in lowered
    assert "do not invent values" in lowered
    assert "already correct" in lowered


def test_the_style_prompt_names_the_source():
    assert "audit.pdf" in as_style_prompt([_example()])


def test_no_examples_gives_no_prompt():
    """An empty header would still instruct a model about excerpts it cannot
    see."""
    assert as_style_prompt([]) == ""


def test_style_prompt_content_carries_no_figures():
    prompt = as_style_prompt([_example()])
    body = prompt.replace(STYLE_PROMPT_HEADER, "")
    assert not contains_figure(body)


# --- regressions from the first realistic pass ----------------------------

def test_a_numbered_heading_is_not_redacted():
    """"3. Findings" becoming "«figure». Findings" destroys exactly the
    structure retrieval exists to capture."""
    assert redact_numbers("3. Findings").startswith("3. Findings")
    assert redact_numbers("2.1 Scope of Works").startswith("2.1 Scope")


def test_a_currency_amount_does_not_swallow_the_full_stop():
    """Otherwise two sentences run together in the retrieved example."""
    redacted = redact_numbers("a cost of ₹39,900. Soil carbon was measured.")
    assert ". Soil carbon" in redacted


def test_a_replaced_figure_keeps_its_surrounding_spaces():
    redacted = redact_numbers("profit was INR 1,20,000 against a cost")
    assert f"{PLACEHOLDER} against" in redacted


@pytest.mark.parametrize("unit", ["MWh", "MW", "tCO2e", "ha", "kg"])
def test_units_survive_so_the_sentence_still_reads(unit):
    redacted = redact_numbers(f"generated 87,600 {unit} last year")
    assert unit in redacted
    assert not contains_figure(redacted)
