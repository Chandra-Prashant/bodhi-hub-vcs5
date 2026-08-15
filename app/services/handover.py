"""
The join between ingestion and assessment.

Until now the two halves ran separately: a document could be uploaded,
extracted and reviewed, and a project could be assessed — but the reviewed
values had to be retyped into the assessment form. This closes that.

Three rules govern the handover, and each exists because the alternative loses
something a reviewer did:

1. **A reviewer's correction wins.** If a field was EDITED during review, the
   corrected value is used, not what the model extracted. That is the entire
   point of the review step; ignoring it would make the queue decorative.

2. **Unresolved blocking items stop the handover.** A field flagged ERROR and
   still PENDING means somebody has not looked at a value the validator does
   not believe. Calculating on it produces a number that looks like every other
   number in the report.

3. **An unmappable value is refused, never guessed.** A technology string that
   matches no known type goes back to a person rather than being resolved to
   the nearest match. "Solar thermal" is not solar PV, and a fuzzy match here
   would silently select the wrong methodology table.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.constants import Technology
from app.models.ingestion import Extraction, ReviewItem, ReviewState


class HandoverRefused(Exception):
    """The extraction is not in a state that can be calculated on."""


# Words that disqualify a match outright, whatever else the string contains.
#
# "Solar thermal" and "concentrated solar power" contain "solar" but are not
# photovoltaic, and VMR0017 Table 1 does not list them. Matching them to solar
# PV would select the wrong eligibility rules, the wrong embodied emission
# factor, and the wrong capacity conditions — while looking entirely correct.
# The same trap exists for hybrid plants, where a single technology type cannot
# describe the project at all.
_DISQUALIFYING = (
    "thermal", "concentrated", "csp", "hybrid", "biomass", "bagasse",
    "diesel", "gas", "coal", "nuclear",
)

# Explicit, ordered, and deliberately not fuzzy. Longer/more specific patterns
# first, because "floating solar" also contains "solar".
_TECHNOLOGY_PATTERNS: tuple[tuple[tuple[str, ...], Technology], ...] = (
    (("solar", "floating"), Technology.SOLAR_PV_FLOATING),
    (("solar", "float"), Technology.SOLAR_PV_FLOATING),
    (("wind", "offshore"), Technology.WIND_OFFSHORE),
    (("wind", "onshore"), Technology.WIND_ONSHORE),
    (("photovoltaic",), Technology.SOLAR_PV_TERRESTRIAL),
    (("solar pv",), Technology.SOLAR_PV_TERRESTRIAL),
    (("solar",), Technology.SOLAR_PV_TERRESTRIAL),
    (("wind",), Technology.WIND_ONSHORE),
    (("geothermal",), Technology.GEOTHERMAL),
    (("hydro",), Technology.HYDRO),
    (("tidal",), Technology.TIDAL),
    (("wave",), Technology.WAVE),
)


def map_technology(stated: str) -> Technology:
    """Resolve a document's wording to a methodology technology type.

    Raises rather than guessing. VMR0017 Table 1 sets different eligibility and
    capacity rules per technology, so a wrong match here selects the wrong
    rules and everything downstream is confidently wrong.
    """
    text = (stated or "").strip().lower()
    if not text:
        raise HandoverRefused("No technology stated.")

    # An exact enum name, e.g. from a corrected value typed by a reviewer.
    for technology in Technology:
        if text == technology.value.lower():
            return technology

    for keywords, technology in _TECHNOLOGY_PATTERNS:
        if not all(keyword in text for keyword in keywords):
            continue

        # Disqualifiers are checked only against the text the match did NOT
        # account for. Checking the whole string first rejects "geothermal",
        # which contains "thermal" — the substring belongs to the matched word
        # itself, not to a second technology.
        remainder = text
        for keyword in keywords:
            remainder = remainder.replace(keyword, " ")
        blocked = [word for word in _DISQUALIFYING if word in remainder]
        if blocked:
            raise HandoverRefused(
                f"The stated technology {stated!r} also mentions "
                f"{blocked[0]!r}, which is not a VMR0017 Table 1 technology "
                f"type. Solar thermal, CSP, biomass and hybrid plants are not "
                f"covered by this methodology — confirm what the project "
                f"actually is during review."
            )
        return technology

    raise HandoverRefused(
        f"Could not map the stated technology {stated!r} to a methodology "
        f"type. Correct it during review to one of: "
        f"{', '.join(t.value for t in Technology)}."
    )


def _to_number(name: str, raw: str) -> float:
    text = str(raw).strip().replace(",", "").replace("%", "")
    try:
        return float(text)
    except ValueError:
        raise HandoverRefused(
            f"{name} is {raw!r}, which is not a number. Correct it during "
            f"review.") from None


def _to_date(name: str, raw) -> date:
    if isinstance(raw, date):
        return raw
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d-%b-%Y", "%d %B %Y"):
        try:
            from datetime import datetime

            return datetime.strptime(str(raw).strip(), fmt).date()
        except ValueError:
            continue
    raise HandoverRefused(
        f"{name} is {raw!r}, which is not a recognisable date. Correct it "
        f"during review.")


@dataclass
class Handover:
    values: dict[str, object] = field(default_factory=dict)
    corrections_applied: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def resolve_values(db: Session, extraction: Extraction) -> Handover:
    """Extracted values, with reviewer corrections applied over the top."""
    if not extraction.data:
        raise HandoverRefused(
            "This document produced no extraction data. It needs manual entry.")

    items = list(db.scalars(
        select(ReviewItem).where(ReviewItem.extraction_id == extraction.id)))

    blocking = [i for i in items
                if i.state is ReviewState.PENDING and i.severity == "ERROR"]
    if blocking:
        raise HandoverRefused(
            f"{len(blocking)} blocking review item(s) are unresolved: "
            f"{', '.join(sorted({i.field_name for i in blocking}))}. "
            f"Resolve them before calculating.")

    handover = Handover()
    for name, entry in extraction.data.items():
        if isinstance(entry, dict) and entry.get("value") is not None:
            handover.values[name] = entry["value"]

    for item in items:
        if item.state is ReviewState.EDITED and item.corrected_value:
            handover.values[item.field_name] = item.corrected_value
            handover.corrections_applied.append(item.field_name)
        elif item.state is ReviewState.REJECTED:
            # A rejected value is one a reviewer does not accept. Carrying it
            # forward would make the rejection meaningless.
            handover.values.pop(item.field_name, None)
            handover.notes.append(
                f"{item.field_name} was rejected during review and is not "
                f"carried into the assessment.")

    return handover


REQUIRED = (
    "project_name", "proponent", "country_iso2", "technology",
    "installed_capacity_mw", "expected_annual_generation_mwh",
    "initial_crediting_period_start",
)


def build_assessment_payload(handover: Handover) -> dict:
    """Map resolved values onto the assessment request shape.

    Grid units are deliberately absent. A project document states its own
    capacity and generation; it does not describe the power units of the
    national grid, which is where the emission factor comes from. The
    assessment will report quantification as unavailable rather than inventing
    a factor — that is correct, and it is the honest state of a project whose
    dispatch data has not been supplied.
    """
    values = handover.values
    missing = [name for name in REQUIRED if not values.get(name)]
    if missing:
        raise HandoverRefused(
            f"Required field(s) still missing: {', '.join(missing)}. "
            f"Enter them during review.")

    payload: dict = {
        "name": str(values["project_name"]),
        "proponent": str(values["proponent"]),
        "country_iso2": str(values["country_iso2"]).strip().upper(),
        "technology": map_technology(str(values["technology"])).value,
        "installed_capacity_mw": _to_number(
            "installed_capacity_mw", values["installed_capacity_mw"]),
        "expected_annual_generation_mwh": _to_number(
            "expected_annual_generation_mwh",
            values["expected_annual_generation_mwh"]),
        "initial_crediting_period_start": _to_date(
            "initial_crediting_period_start",
            values["initial_crediting_period_start"]).isoformat(),
        "grid_units": [],
    }

    financial_fields = ("capex", "annual_opex", "tariff_per_mwh",
                        "project_lifetime_years", "benchmark_irr")
    if all(values.get(name) for name in financial_fields):
        benchmark = _to_number("benchmark_irr", values["benchmark_irr"])
        # A document usually states the benchmark as a percentage. The
        # validator warns about this; here it is converted so the engine
        # receives the fraction it expects.
        if benchmark > 1:
            benchmark = benchmark / 100
            handover.notes.append(
                "benchmark_irr was stated as a percentage and converted to a "
                "fraction for the additionality test.")
        payload["financials"] = {
            "capex": _to_number("capex", values["capex"]),
            "annual_opex": _to_number("annual_opex", values["annual_opex"]),
            "annual_generation_mwh": payload["expected_annual_generation_mwh"],
            "tariff_per_mwh": _to_number(
                "tariff_per_mwh", values["tariff_per_mwh"]),
            "project_lifetime_years": int(_to_number(
                "project_lifetime_years", values["project_lifetime_years"])),
            "discount_rate": 0.10,
            "benchmark_irr": benchmark,
        }
    else:
        absent = [n for n in financial_fields if not values.get(n)]
        handover.notes.append(
            f"Additionality was not assessed: {', '.join(absent)} not found in "
            f"the document. Supply them to run the investment analysis.")

    return payload


def latest_extraction_for(
    db: Session, document_id: uuid.UUID, organization: str
) -> Extraction:
    extraction = db.scalars(
        select(Extraction)
        .where(Extraction.document_id == document_id,
               Extraction.organization == organization)
        .order_by(Extraction.created_at.desc())
    ).first()
    if extraction is None:
        raise HandoverRefused("No extraction exists for that document.")
    return extraction
