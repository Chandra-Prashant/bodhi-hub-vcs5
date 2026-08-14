"""
Validator — combines rule flags and extraction confidence into one queue.

The output is the thing the review dashboard renders and the calculation engine
gates on. Its job is to answer two questions:

  Can this proceed to calculation?   (no ERROR flags)
  What does a human need to look at? (rule flags + low-confidence fields)

Confidence and rules are kept separate all the way through. A HIGH-confidence
field that fails a range check is still flagged — the model being sure it read
the value correctly says nothing about whether the value is right.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.extraction.schema import (
    Confidence,
    ExtractionResult,
    ExtractionStatus,
    ProjectExtraction,
)
from app.validation.rules import RULES, Flag, Severity, _flag


@dataclass
class ReviewItem:
    """One thing a reviewer has to act on."""

    field_name: str
    reason: str
    severity: Severity
    observed: str = ""
    source_text: str = ""
    source_page: int | None = None
    rule_id: str = ""

    @property
    def blocking(self) -> bool:
        return self.severity is Severity.ERROR


@dataclass
class ValidationResult:
    flags: list[Flag] = field(default_factory=list)
    review_items: list[ReviewItem] = field(default_factory=list)
    fields_checked: int = 0

    @property
    def errors(self) -> list[Flag]:
        return [f for f in self.flags if f.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[Flag]:
        return [f for f in self.flags if f.severity is Severity.WARNING]

    @property
    def blocking_items(self) -> list[ReviewItem]:
        return [i for i in self.review_items if i.blocking]

    @property
    def can_calculate(self) -> bool:
        """An ERROR means a value is wrong or unusable, so the engine must not
        run on it. Warnings do not block — they are reviewed alongside the
        result.

        This reads review_items rather than flags, because the two sources of
        blocking are not the same. A rule failure produces a flag; a field the
        model essentially guessed at produces no flag at all but must still
        stop the calculation. Checking only flags let low-confidence values
        through to the engine, which is the one thing this stage exists to
        prevent.
        """
        return not self.blocking_items

    @property
    def auto_approvable(self) -> bool:
        """PRD: "only flagged items require manual review". Nothing flagged and
        nothing uncertain means this passes through without a reviewer."""
        return not self.review_items

    def as_text(self) -> str:
        if self.auto_approvable:
            return f"{self.fields_checked} fields checked — nothing flagged."
        lines = [
            f"{self.fields_checked} fields checked, "
            f"{len(self.review_items)} need review "
            f"({len(self.blocking_items)} blocking)",
        ]
        for item in sorted(self.review_items,
                           key=lambda i: (i.severity is not Severity.ERROR,
                                          i.field_name)):
            lines.append(f"  [{item.severity.value}] {item.field_name}: "
                         f"{item.reason}")
            if item.source_text:
                lines.append(f"      document says: \"{item.source_text}\"")
        return "\n".join(lines)


def validate(data: ProjectExtraction) -> ValidationResult:
    """Run every rule, then fold in extraction confidence."""
    result = ValidationResult(fields_checked=len(ProjectExtraction.model_fields))
    flagged_fields: set[str] = set()

    for rule in RULES:
        flag = rule.check(data)
        if flag is None:
            continue
        result.flags.append(flag)
        flagged_fields.add(flag.field_name)
        source = getattr(data, flag.field_name, None)
        result.review_items.append(ReviewItem(
            field_name=flag.field_name,
            reason=flag.message,
            severity=flag.severity,
            observed=flag.observed,
            source_text=getattr(source, "source_text", "") if source else "",
            source_page=getattr(source, "source_page", None) if source else None,
            rule_id=flag.rule_id,
        ))

    # Low-confidence fields the rules did not already catch. A field can be
    # perfectly plausible and still have been read uncertainly.
    for name in ProjectExtraction.model_fields:
        extracted = getattr(data, name)
        if not extracted.is_present or name in flagged_fields:
            continue
        if extracted.confidence is Confidence.HIGH:
            continue
        result.review_items.append(ReviewItem(
            field_name=name,
            reason=(
                f"Extracted with {extracted.confidence.value.lower()} "
                f"confidence"
                + (f" — {extracted.note}" if extracted.note else "")
            ),
            severity=(Severity.WARNING
                      if extracted.confidence is Confidence.MEDIUM
                      else Severity.ERROR),
            observed=str(extracted.value),
            source_text=extracted.source_text,
            source_page=extracted.source_page,
        ))

    return result


def validate_extraction(extraction: ExtractionResult) -> ValidationResult:
    """Validate a whole extraction, including its own failure state."""
    if extraction.status is ExtractionStatus.FAILED:
        result = ValidationResult(
            fields_checked=len(ProjectExtraction.model_fields))
        result.flags.append(_flag(
            "extraction.failed", "*", Severity.ERROR,
            extraction.error or "Extraction failed; the document needs manual "
                                "entry."))
        result.review_items.append(ReviewItem(
            field_name="*",
            reason=extraction.error or "Extraction failed — manual entry required.",
            severity=Severity.ERROR,
            rule_id="extraction.failed",
        ))
        return result

    result = validate(extraction.data)

    for name in extraction.data.missing_required():
        result.flags.append(_flag(
            "required.missing", name, Severity.ERROR,
            "Required field not found in the document. The assessment cannot "
            "run without it."))
        result.review_items.append(ReviewItem(
            field_name=name,
            reason="Required field not found — needs manual entry.",
            severity=Severity.ERROR,
            rule_id="required.missing",
        ))

    return result
