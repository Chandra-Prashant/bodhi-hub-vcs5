"""
Country reference data used by the VMR0017 eligibility check.

IMPORTANT — this data expires. The World Bank reclassifies income groups every
July; the UN reviews the LDC list every three years. `AS_OF` below is the date
this table was last verified. `app.domain.classification` returns a WARNING
when the table is more than 12 months stale rather than silently trusting it.

Sources:
  World Bank Country and Lending Groups
    https://datahelpdesk.worldbank.org/knowledgebase/articles/906519
  UN list of Least Developed Countries
    https://www.un.org/ohrlls/content/list-ldcs

Countries not present in INCOME_GROUPS resolve to IncomeGroup.UNKNOWN, which
blocks automated eligibility sign-off and routes to manual review. That is
deliberate: a wrong PASS here invalidates the whole PDD.
"""

from __future__ import annotations

from datetime import date

from app.domain.constants import IncomeGroup

AS_OF = date(2025, 7, 1)

# UN list of Least Developed Countries (ISO 3166-1 alpha-2).
LDC_COUNTRIES: frozenset[str] = frozenset({
    "AF", "AO", "BD", "BJ", "BF", "BI", "KH", "CF", "TD", "KM", "CD", "DJ",
    "ER", "ET", "GM", "GN", "GW", "HT", "KI", "LA", "LS", "LR", "MG", "MW",
    "ML", "MR", "MZ", "MM", "NP", "NE", "RW", "ST", "SN", "SL", "SB", "SO",
    "SS", "SD", "TL", "TG", "TV", "UG", "TZ", "YE", "ZM",
})

# Partial seed of World Bank income groups. Extend as client projects come in;
# anything absent is UNKNOWN, not assumed eligible.
INCOME_GROUPS: dict[str, IncomeGroup] = {
    # South Asia
    "IN": IncomeGroup.LOWER_MIDDLE,
    "PK": IncomeGroup.LOWER_MIDDLE,
    "BD": IncomeGroup.LOWER_MIDDLE,
    "LK": IncomeGroup.LOWER_MIDDLE,
    "NP": IncomeGroup.LOWER_MIDDLE,
    "BT": IncomeGroup.LOWER_MIDDLE,
    # Southeast / East Asia
    "VN": IncomeGroup.LOWER_MIDDLE,
    "PH": IncomeGroup.LOWER_MIDDLE,
    "ID": IncomeGroup.UPPER_MIDDLE,
    "TH": IncomeGroup.UPPER_MIDDLE,
    "MY": IncomeGroup.UPPER_MIDDLE,
    "CN": IncomeGroup.UPPER_MIDDLE,
    "JP": IncomeGroup.HIGH,
    "KR": IncomeGroup.HIGH,
    "SG": IncomeGroup.HIGH,
    # Africa
    "ZA": IncomeGroup.UPPER_MIDDLE,
    "EG": IncomeGroup.LOWER_MIDDLE,
    "MA": IncomeGroup.LOWER_MIDDLE,
    "KE": IncomeGroup.LOWER_MIDDLE,
    "NG": IncomeGroup.LOWER_MIDDLE,
    "GH": IncomeGroup.LOWER_MIDDLE,
    "ET": IncomeGroup.LOW,
    "TZ": IncomeGroup.LOWER_MIDDLE,
    "UG": IncomeGroup.LOW,
    # Latin America
    "BR": IncomeGroup.UPPER_MIDDLE,
    "MX": IncomeGroup.UPPER_MIDDLE,
    "CL": IncomeGroup.HIGH,
    "CO": IncomeGroup.UPPER_MIDDLE,
    "PE": IncomeGroup.UPPER_MIDDLE,
    "AR": IncomeGroup.UPPER_MIDDLE,
    # High income (explicitly listed so wind/solar correctly FAIL)
    "US": IncomeGroup.HIGH,
    "GB": IncomeGroup.HIGH,
    "DE": IncomeGroup.HIGH,
    "FR": IncomeGroup.HIGH,
    "AU": IncomeGroup.HIGH,
    "CA": IncomeGroup.HIGH,
    "AE": IncomeGroup.HIGH,
    "SA": IncomeGroup.HIGH,
}


def income_group(country_iso2: str) -> IncomeGroup:
    return INCOME_GROUPS.get(country_iso2.upper(), IncomeGroup.UNKNOWN)


def is_ldc(country_iso2: str) -> bool:
    return country_iso2.upper() in LDC_COUNTRIES
