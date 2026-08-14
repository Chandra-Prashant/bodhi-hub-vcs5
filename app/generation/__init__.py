"""Phase 6 — narrative generation. The model writes prose; numbers are inserted."""

from app.generation.narrative import (  # noqa: F401
    GeneratedSection,
    GenerationResult,
    NarrativeModel,
    GeminiNarrator,
    SectionBrief,
    generate_report,
    generate_section,
)
from app.generation.placeholders import (  # noqa: F401
    NumberInNarrative,
    UnknownPlaceholder,
    ValueBundle,
    assert_no_literal_numbers,
    placeholders_in,
    render,
    substitute,
)
