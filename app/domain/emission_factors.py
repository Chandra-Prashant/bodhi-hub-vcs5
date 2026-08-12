"""
Module 2a — Grid emission factors (VT0011 v1.0).

VT0011 is a delta on CDM TOOL07 "Tool to calculate the emission factor for an
electricity system". It replaces paragraphs 25, 26, 39, 45, 50, 72, 75, 79 and
86; every other paragraph, INCLUDING THE CORE EQUATIONS, comes from TOOL07.

    !! VERIFICATION REQUIRED !!
    The equations below are the standard TOOL07 formulation. TOOL07 itself is
    not in the regulations pack. Before any output of this module reaches a
    PDD, check each function's docstring against the current TOOL07 text and
    record the check in the traceability matrix. Where TOOL07 and this module
    disagree, TOOL07 wins.

Units, fixed throughout:
    EG      MWh
    FC      mass or volume unit consistent with NCV
    NCV     GJ per FC unit
    EF_CO2  t CO2 per GJ
    EF_EL   t CO2 per MWh
    eta     dimensionless (0 < eta <= 1)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from app.domain.classification import Finding, Severity
from app.domain import constants as K

GJ_PER_MWH = 3.6

VT0011 = "VT0011 v1.0"
TOOL07 = "CDM TOOL07 (via VT0011 v1.0) — UNVERIFIED, see module docstring"


class OMMethod(str, Enum):
    SIMPLE = "SIMPLE"
    SIMPLE_ADJUSTED = "SIMPLE_ADJUSTED"
    DISPATCH_DATA = "DISPATCH_DATA"
    AVERAGE = "AVERAGE"


class ProjectCase(str, Enum):
    """VT0011 para 86. Case 1 = supplies electricity to the grid or reduces
    grid consumption. Case 2 = increases grid consumption."""
    SUPPLIES_GRID = "CASE_1"
    INCREASES_CONSUMPTION = "CASE_2"


@dataclass
class FuelInput:
    """One fuel burned by one power unit in one year."""
    fuel: str
    quantity: float          # FC_i,m,y
    ncv_gj_per_unit: float   # NCV_i,y
    ef_co2_t_per_gj: float   # EF_CO2,i,y

    @property
    def emissions_t(self) -> float:
        return self.quantity * self.ncv_gj_per_unit * self.ef_co2_t_per_gj


@dataclass
class PowerUnit:
    """A generating unit in the project electricity system for year y."""
    unit_id: str
    generation_mwh: float                  # EG_m,y (net)
    commissioning_year: int
    low_cost_must_run: bool = False        # hydro, geothermal, wind, solar, nuclear, low-cost biomass
    fuels: list[FuelInput] = field(default_factory=list)   # Option A1
    efficiency: float | None = None        # eta_m,y — Option A2
    efficiency_fuel_ef_t_per_gj: float | None = None       # EF_CO2,m,i,y for Option A2
    generation_only: bool = False          # Option A3 — no fuel or efficiency data


@dataclass
class EmissionFactorResult:
    ef_grid_om: float
    ef_grid_bm: float
    ef_grid_cm: float
    w_om: float
    w_bm: float
    om_method: OMMethod
    bm_sample_unit_ids: list[str]
    findings: list[Finding] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return any(f.severity is Severity.FAIL for f in self.findings)


# ---------------------------------------------------------------------------
# Per-unit emission factor (TOOL07 Step 4, as modified by VT0011 para 50)
# ---------------------------------------------------------------------------

def unit_emission_factor(
    unit: PowerUnit,
    case: ProjectCase,
) -> tuple[float, list[Finding]]:
    """EF_EL,m,y in t CO2/MWh.

    Option A1 (fuel data):
        EF_EL,m,y = sum_i (FC_i,m,y * NCV_i,y * EF_CO2,i,y) / EG_m,y

    Option A2 (efficiency):
        EF_EL,m,y = EF_CO2,m,i,y * 3.6 / eta_m,y

    Option A3 (generation data only) — VT0011 para 50:
        A.3.i  Case 1: 0 t CO2/MWh
        A.3.ii Case 2: 1.3 t CO2/MWh
    """
    findings: list[Finding] = []

    if unit.generation_mwh <= 0:
        return 0.0, [Finding(
            f"vt0011.unit.{unit.unit_id}", Severity.FAIL,
            "Annual generation must be positive to derive an emission factor.",
            TOOL07)]

    if unit.generation_only or (not unit.fuels and unit.efficiency is None):
        ef = 0.0 if case is ProjectCase.SUPPLIES_GRID else 1.3
        findings.append(Finding(
            f"vt0011.unit.{unit.unit_id}", Severity.WARNING,
            f"Only generation data available; Option A3 default of {ef} "
            f"t CO2/MWh applied. Obtain fuel or efficiency data if the unit is "
            f"material to the OM.", f"{VT0011} para 50"))
        return ef, findings

    if unit.fuels:
        # Option A1. VT0011 para 50 Option A.2.i/ii govern MULTI-FUEL units:
        # Case 1 takes the lowest-EF fuel, Case 2 the highest. Applied here to
        # the per-fuel emission factor when more than one fuel is present.
        if len({f.fuel for f in unit.fuels}) > 1:
            chooser = min if case is ProjectCase.SUPPLIES_GRID else max
            selected = chooser(unit.fuels, key=lambda f: f.ef_co2_t_per_gj)
            findings.append(Finding(
                f"vt0011.unit.{unit.unit_id}", Severity.WARNING,
                f"Multi-fuel unit; {selected.fuel} selected as the "
                f"{'lowest' if case is ProjectCase.SUPPLIES_GRID else 'highest'}"
                f"-emission-factor fuel.", f"{VT0011} para 50"))
            total_t = sum(
                f.quantity * f.ncv_gj_per_unit * selected.ef_co2_t_per_gj
                for f in unit.fuels
            )
        else:
            total_t = sum(f.emissions_t for f in unit.fuels)
        return total_t / unit.generation_mwh, findings

    # Option A2
    if not 0 < (unit.efficiency or 0) <= 1:
        return 0.0, [Finding(
            f"vt0011.unit.{unit.unit_id}", Severity.FAIL,
            f"Efficiency {unit.efficiency} is outside (0, 1].", TOOL07)]
    if unit.efficiency_fuel_ef_t_per_gj is None:
        return 0.0, [Finding(
            f"vt0011.unit.{unit.unit_id}", Severity.FAIL,
            "Option A2 requires a fuel CO2 emission factor (t CO2/GJ).",
            TOOL07)]
    ef = unit.efficiency_fuel_ef_t_per_gj * GJ_PER_MWH / unit.efficiency
    return ef, findings


# ---------------------------------------------------------------------------
# Operating margin (TOOL07 Steps 3-4)
# ---------------------------------------------------------------------------

def check_simple_om_applicability(
    units: list[PowerUnit],
) -> list[Finding]:
    """TOOL07 para 40: the simple OM may only be used where low-cost/must-run
    resources are less than 50% of total grid generation, averaged over the
    five most recent years or based on long-term averages."""
    total = sum(u.generation_mwh for u in units)
    if total <= 0:
        return [Finding("vt0011.om.applicability", Severity.FAIL,
                        "Total system generation is zero.", TOOL07)]

    lcmr = sum(u.generation_mwh for u in units if u.low_cost_must_run)
    share = lcmr / total

    if share >= 0.50:
        return [Finding(
            "vt0011.om.applicability", Severity.FAIL,
            f"Low-cost/must-run resources are {share:.1%} of generation. The "
            f"simple OM requires under 50%. Use the simple adjusted OM, "
            f"dispatch data analysis, or the average OM instead.", TOOL07)]

    return [Finding(
        "vt0011.om.applicability", Severity.PASS,
        f"Low-cost/must-run share is {share:.1%}; simple OM is available.",
        TOOL07)]


def simple_om(
    units: list[PowerUnit],
    case: ProjectCase,
) -> tuple[float, list[Finding]]:
    """EF_grid,OMsimple,y = sum_m (EG_m,y * EF_EL,m,y) / sum_m EG_m,y

    Low-cost/must-run units are excluded from the sample entirely.
    """
    findings = check_simple_om_applicability(units)
    if any(f.severity is Severity.FAIL for f in findings):
        return 0.0, findings

    dispatchable = [u for u in units if not u.low_cost_must_run]
    if not dispatchable:
        findings.append(Finding("vt0011.om.simple", Severity.FAIL,
                                "No dispatchable units remain after excluding "
                                "low-cost/must-run resources.", TOOL07))
        return 0.0, findings

    numerator = 0.0
    denominator = 0.0
    for unit in dispatchable:
        ef, unit_findings = unit_emission_factor(unit, case)
        findings.extend(unit_findings)
        numerator += unit.generation_mwh * ef
        denominator += unit.generation_mwh

    if denominator <= 0:
        findings.append(Finding("vt0011.om.simple", Severity.FAIL,
                                "Dispatchable generation is zero.", TOOL07))
        return 0.0, findings

    ef_om = numerator / denominator
    findings.append(Finding(
        "vt0011.om.simple", Severity.PASS,
        f"Simple OM = {ef_om:.4f} t CO2/MWh across {len(dispatchable)} "
        f"dispatchable units.", TOOL07))
    return ef_om, findings


def average_om(
    units: list[PowerUnit],
    case: ProjectCase,
) -> tuple[float, list[Finding]]:
    """Average OM — all units, including low-cost/must-run."""
    findings: list[Finding] = []
    numerator = 0.0
    denominator = 0.0
    for unit in units:
        ef, unit_findings = unit_emission_factor(unit, case)
        findings.extend(unit_findings)
        numerator += unit.generation_mwh * ef
        denominator += unit.generation_mwh

    if denominator <= 0:
        findings.append(Finding("vt0011.om.average", Severity.FAIL,
                                "Total generation is zero.", TOOL07))
        return 0.0, findings

    ef_om = numerator / denominator
    findings.append(Finding(
        "vt0011.om.average", Severity.PASS,
        f"Average OM = {ef_om:.4f} t CO2/MWh across all {len(units)} units.",
        TOOL07))
    return ef_om, findings


# ---------------------------------------------------------------------------
# Build margin (TOOL07 Step 5, as modified by VT0011 paras 72, 75, 79)
# ---------------------------------------------------------------------------

def select_bm_sample(
    units: list[PowerUnit],
) -> tuple[list[PowerUnit], list[Finding]]:
    """VT0011 para 75.

    (a) SET_5      — the five most recently commissioned units.
    (b) SET_>=20%  — most recent units together comprising >= 20% of total
                     annual generation; a unit straddling the boundary is
                     included in full.
    (c) SET_sample — whichever of the two has the LARGER annual generation.

    All units connected to the system are eligible, including those registered
    under the VCS Program or another GHG programme (para 45 / para 75(a)).
    """
    findings: list[Finding] = []
    if not units:
        return [], [Finding("vt0011.bm.sample", Severity.FAIL,
                            "No units supplied for the build margin.", TOOL07)]

    total_generation = sum(u.generation_mwh for u in units)
    by_recency = sorted(units, key=lambda u: u.commissioning_year, reverse=True)

    set_5 = by_recency[:5]
    gen_5 = sum(u.generation_mwh for u in set_5)

    set_20: list[PowerUnit] = []
    running = 0.0
    for unit in by_recency:
        set_20.append(unit)
        running += unit.generation_mwh
        if running >= 0.20 * total_generation:
            break
    gen_20 = running

    if gen_20 >= gen_5:
        sample, label, gen = set_20, "SET_>=20%", gen_20
    else:
        sample, label, gen = set_5, "SET_5", gen_5

    findings.append(Finding(
        "vt0011.bm.sample", Severity.PASS,
        f"{label} selected ({len(sample)} units, {gen:,.0f} MWh, "
        f"{gen / total_generation:.1%} of system generation).",
        f"{VT0011} para 75"))

    # VT0011 para 79 — conservatism constraint on old units.
    newest_year = by_recency[0].commissioning_year
    old = [u for u in sample if newest_year - u.commissioning_year > 10]
    if old:
        findings.append(Finding(
            "vt0011.bm.old_units", Severity.WARNING,
            f"{len(old)} unit(s) in the sample commissioned more than 10 years "
            f"before the most recent addition. Para 79 restricts these to "
            f"Option A2 with TOOL09 Table 2 default efficiencies.",
            f"{VT0011} para 79"))

    return sample, findings


def build_margin(
    units: list[PowerUnit],
    case: ProjectCase,
) -> tuple[float, list[str], list[Finding]]:
    """EF_grid,BM,y = sum_m (EG_m,y * EF_EL,m,y) / sum_m EG_m,y over SET_sample."""
    sample, findings = select_bm_sample(units)
    if any(f.severity is Severity.FAIL for f in findings):
        return 0.0, [], findings

    numerator = 0.0
    denominator = 0.0
    for unit in sample:
        ef, unit_findings = unit_emission_factor(unit, case)
        findings.extend(unit_findings)
        numerator += unit.generation_mwh * ef
        denominator += unit.generation_mwh

    if denominator <= 0:
        findings.append(Finding("vt0011.bm", Severity.FAIL,
                                "Build margin sample generation is zero.",
                                TOOL07))
        return 0.0, [], findings

    ef_bm = numerator / denominator
    findings.append(Finding(
        "vt0011.bm", Severity.PASS,
        f"Build margin = {ef_bm:.4f} t CO2/MWh.", TOOL07))
    return ef_bm, [u.unit_id for u in sample], findings


# ---------------------------------------------------------------------------
# Combined margin (VT0011 Step 6, para 86)
# ---------------------------------------------------------------------------

def combined_margin(
    ef_om: float,
    ef_bm: float,
    technology: K.Technology,
    crediting_period_ordinal: int,
    case: ProjectCase = ProjectCase.SUPPLIES_GRID,
) -> tuple[float, tuple[float, float], list[Finding]]:
    """EF_grid,CM,y = EF_grid,OM,y * w_OM + EF_grid,BM,y * w_BM"""
    findings: list[Finding] = []

    if case is ProjectCase.INCREASES_CONSUMPTION:
        w_om, w_bm = K.CASE2_CM_WEIGHTS
    elif technology in K.WIND_SOLAR_TECHNOLOGIES:
        w_om, w_bm = K.WIND_SOLAR_CM_WEIGHTS.get(
            crediting_period_ordinal, K.WIND_SOLAR_CM_WEIGHTS[3])
    else:
        w_om, w_bm = (K.OTHER_CASE1_CM_WEIGHTS.get(crediting_period_ordinal)
                      or K.OTHER_CASE1_CM_WEIGHTS_SUBSEQUENT)

    ef_cm = ef_om * w_om + ef_bm * w_bm
    findings.append(Finding(
        "vt0011.cm", Severity.PASS,
        f"Combined margin = {ef_om:.4f} x {w_om} + {ef_bm:.4f} x {w_bm} "
        f"= {ef_cm:.4f} t CO2/MWh.", K.CM_WEIGHTS_SOURCE))
    return ef_cm, (w_om, w_bm), findings


def grid_emission_factor(
    units: list[PowerUnit],
    technology: K.Technology,
    crediting_period_ordinal: int,
    om_method: OMMethod = OMMethod.SIMPLE,
    case: ProjectCase = ProjectCase.SUPPLIES_GRID,
) -> EmissionFactorResult:
    """Full VT0011 Steps 3-6 for one project electricity system and year."""
    if om_method is OMMethod.SIMPLE:
        ef_om, om_findings = simple_om(units, case)
    elif om_method is OMMethod.AVERAGE:
        ef_om, om_findings = average_om(units, case)
    else:
        ef_om, om_findings = 0.0, [Finding(
            "vt0011.om", Severity.FAIL,
            f"{om_method.value} is not implemented. Simple adjusted OM needs "
            f"the lambda_y low-cost/must-run split; dispatch data analysis "
            f"needs hourly system dispatch records.", TOOL07)]

    ef_bm, sample_ids, bm_findings = build_margin(units, case)
    ef_cm, weights, cm_findings = combined_margin(
        ef_om, ef_bm, technology, crediting_period_ordinal, case)

    return EmissionFactorResult(
        ef_grid_om=ef_om,
        ef_grid_bm=ef_bm,
        ef_grid_cm=ef_cm,
        w_om=weights[0],
        w_bm=weights[1],
        om_method=om_method,
        bm_sample_unit_ids=sample_ids,
        findings=[*om_findings, *bm_findings, *cm_findings],
    )
