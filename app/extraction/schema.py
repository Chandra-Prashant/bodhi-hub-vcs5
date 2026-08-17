"""
Extraction schema — Phase 3.

Rules.md: "Every extraction output must validate against a defined Pydantic
schema before moving to the next stage." So extraction produces this, or it
produces a flagged document. It never produces free text.

THE FIELD LIST IS DELIBERATELY SHORT, AND WHAT IT OMITS IS THE POINT
--------------------------------------------------------------------
This schema contains only *inputs* — figures a document legitimately states
about a project. It contains no figure the calculation engine derives.

That is not an oversight. A project document will often quote its own emission
reductions, its own IRR, its own grid emission factor. Extracting those and
carrying them forward would let a number typed by someone else bypass the
engine entirely and land in a report under our name. The whole architecture
exists to stop that. `guards.py` enforces it and a test asserts it.

Where a document does state a derived figure, the right move is to extract
nothing, compute it, and compare — a disagreement is a finding worth raising,
not a value worth adopting.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Confidence(str, Enum):
    """Per-field confidence. Anything below HIGH reaches a reviewer.

    Deliberately three bands rather than a raw score: a reviewer acts on
    "check this", not on 0.72. The numeric score is retained on the field for
    threshold tuning during Phase 9's parallel run.
    """
    HIGH = "HIGH"           # clearly stated, unambiguous, format as expected
    MEDIUM = "MEDIUM"       # found, but inferred, reformatted or ambiguous
    LOW = "LOW"             # a guess — always reviewed
    NOT_FOUND = "NOT_FOUND"  # absent from the document


HIGH_THRESHOLD = 0.90
MEDIUM_THRESHOLD = 0.70


def band(score: float) -> Confidence:
    if score >= HIGH_THRESHOLD:
        return Confidence.HIGH
    if score >= MEDIUM_THRESHOLD:
        return Confidence.MEDIUM
    return Confidence.LOW


class ExtractedField(BaseModel, Generic[T]):
    """One value, with everything a reviewer needs to check it.

    `source_text` is what makes review fast. Without the surrounding sentence a
    reviewer has to reopen the source document and search it, which is most of
    the manual effort this system is meant to remove.
    """

    value: T | None = None
    confidence: Confidence = Confidence.NOT_FOUND
    score: float = 0.0
    source_page: int | None = None
    source_text: str = ""
    note: str = ""

    @property
    def needs_review(self) -> bool:
        return self.confidence is not Confidence.HIGH

    @property
    def is_present(self) -> bool:
        return self.value is not None and self.confidence is not Confidence.NOT_FOUND


class ProjectExtraction(BaseModel):
    """Inputs to the assessment, as stated by a source document.

    Every field here is something a person wrote down. Nothing here is
    computed by us, and nothing computed by us belongs here.
    """

    model_config = {"extra": "forbid"}

    project_name: ExtractedField[str] = Field(
        default_factory=ExtractedField,
        description="The name of the project itself, not the document title "
                    "and not the proponent's company name.")
    proponent: ExtractedField[str] = Field(
        default_factory=ExtractedField,
        description="The organisation developing or owning the project.")
    country_iso2: ExtractedField[str] = Field(
        default_factory=ExtractedField,
        description="Host country as a two-letter ISO code, e.g. IN for India. "
                    "If the document names the country in words, give the code "
                    "and say so in note.")
    technology: ExtractedField[str] = Field(
        default_factory=ExtractedField,
        description="Generation technology as the document describes it, e.g. "
                    "'terrestrial solar photovoltaic', 'onshore wind'.")
    installed_capacity_mw: ExtractedField[str] = Field(
        default_factory=ExtractedField,
        description="Installed capacity as a number only, no unit. Record the "
                    "unit the document used in note; do not convert.")
    expected_annual_generation_mwh: ExtractedField[str] = Field(
        default_factory=ExtractedField,
        description="Expected net annual electricity export as a number only, "
                    "no unit. Do not convert.")
    initial_crediting_period_start: ExtractedField[date] = Field(
        default_factory=ExtractedField,
        description="Start date of the initial crediting period, as written "
                    "(e.g. 01-MAR-2026). Not the construction or commissioning "
                    "date unless the document says they are the same.")
    location_description: ExtractedField[str] = Field(
        default_factory=ExtractedField,
        description="Where the project is, in the document's own words.")

    # Financial model inputs — stated in a project's own financial documents.
    capex: ExtractedField[str] = Field(
        default_factory=ExtractedField,
        description="Total capital cost as a number only. Record the currency "
                    "and scale (lakh, crore, million) in note; do not convert.")
    annual_opex: ExtractedField[str] = Field(
        default_factory=ExtractedField,
        description="Annual operating expenditure as a number only, same "
                    "treatment as capital cost.")
    tariff_per_mwh: ExtractedField[str] = Field(
        default_factory=ExtractedField,
        description="Power purchase tariff per MWh as a number only.")
    project_lifetime_years: ExtractedField[str] = Field(
        default_factory=ExtractedField,
        description="Operating life in years as a number only. Not the "
                    "crediting period.")
    benchmark_irr: ExtractedField[str] = Field(
        default_factory=ExtractedField,
        description="The required or benchmark rate of return the project must "
                    "clear — often a regulator-approved return on equity. "
                    "Number only; say in note whether it was a percentage. "
                    "This is a required hurdle rate, NOT a computed IRR.")

    def fields_needing_review(self) -> list[str]:
        """Fields that were found but are not certain.

        A field the document simply does not contain is NOT in this list. It is
        absent, not uncertain, and the two need different handling: an
        uncertain value is checked against the source text, a missing required
        value is typed in. Conflating them sends a reviewer to verify a blank.
        """
        return [
            name for name in type(self).model_fields
            if getattr(self, name).is_present and getattr(self, name).needs_review
        ]

    def missing_required(self) -> list[str]:
        """Required fields the document did not yield — these need manual entry."""
        return [
            name for name in REQUIRED_FIELDS
            if not getattr(self, name).is_present
        ]

    def fields_found(self) -> list[str]:
        return [
            name for name in type(self).model_fields
            if getattr(self, name).is_present
        ]

    def as_inputs(self) -> dict[str, Any]:
        """Flatten to plain values for the assessment engine.

        Numbers stay as strings. They were strings in the document and the
        engine parses them itself; converting here would put a float between
        the document and the calculation.
        """
        return {
            name: getattr(self, name).value
            for name in type(self).model_fields
            if getattr(self, name).is_present
        }


# Without these the assessment cannot run at all. Financial fields are absent
# from this list on purpose: a project can be classified and quantified without
# them, and only the additionality test needs them.
REQUIRED_FIELDS: tuple[str, ...] = (
    "project_name",
    "proponent",
    "country_iso2",
    "technology",
    "installed_capacity_mw",
    "expected_annual_generation_mwh",
    "initial_crediting_period_start",
)


class ExtractionStatus(str, Enum):
    EXTRACTED = "EXTRACTED"
    PARTIAL = "PARTIAL"           # some fields found, review required
    FAILED = "FAILED"             # flag for manual entry


class ExtractionResult(BaseModel):
    """What the pipeline hands to validation.

    Rules.md: "Extraction failures must never fail silently — flag the document
    for manual entry." A FAILED result is a normal outcome with a reason
    attached, not an exception swallowed somewhere upstream.
    """

    document_name: str
    status: ExtractionStatus
    data: ProjectExtraction = Field(default_factory=ProjectExtraction)
    error: str = ""
    pages_read: int = 0
    model: str = ""

    @property
    def requires_manual_entry(self) -> bool:
        return self.status is ExtractionStatus.FAILED

    @property
    def review_queue(self) -> list[str]:
        """What a reviewer has to touch: uncertain values first, then blanks
        that have to be filled before anything can run."""
        if self.status is ExtractionStatus.FAILED:
            return list(ProjectExtraction.model_fields)
        return self.data.fields_needing_review() + self.data.missing_required()


def field_specification() -> str:
    """The exact field list, rendered for the extraction prompt.

    Generated from the schema rather than written out by hand. The prompt used
    to say "return JSON matching the given schema" without ever supplying one,
    so the model invented its own field names and `parse_response` — which
    keeps only exact matches — discarded most of what it found. Eleven of
    thirteen values were lost silently, and every test passed because the test
    double returned correctly-named keys.

    Generating this means the prompt cannot drift from the schema again.
    """
    lines = []
    for name, field in ProjectExtraction.model_fields.items():
        required = " (REQUIRED)" if name in REQUIRED_FIELDS else ""
        lines.append(f'  "{name}"{required} — {field.description or ""}')
    return "\n".join(lines)
