"""
Module 3d — not-applicable sections.

The Verra Project Description template covers every project category. An E&I
solar or wind project leaves a substantial block of AFOLU-specific sections
with nothing to say — and leaving them blank is itself a validation finding.
Verra expects an explicit statement of non-applicability with a justification.

Two rules govern what may be auto-filled here:

  1. Only sections that are inapplicable **as a matter of the standard**, with
     a citable clause. Never a section whose applicability depends on facts the
     engine does not hold.
  2. Never a safeguards or stakeholder section. Whether free, prior and
     informed consent applies, whether Indigenous Peoples' rights are engaged,
     whether an ecosystem is being converted — these depend on the site, and a
     validator scrutinises them hardest. An auto-generated "not applicable"
     there would be a liability, not a convenience.

Sections deliberately left for the author, because applicability is
site-specific or proponent-specific: Grouped Project Design, all Other GHG
Program sections, all Safeguards and Stakeholder Engagement sections, Ecosystem
Health, Methodology Deviations, Sensitive Information.
"""

from __future__ import annotations

from app.domain import constants as K
from app.domain.classification import Classification, Finding, ProjectIntake, Severity

VCS5 = "VCS Standard v5.0"


def not_applicable_sections(
    intake: ProjectIntake,
    classification: Classification,
) -> tuple[dict[str, list[str]], list[Finding]]:
    """Return heading -> justification paragraphs, plus findings explaining
    what was auto-completed and what was deliberately left alone."""
    sections: dict[str, list[str]] = {}
    findings: list[Finding] = []

    is_ei = classification.project_category == K.PROJECT_CATEGORY_EI
    if not is_ei:
        findings.append(Finding(
            "pdd.not_applicable", Severity.WARNING,
            f"Project category is {classification.project_category}; the "
            f"not-applicable pass covers E&I projects only. All sections left "
            f"for the author.", VCS5))
        return sections, findings

    # --- AFOLU-specific sections ------------------------------------------
    afolu_note = (
        f"Not applicable. The project is an Energy and Industry (E&I) project "
        f"under sectoral scope {classification.sectoral_scope}, generating "
        f"emission reductions through the displacement of grid electricity. It "
        f"is not an agriculture, forestry, or other land use (AFOLU) project "
        f"activity.")

    sections["AFOLU Project Eligibility"] = [afolu_note]

    # VCS Standard v5.0 s3.2.8 is explicit and technology-independent for
    # fossil-derived CO2 displacement, which is what grid renewables produce.
    sections["Non-Permanence Risk Analysis"] = [
        "Not applicable. Under VCS Standard v5.0, Section 3.2.8, "
        "non-permanence risk analysis applies only to reductions and removals "
        "generated through carbon sinks. The project generates reductions in "
        "fossil fuel-derived CO2 by displacing grid electricity and is "
        "therefore not subject to non-permanence risk analysis.",
    ]
    sections["Buffer Pool Allocation Calculation"] = [
        "Not applicable. No buffer credits are required, as the project is not "
        "subject to non-permanence risk analysis under VCS Standard v5.0, "
        "Section 3.2.8.",
    ]
    sections["Long-Term Average"] = [
        "Not applicable. The long-term average applies to AFOLU project "
        "activities. The project is an E&I project activity.",
    ]

    findings.append(Finding(
        "pdd.not_applicable.afolu", Severity.PASS,
        "AFOLU eligibility, non-permanence risk, buffer pool allocation and "
        "long-term average marked not applicable for this E&I project.",
        f"{VCS5} s3.2.8"))

    # --- Capacity limit: technology-dependent -----------------------------
    rule = K.VMR0017_ELIGIBILITY[intake.technology]
    if rule.max_capacity_mw is None:
        sections["Capacity Limit Eligibility"] = [
            f"Not applicable. VMR0017 v1.0 imposes no capacity limit on "
            f"{intake.technology.value.replace('_', ' ').lower()} project "
            f"activities (VMR0017 v1.0, Section 4, Table 1). As the applied "
            f"methodology has no capacity limit, the project fragmentation "
            f"conditions of VCS Standard v5.0, Section 3.5.13 are not met, "
            f"since condition (1) requires a methodology with a capacity limit.",
        ]
        findings.append(Finding(
            "pdd.not_applicable.capacity_limit", Severity.PASS,
            f"No capacity limit applies to {intake.technology.value} under "
            f"VMR0017; capacity limit eligibility marked not applicable.",
            f"{VCS5} s3.5.12-3.5.13"))
    else:
        findings.append(Finding(
            "pdd.not_applicable.capacity_limit", Severity.WARNING,
            f"VMR0017 imposes a {rule.max_capacity_mw:g} MW capacity limit on "
            f"{intake.technology.value}. Capacity Limit Eligibility must be "
            f"completed by the author, including the fragmentation assessment "
            f"under VCS Standard v5.0 Section 3.5.13.", f"{VCS5} s3.5.13"))

    findings.append(Finding(
        "pdd.not_applicable.scope", Severity.WARNING,
        "Safeguards, stakeholder engagement, ecosystem health, grouped project "
        "design and other-GHG-programme sections are NOT auto-completed. Their "
        "applicability is site- and proponent-specific and must be assessed by "
        "the author.", VCS5))

    return sections, findings
