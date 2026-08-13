"""
Module 8 — Regulatory updates tracking.

The naive reading of this requirement is "scrape Verra's website for new
document versions". That is the wrong shape. Verra publishes irregularly, the
site layout changes, and a scraper that silently stops working is worse than no
scraper — it converts an absent alert into a false assurance that nothing has
changed.

What actually causes damage when a regulation is revised is not failing to
notice the revision. It is not knowing what the revision touches. When VT0011
v1.1 lands, the question a project manager needs answered in thirty seconds is:
which of our constants, which functions, which registered projects?

So this module holds a dependency map: every regulatory document in use, the
version relied upon, the code that implements it, and a content hash of the
local copy. It answers three questions:

    * has a document we depend on been swapped or edited underneath us?
    * we are told version X.Y exists — what do we re-verify?
    * which documents do we depend on but not hold a copy of?

The third is how TOOL07 surfaces. VT0011 replaces specific paragraphs of it but
the core equations live there, the document is not in the regulations pack, and
the implementation is consequently marked UNVERIFIED. A tracking module that
did not report that would be decorative.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from app.domain.classification import Finding, Severity

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"


@dataclass(frozen=True)
class Dependency:
    """A place in the codebase that implements part of a regulatory document."""
    module: str
    symbol: str
    description: str


@dataclass(frozen=True)
class RegulatoryDocument:
    doc_id: str
    title: str
    version: str
    dependencies: tuple[Dependency, ...]
    filename: str | None = None       # vendored under app/templates/
    effective_date: date | None = None
    verified: bool = True             # False = implemented without the source
    notes: str = ""


REGISTRY: tuple[RegulatoryDocument, ...] = (
    RegulatoryDocument(
        doc_id="VCS-STANDARD", title="VCS Standard", version="v5.0",
        dependencies=(
            Dependency("domain.constants", "EI_CREDITING_PERIOD_YEARS",
                       "E&I crediting period, 5 years (Table 8)"),
            Dependency("domain.constants", "EI_MAX_RENEWALS",
                       "Renewals permitted, 2 (Table 8)"),
            Dependency("domain.constants", "EI_MAX_TOTAL_CREDITING_YEARS",
                       "Maximum total crediting years, 15 (Table 8)"),
            Dependency("domain.constants", "EI_REGISTRATION_DEADLINE_YEARS",
                       "Registration deadline, 2 years (s3.8.2, Table 7)"),
            Dependency("domain.constants", "PIPELINE_LISTING_DEADLINE_YEARS",
                       "Pipeline listing deadline, 1 year (s3.8.2)"),
            Dependency("domain.compliance", "REGISTRY",
                       "The requirement register itself (s3.1-s3.24)"),
            Dependency("domain.esg", "CATEGORY_TITLES",
                       "Twelve safeguard categories (s3.18.4-3.18.38)"),
            Dependency("domain.pdd_applicability", "not_applicable_sections",
                       "Non-permanence exemption for fossil CO2 (s3.2.8) and "
                       "capacity-limit fragmentation (s3.5.13)"),
        )),
    RegulatoryDocument(
        doc_id="VMR0017",
        title="Grid-Connected Electricity Generation from Renewable Sources "
              "(ACM0002 Revision)",
        version="v1.0",
        dependencies=(
            Dependency("domain.constants", "VMR0017_ELIGIBILITY",
                       "Technology, capacity and geography table (s4, Table 1)"),
            Dependency("domain.constants",
                       "BARRIER_ANALYSIS_ALLOWED_UNDER_VMR0017",
                       "Barrier analysis excluded (s5.3.2)"),
            Dependency("domain.monitoring", "EMBODIED_EF_G_CO2E_PER_KWH",
                       "Mandated embodied emission factors (s9.1)"),
            Dependency("domain.monitoring", "RESERVOIR_EF_KG_CO2E_PER_MWH",
                       "Reservoir emission factor, 100 kg CO2e/MWh (s9.1)"),
            Dependency("domain.monitoring", "_monitored",
                       "Monitored parameter tables (s9.2)"),
            Dependency("domain.baseline", "leakage_emissions",
                       "Embodied-emissions leakage, equations 19 and 20"),
            Dependency("domain.baseline", "emission_reductions",
                       "ER_y = BE_y - PE_y - LE_y, equation 17"),
        )),
    RegulatoryDocument(
        doc_id="ACM0002", title="CDM ACM0002", version="v22.0",
        dependencies=(
            Dependency("domain.baseline", "baseline_emissions",
                       "BE_y = EG_PJ,y x EF_grid,CM,y"),
        )),
    RegulatoryDocument(
        doc_id="VT0008", title="Additionality Assessment", version="v1.0",
        dependencies=(
            Dependency("domain.constants", "COMMON_PRACTICE_F_THRESHOLD",
                       "Common practice F > 20% (s5.5.2)"),
            Dependency("domain.constants",
                       "COMMON_PRACTICE_MIN_SIMILAR_PROJECTS",
                       "N_all - N_diff > 3 (s5.5.2, footnote 17)"),
            Dependency("domain.additionality", "benchmark_analysis",
                       "Investment analysis conditions (s5.4.2)"),
            Dependency("domain.additionality", "sensitivity_analysis",
                       "Sensitivity requirement (s5.4.2(3))"),
        )),
    RegulatoryDocument(
        doc_id="VT0011", title="Electricity System Emission Factors",
        version="v1.0",
        dependencies=(
            Dependency("domain.constants", "WIND_SOLAR_CM_WEIGHTS",
                       "Combined margin weights by crediting period (para 86)"),
            Dependency("domain.constants", "LDC_CM_WEIGHTS_OPTION",
                       "LDC weighting election (para 90)"),
            Dependency("domain.constants", "DEFAULT_BM_EF_TCO2_PER_MWH",
                       "Default build margin factor (para 91)"),
            Dependency("domain.emission_factors", "select_bm_sample",
                       "Build margin sample selection (para 75)"),
            Dependency("domain.emission_factors", "unit_emission_factor",
                       "Per-unit emission factor options (para 50)"),
        )),
    RegulatoryDocument(
        doc_id="TOOL07",
        title="Tool to calculate the emission factor for an electricity system",
        version="unknown",
        verified=False,
        notes="VT0011 is a delta on this document, replacing paragraphs 25, "
              "26, 39, 45, 50, 72, 75, 79 and 86. The core OM/BM/CM equations "
              "live here and are NOT in the regulations pack. The "
              "implementation follows the standard TOOL07 formulation and is "
              "marked UNVERIFIED in source.",
        dependencies=(
            Dependency("domain.emission_factors", "simple_om",
                       "Simple operating margin"),
            Dependency("domain.emission_factors", "average_om",
                       "Average operating margin"),
            Dependency("domain.emission_factors", "build_margin",
                       "Build margin"),
            Dependency("domain.emission_factors",
                       "check_simple_om_applicability",
                       "Low-cost/must-run 50% gate (para 40)"),
        )),
    RegulatoryDocument(
        doc_id="PD-TEMPLATE-A", title="VCS Project Description Template",
        version="v5.0A",
        filename="VCS-Project-Description-Template-v5.0A.docx",
        dependencies=(
            Dependency("services.pdd_builder", "PD_TEMPLATES",
                       "Template selection before 1 Jan 2027"),
            Dependency("domain.pdd_content", "build_fields",
                       "Cover-page field labels"),
            Dependency("domain.pdd_content", "build_sections",
                       "Section heading text"),
        )),
    RegulatoryDocument(
        doc_id="PD-TEMPLATE-B", title="VCS Project Description Template",
        version="v5.0B",
        filename="VCS-Project-Description-Template-v5.0B.docx",
        dependencies=(
            Dependency("services.pdd_builder", "PD_TEMPLATES",
                       "Template selection on or after 1 Jan 2027"),
        )),
    RegulatoryDocument(
        doc_id="MR-TEMPLATE-A", title="VCS Monitoring Report Template",
        version="V5.0A",
        filename="VCS-Monitoring-Report-Template-V5.0A.docx",
        dependencies=(
            Dependency("services.pdd_builder", "MR_TEMPLATES",
                       "Monitoring report template selection"),
            Dependency("services.monitoring_report_builder",
                       "build_monitoring_report_fields",
                       "Cover-page field labels"),
        )),
    RegulatoryDocument(
        doc_id="MR-TEMPLATE-B", title="VCS Monitoring Report Template",
        version="V5.0B",
        filename="VCS-Monitoring-Report-Template-V5.0B.docx",
        dependencies=(
            Dependency("services.pdd_builder", "MR_TEMPLATES",
                       "Monitoring report template selection"),
        )),
    RegulatoryDocument(
        doc_id="ESG-TEMPLATE", title="VCS ESG Risk Assessment Template",
        version="v5.0",
        filename="VCS-ESG-Risk-Assessment-Template-v5.0.docx",
        dependencies=(
            Dependency("domain.esg", "RISK_MATRIX",
                       "5x5 severity and likelihood matrix"),
            Dependency("domain.esg", "SEVERITY_LABELS",
                       "Severity scale labels"),
            Dependency("domain.esg", "LIKELIHOOD_LABELS",
                       "Likelihood scale labels"),
        )),
)


def _document(doc_id: str) -> RegulatoryDocument:
    for doc in REGISTRY:
        if doc.doc_id == doc_id:
            return doc
    raise KeyError(f"Unknown regulatory document: {doc_id}")


def content_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def document_hashes(template_dir: Path | None = None) -> dict[str, str]:
    """Hash every vendored document. Record the output; a later mismatch means
    a file was replaced or edited without the dependent code being revisited."""
    directory = template_dir or TEMPLATE_DIR
    hashes: dict[str, str] = {}
    for doc in REGISTRY:
        if not doc.filename:
            continue
        path = directory / doc.filename
        if path.exists():
            hashes[doc.doc_id] = content_hash(path)
    return hashes


def check_integrity(
    baseline_hashes: dict[str, str],
    template_dir: Path | None = None,
) -> list[Finding]:
    """Compare vendored documents against a previously recorded set of hashes."""
    directory = template_dir or TEMPLATE_DIR
    findings: list[Finding] = []
    current = document_hashes(directory)

    for doc_id, expected in baseline_hashes.items():
        actual = current.get(doc_id)
        doc = _document(doc_id)
        if actual is None:
            findings.append(Finding(
                "regulatory.document_missing", Severity.FAIL,
                f"{doc.title} {doc.version} is recorded but no longer present "
                f"in the templates directory.", doc.doc_id))
        elif actual != expected:
            affected = ", ".join(
                f"{d.module}.{d.symbol}" for d in doc.dependencies)
            findings.append(Finding(
                "regulatory.document_changed", Severity.FAIL,
                f"{doc.title} {doc.version} has changed on disk. Re-verify: "
                f"{affected}.", doc.doc_id))

    for doc_id in current:
        if doc_id not in baseline_hashes:
            doc = _document(doc_id)
            findings.append(Finding(
                "regulatory.document_new", Severity.WARNING,
                f"{doc.title} {doc.version} is present but was not in the "
                f"recorded baseline. Record its hash.", doc.doc_id))

    if not findings:
        findings.append(Finding(
            "regulatory.integrity", Severity.PASS,
            f"All {len(current)} vendored regulatory documents match their "
            f"recorded hashes.", "Module 8"))
    return findings


def check_registry(template_dir: Path | None = None) -> list[Finding]:
    """Report unverified dependencies and documents we rely on but do not hold."""
    directory = template_dir or TEMPLATE_DIR
    findings: list[Finding] = []

    for doc in REGISTRY:
        if not doc.verified:
            affected = ", ".join(
                f"{d.module}.{d.symbol}" for d in doc.dependencies)
            findings.append(Finding(
                "regulatory.unverified", Severity.FAIL,
                f"{doc.title} is relied upon but has not been verified against "
                f"the source document. Affected: {affected}. {doc.notes}",
                doc.doc_id))
            continue

        if doc.filename and not (directory / doc.filename).exists():
            findings.append(Finding(
                "regulatory.not_vendored", Severity.WARNING,
                f"{doc.title} {doc.version} is referenced but the file "
                f"{doc.filename} is not present.", doc.doc_id))

        if doc.effective_date is None:
            findings.append(Finding(
                "regulatory.no_effective_date", Severity.WARNING,
                f"No effective date recorded for {doc.title} {doc.version}. "
                f"Record it so version currency can be checked against a "
                f"project's crediting period start date.", doc.doc_id))

    verified = sum(1 for d in REGISTRY if d.verified)
    findings.append(Finding(
        "regulatory.coverage", Severity.PASS,
        f"{verified} of {len(REGISTRY)} regulatory documents verified, "
        f"covering {sum(len(d.dependencies) for d in REGISTRY)} code "
        f"dependencies.", "Module 8"))
    return findings


@dataclass
class UpdateImpact:
    document: RegulatoryDocument
    announced_version: str
    dependencies: list[Dependency] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)

    @property
    def is_newer(self) -> bool:
        return self.announced_version != self.document.version

    def as_checklist(self) -> list[str]:
        return [f"{d.module}.{d.symbol} — {d.description}"
                for d in self.dependencies]


def assess_update(doc_id: str, announced_version: str) -> UpdateImpact:
    """Given word that a new version exists, list what must be re-verified."""
    doc = _document(doc_id)
    findings: list[Finding] = []

    if announced_version == doc.version:
        findings.append(Finding(
            "regulatory.up_to_date", Severity.PASS,
            f"{doc.title} {doc.version} is the version in use.", doc.doc_id))
        return UpdateImpact(doc, announced_version, [], findings)

    findings.append(Finding(
        "regulatory.update_available", Severity.WARNING,
        f"{doc.title} {announced_version} supersedes the {doc.version} this "
        f"system implements. {len(doc.dependencies)} code dependencies require "
        f"re-verification before the new version is applied to any project.",
        doc.doc_id))

    for dependency in doc.dependencies:
        findings.append(Finding(
            "regulatory.reverify", Severity.WARNING,
            f"Re-verify {dependency.module}.{dependency.symbol}: "
            f"{dependency.description}.", doc.doc_id))

    return UpdateImpact(doc, announced_version, list(doc.dependencies), findings)


def dependency_index() -> dict[str, list[str]]:
    """Inverse map: code symbol -> the documents that govern it.

    Useful in review — before changing a constant, check what it answers to.
    """
    index: dict[str, list[str]] = {}
    for doc in REGISTRY:
        for dependency in doc.dependencies:
            key = f"{dependency.module}.{dependency.symbol}"
            index.setdefault(key, []).append(f"{doc.doc_id} {doc.version}")
    return index
