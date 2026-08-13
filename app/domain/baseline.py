"""
Module 2b — Baseline emissions and emission reductions.

VMR0017 v1.0 s8.1 makes no change to ACM0002 for baseline emissions:

    BE_y = EG_PJ,y * EF_grid,CM,y

VMR0017 v1.0 s8.2 (replacing ACM0002 para 40) — for most renewable generation
PE_y = 0, but where material:

    PE_y = PE_FF,y + PE_GP,y + PE_HP,y + PE_BESS,y + PE_PV,y + PE_FEC,y   (1)

VMR0017 v1.0 equations (19)/(20) — leakage from annualised embodied emissions:

    LE_y = LE_embodied = EG_facility,y * EF_embodied * 10^-3

Emission reductions, VMR0017 equation (17):

    ER_y = BE_y - PE_y - LE_y
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.classification import Finding, Severity

VMR0017 = "VMR0017 v1.0"
ACM0002 = "CDM ACM0002 v22.0 (via VMR0017 v1.0 s8.1)"


@dataclass
class ProjectEmissions:
    """VMR0017 equation (1). Zero for a typical solar or wind project; a
    BESS-equipped or geothermal project will have non-zero components."""
    fossil_fuel_combustion: float = 0.0   # PE_FF,y
    geothermal: float = 0.0               # PE_GP,y
    hydro_reservoir: float = 0.0          # PE_HP,y
    bess: float = 0.0                     # PE_BESS,y — incl. fire suppression
    pv_specific: float = 0.0              # PE_PV,y
    fugitive_electrical: float = 0.0      # PE_FEC,y — e.g. SF6 from switchgear

    @property
    def total(self) -> float:
        return (self.fossil_fuel_combustion + self.geothermal
                + self.hydro_reservoir + self.bess + self.pv_specific
                + self.fugitive_electrical)


@dataclass
class EmissionReductionResult:
    baseline_emissions_tco2e: float
    project_emissions_tco2e: float
    leakage_emissions_tco2e: float
    emission_reductions_tco2e: float
    findings: list[Finding] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return any(f.severity is Severity.FAIL for f in self.findings)


def baseline_emissions(
    eg_project_mwh: float,
    ef_grid_cm: float,
) -> tuple[float, list[Finding]]:
    """BE_y = EG_PJ,y * EF_grid,CM,y  (ACM0002, unchanged by VMR0017 s8.1)."""
    findings: list[Finding] = []
    if eg_project_mwh < 0:
        findings.append(Finding("acm0002.baseline", Severity.FAIL,
                                "Net project generation cannot be negative.",
                                ACM0002))
        return 0.0, findings
    if ef_grid_cm <= 0:
        findings.append(Finding("acm0002.baseline", Severity.FAIL,
                                "Combined margin emission factor must be "
                                "positive.", ACM0002))
        return 0.0, findings

    be = eg_project_mwh * ef_grid_cm
    findings.append(Finding(
        "acm0002.baseline", Severity.PASS,
        f"BE_y = {eg_project_mwh:,.0f} MWh x {ef_grid_cm:.4f} t CO2/MWh "
        f"= {be:,.1f} t CO2e.", ACM0002))
    return be, findings


def leakage_emissions(
    eg_facility_mwh: float,
    ef_embodied_kg_per_mwh: float,
) -> tuple[float, list[Finding]]:
    """LE_y = EG_facility,y * EF_embodied * 10^-3   (VMR0017 eq. 19/20).

    The 10^-3 factor converts an embodied factor expressed in kg CO2e/MWh to
    tonnes. VMR0017 introduced embodied-emissions leakage; ACM0002 did not
    have it, so a PDD carried over from ACM0002 will be missing this term.
    """
    findings: list[Finding] = []
    if ef_embodied_kg_per_mwh < 0 or eg_facility_mwh < 0:
        findings.append(Finding("vmr0017.leakage", Severity.FAIL,
                                "Embodied emission factor and facility "
                                "generation must both be non-negative.",
                                f"{VMR0017} eq. 19"))
        return 0.0, findings

    le = eg_facility_mwh * ef_embodied_kg_per_mwh * 1e-3
    findings.append(Finding(
        "vmr0017.leakage", Severity.PASS,
        f"LE_y = {eg_facility_mwh:,.0f} MWh x {ef_embodied_kg_per_mwh:g} "
        f"kg CO2e/MWh x 10^-3 = {le:,.1f} t CO2e.", f"{VMR0017} eq. 19"))
    return le, findings


def emission_reductions(
    eg_project_mwh: float,
    ef_grid_cm: float,
    project_emissions: ProjectEmissions | None = None,
    eg_facility_mwh: float | None = None,
    ef_embodied_kg_per_mwh: float | None = None,
    technology=None,
) -> EmissionReductionResult:
    """ER_y = BE_y - PE_y - LE_y   (VMR0017 eq. 17).

    When `technology` is supplied and no embodied factor is given, the
    methodology default from VMR0017 s9.1 is applied. That table is mandatory,
    not advisory: a caller-supplied figure that undercuts it overstates the
    project's reductions.
    """
    if ef_embodied_kg_per_mwh is None and technology is not None:
        from app.domain.monitoring import embodied_emission_factor
        ef_embodied_kg_per_mwh, _ = embodied_emission_factor(technology)
        if ef_embodied_kg_per_mwh == 0.0:
            ef_embodied_kg_per_mwh = None
    be, findings = baseline_emissions(eg_project_mwh, ef_grid_cm)

    pe_obj = project_emissions or ProjectEmissions()
    pe = pe_obj.total
    if pe == 0.0:
        findings.append(Finding(
            "vmr0017.project_emissions", Severity.WARNING,
            "Project emissions taken as zero. VMR0017 s8.2 permits this for "
            "most renewable generation, but a BESS, geothermal, or SF6-bearing "
            "switchgear installation must be quantified under equation (1).",
            f"{VMR0017} s8.2"))

    if eg_facility_mwh is None or ef_embodied_kg_per_mwh is None:
        le = 0.0
        findings.append(Finding(
            "vmr0017.leakage", Severity.FAIL,
            "Embodied-emissions leakage not supplied. VMR0017 requires it "
            "(equations 19/20) and ACM0002 did not — a PDD migrated from "
            "ACM0002 will be missing this term.", f"{VMR0017} eq. 19"))
    else:
        le, le_findings = leakage_emissions(
            eg_facility_mwh, ef_embodied_kg_per_mwh)
        findings.extend(le_findings)

    er = be - pe - le
    if er < 0:
        findings.append(Finding(
            "vmr0017.emission_reductions", Severity.FAIL,
            f"ER_y is negative ({er:,.1f} t CO2e): project and leakage "
            f"emissions exceed the baseline.", f"{VMR0017} eq. 17"))
    else:
        findings.append(Finding(
            "vmr0017.emission_reductions", Severity.PASS,
            f"ER_y = {be:,.1f} - {pe:,.1f} - {le:,.1f} = {er:,.1f} t CO2e.",
            f"{VMR0017} eq. 17"))

    return EmissionReductionResult(
        baseline_emissions_tco2e=be,
        project_emissions_tco2e=pe,
        leakage_emissions_tco2e=le,
        emission_reductions_tco2e=er,
        findings=findings,
    )
