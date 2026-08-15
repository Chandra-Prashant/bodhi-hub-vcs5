"""
Narrative generation — Phase 6.

Assembles report prose from three inputs, in descending order of authority:

  1. The calculated values — fixed before any text exists, inserted afterwards
  2. The section brief — what this section must cover, from the template
  3. Retrieved style exemplars — optional, and only ever shape and register

Point 3 is optional by design. The historical report corpus is a Phase 5
deliverable that may not exist yet, and a generator that cannot run without it
would block the whole pipeline on a document handover. Without a corpus the
prose is generated from the brief alone; with one it also matches Bodhi-hub's
house register. Nothing needs rewriting when the corpus lands.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.generation.placeholders import (
    NumberInNarrative,
    UnknownPlaceholder,
    ValueBundle,
    render,
    substitute,
)
from app.rag.index import Retrieved, as_style_prompt

SYSTEM_PROMPT = """\
You draft sections of a carbon project report for a climate advisory firm.

You never write a number. Not one — not a quantity, not a percentage, not a
date, not a currency amount. Every figure is computed elsewhere and inserted
after you finish. Where a value belongs, write its placeholder exactly as given
to you, for example {{reductions_tco2e}}.

A draft containing a literal figure is rejected and regenerated, so writing one
wastes the attempt.

Also:
- Use only the placeholders listed in the brief. Inventing one causes a
  failure, because there is no computed value behind it.
- Do not describe a figure you were not given a placeholder for. If the brief
  offers no placeholder for a quantity, that quantity does not belong in the
  section.
- Cite clauses where the brief supplies them, in the form given.
- Write plainly and in the past or present tense as the brief indicates. No
  marketing language, no hedging, no summarising what you are about to say.
- Do not add headings; the section heading is supplied by the template.
"""


class NarrativeModel(ABC):
    """Model boundary, isolated so assembly and verification are testable."""

    name = "abstract"

    @abstractmethod
    def draft(self, system: str, brief: str) -> str:
        ...


class GeminiNarrator(NarrativeModel):
    name = "gemini"

    def __init__(self, api_key: str, model: str = "gemini-flash-latest") -> None:
        self.api_key = api_key
        self.model = model
        self.name = model

    def draft(self, system: str, brief: str) -> str:
        from google import genai

        client = genai.Client(api_key=self.api_key)
        response = client.models.generate_content(
            model=self.model, contents=f"{system}\n\n{brief}")
        return response.text or ""


@dataclass
class SectionBrief:
    """What one section must say, and which values it may reference."""

    heading: str
    instruction: str
    placeholders: tuple[str, ...] = ()
    clauses: tuple[str, ...] = ()
    fallback: str = ""

    def as_prompt(self, style: str = "") -> str:
        parts = [f"SECTION: {self.heading}", "", self.instruction]
        if self.placeholders:
            parts += ["", "Available placeholders (use only these):"]
            parts += [f"  {{{{{name}}}}}" for name in self.placeholders]
        else:
            parts += ["", "This section references no computed values. Do not "
                          "write any figure at all."]
        if self.clauses:
            parts += ["", "Cite these where relevant:"]
            parts += [f"  {clause}" for clause in self.clauses]
        if style:
            parts += ["", style]
        return "\n".join(parts)


@dataclass
class GeneratedSection:
    heading: str
    text: str
    used_model: bool
    style_examples: int = 0
    attempts: int = 1
    note: str = ""


@dataclass
class GenerationResult:
    sections: list[GeneratedSection] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def used_style_corpus(self) -> bool:
        return any(s.style_examples for s in self.sections)

    def as_dict(self) -> dict[str, str]:
        return {s.heading: s.text for s in self.sections}


MAX_ATTEMPTS = 3


def _render_fallback(text: str, bundle: ValueBundle) -> str:
    """Substitute into template text WITHOUT the no-literal-numbers check.

    That check exists to catch a model writing a figure it was told not to
    write. Template text is ours: it is deterministic, clause-cited, and often
    contains figures on purpose — the equations in the quantification sections
    are literally arithmetic. Verifying it would reject the very prose the
    fallback exists to preserve.

    Placeholders are still substituted, and an unknown one still raises, so a
    template referencing a value the engine did not produce fails loudly.
    """
    return substitute(text, bundle)


def generate_section(
    brief: SectionBrief,
    bundle: ValueBundle,
    model: NarrativeModel | None = None,
    style: list[Retrieved] | None = None,
) -> GeneratedSection:
    """Draft one section, verify it wrote no figures, then insert the values.

    With no model, the brief's `fallback` is rendered instead. That is not a
    degraded mode to be embarrassed about: a deterministic sentence carrying
    correct inserted figures is more defensible than generated prose, and it is
    what a report falls back to if the model is unavailable mid-run.
    """
    style_prompt = as_style_prompt(style or [])

    if model is None:
        if not brief.fallback:
            return GeneratedSection(
                brief.heading, "", used_model=False,
                note="No model configured and no fallback text for this "
                     "section — it needs an author.")
        return GeneratedSection(
            brief.heading, _render_fallback(brief.fallback, bundle),
            used_model=False,
            note="Generated from the template without a model.")

    last_error = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            draft = model.draft(SYSTEM_PROMPT, brief.as_prompt(style_prompt))
            text = render(draft, bundle)
        except (NumberInNarrative, UnknownPlaceholder) as exc:
            # Regenerating is correct here. The failure is that the model wrote
            # something it was told not to; repairing the text ourselves would
            # mean editing prose around a figure we just refused to trust.
            last_error = str(exc)
            continue
        except Exception as exc:  # noqa: BLE001
            last_error = f"{type(exc).__name__}: {exc}"
            break
        return GeneratedSection(
            brief.heading, text, used_model=True,
            style_examples=len(style or []), attempts=attempt)

    if brief.fallback:
        return GeneratedSection(
            brief.heading, _render_fallback(brief.fallback, bundle),
            used_model=False, attempts=MAX_ATTEMPTS,
            note=f"Model output rejected {MAX_ATTEMPTS} times; template text "
                 f"used instead. Last reason: {last_error}")

    return GeneratedSection(
        brief.heading, "", used_model=False, attempts=MAX_ATTEMPTS,
        note=f"Could not generate this section: {last_error}")


def generate_report(
    briefs: list[SectionBrief],
    bundle: ValueBundle,
    model: NarrativeModel | None = None,
    retriever=None,
    organization: str = "",
) -> GenerationResult:
    """Draft every section of a report.

    `retriever` is a callable taking (query, heading) and returning style
    exemplars. Passing None — or having an empty corpus — is a supported state,
    not an error.
    """
    result = GenerationResult()

    if model is None:
        result.warnings.append(
            "No narrative model configured; sections were rendered from the "
            "template. Figures are inserted from the calculation engine either "
            "way.")

    corpus_used = False
    for brief in briefs:
        style: list[Retrieved] = []
        if retriever is not None:
            try:
                style = retriever(brief.instruction, brief.heading) or []
            except Exception as exc:  # noqa: BLE001
                result.warnings.append(
                    f"Style retrieval failed for '{brief.heading}': {exc}. "
                    f"The section was drafted without exemplars.")
        corpus_used = corpus_used or bool(style)
        result.sections.append(
            generate_section(brief, bundle, model, style))

    if retriever is not None and not corpus_used:
        result.warnings.append(
            "No style exemplars were retrieved — the historical report corpus "
            "is empty. Prose follows the template rather than the firm's "
            "house register. Index the past reports to change that; no code "
            "changes are needed.")

    for section in result.sections:
        if not section.text:
            result.warnings.append(
                f"'{section.heading}' is empty and needs an author. "
                f"{section.note}")

    return result
