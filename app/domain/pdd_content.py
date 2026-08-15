"""
Module 3a — PDD content model.

Turns the deterministic outputs of Modules 1 and 2 into the field values and
prose blocks that populate a VCS Project Description. No docx handling here and
no LLM: this layer is pure and testable, which is what lets a VVB reproduce
every figure in the finished document.

The prose generated here is a *defensible first draft*, assembled from findings
that already carry clause citations. An LLM pass may later improve readability
via `services/pdd_narrative.py`, but it may never introduce or alter a number —
see the architecture rule in README.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.domain import constants as K
from app.domain.additionality import AdditionalityResult, AdditionalityVerdict
from app.domain.baseline import EmissionReductionResult
from app.domain.classification import Classification, Finding, ProjectIntake, Severity
from app.domain.emission_factors import EmissionFactorResult
from app.domain.monitoring import MonitoringParameters, monitoring_plan_sections
from app.domain.pdd_applicability import not_applicable_sections

DATE_FMT = "%d-%b-%Y"


def fmt_date(d: date) -> str:
    """Verra templates specify DD-MMM-YYYY throughout."""
    return d.strftime(DATE_FMT).upper()


@dataclass
class ProjectIdentity:
    """PDD front-matter that isn't derivable from the calculation engines."""
    verra_project_id: str = ""
    location_description: str = ""
    project_start_date: date | None = None
    proponent_contact: str = ""
    prepared_by: str = ""
    other_entities: str = ""
    ownership_basis: str = ""


@dataclass
class AnnualEstimate:
    year: int
    period_label: str
    baseline_tco2e: float
    project_tco2e: float
    leakage_tco2e: float
    reductions_tco2e: float


@dataclass
class PDDContent:
    template_version: K.TemplateVersion
    fields: dict[str, str]
    sections: dict[str, list[str]]
    annual_estimates: list[AnnualEstimate]
    monitoring: MonitoringParameters | None = None
    findings: list[Finding] = field(default_factory=list)

    @property
    def total_estimated_reductions(self) -> float:
        return sum(a.reductions_tco2e for a in self.annual_estimates)

    @property
    def average_annual_reductions(self) -> float:
        if not self.annual_estimates:
            return 0.0
        return self.total_estimated_reductions / len(self.annual_estimates)

    @property
    def blocked(self) -> bool:
        return any(f.severity is Severity.FAIL for f in self.findings)


# ---------------------------------------------------------------------------
# Field values — the two-column label/value tables in the template
# ---------------------------------------------------------------------------

_TECHNOLOGY_LABEL = {
    K.Technology.WIND_ONSHORE: "onshore wind",
    K.Technology.WIND_OFFSHORE: "offshore wind",
    K.Technology.SOLAR_PV_TERRESTRIAL: "terrestrial solar photovoltaic",
    K.Technology.SOLAR_PV_FLOATING: "floating solar photovoltaic",
    K.Technology.GEOTHERMAL: "geothermal",
    K.Technology.WAVE: "wave",
    K.Technology.TIDAL: "tidal",
    K.Technology.HYDRO: "hydroelectric",
}


def build_fields(
    intake: ProjectIntake,
    classification: Classification,
    identity: ProjectIdentity,
) -> dict[str, str]:
    """Label text as it appears in the template -> value to write."""
    start = intake.initial_crediting_period_start
    return {
        "Project name": intake.name,
        "Project ID": identity.verra_project_id or "To be assigned by Verra",
        "Crediting period start": fmt_date(start),
        "Crediting period end": fmt_date(classification.crediting_period_end),
        "Sectoral scope": f"{classification.sectoral_scope} — Energy "
                          f"(renewable/non-renewable sources)",
        "Project category": classification.project_category,
        "Project activity type": (
            f"Grid-connected electricity generation from renewable sources — "
            f"{_TECHNOLOGY_LABEL[intake.technology]}"),
        "Pipeline listing deadline": fmt_date(classification.pipeline_listing_deadline),
        "Registration request deadline": fmt_date(classification.registration_deadline),
        "Initial crediting period start date": fmt_date(start),
        # Cover-page table label; the standalone "Project Proponent" section
        # further down uses Organization name / Contact person / Address rows.
        "Project proponent name and contact": (
            f"{intake.proponent}"
            + (f" — {identity.proponent_contact}" if identity.proponent_contact else "")),
        "Methodology ID and version": "VMR0017 v1.0",
        "VCS Standard version used for validation": "VCS Standard v5.0",
        "Document version": "1.0",
        "Document completion date": fmt_date(date.today()),
        "Organization name": intake.proponent,
        "Prepared by": identity.prepared_by or intake.proponent,
    }


# ---------------------------------------------------------------------------
# Prose sections
# ---------------------------------------------------------------------------

def _summary(intake: ProjectIntake, classification: Classification,
             er: EmissionReductionResult | None) -> list[str]:
    para = (
        f"{intake.name} is a {intake.installed_capacity_mw:g} MW "
        f"{_TECHNOLOGY_LABEL[intake.technology]} power project located in "
        f"{intake.country_iso2.upper()}, supplying electricity to the national "
        f"grid. The project is expected to generate approximately "
        f"{intake.expected_annual_generation_mwh:,.0f} MWh of electricity "
        f"annually, displacing generation that would otherwise be supplied by "
        f"the grid.")
    method = (
        f"The project applies {classification.methodology} and is classified "
        f"under sectoral scope {classification.sectoral_scope}. The initial "
        f"crediting period runs from "
        f"{fmt_date(intake.initial_crediting_period_start)} to "
        f"{fmt_date(classification.crediting_period_end)} "
        f"({classification.crediting_period_years} years), renewable up to a "
        f"maximum of {classification.max_total_crediting_years} years in "
        f"accordance with {K.CREDITING_PERIOD_SOURCE}.")
    out = [para, method]
    if er is not None:
        out.append(
            f"Estimated emission reductions are "
            f"{er.emission_reductions_tco2e:,.0f} tCO2e per year.")
    return out


def _eligibility(intake: ProjectIntake, classification: Classification) -> list[str]:
    geo = next((f for f in classification.findings
                if f.check == "vmr0017.geography"), None)
    lines = [
        f"Applicability under {classification.methodology} has been assessed "
        f"against the technology, capacity and geography conditions of "
        f"VMR0017 v1.0, Section 4, Table 1."]
    if geo:
        lines.append(f"{geo.message} (Source: {geo.source})")
    cap = next((f for f in classification.findings
                if f.check == "vmr0017.capacity"), None)
    if cap:
        lines.append(f"{cap.message} (Source: {cap.source})")
    else:
        lines.append(
            f"No capacity ceiling applies to "
            f"{_TECHNOLOGY_LABEL[intake.technology]} projects under VMR0017 "
            f"Table 1; the project's installed capacity is "
            f"{intake.installed_capacity_mw:g} MW.")
    return lines


def _baseline_scenario(ef: EmissionFactorResult | None) -> list[str]:
    lines = [
        "The baseline scenario is the continuation of the current situation, "
        "in which the electricity delivered to the grid by the project "
        "activity would otherwise have been generated by the operation of "
        "grid-connected power plants and by the addition of new generation "
        "sources, as reflected in the combined margin emission factor.",
        "The baseline emission factor has been determined in accordance with "
        "VT0011 Electricity System Emission Factors, v1.0, which modifies CDM "
        "TOOL07 for use under the VCS Program.",
    ]
    if ef is not None:
        lines.append(
            f"The operating margin emission factor is "
            f"{ef.ef_grid_om:.4f} tCO2/MWh, determined using the "
            f"{ef.om_method.value.replace('_', ' ').lower()} operating margin "
            f"method. The build margin emission factor is "
            f"{ef.ef_grid_bm:.4f} tCO2/MWh, calculated over a sample of "
            f"{len(ef.bm_sample_unit_ids)} power units selected in accordance "
            f"with VT0011 paragraph 75.")
        lines.append(
            f"The combined margin emission factor is "
            f"{ef.ef_grid_cm:.4f} tCO2/MWh, applying weightings of "
            f"w_OM = {ef.w_om} and w_BM = {ef.w_bm} in accordance with "
            f"{K.CM_WEIGHTS_SOURCE}.")
    return lines


def _additionality(add: AdditionalityResult | None) -> list[str]:
    lines = [
        "Additionality is demonstrated in accordance with VT0008 Additionality "
        "Assessment, v1.0. As required by VMR0017 v1.0 Section 5.3.2, barrier "
        "analysis (VT0008 Step 2) is not applied; the assessment comprises "
        "regulatory surplus, investment analysis, and common practice analysis.",
    ]
    if add is None:
        return lines

    inv = add.investment
    if inv.irr_without_credits is None:
        lines.append(
            "The project generates no positive net cashflow in the absence of "
            "carbon credit revenue and therefore has no defined internal rate "
            "of return. It cannot meet any financial benchmark unaided.")
    else:
        lines.append(
            f"Benchmark analysis has been applied in accordance with VT0008 "
            f"Section 5.4.2, using the project internal rate of return as the "
            f"financial indicator. Without carbon credit revenue the project "
            f"IRR is {inv.irr_without_credits:.2%}, below the required "
            f"benchmark of {inv.benchmark_irr:.2%}. Condition 5.4.2(2)(a) is "
            f"therefore satisfied.")
    if inv.irr_with_credits is not None:
        lines.append(
            f"With carbon credit revenue the project IRR rises to "
            f"{inv.irr_with_credits:.2%}. Credit revenue is applied over the "
            f"crediting period only, consistent with "
            f"{K.CREDITING_PERIOD_SOURCE}.")
    if not inv.meets_ccp_conditions:
        lines.append(
            "Conditions 5.4.2(2)(b) and (c) are not both satisfied. The "
            "project is additional but may not be eligible for Core Carbon "
            "Principles labels, per the note to VT0008 Section 5.4.2.")

    lines.append(
        f"Sensitivity analysis was conducted across variations in capital "
        f"cost, operating cost, tariff and generation. The condition in "
        f"5.4.2(2)(a) "
        f"{'holds' if add.sensitivity_robust else 'does NOT hold'} under all "
        f"variations tested.")

    cp = add.common_practice_result
    lines.append(
        f"Common practice analysis was conducted in accordance with VT0008 "
        f"Section 5.5.2. Of {cp.n_all} similar projects identified in the "
        f"applicable geographic area, {cp.n_diff} exhibit essential "
        f"distinctions, giving F = {cp.f_factor:.1%} and N_all − N_diff = "
        f"{cp.n_all - cp.n_diff}. The project "
        f"{'is' if cp.is_common_practice else 'is not'} considered common "
        f"practice.")
    lines.append(f"Conclusion: the project activity is "
                 f"{add.verdict.value.replace('_', ' ').lower()}.")
    return lines


def _quantification(er: EmissionReductionResult | None,
                    ef: EmissionFactorResult | None,
                    intake: ProjectIntake) -> dict[str, list[str]]:
    if er is None or ef is None:
        return {}
    return {
        "Baseline Emissions": [
            "Baseline emissions are calculated in accordance with ACM0002 "
            "v22.0 as applied by VMR0017 v1.0 Section 8.1:",
            "BE_y = EG_PJ,y × EF_grid,CM,y",
            f"where EG_PJ,y is {intake.expected_annual_generation_mwh:,.0f} MWh "
            f"of net electricity supplied to the grid and EF_grid,CM,y is "
            f"{ef.ef_grid_cm:.4f} tCO2/MWh, giving baseline emissions of "
            f"{er.baseline_emissions_tco2e:,.1f} tCO2e per year.",
        ],
        "Project Emissions": [
            "Project emissions are quantified in accordance with VMR0017 v1.0 "
            "Section 8.2, equation (1).",
            f"Total project emissions are {er.project_emissions_tco2e:,.1f} "
            f"tCO2e per year."
            + (" No fossil fuel combustion, geothermal, reservoir, battery "
               "storage, photovoltaic-specific or fugitive electrical "
               "emission sources are present within the project boundary."
               if er.project_emissions_tco2e == 0 else ""),
        ],
        "Leakage Emissions": [
            "Leakage from embodied emissions is quantified in accordance with "
            "VMR0017 v1.0, equations (19) and (20):",
            "LE_y = EG_facility,y × EF_embodied × 10^-3",
            f"giving leakage emissions of {er.leakage_emissions_tco2e:,.1f} "
            f"tCO2e per year.",
        ],
        "Quantification of Estimated Reductions and Removals": [
            "Emission reductions are calculated in accordance with VMR0017 "
            "v1.0, equation (17):",
            "ER_y = BE_y − PE_y − LE_y",
            f"ER_y = {er.baseline_emissions_tco2e:,.1f} − "
            f"{er.project_emissions_tco2e:,.1f} − "
            f"{er.leakage_emissions_tco2e:,.1f} = "
            f"{er.emission_reductions_tco2e:,.1f} tCO2e per year.",
        ],
    }


def build_sections(
    intake: ProjectIntake,
    classification: Classification,
    ef: EmissionFactorResult | None,
    er: EmissionReductionResult | None,
    add: AdditionalityResult | None,
    monitoring: MonitoringParameters | None = None,
) -> dict[str, list[str]]:
    """Template heading text -> replacement paragraphs."""
    sections: dict[str, list[str]] = {
        "Summary Description of the Project": _summary(intake, classification, er),
        "Applicability of Methodology": _eligibility(intake, classification),
        "Baseline Scenario": _baseline_scenario(ef),
        "Additionality Methods": _additionality(add),
        "Methodology Details": [
            f"Title: {classification.methodology}",
            "Reference: VMR0017 Grid-Connected Electricity Generation from "
            "Renewable Sources (ACM0002 Revision), v1.0",
            "Version: 1.0",
        ],
        "Project Crediting Period": [
            f"Initial crediting period: "
            f"{fmt_date(intake.initial_crediting_period_start)} to "
            f"{fmt_date(classification.crediting_period_end)} "
            f"({classification.crediting_period_years} years), renewable up to "
            f"{K.EI_MAX_RENEWALS} times for a maximum total of "
            f"{classification.max_total_crediting_years} years, in accordance "
            f"with {K.CREDITING_PERIOD_SOURCE}.",
        ],
    }

    if add is not None:
        rs = next((f for f in add.findings
                   if f.check == "vcs.regulatory_surplus"), None)
        sections["Regulatory Surplus"] = [
            rs.message if rs else
            "The project activity is not mandated by any law, statute or other "
            "regulatory framework that is systematically enforced in the host "
            "country. Regulatory surplus is therefore demonstrated."
        ]

    if monitoring is not None:
        sections.update(monitoring_plan_sections(
            intake.technology,
            has_bess=any(p.name == "Me,released,y" for p in monitoring.monitored)))

    # Not-applicable sections are merged LAST but must never overwrite drafted
    # content, so anything already present wins.
    na_sections, _ = not_applicable_sections(intake, classification)
    for heading, paragraphs in na_sections.items():
        sections.setdefault(heading, paragraphs)

    sections.update(_quantification(er, ef, intake))
    return sections


def build_annual_estimates(
    classification: Classification,
    er: EmissionReductionResult | None,
) -> list[AnnualEstimate]:
    """One row per year of the initial crediting period.

    Held flat across years: a year-varying grid emission factor requires
    annually updated OM/BM data (VT0011 para 72 Option 2), which the engine
    does not yet ingest. Flat is the conservative, defensible default and the
    caller is warned.
    """
    if er is None:
        return []

    start_year = classification.crediting_period_end.year - classification.crediting_period_years
    return [
        AnnualEstimate(
            year=start_year + i + 1,
            period_label=f"Year {i + 1}",
            baseline_tco2e=er.baseline_emissions_tco2e,
            project_tco2e=er.project_emissions_tco2e,
            leakage_tco2e=er.leakage_emissions_tco2e,
            reductions_tco2e=er.emission_reductions_tco2e,
        )
        for i in range(classification.crediting_period_years)
    ]


def build_pdd_content(
    intake: ProjectIntake,
    classification: Classification,
    identity: ProjectIdentity | None = None,
    ef: EmissionFactorResult | None = None,
    er: EmissionReductionResult | None = None,
    add: AdditionalityResult | None = None,
    monitoring: MonitoringParameters | None = None,
    narrator=None,
    retriever=None,
) -> PDDContent:
    identity = identity or ProjectIdentity()
    findings: list[Finding] = []

    if classification.blocked:
        findings.append(Finding(
            "pdd.classification", Severity.FAIL,
            "Project classification is blocked; a PDD must not be generated "
            "until the blocking findings are resolved.",
            "Module 1"))

    if ef is None:
        findings.append(Finding(
            "pdd.emission_factors", Severity.FAIL,
            "No grid emission factor supplied. Sections on the baseline "
            "scenario and quantification cannot be completed.", "VT0011 v1.0"))
    if er is None:
        findings.append(Finding(
            "pdd.quantification", Severity.FAIL,
            "No emission reduction estimate supplied. Section 4 "
            "(Quantification) cannot be completed.", "VMR0017 v1.0 s8"))
    if add is None:
        findings.append(Finding(
            "pdd.additionality", Severity.FAIL,
            "No additionality assessment supplied. Section 3.6 cannot be "
            "completed.", "VT0008 v1.0"))
    elif add.verdict is not AdditionalityVerdict.ADDITIONAL:
        findings.append(Finding(
            "pdd.additionality", Severity.FAIL,
            f"Additionality verdict is {add.verdict.value}. A PDD asserting "
            f"additionality must not be issued on this basis.", "VT0008 v1.0"))

    if monitoring is None:
        findings.append(Finding(
            "pdd.monitoring", Severity.FAIL,
            "No monitoring parameters supplied. The Monitoring section and "
            "Appendix 2 (Data and Parameters) cannot be completed.",
            "VMR0017 v1.0 s9"))
    else:
        findings.extend(monitoring.findings)

    if er is not None:
        findings.append(Finding(
            "pdd.annual_estimates", Severity.WARNING,
            "Annual estimates are held constant across the crediting period. "
            "VT0011 para 72 Option 2 requires the build margin to be updated "
            "annually; supply per-year factors before submission.",
            "VT0011 v1.0 para 72"))

    _, na_findings = not_applicable_sections(intake, classification)
    findings.extend(na_findings)

    sections = build_sections(intake, classification, ef, er, add, monitoring)

    # Optional narrative pass. Without a narrator this is a no-op and the
    # deterministic prose above is what the report contains — which is the
    # current behaviour, byte for byte. With one, each section is redrafted in
    # the firm's register while its figures are still inserted from the engine,
    # and any section the model fails to produce falls back to the text it
    # would have had anyway.
    if narrator is not None:
        from app.generation.bridge import (
            SECTION_CLAUSES,
            SECTION_PLACEHOLDERS,
            briefs_from_sections,
            build_value_bundle,
        )
        from app.generation.narrative import generate_report

        bundle = build_value_bundle(intake, classification, ef, er, add)
        briefs = briefs_from_sections(
            sections, bundle, SECTION_PLACEHOLDERS, SECTION_CLAUSES)
        generated = generate_report(briefs, bundle, narrator, retriever)

        for section in generated.sections:
            if section.text:
                sections[section.heading] = section.text.split("\n\n")

        for warning in generated.warnings:
            findings.append(Finding(
                "pdd.narrative", Severity.WARNING, warning, "Phase 6"))

    return PDDContent(
        template_version=classification.template_version,
        fields=build_fields(intake, classification, identity),
        sections=sections,
        annual_estimates=build_annual_estimates(classification, er),
        monitoring=monitoring,
        findings=findings,
    )
