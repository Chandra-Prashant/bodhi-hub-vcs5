"""
Module 6b — Monitoring Report rendering.

Reuses the same machinery as the Project Description builder: label/value
tables matched by text, guidance paragraphs styled `Instruction` replaced by
drafted prose, Appendix 2 Data/Parameter tables cloned per parameter, and
whatever guidance remains counted as the author's to-do list.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from docx import Document

from app.domain import constants as K
from app.domain.classification import Classification, Finding, Severity
from app.domain.monitoring import MonitoringParameters
from app.domain.monitoring_report import (
    MonitoringReportResult,
    monitoring_report_sections,
)
from app.domain.pdd_content import fmt_date
from app.services import docx_filler
from app.services.pdd_builder import monitoring_report_template_path


@dataclass
class MonitoringReportBuildResult:
    output_path: Path
    template_used: str
    report: docx_filler.FillReport
    findings: list[Finding] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return any(f.severity is Severity.FAIL for f in self.findings)

    @property
    def sections_needing_input(self) -> list[tuple[str, int]]:
        return sorted(self.report.instructions_remaining.items(),
                      key=lambda kv: -kv[1])


def build_monitoring_report_fields(
    result: MonitoringReportResult,
    project_name: str,
    proponent: str,
    classification: Classification,
    verra_project_id: str = "",
    prepared_by: str = "",
    document_version: str = "1.0",
) -> dict[str, str]:
    return {
        "Project name": project_name,
        "Project ID": verra_project_id or "To be assigned by Verra",
        "Monitoring period start": fmt_date(result.period.start),
        "Monitoring period end": fmt_date(result.period.end),
        "Document completion date": fmt_date(date.today()),
        "Document version": document_version,
        "VCS Standard version used for verification": "VCS Standard v5.0",
        "Methodology ID and version": "VMR0017 v1.0",
        "Project proponent name and contact": proponent,
        "Prepared by": prepared_by or proponent,
        "Sectoral scope": f"{classification.sectoral_scope} — Energy "
                          f"(renewable/non-renewable sources)",
        "Project category": classification.project_category,
        "Organization name": proponent,
    }


def build_monitoring_report(
    result: MonitoringReportResult,
    classification: Classification,
    project_name: str,
    proponent: str,
    output_path: Path,
    monitoring: MonitoringParameters | None = None,
    verra_project_id: str = "",
    prepared_by: str = "",
    document_version: str = "1.0",
    strip_guidance: bool = False,
) -> MonitoringReportBuildResult:
    findings = list(result.findings)

    if result.blocked:
        findings.append(Finding(
            "mr.build", Severity.FAIL,
            "Monitoring period has unresolved blocking findings. A monitoring "
            "report claiming these reductions must not be issued until they "
            "are cleared.", "Module 6"))

    source = monitoring_report_template_path(classification.template_version)
    doc = Document(str(source))

    fields = build_monitoring_report_fields(
        result, project_name, proponent, classification,
        verra_project_id, prepared_by, document_version)
    fields_written, fields_missing = docx_filler.fill_fields(doc, fields)

    sections = monitoring_report_sections(result)
    sections_written, sections_missing = docx_filler.fill_sections(doc, sections)

    if monitoring is not None:
        counts = docx_filler.fill_parameter_tables(
            doc, monitoring.at_validation, monitoring.monitored)
        if counts["monitored"] == 0:
            findings.append(Finding(
                "mr.parameter_tables", Severity.WARNING,
                "Appendix 2 monitored-parameter tables were not rendered; "
                "check the template's Data/Parameter table layout.",
                source.name))

    for label in fields_missing:
        findings.append(Finding(
            "mr.field_not_found", Severity.WARNING,
            f"Field '{label}' was not found in {source.name}.", source.name))
    for heading in sections_missing:
        findings.append(Finding(
            "mr.section_not_found", Severity.WARNING,
            f"Section '{heading}' was not found in {source.name}.",
            source.name))

    if strip_guidance:
        docx_filler.strip_instructions(doc)
        remaining: dict[str, int] = {}
    else:
        remaining = docx_filler.remaining_instructions(doc)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output_path))

    total_remaining = sum(remaining.values())
    if total_remaining:
        findings.append(Finding(
            "mr.completion", Severity.WARNING,
            f"{total_remaining} guidance blocks across {len(remaining)} "
            f"sections still require author input. This is a working draft, "
            f"not a submission.", source.name))

    return MonitoringReportBuildResult(
        output_path=output_path,
        template_used=source.name,
        report=docx_filler.FillReport(
            fields_written=fields_written,
            fields_not_found=fields_missing,
            sections_written=sections_written,
            sections_not_found=sections_missing,
            instructions_remaining=remaining,
        ),
        findings=findings,
    )
