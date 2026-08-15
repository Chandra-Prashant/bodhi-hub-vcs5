"""
The bridge between the calculation engine and the narrative generator.

Phases.md, Phase 6: "Wire calculation engine output + RAG-retrieved examples
into LLM narrative generation."

Two things happen here and both matter.

**The value bundle is built from engine output only.** The set of figures a
report can contain is fixed before any text is drafted. A model cannot
reference a number that is not here, because `substitute` raises on an unknown
placeholder.

**Each brief carries the existing deterministic prose as its fallback.** That
prose is already correct and already clause-cited — it is what the report
contains today. So with no model configured the output is byte-identical to the
current behaviour, and with one it becomes better-written rather than
differently-sourced. The generator is an improvement to register, never a
replacement for the citation trail.
"""

from __future__ import annotations

from app.domain.classification import Classification
from app.generation.narrative import SectionBrief
from app.generation.placeholders import ValueBundle


def build_value_bundle(
    intake,
    classification: Classification,
    ef=None,
    er=None,
    add=None,
) -> ValueBundle:
    """Every figure the narrative may reference, formatted for a report."""
    bundle = ValueBundle()

    bundle.add("capacity_mw", intake.installed_capacity_mw, "MW", 0)
    bundle.add("generation_mwh", intake.expected_annual_generation_mwh, "MWh", 0)
    bundle.add("crediting_period_years",
               classification.crediting_period_years, "years", 0)
    bundle.add("max_crediting_years",
               classification.max_total_crediting_years, "years", 0)
    bundle.add("cm_weight_om", classification.cm_weights[0], "", 2)
    bundle.add("cm_weight_bm", classification.cm_weights[1], "", 2)

    if ef is not None:
        bundle.add("ef_grid_om", ef.ef_grid_om, "tCO2/MWh", 4)
        bundle.add("ef_grid_bm", ef.ef_grid_bm, "tCO2/MWh", 4)
        bundle.add("ef_grid_cm", ef.ef_grid_cm, "tCO2/MWh", 4)
        bundle.add("bm_sample_size", len(ef.bm_sample_unit_ids), "units", 0)

    if er is not None:
        bundle.add("baseline_tco2e", er.baseline_emissions_tco2e, "tCO2e", 1)
        bundle.add("project_tco2e", er.project_emissions_tco2e, "tCO2e", 1)
        bundle.add("leakage_tco2e", er.leakage_emissions_tco2e, "tCO2e", 1)
        bundle.add("reductions_tco2e", er.emission_reductions_tco2e, "tCO2e", 1)
        bundle.add("crediting_total_tco2e",
                   er.emission_reductions_tco2e
                   * classification.crediting_period_years, "tCO2e", 0)

    if add is not None:
        investment = add.investment
        # A percentage, formatted here rather than in prose — the model cannot
        # multiply by 100 because it cannot write a number at all.
        if investment.irr_without_credits is not None:
            bundle.add("irr_without_credits",
                       investment.irr_without_credits * 100, "%", 2)
        if investment.irr_with_credits is not None:
            bundle.add("irr_with_credits",
                       investment.irr_with_credits * 100, "%", 2)
        bundle.add("benchmark_irr", investment.benchmark_irr * 100, "%", 2)
        bundle.add("common_practice_f",
                   add.common_practice_result.f_factor * 100, "%", 1)

    return bundle


def briefs_from_sections(
    deterministic: dict[str, list[str]],
    bundle: ValueBundle,
    placeholders_by_heading: dict[str, tuple[str, ...]] | None = None,
    clauses_by_heading: dict[str, tuple[str, ...]] | None = None,
) -> list[SectionBrief]:
    """Turn the existing deterministic prose into briefs a model can improve.

    The deterministic text becomes the fallback, so nothing is lost if the
    model is unavailable or writes something that fails verification. The
    instruction describes what the section must cover rather than quoting the
    prose, because handing a model the finished text and asking it to rewrite
    produces a paraphrase, not a report in the firm's register.
    """
    placeholders_by_heading = placeholders_by_heading or {}
    clauses_by_heading = clauses_by_heading or {}

    briefs: list[SectionBrief] = []
    for heading, paragraphs in deterministic.items():
        text = " ".join(paragraphs).strip()
        if not text:
            continue

        allowed = placeholders_by_heading.get(heading)
        if allowed is None:
            # Nothing declared for this section, so no figures are offered.
            # A model with no placeholders is told explicitly to write none.
            allowed = ()

        briefs.append(SectionBrief(
            heading=heading,
            instruction=_instruction_for(heading, len(paragraphs)),
            placeholders=tuple(p for p in allowed if p in bundle),
            clauses=clauses_by_heading.get(heading, ()),
            # The fallback keeps the deterministic prose verbatim. It contains
            # literal figures, which is fine — it never passes through the
            # model, and render() only checks drafts the model produced.
            fallback="\n\n".join(paragraphs),
        ))
    return briefs


def _instruction_for(heading: str, paragraph_count: int) -> str:
    length = ("one paragraph" if paragraph_count <= 1
              else f"about {paragraph_count} paragraphs")
    return (
        f"Write the '{heading}' section of a VCS project description, in "
        f"{length}. State what is the case plainly and in the present tense. "
        f"Cite the clauses given. Do not summarise what you are about to say "
        f"and do not restate the heading."
    )


# Which computed values each section may legitimately reference. A section not
# listed here gets none, which is the safe default: a model offered a figure it
# has no business mentioning will usually find a way to mention it.
SECTION_PLACEHOLDERS: dict[str, tuple[str, ...]] = {
    "Summary Description of the Project": (
        "capacity_mw", "generation_mwh", "reductions_tco2e",
        "crediting_period_years"),
    "Baseline Scenario": (
        "ef_grid_om", "ef_grid_bm", "ef_grid_cm",
        "cm_weight_om", "cm_weight_bm", "bm_sample_size"),
    "Baseline Emissions": (
        "generation_mwh", "ef_grid_cm", "baseline_tco2e"),
    "Project Emissions": ("project_tco2e",),
    "Leakage Emissions": ("generation_mwh", "leakage_tco2e"),
    "Quantification of Estimated Reductions and Removals": (
        "baseline_tco2e", "project_tco2e", "leakage_tco2e", "reductions_tco2e"),
    "Additionality Methods": (
        "irr_without_credits", "irr_with_credits", "benchmark_irr",
        "common_practice_f"),
    "Project Crediting Period": (
        "crediting_period_years", "max_crediting_years"),
}

SECTION_CLAUSES: dict[str, tuple[str, ...]] = {
    "Baseline Scenario": ("VT0011 v1.0 Step 3", "VT0011 v1.0 para 86"),
    "Baseline Emissions": ("ACM0002 v22.0",),
    "Project Emissions": ("VMR0017 v1.0 eq. 1",),
    "Leakage Emissions": ("VMR0017 v1.0 eq. 19",),
    "Quantification of Estimated Reductions and Removals": (
        "VMR0017 v1.0 eq. 17",),
    "Additionality Methods": (
        "VT0008 v1.0 s5.4.2", "VMR0017 v1.0 s5.3.2"),
    "Project Crediting Period": ("VCS Standard v5.0 s3.8.4, Table 8",),
}
