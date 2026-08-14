"""
The boundary between what a document may tell us and what only the engine may
compute.

Rules.md, hard rule: the LLM must never generate, alter, or estimate any
numeric calculation. That rule is usually read as "don't ask the model to do
arithmetic", which is necessary but not sufficient. There is a quieter way to
break it: let the model *read* a computed figure off a document and carry it
forward.

A project document routinely states its own emission reductions, its own IRR,
its own grid emission factor. Those numbers came from somebody else's
spreadsheet. Extracting one and putting it in a report we generate means a
figure nobody in this system computed, and nobody can defend, appears under our
name — while every check we built quietly passes, because no calculation was
performed at all.

So the extraction schema is checked against this list at import time. Adding a
derived field to the schema fails the test suite rather than shipping.

Where a document does state a derived figure, the correct handling is to
compute it independently and compare. A disagreement is a finding worth
raising with the client; it is never a value worth adopting.
"""

from __future__ import annotations

# Names the calculation engine produces. None of these may appear in any
# extraction schema, under any spelling.
CALCULATED_FIELDS: frozenset[str] = frozenset({
    # VT0011 emission factors
    "ef_grid_om", "ef_grid_bm", "ef_grid_cm",
    "operating_margin", "build_margin", "combined_margin",
    "grid_emission_factor",
    # VMR0017 / ACM0002 quantification
    "baseline_emissions", "baseline_tco2e",
    "project_emissions", "project_tco2e",
    "leakage_emissions", "leakage_tco2e",
    "emission_reductions", "reductions_tco2e",
    "annual_reductions", "total_reductions",
    "ef_embodied",  # mandated by VMR0017 s9.1 — a default, not a document value
    # VT0008 additionality
    "irr", "irr_with_credits", "irr_without_credits",
    "npv", "f_factor", "common_practice_factor",
    "additionality_verdict",
    # Classification outputs
    "template_version", "crediting_period_end", "crediting_period_years",
    "registration_deadline", "pipeline_listing_deadline",
    "cm_weight_om", "cm_weight_bm",
    # ESG
    "risk_level",
})

# Names that trip the heuristic below but are genuinely stated inputs. Each
# needs a written reason, and the reason has to say who states the value.
#
# This overrides the SUBSTRING HEURISTIC ONLY. Nothing here can excuse a name
# in CALCULATED_FIELDS — that list is absolute, because those are figures this
# system computes and a document's version of them is somebody else's
# arithmetic.
STATED_INPUT_EXCEPTIONS: dict[str, str] = {
    "benchmark_irr": (
        "The hurdle rate the project must clear, not a rate we compute. VT0008 "
        "Appendix 2 sA2.3 requires it to come from a documented source — a "
        "CERC-approved return on equity, a WACC build-up, or a bond yield plus "
        "a stated premium — so it is read from the client's financial "
        "documentation. The IRRs compared against it are computed and remain "
        "banned. Keeping VT0008's own term preserves the link to the clause."
    ),
}

# Substrings that betray a derived quantity even under an unfamiliar name.
_DERIVED_MARKERS = (
    "emission_reduction", "reductions_tco2e", "_tco2e",
    "ef_grid", "emission_factor", "margin",
    "irr", "npv", "verdict", "risk_level",
)


class CalculatedFieldInSchema(Exception):
    """Raised when an extraction schema declares a field the engine computes."""


def assert_extraction_safe(field_names: object) -> None:
    """Check a set of extraction field names against the boundary.

    Called at import time by the extraction package, so a schema change that
    crosses the line fails immediately rather than at runtime on a client
    document.
    """
    names = {str(n) for n in field_names}

    direct = names & CALCULATED_FIELDS
    if direct:
        raise CalculatedFieldInSchema(
            f"Extraction schema declares field(s) the calculation engine "
            f"produces: {', '.join(sorted(direct))}. A computed figure read off "
            f"a document bypasses the engine and cannot be defended. Compute "
            f"it and compare instead."
        )

    suspicious = sorted(
        name for name in names
        if any(marker in name.lower() for marker in _DERIVED_MARKERS)
        and name not in STATED_INPUT_EXCEPTIONS
    )
    if suspicious:
        raise CalculatedFieldInSchema(
            f"Extraction schema field(s) look like derived quantities: "
            f"{', '.join(suspicious)}. Either rename them so the distinction is "
            f"visible at a glance, or — if the value really is stated by a "
            f"source document rather than computed here — add an entry to "
            f"STATED_INPUT_EXCEPTIONS explaining who states it. An exception "
            f"without a reason is how this boundary erodes."
        )
