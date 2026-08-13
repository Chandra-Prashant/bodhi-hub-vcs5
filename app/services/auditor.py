"""
Module 7b — the auditor.

This is the "agent that reviews the report and flags missing data" from the
original brief. It is deliberately NOT an LLM deciding what is wrong.

The gap detection is deterministic: it reads the compliance report, the PDD
completion report, and the findings from every module, and ranks what is
outstanding. A language model then explains the ranked list in plain English
for the project manager. That ordering matters — if the model did the detecting,
its output would be unreproducible, and two runs on the same project could
disagree about whether a project is ready for validation.

`narrate()` is the only place in this system an LLM touches project content,
and it is given a closed list of gaps and told to explain, not to assess.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from app.domain.classification import Finding, Severity
from app.domain.compliance import ComplianceReport, Status


class Priority(str, Enum):
    BLOCKER = "BLOCKER"       # cannot proceed to validation
    REQUIRED = "REQUIRED"     # must be done before submission
    REVIEW = "REVIEW"         # check before submission
    INFO = "INFO"


_PRIORITY_ORDER = {
    Priority.BLOCKER: 0, Priority.REQUIRED: 1,
    Priority.REVIEW: 2, Priority.INFO: 3,
}


@dataclass
class Gap:
    priority: Priority
    area: str
    detail: str
    clause: str
    action: str = ""
    weight: int = 0   # magnitude within a priority band; higher sorts first

    def sort_key(self) -> tuple[int, int, str]:
        # Weight is negated so the biggest item in each band leads. Without it
        # the list sorts alphabetically inside a priority, which buries a
        # section needing ten paragraphs under one needing a single line.
        return (_PRIORITY_ORDER[self.priority], -self.weight, self.area)


@dataclass
class AuditResult:
    gaps: list[Gap]
    ready_for_validation: bool
    compliance_summary: dict[str, int]
    document_completion: dict[str, int] = field(default_factory=dict)

    @property
    def blockers(self) -> list[Gap]:
        return [g for g in self.gaps if g.priority is Priority.BLOCKER]

    @property
    def required(self) -> list[Gap]:
        return [g for g in self.gaps if g.priority is Priority.REQUIRED]

    def as_text(self) -> str:
        """Plain-text report, no LLM involved."""
        lines = [
            f"Readiness: {'READY' if self.ready_for_validation else 'NOT READY'} "
            f"for validation",
            "",
            "Compliance: " + ", ".join(
                f"{v} {k.lower().replace('_', ' ')}"
                for k, v in self.compliance_summary.items() if v),
            "",
        ]
        current = None
        for gap in self.gaps:
            if gap.priority is not current:
                current = gap.priority
                lines.append(f"--- {current.value} ---")
            lines.append(f"  [{gap.clause}] {gap.area}: {gap.detail}")
            if gap.action:
                lines.append(f"      -> {gap.action}")
        return "\n".join(lines)


def audit(
    report: ComplianceReport,
    findings: list[Finding] | None = None,
    instructions_remaining: dict[str, int] | None = None,
) -> AuditResult:
    """Deterministic gap analysis across compliance, findings and the document."""
    gaps: list[Gap] = []

    for result in report.results:
        if result.status is Status.FAILED:
            gaps.append(Gap(
                Priority.BLOCKER, result.requirement.title, result.note,
                result.clause,
                "Resolve the blocking finding; the project cannot be validated "
                "as currently described."))
        elif result.status is Status.NEEDS_INPUT:
            gaps.append(Gap(
                Priority.REQUIRED, result.requirement.title, result.note,
                result.clause,
                "Supply the missing documentation or run the relevant module."))
        elif result.status is Status.SATISFIED and result.note:
            gaps.append(Gap(
                Priority.REVIEW, result.requirement.title, result.note,
                result.clause, "Review the open warnings before submission."))

    # Warnings that no requirement picked up still deserve an airing — they are
    # usually the methodology-specific traps (stale reference data, flat annual
    # estimates, LDC weighting elections).
    evidenced = {id(f) for r in report.results for f in r.evidence}
    for finding in findings or []:
        if id(finding) in evidenced:
            continue
        if finding.severity is Severity.WARNING:
            gaps.append(Gap(
                Priority.REVIEW, finding.check, finding.message,
                finding.source))
        elif finding.severity is Severity.FAIL:
            gaps.append(Gap(
                Priority.BLOCKER, finding.check, finding.message,
                finding.source))

    for section, count in sorted(
            (instructions_remaining or {}).items(), key=lambda kv: -kv[1]):
        gaps.append(Gap(
            Priority.REQUIRED, f"Document section: {section}",
            f"{count} guidance block(s) still require author input.",
            "VCS PD Template",
            "Write this section in the generated Project Description.",
            weight=count))

    gaps.sort(key=lambda g: g.sort_key())

    return AuditResult(
        gaps=gaps,
        ready_for_validation=report.ready_for_validation and not any(
            g.priority is Priority.BLOCKER for g in gaps),
        compliance_summary=report.summary,
        document_completion=dict(instructions_remaining or {}),
    )


# ---------------------------------------------------------------------------
# Optional narrative layer
# ---------------------------------------------------------------------------

AUDITOR_SYSTEM_PROMPT = """\
You are drafting a readiness briefing for a carbon project manager preparing a \
VCS v5.0 Project Description.

You will be given a closed list of gaps that has already been determined by a \
deterministic compliance engine. Your job is to explain that list clearly and \
help the reader prioritise.

Rules, without exception:
- Do not add gaps. Do not remove gaps. The list is complete and final.
- Do not state, estimate, adjust or recalculate any number. Emission factors, \
emission reductions, IRRs, capacities and dates are computed elsewhere and \
audited by a third party.
- Do not assess whether the project is additional, eligible, or ready. That \
determination is in the input; report it, do not form your own.
- Do not invent clause references. Use only the clauses given.
- If something is unclear, say so rather than filling the gap.

Write in plain English, grouped by priority, with the blockers first."""


def narrative_prompt(result: AuditResult) -> tuple[str, str]:
    """Return (system_prompt, user_content) for the narrative pass.

    Kept as a pure function so the prompt can be inspected and tested without
    calling a model.
    """
    lines = [
        f"Readiness determination (do not revise): "
        f"{'READY' if result.ready_for_validation else 'NOT READY'}",
        "",
        "Gaps:",
    ]
    for gap in result.gaps:
        lines.append(f"- [{gap.priority.value}] ({gap.clause}) {gap.area}: "
                     f"{gap.detail}")
    return AUDITOR_SYSTEM_PROMPT, "\n".join(lines)
