"""
Module 7 — Compliance engine and traceability.

Aggregates the findings produced by every other module into a single register
of VCS Standard v5.0 requirements, each with its clause, its evidence, and its
status. This is the artefact a validation/verification body works from, and the
reason every finding in this system carries a `source` string.

A requirement can be in one of four states:

    SATISFIED     evidence exists and no blocking finding contradicts it
    NEEDS_INPUT   nothing in the system speaks to it yet — author work
    FAILED        a finding actively blocks it
    NOT_APPLICABLE with a reason, per the project's category and technology

The distinction between NEEDS_INPUT and FAILED matters commercially. A project
manager can act on the first; the second means something is wrong with the
project as described, not with the paperwork.

The registry deliberately covers only requirements this system can evidence or
detect. Sections of the Standard the engine does not touch — stakeholder
engagement (s3.17), right to operate (s3.6), records (s3.24) — appear as
NEEDS_INPUT rather than being silently omitted, because a compliance report
that lists only what the software happens to know is worse than no report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from app.domain import constants as K
from app.domain.classification import Finding, Severity


class Status(str, Enum):
    SATISFIED = "SATISFIED"
    NEEDS_INPUT = "NEEDS_INPUT"
    FAILED = "FAILED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True)
class Requirement:
    """One VCS Standard requirement the engine tracks."""
    ref: str                 # our stable key
    clause: str              # VCS Standard v5.0 section
    title: str
    evidence_checks: tuple[str, ...] = ()   # Finding.check values that evidence it
    author_supplied: bool = False           # engine cannot evidence this


# Ordered as they appear in the Standard.
REGISTRY: tuple[Requirement, ...] = (
    Requirement(
        "methodology_applicability", "s3.1 / VMR0017 s4",
        "Project meets the applicability conditions of the applied methodology",
        ("vmr0017.geography", "vmr0017.capacity", "intake.grid_connection")),
    Requirement(
        "project_documentation", "s3.4",
        "Project description prepared using the applicable VCS template",
        ("pdd.completion",)),
    Requirement(
        "capacity_limit", "s3.5.12–3.5.13",
        "Project does not exceed the methodology capacity limit and is not a "
        "fragment of another project",
        ("vmr0017.capacity", "pdd.not_applicable.capacity_limit")),
    Requirement(
        "right_to_operate", "s3.6",
        "Project proponent holds the right to operate and the right to "
        "reductions and removals", author_supplied=True),
    Requirement(
        "project_start_date", "s3.7",
        "Project start date is determined and evidenced",
        ("intake.start_date",)),
    Requirement(
        "crediting_period", "s3.8.4",
        "Crediting period length and renewals comply with Table 8",
        ("vcs.crediting_period",)),
    Requirement(
        "pipeline_listing", "s3.8.2",
        "Project listed on the VCS pipeline within the applicable deadline",
        ("vcs.pipeline_listing_deadline",)),
    Requirement(
        "registration_deadline", "s3.8.2",
        "Registration requested within the applicable deadline",
        ("vcs.registration_deadline",)),
    Requirement(
        "project_location", "s3.10",
        "Project location specified with geolocation files meeting the "
        "Geolocation File Requirements", author_supplied=True),
    Requirement(
        "project_boundary", "s3.11",
        "Project boundary defined, including all relevant sources and gases",
        author_supplied=True),
    Requirement(
        "baseline_scenario", "s3.12",
        "Baseline scenario identified and justified",
        ("vt0011.cm", "vt0011.om.simple", "vt0011.bm")),
    Requirement(
        "additionality", "s3.13",
        "Additionality demonstrated using the applicable procedure",
        ("vt0008.verdict", "vcs.regulatory_surplus", "vt0008.step3.benchmark",
         "vt0008.step4")),
    Requirement(
        "quantification", "s3.14",
        "Emission reductions quantified in accordance with the methodology",
        ("acm0002.baseline", "vmr0017.leakage",
         "vmr0017.emission_reductions")),
    Requirement(
        "monitoring", "s3.15",
        "Monitoring plan and data/parameter tables complete",
        ("vmr0017.embodied_ef",)),
    Requirement(
        "sustainable_development", "s3.16",
        "Sustainable development contributions described",
        author_supplied=True),
    Requirement(
        "stakeholder_engagement", "s3.17",
        "Stakeholder engagement conducted and documented",
        author_supplied=True),
    Requirement(
        "esg_safeguards", "s3.18",
        "ESG risk assessment conducted before the project start date, with "
        "mitigation commensurate with risk levels",
        ("esg.complete", "esg.assessment", "esg.incomplete")),
    Requirement(
        "double_counting", "s3.21",
        "No double counting with other GHG programs", author_supplied=True),
    Requirement(
        "double_claiming_scope3", "s3.22",
        "Double claiming, other forms of credit and Scope 3 emissions "
        "addressed", author_supplied=True),
    Requirement(
        "records", "s3.24",
        "Records and information retained per the Program requirements",
        author_supplied=True),
)


@dataclass
class RequirementResult:
    requirement: Requirement
    status: Status
    evidence: list[Finding] = field(default_factory=list)
    note: str = ""

    @property
    def clause(self) -> str:
        return self.requirement.clause


@dataclass
class ComplianceReport:
    results: list[RequirementResult]

    def _count(self, status: Status) -> int:
        return sum(1 for r in self.results if r.status is status)

    @property
    def failed(self) -> list[RequirementResult]:
        return [r for r in self.results if r.status is Status.FAILED]

    @property
    def needs_input(self) -> list[RequirementResult]:
        return [r for r in self.results if r.status is Status.NEEDS_INPUT]

    @property
    def satisfied(self) -> list[RequirementResult]:
        return [r for r in self.results if r.status is Status.SATISFIED]

    @property
    def ready_for_validation(self) -> bool:
        """No FAILED and nothing outstanding. NOT_APPLICABLE is fine."""
        return not self.failed and not self.needs_input

    @property
    def summary(self) -> dict[str, int]:
        return {s.value: self._count(s) for s in Status}


def _not_applicable_reason(
    requirement: Requirement,
    technology: K.Technology | None,
) -> str | None:
    if requirement.ref == "capacity_limit" and technology is not None:
        rule = K.VMR0017_ELIGIBILITY[technology]
        if rule.max_capacity_mw is None:
            return (f"VMR0017 imposes no capacity limit on "
                    f"{technology.value.replace('_', ' ').lower()}; the "
                    f"fragmentation conditions of s3.5.13 are consequently not "
                    f"met (condition 1 requires a methodology with a limit).")
    return None


def build_compliance_report(
    findings: list[Finding],
    technology: K.Technology | None = None,
) -> ComplianceReport:
    """Map all findings gathered across the modules onto the requirement set."""
    by_check: dict[str, list[Finding]] = {}
    for finding in findings:
        by_check.setdefault(finding.check, []).append(finding)

    results: list[RequirementResult] = []
    for requirement in REGISTRY:
        na_reason = _not_applicable_reason(requirement, technology)
        if na_reason:
            results.append(RequirementResult(
                requirement, Status.NOT_APPLICABLE, note=na_reason))
            continue

        if requirement.author_supplied:
            results.append(RequirementResult(
                requirement, Status.NEEDS_INPUT,
                note="Not evidenced by the system. Requires documentation "
                     "prepared by the project proponent."))
            continue

        evidence: list[Finding] = []
        for check in requirement.evidence_checks:
            evidence.extend(by_check.get(check, []))

        if not evidence:
            results.append(RequirementResult(
                requirement, Status.NEEDS_INPUT,
                note="No evidence produced yet. Run the relevant module or "
                     "supply the missing inputs."))
        elif any(f.severity is Severity.FAIL for f in evidence):
            blocking = next(f for f in evidence if f.severity is Severity.FAIL)
            results.append(RequirementResult(
                requirement, Status.FAILED, evidence, blocking.message))
        elif any(f.severity is Severity.WARNING for f in evidence):
            results.append(RequirementResult(
                requirement, Status.SATISFIED, evidence,
                "Satisfied with open warnings — review before submission."))
        else:
            results.append(RequirementResult(
                requirement, Status.SATISFIED, evidence))

    return ComplianceReport(results=results)


# ---------------------------------------------------------------------------
# Traceability matrix
# ---------------------------------------------------------------------------

def traceability_rows(report: ComplianceReport) -> list[dict[str, str]]:
    """One row per requirement, naming the clause and the evidence source.

    This is the export a VVB asks for: what was claimed, under which clause,
    on the strength of which document.
    """
    rows = []
    for result in report.results:
        sources = sorted({f.source for f in result.evidence})
        rows.append({
            "requirement": result.requirement.ref,
            "clause": result.requirement.clause,
            "title": result.requirement.title,
            "status": result.status.value,
            "evidence_sources": "; ".join(sources),
            "evidence_count": str(len(result.evidence)),
            "note": result.note,
        })
    return rows


def traceability_csv(report: ComplianceReport) -> str:
    import csv
    import io

    rows = traceability_rows(report)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()
