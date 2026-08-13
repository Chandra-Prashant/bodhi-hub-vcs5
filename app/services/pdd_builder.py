"""
Module 3c — PDD builder orchestration.

Selects the correct template for the project's crediting period start date,
fills it, and reports what remains unwritten.

Template routing is the point most easily got wrong: VCS v5.0A applies to
projects whose initial crediting period starts before 1 January 2027, and
v5.0B on or after. The choice comes from Module 1's classification rather than
from a caller-supplied argument, so the two cannot drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from docx import Document

from app.domain import constants as K
from app.domain.classification import Finding, Severity
from app.domain.pdd_content import PDDContent
from app.services import docx_filler

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"

PD_TEMPLATES: dict[K.TemplateVersion, str] = {
    K.TemplateVersion.A: "VCS-Project-Description-Template-v5.0A.docx",
    K.TemplateVersion.B: "VCS-Project-Description-Template-v5.0B.docx",
}


@dataclass
class PDDBuildResult:
    output_path: Path
    template_used: str
    report: docx_filler.FillReport
    findings: list[Finding]

    @property
    def blocked(self) -> bool:
        return any(f.severity is Severity.FAIL for f in self.findings)

    @property
    def sections_needing_input(self) -> list[tuple[str, int]]:
        return sorted(self.report.instructions_remaining.items(),
                      key=lambda kv: -kv[1])


def template_path(version: K.TemplateVersion) -> Path:
    path = TEMPLATE_DIR / PD_TEMPLATES[version]
    if not path.exists():
        raise FileNotFoundError(
            f"Template {path.name} not found in {TEMPLATE_DIR}. The official "
            f"Verra templates must be present; do not substitute a copy edited "
            f"by hand.")
    return path


def build_pdd(
    content: PDDContent,
    output_path: Path,
    strip_guidance: bool = False,
) -> PDDBuildResult:
    """Render a Project Description from prepared content.

    strip_guidance removes all remaining Verra guidance text. Leave it False
    for working drafts: the guidance is what tells the author what is still
    missing, and the completion report is derived from it.
    """
    findings = list(content.findings)
    source = template_path(content.template_version)
    doc = Document(str(source))

    fields_written, fields_missing = docx_filler.fill_fields(doc, content.fields)
    sections_written, sections_missing = docx_filler.fill_sections(
        doc, content.sections)

    if content.monitoring is not None:
        counts = docx_filler.fill_parameter_tables(
            doc, content.monitoring.at_validation, content.monitoring.monitored)
        if counts["at_validation"] == 0 or counts["monitored"] == 0:
            findings.append(Finding(
                "pdd.parameter_tables", Severity.WARNING,
                f"Appendix 2 rendering incomplete: "
                f"{counts['at_validation']} at-validation and "
                f"{counts['monitored']} monitored parameter tables written. "
                f"Check the template's Data/Parameter table layout.",
                source.name))

    if content.annual_estimates:
        if not docx_filler.fill_estimates_table(doc, content.annual_estimates):
            findings.append(Finding(
                "pdd.estimates_table", Severity.WARNING,
                "Could not locate the estimated reductions summary table in "
                "the template; the yearly figures must be entered by hand.",
                source.name))

    for label in fields_missing:
        findings.append(Finding(
            "pdd.field_not_found", Severity.WARNING,
            f"Field '{label}' was not found in {source.name}. The template may "
            f"have been revised — check the label text.", source.name))

    for heading in sections_missing:
        findings.append(Finding(
            "pdd.section_not_found", Severity.WARNING,
            f"Section '{heading}' was not found in {source.name}.", source.name))

    if strip_guidance:
        docx_filler.strip_instructions(doc)
        remaining: dict[str, int] = {}
    else:
        remaining = docx_filler.remaining_instructions(doc)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output_path))

    report = docx_filler.FillReport(
        fields_written=fields_written,
        fields_not_found=fields_missing,
        sections_written=sections_written,
        sections_not_found=sections_missing,
        instructions_remaining=remaining,
    )

    total_remaining = sum(remaining.values())
    if total_remaining:
        findings.append(Finding(
            "pdd.completion", Severity.WARNING,
            f"{total_remaining} guidance blocks across {len(remaining)} "
            f"sections still require author input. The document is a working "
            f"draft, not a submission.", source.name))

    return PDDBuildResult(
        output_path=output_path,
        template_used=source.name,
        report=report,
        findings=findings,
    )
