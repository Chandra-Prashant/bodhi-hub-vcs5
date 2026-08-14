"""
Numeric redaction — the enforcement behind "RAG does not influence any
calculated value."

Architecture.md: "RAG is used only for structure/style, not for numbers. It
retrieves similar past reports so the AI-written narrative matches Bodhi-hub's
existing tone and format — it does not influence any calculated value."

That is a rule, and a rule needs a mechanism. Retrieved passages are full of
figures: last year's yields, another farm's profit, a different project's
tonnage. A model handed those alongside an instruction to write about *this*
farm has every opportunity to carry one across, and the resulting number would
be plausible, specific, wrong, and untraceable to any calculation.

So the figures are removed before the model ever sees them. What survives is
exactly what the retrieval is for — sentence shape, section order, register,
the way Bodhi-hub phrases a finding:

    "The plant generated 87,600 MWh, exceeding the estimate by 4.2%."
    → "The plant generated «figure» MWh, exceeding the estimate by «figure»."

The shape is intact. The number cannot be copied because it is not there.
"""

from __future__ import annotations

import re

PLACEHOLDER = "«figure»"

# Ordered: the more specific patterns run first so a percentage or a currency
# amount is replaced whole rather than leaving a stray symbol behind.
_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Currency with a symbol or code: ₹1,20,000 · INR 40,000 · $2.5m
    # The decimal group is explicit rather than lumping '.' into the digit
    # class — otherwise a sentence-ending full stop is swallowed with the
    # amount and two sentences run together.
    re.compile(r"(?:₹|Rs\.?|INR|USD|EUR|\$|€)\s?\d[\d,]*(?:\.\d+)?"
               r"(?:\s(?:lakh|crore|cr|k|m|bn|million|billion))?",
               re.IGNORECASE),
    # Bare number followed by a scale word: 40,000 lakh
    re.compile(r"\b\d[\d,]*(?:\.\d+)?\s(?:lakh|crore|million|billion)\b",
               re.IGNORECASE),
    # Percentages: 4.2% · 14 per cent
    re.compile(r"\b\d[\d,]*(?:\.\d+)?\s?(?:%|per cent|percent)", re.IGNORECASE),
    # A bare number immediately followed by a unit — keeps the unit, which is
    # part of the sentence shape.
    re.compile(r"\b\d[\d,]*(?:\.\d+)?(?=\s?(?:MWh|MW|kWh|kW|tCO2e?|ha|kg|t)\b)",
               re.IGNORECASE),
    # Any remaining number, including thousands separators and decimals.
    re.compile(r"\b\d[\d,]*(?:\.\d+)?\b"),
)

# Digits that carry no quantitative meaning and are worth keeping, because they
# help a model match Bodhi-hub's document structure rather than its arithmetic.
_STRUCTURAL = (
    # A numbered heading or list marker at the start of a line: "3. Findings".
    # Redacting these turns every heading into "«figure». Findings", which
    # destroys exactly the structure the retrieval exists to capture.
    re.compile(r"(?m)^\s*\d+(?:\.\d+)*\.?(?=\s+\S)"),
    # Section and clause references: 3.18.1 · s5.4.2(2)(a) · Table 8
    re.compile(r"\b(?:s|section|clause|para(?:graph)?|table|annex|appendix)\s?"
               r"\d+(?:\.\d+)*(?:\([a-z0-9]+\))*", re.IGNORECASE),
    # Standard and methodology identifiers: VCS v5.0 · VMR0017 · ACM0002 v22.0
    re.compile(r"\b(?:v|version)\s?\d+(?:\.\d+)*[AB]?\b", re.IGNORECASE),
    re.compile(r"\b(?:VMR|VT|ACM|AM|VM|TOOL)\s?\d+\b", re.IGNORECASE),
)

_KEEP = "\x00KEEP{}\x00"


def redact_numbers(text: str) -> str:
    """Replace quantitative figures with a placeholder, keeping structure.

    Clause references, version numbers and methodology identifiers survive:
    they tell a model how Bodhi-hub organises a document, and none of them can
    be mistaken for a calculated result.
    """
    if not text:
        return text

    preserved: list[str] = []

    def _stash(match: re.Match[str]) -> str:
        preserved.append(match.group(0))
        return _KEEP.format(len(preserved) - 1)

    working = text
    for pattern in _STRUCTURAL:
        working = pattern.sub(_stash, working)

    for pattern in _PATTERNS:
        working = pattern.sub(PLACEHOLDER, working)

    for index, original in enumerate(preserved):
        working = working.replace(_KEEP.format(index), original)

    # Collapse runs left by adjacent figures, e.g. a table row of numbers.
    working = re.sub(rf"(?:{re.escape(PLACEHOLDER)}[\s,;|]*){{2,}}",
                     f"{PLACEHOLDER} ", working)
    return working


def contains_figure(text: str) -> bool:
    """True if any quantitative figure survives redaction.

    Used as an assertion at the retrieval boundary rather than a filter — if
    this ever returns True on redacted text, the redaction has a hole and the
    right response is to find it, not to pass the text along.
    """
    stripped = text
    for pattern in _STRUCTURAL:
        stripped = pattern.sub("", stripped)
    return bool(re.search(r"\b\d[\d,]*(?:\.\d+)?\b", stripped))
