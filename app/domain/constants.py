"""
Regulatory constants for the Bodhi Hub VCS v5.0 platform.

EVERY value in this file is traceable to a clause in a source document.
Do not add a constant without a `source` citation. The Auditor agent and the
traceability matrix export both read these citations.

Sources on disk (801-04-01 Verra Regulations/):
  - VCS Standard, v5.0
  - VMR0017-Grid-Connected-Electricity-Generation-from-Renewable-Sources-
    ACM0002-Revision-v1.0.pdf
  - VT0011-Electricity-System-Emission-Factors-v1.0.pdf
  - VT0008-Additionality-Assessment-v1.0.pdf
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import NamedTuple


# ---------------------------------------------------------------------------
# Template version routing
# ---------------------------------------------------------------------------

# VCS Version 5 program updates (Dec 2025). Projects with an initial crediting
# period start date on/after this date use the 5.0B template family.
TEMPLATE_B_CUTOVER = date(2027, 1, 1)


class TemplateVersion(str, Enum):
    A = "5.0A"
    B = "5.0B"


# ---------------------------------------------------------------------------
# Sectoral scope (VCS Sectoral Scopes and Project Classification System
# Guidance, v5.0). Grid-connected solar and wind fall in Scope 1.
# ---------------------------------------------------------------------------

SECTORAL_SCOPE_ENERGY_RENEWABLE = 1
PROJECT_CATEGORY_EI = "E&I"  # Energy & Industry


# ---------------------------------------------------------------------------
# Technology types eligible under VMR0017
# ---------------------------------------------------------------------------

class Technology(str, Enum):
    WIND_ONSHORE = "WIND_ONSHORE"
    WIND_OFFSHORE = "WIND_OFFSHORE"
    SOLAR_PV_TERRESTRIAL = "SOLAR_PV_TERRESTRIAL"
    SOLAR_PV_FLOATING = "SOLAR_PV_FLOATING"
    GEOTHERMAL = "GEOTHERMAL"
    WAVE = "WAVE"
    TIDAL = "TIDAL"
    HYDRO = "HYDRO"


class IncomeGroup(str, Enum):
    """World Bank country and lending groups."""
    LOW = "LOW"
    LOWER_MIDDLE = "LOWER_MIDDLE"
    UPPER_MIDDLE = "UPPER_MIDDLE"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"


class GeographyRule(str, Enum):
    GLOBAL = "GLOBAL"
    NON_HIGH_INCOME = "NON_HIGH_INCOME"  # low, lower-middle, upper-middle only
    LDC_ONLY = "LDC_ONLY"


class TechnologyRule(NamedTuple):
    geography: GeographyRule
    max_capacity_mw: float | None  # None == any capacity
    source: str


# VMR0017 v1.0, Section 4, Table 1 "Applicable technology, capacity, and
# geographies". Income classification per World Bank Country and Lending
# Groups; LDC list per UN OHRLLS.
VMR0017_ELIGIBILITY: dict[Technology, TechnologyRule] = {
    Technology.WIND_ONSHORE: TechnologyRule(
        GeographyRule.NON_HIGH_INCOME, None, "VMR0017 v1.0 Table 1"),
    Technology.WIND_OFFSHORE: TechnologyRule(
        GeographyRule.NON_HIGH_INCOME, None, "VMR0017 v1.0 Table 1"),
    Technology.SOLAR_PV_TERRESTRIAL: TechnologyRule(
        GeographyRule.NON_HIGH_INCOME, None, "VMR0017 v1.0 Table 1"),
    Technology.SOLAR_PV_FLOATING: TechnologyRule(
        GeographyRule.NON_HIGH_INCOME, None, "VMR0017 v1.0 Table 1"),
    Technology.GEOTHERMAL: TechnologyRule(
        GeographyRule.NON_HIGH_INCOME, None, "VMR0017 v1.0 Table 1"),
    Technology.WAVE: TechnologyRule(
        GeographyRule.GLOBAL, None, "VMR0017 v1.0 Table 1"),
    Technology.TIDAL: TechnologyRule(
        GeographyRule.GLOBAL, None, "VMR0017 v1.0 Table 1"),
    # Hydro: 15 MW or less, by rated OR authorised capacity, whichever is
    # higher; LDC countries only.
    Technology.HYDRO: TechnologyRule(
        GeographyRule.LDC_ONLY, 15.0, "VMR0017 v1.0 Table 1"),
}


# ---------------------------------------------------------------------------
# Crediting period — VCS Standard v5.0, Table 8
#
# NOTE FOR THE FINANCIAL MODEL: under VCS v5.0 an E&I project (solar/wind) has
# a FIVE year crediting period, renewable twice, for a maximum of 15 years.
# This replaces the 7 x 3 = 21 year pattern many older PDDs assume. Any NPV or
# IRR built on a 21-year credit stream is wrong under v5.0.
# ---------------------------------------------------------------------------

EI_CREDITING_PERIOD_YEARS = 5
EI_MAX_RENEWALS = 2
EI_MAX_TOTAL_CREDITING_YEARS = 15
CREDITING_PERIOD_SOURCE = "VCS Standard v5.0 s3.8.4, Table 8"

# VCS Standard v5.0 s3.8.2 and Table 7
PIPELINE_LISTING_DEADLINE_YEARS = 1   # from initial crediting period start date
EI_REGISTRATION_DEADLINE_YEARS = 2    # E&I / GCS
EI_NEW_METHODOLOGY_REGISTRATION_YEARS = 4  # E&I applying a new VCS methodology


# ---------------------------------------------------------------------------
# Combined margin weights — VT0011 v1.0, Step 6, para 86 (Case 1)
# Indexed by crediting period ordinal (1 = initial, 2 = first renewal, ...)
# ---------------------------------------------------------------------------

WIND_SOLAR_CM_WEIGHTS: dict[int, tuple[float, float]] = {
    1: (0.50, 0.50),
    2: (0.40, 0.60),
    3: (0.30, 0.70),
}
OTHER_CASE1_CM_WEIGHTS: dict[int, tuple[float, float]] = {
    1: (0.40, 0.60),
}
OTHER_CASE1_CM_WEIGHTS_SUBSEQUENT = (0.25, 0.75)
CASE2_CM_WEIGHTS = (1.0, 0.0)  # projects increasing grid consumption

# VT0011 v1.0 para 90: LDC projects may use wOM = 1, wBM = 0.
LDC_CM_WEIGHTS_OPTION = (1.0, 0.0)

# VT0011 v1.0 para 91(a): non-LDC, renewable share of installed capacity
# <= 20%, a default build margin may be applied (NG-fired CCGT, BAT).
DEFAULT_BM_EF_TCO2_PER_MWH = 0.326
DEFAULT_BM_RENEWABLE_SHARE_THRESHOLD = 0.20

CM_WEIGHTS_SOURCE = "VT0011 v1.0 Step 6, paras 86, 90, 91"

WIND_SOLAR_TECHNOLOGIES = frozenset({
    Technology.WIND_ONSHORE,
    Technology.WIND_OFFSHORE,
    Technology.SOLAR_PV_TERRESTRIAL,
    Technology.SOLAR_PV_FLOATING,
})


# ---------------------------------------------------------------------------
# VT0008 additionality thresholds
# ---------------------------------------------------------------------------

# VT0008 v1.0 s5.5.2: common practice where F > 20% AND (Nall - Ndiff) > 3.
COMMON_PRACTICE_F_THRESHOLD = 0.20
COMMON_PRACTICE_MIN_SIMILAR_PROJECTS = 3
COMMON_PRACTICE_SOURCE = "VT0008 v1.0 s5.5.2"

# VMR0017 v1.0 s5.3.2 note: barrier analysis (VT0008 Step 2) is NOT applicable
# under VMR0017. Only regulatory surplus -> investment analysis -> common
# practice.
BARRIER_ANALYSIS_ALLOWED_UNDER_VMR0017 = False
