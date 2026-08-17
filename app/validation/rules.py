"""
Validation — Phase 4.

Phases.md: "Auto-flag suspicious/low-confidence extracted data before it
reaches the calculation engine. Done when: flagging correctly catches injected
test errors in sample data."

Two things flag a field, and they are independent:

  * **Extraction confidence** — the model was unsure it read the right value.
  * **A validation rule** — the value is implausible, inconsistent, or wrong.

They catch different failures and neither subsumes the other. A model can be
entirely confident about a figure it read perfectly from a document that
contains a typo; confidence says nothing about whether the number is right.
So a rule failure flags a field regardless of how certain the extraction was —
confidence never suppresses a rule.

Every rule is a pure function over the extracted data. No model is involved in
deciding whether something is suspicious, because a flag that appears on one
run and not the next is worse than no flag at all: a reviewer stops trusting
the queue.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any

from app.extraction.schema import Confidence, ProjectExtraction


class Severity(str, Enum):
    ERROR = "ERROR"      # cannot proceed — the value is wrong or unusable
    WARNING = "WARNING"  # proceed, but a reviewer must confirm
    INFO = "INFO"        # worth knowing, no action required


@dataclass(frozen=True)
class Flag:
    rule_id: str
    field_name: str
    severity: Severity
    message: str
    source: str = ""
    observed: str = ""
    # Other fields implicated in the same finding.
    #
    # A consistency rule compares two values and can only report one. Capacity
    # against generation, capital cost against tariff — the rule knows both are
    # involved but names the one it happens to be registered under, and that is
    # frequently not the one a reviewer needs to change. Queuing only that field
    # leaves the real correction unreachable.
    related: tuple[str, ...] = ()

    def __str__(self) -> str:
        return f"[{self.severity.value}] {self.field_name}: {self.message}"


@dataclass(frozen=True)
class Rule:
    id: str
    field_name: str
    description: str
    check: Callable[[ProjectExtraction], Flag | None]
    source: str = ""


RULES: list[Rule] = []


def rule(
    *, id: str, field_name: str, description: str, source: str = ""
) -> Callable[[Callable[[ProjectExtraction], Flag | None]], Rule]:
    def decorate(fn: Callable[[ProjectExtraction], Flag | None]) -> Rule:
        if any(r.id == id for r in RULES):
            raise ValueError(f"Rule id {id!r} is already registered.")
        registered = Rule(id=id, field_name=field_name, description=description,
                          check=fn, source=source)
        RULES.append(registered)
        return registered

    return decorate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _value(data: ProjectExtraction, name: str) -> Any:
    field_obj = getattr(data, name)
    return field_obj.value if field_obj.is_present else None


def _number(data: ProjectExtraction, name: str) -> Decimal | None:
    """Parse a stated value to Decimal, or None if it is absent or not numeric.

    Never raises. A non-numeric value where a number is expected is itself a
    finding, reported by the rule that checks it rather than by an exception
    from a helper.
    """
    raw = _value(data, name)
    if raw is None:
        return None
    try:
        return Decimal(str(raw).strip().replace(",", "").replace("%", ""))
    except (InvalidOperation, ValueError):
        return None


def _flag(rule_id, name, severity, message, source="", observed="",
          related=()) -> Flag:
    return Flag(rule_id=rule_id, field_name=name, severity=severity,
                message=message, source=source, observed=str(observed),
                related=tuple(related))


# ---------------------------------------------------------------------------
# Rules — type and range
# ---------------------------------------------------------------------------

_NUMERIC_FIELDS = (
    "installed_capacity_mw", "expected_annual_generation_mwh",
    "capex", "annual_opex", "tariff_per_mwh", "project_lifetime_years",
    "benchmark_irr",
)


@rule(id="type.numeric", field_name="*",
      description="Fields the engine will parse as numbers must be numeric.",
      source="Rules.md — calculation engine raises on invalid fields")
def numeric_fields_parse(data: ProjectExtraction) -> Flag | None:
    for name in _NUMERIC_FIELDS:
        if _value(data, name) is not None and _number(data, name) is None:
            return _flag("type.numeric", name, Severity.ERROR,
                         "Value is not a number. The calculation engine will "
                         "refuse it rather than guess.",
                         observed=_value(data, name))
    return None


@rule(id="range.capacity_positive", field_name="installed_capacity_mw",
      description="Installed capacity must be greater than zero.")
def capacity_positive(data: ProjectExtraction) -> Flag | None:
    value = _number(data, "installed_capacity_mw")
    if value is not None and value <= 0:
        return _flag("range.capacity_positive", "installed_capacity_mw",
                     Severity.ERROR, "Capacity must be greater than 0 MW.",
                     observed=value)
    return None


@rule(id="range.capacity_plausible", field_name="installed_capacity_mw",
      description="Capacity outside 0.1–5000 MW is likely a unit error.")
def capacity_plausible(data: ProjectExtraction) -> Flag | None:
    value = _number(data, "installed_capacity_mw")
    if value is not None and value > 0 and not (Decimal("0.1") <= value <= Decimal("5000")):
        return _flag("range.capacity_plausible", "installed_capacity_mw",
                     Severity.WARNING,
                     "Outside the plausible 0.1–5000 MW range. Check whether "
                     "the document states kW rather than MW.", observed=value)
    return None


@rule(id="range.generation_positive", field_name="expected_annual_generation_mwh",
      description="Expected generation must be greater than zero.")
def generation_positive(data: ProjectExtraction) -> Flag | None:
    value = _number(data, "expected_annual_generation_mwh")
    if value is not None and value <= 0:
        return _flag("range.generation_positive",
                     "expected_annual_generation_mwh", Severity.ERROR,
                     "Generation must be greater than 0 MWh.", observed=value)
    return None


@rule(id="format.country_code", field_name="country_iso2",
      description="Country must be a two-letter ISO code.",
      source="VMR0017 v1.0 Table 1 — eligibility depends on the country")
def country_code_format(data: ProjectExtraction) -> Flag | None:
    value = _value(data, "country_iso2")
    if value is None:
        return None
    text = str(value).strip()
    if len(text) != 2 or not text.isalpha():
        return _flag("format.country_code", "country_iso2", Severity.ERROR,
                     "Not a two-letter ISO code. Eligibility under VMR0017 "
                     "Table 1 is decided by this value.", observed=value)
    return None


@rule(id="range.lifetime_plausible", field_name="project_lifetime_years",
      description="Project life outside 5–50 years is implausible.")
def lifetime_plausible(data: ProjectExtraction) -> Flag | None:
    value = _number(data, "project_lifetime_years")
    if value is not None and not (5 <= value <= 50):
        return _flag("range.lifetime_plausible", "project_lifetime_years",
                     Severity.WARNING,
                     "Outside the plausible 5–50 year range.", observed=value)
    return None


@rule(id="range.benchmark_irr", field_name="benchmark_irr",
      description="Benchmark IRR must be a plausible rate.",
      source="VT0008 v1.0 App. 2 sA2.3")
def benchmark_irr_range(data: ProjectExtraction) -> Flag | None:
    value = _number(data, "benchmark_irr")
    if value is None:
        return None
    if value <= 0:
        return _flag("range.benchmark_irr", "benchmark_irr", Severity.ERROR,
                     "Benchmark must be greater than zero.", observed=value)
    if 1 < value <= 100:
        return _flag("range.benchmark_irr", "benchmark_irr", Severity.WARNING,
                     "Looks like a percentage (14 rather than 0.14). Confirm "
                     "the unit — the engine expects a fraction, and reading "
                     "14 as 1400% would make every project additional.",
                     observed=value)
    if value > 100:
        return _flag("range.benchmark_irr", "benchmark_irr", Severity.ERROR,
                     "Implausible as either a fraction or a percentage.",
                     observed=value)
    return None


@rule(id="range.crediting_start", field_name="initial_crediting_period_start",
      description="Crediting period start must fall in a sensible window.",
      source="VCS Standard v5.0 s3.8.2")
def crediting_start_window(data: ProjectExtraction) -> Flag | None:
    value = _value(data, "initial_crediting_period_start")
    if not isinstance(value, date):
        return None
    today = date.today()
    if value.year < today.year - 10:
        return _flag("range.crediting_start", "initial_crediting_period_start",
                     Severity.ERROR,
                     "More than 10 years in the past — the registration "
                     "deadline will have passed.", observed=value)
    if value.year > today.year + 5:
        return _flag("range.crediting_start", "initial_crediting_period_start",
                     Severity.WARNING, "More than 5 years in the future.",
                     observed=value)
    return None


# ---------------------------------------------------------------------------
# Rules — cross-field consistency
# ---------------------------------------------------------------------------


@rule(id="consistency.capacity_factor", field_name="expected_annual_generation_mwh",
      description="Implied capacity factor must be physically plausible.",
      source="Derived check — catches kW/MW and kWh/MWh mix-ups")
def capacity_factor_plausible(data: ProjectExtraction) -> Flag | None:
    """The single most valuable rule here.

    Capacity and generation are usually extracted from different parts of a
    document, so a unit error in either is invisible on its own and obvious
    once they are divided. A 1000x error produces a capacity factor of 20,000%,
    and it would otherwise flow straight into the baseline calculation.
    """
    capacity = _number(data, "installed_capacity_mw")
    generation = _number(data, "expected_annual_generation_mwh")
    if not capacity or not generation or capacity <= 0:
        return None

    factor = generation / (capacity * 8760)
    if not (Decimal("0.05") <= factor <= Decimal("0.65")):
        return _flag(
            "consistency.capacity_factor", "expected_annual_generation_mwh",
            Severity.ERROR,
            f"Implied capacity factor is {factor:.1%}, outside the plausible "
            f"5–65% band for grid-connected renewables. Capacity and "
            f"generation disagree — one of them has a unit error.",
            observed=f"{capacity} MW / {generation} MWh",
            related=("installed_capacity_mw",))
    return None


@rule(id="consistency.revenue_vs_cost", field_name="tariff_per_mwh",
      description="Annual operating cost should not exceed annual revenue by "
                  "an implausible margin.")
def revenue_covers_opex(data: ProjectExtraction) -> Flag | None:
    tariff = _number(data, "tariff_per_mwh")
    generation = _number(data, "expected_annual_generation_mwh")
    opex = _number(data, "annual_opex")
    if tariff is None or generation is None or opex is None:
        return None
    revenue = tariff * generation
    if revenue <= 0:
        return None
    if opex > revenue:
        return _flag("consistency.revenue_vs_cost", "annual_opex",
                     Severity.WARNING,
                     "Annual operating cost exceeds annual energy revenue. "
                     "Usually a unit mismatch between the tariff and the cost "
                     "figures — lakh against rupees, for instance.",
                     observed=f"opex {opex} vs revenue {revenue}",
                     related=("tariff_per_mwh",))
    return None


@rule(id="consistency.capex_scale", field_name="capex",
      description="Capital cost per MW should be plausible.")
def capex_per_mw_plausible(data: ProjectExtraction) -> Flag | None:
    """Deliberately wide, and unit-agnostic.

    The figures may be in rupees, lakh or crore, so this cannot check an
    absolute magnitude. It catches only order-of-magnitude nonsense — the case
    where capex and capacity cannot both be right whatever the currency unit.
    """
    capex = _number(data, "capex")
    capacity = _number(data, "installed_capacity_mw")
    if not capex or not capacity or capacity <= 0:
        return None
    per_mw = capex / capacity
    if per_mw <= 0:
        return _flag("consistency.capex_scale", "capex", Severity.ERROR,
                     "Capital cost must be greater than zero.", observed=capex)
    return None


@rule(id="consistency.payback_period", field_name="capex",
      description="Implied simple payback must be plausible for the asset.",
      source="Derived check — catches mixed currency scales")
def payback_period_plausible(data: ProjectExtraction) -> Flag | None:
    """Capital cost against annual net revenue.

    Documents state capital cost in lakh or crore and tariffs in rupees, and
    nothing in either figure alone reveals the mismatch. Divided, it is
    unmistakable: a utility-scale renewable plant pays back in roughly four to
    twenty-five years, so a payback of weeks means the two numbers are on
    different scales.

    Found on a real document whose capital cost was "INR 40,000 lakh" and
    tariff "INR 3,000 per MWh" — the resulting return was so large the IRR
    solver could not bracket it and returned nothing at all.
    """
    capex = _number(data, "capex")
    tariff = _number(data, "tariff_per_mwh")
    generation = _number(data, "expected_annual_generation_mwh")
    opex = _number(data, "annual_opex") or Decimal(0)
    if not capex or not tariff or not generation:
        return None

    net_revenue = tariff * generation - opex
    if net_revenue <= 0:
        return None

    years = capex / net_revenue
    if years < Decimal("1"):
        return _flag(
            "consistency.payback_period", "capex", Severity.ERROR,
            f"Implied payback is {years * 12:.1f} months. Capital cost and "
            f"tariff appear to be on different scales — a cost in lakh or "
            f"crore against a tariff in rupees produces this. State both in "
            f"the same unit.",
            observed=f"capex {capex} vs net revenue {net_revenue:.0f}/yr",
            related=("tariff_per_mwh", "annual_opex"))
    if years > 40:
        return _flag(
            "consistency.payback_period", "capex", Severity.WARNING,
            f"Implied payback is {years:.0f} years, beyond the asset's likely "
            f"life. Check the capital cost and tariff units.",
            observed=f"capex {capex} vs net revenue {net_revenue:.0f}/yr",
            related=("tariff_per_mwh",))
    return None
