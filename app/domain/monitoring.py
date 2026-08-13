"""
Module 4a — Monitoring parameters (VMR0017 v1.0 Section 9).

Two kinds of parameter, matching the two appendices of the Project Description:

  * Available at validation (s9.1) — fixed values, mostly methodology defaults
  * Monitored (s9.2) — measured during each monitoring period

The important content here is the **defaults table in s9.1**. VMR0017 mandates
a technology-specific embodied emissions factor; it is not a free input. A
project that plugs in its own figure without justification will be pulled up at
validation, and one that guesses low overstates its reductions.

    Solar photovoltaic                    43 g CO2e/kWh
    Wind (onshore and offshore)           13
    Biomass                               52
    Geothermal                            37
    Hydropower                            21
    Ocean energy                           8
    Concentrated solar power              28

g CO2e/kWh and kg CO2e/MWh are numerically identical, which is the unit the
leakage equation consumes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from app.domain import constants as K
from app.domain.classification import Finding, Severity

VMR0017_S9 = "VMR0017 v1.0 s9.1"
VMR0017_S92 = "VMR0017 v1.0 s9.2"
ACM0002_S61 = "ACM0002 v22.0 s6.1 (via VMR0017 v1.0 s9.2)"


class ParameterKind(str, Enum):
    AT_VALIDATION = "AT_VALIDATION"
    MONITORED = "MONITORED"


@dataclass
class Parameter:
    """One Data/Parameter table in Appendix 2 of the Project Description."""
    name: str
    unit: str
    description: str
    kind: ParameterKind
    source_of_data: str
    purpose: str
    equations: str = ""
    value_applied: str = ""
    measurement_methods: str = ""
    monitoring_frequency: str = ""
    qa_qc: str = ""
    calculation_method: str = ""
    justification: str = "N/A"
    comments: str = "None"
    citation: str = VMR0017_S9


# ---------------------------------------------------------------------------
# VMR0017 s9.1, EFembodied defaults table
# ---------------------------------------------------------------------------

EMBODIED_EF_G_CO2E_PER_KWH: dict[K.Technology, float] = {
    K.Technology.SOLAR_PV_TERRESTRIAL: 43.0,
    K.Technology.SOLAR_PV_FLOATING: 43.0,
    K.Technology.WIND_ONSHORE: 13.0,
    K.Technology.WIND_OFFSHORE: 13.0,
    K.Technology.GEOTHERMAL: 37.0,
    K.Technology.HYDRO: 21.0,
    K.Technology.WAVE: 8.0,
    K.Technology.TIDAL: 8.0,
}

EMBODIED_EF_SOURCE = (
    "NREL, Life Cycle Greenhouse Gas Emissions from Electricity Generation: "
    "Update (September 2021), as tabulated in VMR0017 v1.0 s9.1")

# VMR0017 s9.1 replaces ACM0002 Data/Parameter table 6.
RESERVOIR_EF_KG_CO2E_PER_MWH = 100.0


def embodied_emission_factor(
    technology: K.Technology,
) -> tuple[float, list[Finding]]:
    """Return EF_embodied in kg CO2e/MWh (numerically equal to g CO2e/kWh).

    Returns a FAIL finding rather than a guess for technologies outside the
    table: VMR0017 permits a value from credible literature, but it must be
    justified and documented, which is an author decision.
    """
    ef = EMBODIED_EF_G_CO2E_PER_KWH.get(technology)
    if ef is None:
        return 0.0, [Finding(
            "vmr0017.embodied_ef", Severity.FAIL,
            f"No default embodied emission factor is tabulated for "
            f"{technology.value}. VMR0017 s9.1 permits a value from credible "
            f"literature, but it must be justified and its source documented.",
            VMR0017_S9)]

    return ef, [Finding(
        "vmr0017.embodied_ef", Severity.PASS,
        f"EF_embodied = {ef:g} g CO2e/kWh applied for "
        f"{technology.value.replace('_', ' ').lower()}, per the defaults table "
        f"in VMR0017 s9.1.", VMR0017_S9)]


# ---------------------------------------------------------------------------
# Parameter registry
# ---------------------------------------------------------------------------

def _at_validation(technology: K.Technology, has_bess: bool,
                   ef_embodied: float) -> list[Parameter]:
    params = [
        Parameter(
            name="EFembodied",
            unit="g CO2e/kWh",
            description="Emission factor of the embodied emissions of the "
                        "renewable energy generation plant",
            kind=ParameterKind.AT_VALIDATION,
            source_of_data=EMBODIED_EF_SOURCE,
            value_applied=f"{ef_embodied:g} g CO2e/kWh",
            equations="(19), (20)",
            purpose="Calculation of leakage emissions",
            citation=VMR0017_S9,
        ),
        Parameter(
            name="EFgrid,CM,y",
            unit="t CO2/MWh",
            description="Combined margin CO2 emission factor for the project "
                        "electricity system in year y",
            kind=ParameterKind.AT_VALIDATION,
            source_of_data="Calculated in accordance with VT0011 Electricity "
                           "System Emission Factors, v1.0",
            equations="(2)",
            purpose="Calculation of baseline emissions",
            justification="Determined ex-ante from the operating margin and "
                          "build margin of the project electricity system, "
                          "weighted per VT0011 Step 6.",
            citation="VT0011 v1.0",
        ),
    ]

    if technology is K.Technology.HYDRO:
        params.append(Parameter(
            name="EFRes",
            unit="kg CO2e/MWh",
            description="Default emission factor for emissions from reservoirs",
            kind=ParameterKind.AT_VALIDATION,
            source_of_data="Hydropower Sustainability Standard and the "
                           "Hydropower Sustainability Guidelines on Good "
                           "International Industry Practice",
            value_applied=f"{RESERVOIR_EF_KG_CO2E_PER_MWH:g} kg CO2e/MWh",
            equations="(9)",
            purpose="Calculation of project emissions",
            citation=VMR0017_S9,
        ))

    if has_bess:
        params.append(Parameter(
            name="GWPagent",
            unit="t CO2e/tonne of agent",
            description="Global warming potential of the fire suppression "
                        "agent, calculated on a 100-year time horizon",
            kind=ParameterKind.AT_VALIDATION,
            source_of_data="IPCC Global Warming Potential values (AR5)",
            value_applied="As per the relevant value for the agent in the "
                          "source above",
            equations="(18)",
            purpose="Calculation of project emissions",
            justification="Where commercial blends are used, the GWP must be "
                          "determined from manufacturer specifications or, "
                          "where unavailable, as a weighted average of the "
                          "constituents used.",
            citation=VMR0017_S9,
        ))

    return params


def _monitored(has_bess: bool) -> list[Parameter]:
    params = [
        Parameter(
            name="EGfacility,y",
            unit="MWh/yr",
            description="Quantity of net electricity generation supplied by "
                        "the project plant/unit to the grid in year y",
            kind=ParameterKind.MONITORED,
            source_of_data="Direct measurement",
            equations="(12), (14), (19)",
            purpose="Calculation of baseline emissions",
            measurement_methods=(
                "Direct measurement is required, using electricity meters "
                "installed at the grid interface for electricity export to "
                "the grid."),
            monitoring_frequency="Monitor continuously; aggregate data at "
                                 "least monthly.",
            qa_qc=(
                "Regularly test and calibrate the meters as per utility or "
                "national requirements and manufacturer specifications. "
                "Cross-check against receipts or invoices from utilities or "
                "suppliers where applicable. Propagate uncertainty per "
                "ACM0002 and VMR0017; for direct measurement use the actual "
                "metering uncertainty from the last calibration event, or the "
                "manufacturer's figure where no previous calibration record "
                "exists."),
            calculation_method=(
                "For cumulative meters, take the difference between initial "
                "and final readings and record the date of each reading. Apply "
                "linear interpolation where reading dates do not align with "
                "the monitoring period."),
            comments=(
                "Where direct measurement is temporarily infeasible for "
                "technical or logistical reasons, estimation methods in line "
                "with VT0010 may be used, with justification and a "
                "demonstration that the constraint is temporary and the "
                "method conservative."),
            citation=VMR0017_S92,
        ),
        Parameter(
            name="EGPJ_Add,y",
            unit="MWh/yr",
            description="Quantity of net electricity supplied to the grid in "
                        "year y by the project plant/unit added under the "
                        "project activity",
            kind=ParameterKind.MONITORED,
            source_of_data="Direct measurement",
            equations="(13), (20)",
            purpose="Calculation of baseline emissions",
            measurement_methods="As for EGfacility,y — metered at the grid "
                                "interface.",
            monitoring_frequency="Monitor continuously; aggregate data at "
                                 "least monthly.",
            qa_qc="As for EGfacility,y.",
            citation=VMR0017_S92,
        ),
    ]

    if has_bess:
        params.append(Parameter(
            name="Me,released,y",
            unit="tonnes",
            description="Mass of fire suppression agent released to the "
                        "atmosphere due to event e in year y",
            kind=ParameterKind.MONITORED,
            source_of_data="Fire suppression system activation logs capable of "
                           "recording all agent release events",
            equations="(18)",
            purpose="Calculation of project emissions",
            measurement_methods=(
                "Record each release event in the on-site activation log, "
                "covering fire events, accidental discharge during maintenance "
                "or repair, leakage from equipment failure, false alarms or "
                "system malfunction, and emergency drills or testing. Determine "
                "the quantity released by weighing cylinders before and after "
                "the event using calibrated equipment. Recovered agent may be "
                "deducted only where supported by certified documentation. "
                "Where the released quantity cannot be reliably determined, "
                "conservatively assume the full charged mass of the affected "
                "system was released."),
            monitoring_frequency="Monitor continuously to capture all events; "
                                 "aggregate at least monthly.",
            qa_qc=(
                "Use weighing equipment calibrated to national or international "
                "standards. Cross-check event records against BESS control "
                "system alarms and maintenance logs."),
            citation=VMR0017_S92,
        ))

    return params


@dataclass
class MonitoringParameters:
    at_validation: list[Parameter]
    monitored: list[Parameter]
    embodied_ef_kg_per_mwh: float
    findings: list[Finding] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return any(f.severity is Severity.FAIL for f in self.findings)

    def all(self) -> list[Parameter]:
        return [*self.at_validation, *self.monitored]


def build_monitoring_parameters(
    technology: K.Technology,
    has_bess: bool = False,
) -> MonitoringParameters:
    ef, findings = embodied_emission_factor(technology)

    if has_bess:
        findings.append(Finding(
            "vmr0017.bess", Severity.WARNING,
            "Battery storage declared. Fire suppression agent releases must be "
            "monitored (Me,released,y) and project emissions PE_BESS,y "
            "quantified under equation (18); these are not zero by default.",
            VMR0017_S92))

    return MonitoringParameters(
        at_validation=_at_validation(technology, has_bess, ef),
        monitored=_monitored(has_bess),
        embodied_ef_kg_per_mwh=ef,
        findings=findings,
    )
