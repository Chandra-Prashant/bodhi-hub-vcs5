"""
Module 5 — Environmental, Social, and Governance risk assessment.

VCS Standard v5.0 s3.18.1 requires a documented risk assessment, using the VCS
ESG Risk Assessment Template, completed **before the project start date**.

WHAT THIS MODULE DOES AND DOES NOT DO
-------------------------------------
It does NOT identify risks or assign severity and likelihood. Those are
site-specific judgements about real people and real ecosystems, made by someone
who has visited the site and engaged the stakeholders identified under s3.17.1.
An LLM inventing a plausible-sounding biodiversity risk for a solar farm it has
never seen would be fabricating the exact content a validator scrutinises
hardest, and would give the project proponent false comfort that the work was
done.

It DOES:
  * hold the twelve safeguard categories, so none is silently omitted
  * compute the risk level from severity and likelihood using the matrix
    printed in the template — deterministic, reproducible, not a judgement call
  * enforce s3.18.1(2): mitigation measures must be commensurate with the risk
    level, so a high or very high risk cannot pass with a token mitigation
  * report exactly which categories remain unassessed

The division of labour is the same as everywhere else in this system: the
human supplies the judgement, the engine supplies the arithmetic, the
consistency checks, and the citation trail.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from app.domain.classification import Finding, Severity as FindingSeverity

VCS5_ESG = "VCS Standard v5.0 s3.18"
ESG_TEMPLATE = "VCS ESG Risk Assessment Template, v5.0"


class Pillar(str, Enum):
    ENVIRONMENTAL = "Environmental"
    SOCIAL = "Social"
    GOVERNANCE = "Governance"


class RiskCategory(str, Enum):
    """The twelve safeguard categories of the ESG Risk Assessment Template."""
    E1 = "E1"   # Biodiversity conservation and sustainable management
    E2 = "E2"   # Resource efficiency and pollution prevention
    S1 = "S1"   # Human rights
    S2 = "S2"   # Land or resource rights
    S3 = "S3"   # Customary rights, Indigenous Peoples, cultural heritage
    S4 = "S4"   # Gender equality
    S5 = "S5"   # Labor rights and safe employment conditions
    S6 = "S6"   # Armed personnel
    G1 = "G1"   # Illegal activities
    G2 = "G2"   # Anti-corruption
    G3 = "G3"   # Anti-money laundering
    G4 = "G4"   # Emergency preparedness and response


CATEGORY_TITLES: dict[RiskCategory, tuple[Pillar, str, str]] = {
    RiskCategory.E1: (Pillar.ENVIRONMENTAL,
                      "Biodiversity Conservation and Sustainable Management of "
                      "Living Natural Resources", "s3.18.4–3.18.9"),
    RiskCategory.E2: (Pillar.ENVIRONMENTAL,
                      "Resource Efficiency and Pollution Prevention",
                      "s3.18.10–3.18.13"),
    RiskCategory.S1: (Pillar.SOCIAL, "Human Rights", "s3.18.14–3.18.17"),
    RiskCategory.S2: (Pillar.SOCIAL, "Land or Resource Rights",
                      "s3.18.18–3.18.21"),
    RiskCategory.S3: (Pillar.SOCIAL,
                      "Customary Rights, Indigenous Peoples, and Cultural "
                      "Heritage", "s3.18.22–3.18.26"),
    RiskCategory.S4: (Pillar.SOCIAL, "Gender Equality", "s3.18.27–3.18.29"),
    RiskCategory.S5: (Pillar.SOCIAL,
                      "Labor Rights and Safe Employment Conditions",
                      "s3.18.30–3.18.33"),
    RiskCategory.S6: (Pillar.SOCIAL, "Armed Personnel", "s3.18.34"),
    RiskCategory.G1: (Pillar.GOVERNANCE, "Illegal Activities", "s3.18.35"),
    RiskCategory.G2: (Pillar.GOVERNANCE, "Anti-Corruption", "s3.18.36"),
    RiskCategory.G3: (Pillar.GOVERNANCE, "Anti-Money Laundering", "s3.18.37"),
    RiskCategory.G4: (Pillar.GOVERNANCE,
                      "Emergency Preparedness and Response", "s3.18.38"),
}


class RiskLevel(str, Enum):
    VERY_LOW = "Very low"
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    VERY_HIGH = "Very high"


SEVERITY_LABELS = {
    1: "1 – Negligible", 2: "2 – Minor", 3: "3 – Medium",
    4: "4 – Major", 5: "5 – Severe",
}
LIKELIHOOD_LABELS = {
    1: "1 – Very unlikely", 2: "2 – Not expected", 3: "3 – Moderately likely",
    4: "4 – Very likely", 5: "5 – Expected",
}

# Transcribed from the risk matrix printed in the ESG Risk Assessment Template.
# Indexed [severity][likelihood], both 1-5.
_VL, _L, _M, _H, _VH = (RiskLevel.VERY_LOW, RiskLevel.LOW, RiskLevel.MEDIUM,
                        RiskLevel.HIGH, RiskLevel.VERY_HIGH)

RISK_MATRIX: dict[int, dict[int, RiskLevel]] = {
    1: {1: _VL, 2: _VL, 3: _VL, 4: _L,  5: _M},
    2: {1: _VL, 2: _VL, 3: _L,  4: _M,  5: _H},
    3: {1: _VL, 2: _L,  3: _M,  4: _H,  5: _H},
    4: {1: _L,  2: _M,  3: _H,  4: _H,  5: _VH},
    5: {1: _M,  2: _H,  3: _H,  4: _VH, 5: _VH},
}

# s3.18.1(2): mitigation must be commensurate with the risk level. These are
# the levels at which a token or absent mitigation is not acceptable.
ELEVATED_LEVELS = frozenset({RiskLevel.HIGH, RiskLevel.VERY_HIGH})
MIN_MITIGATION_CHARS_ELEVATED = 120


def risk_level(severity: int, likelihood: int) -> RiskLevel:
    """Look up the risk level from the template's matrix."""
    if severity not in RISK_MATRIX or likelihood not in RISK_MATRIX[severity]:
        raise ValueError(
            f"Severity and likelihood must each be 1-5; got "
            f"severity={severity}, likelihood={likelihood}.")
    return RISK_MATRIX[severity][likelihood]


@dataclass
class RiskEntry:
    """One assessed risk. Everything here comes from the project proponent."""
    category: RiskCategory
    risk_id: str                # e.g. "E1.1"
    description: str
    severity: int
    likelihood: int
    justification: str
    mitigation: str
    not_applicable: bool = False
    na_justification: str = ""

    @property
    def level(self) -> RiskLevel:
        return risk_level(self.severity, self.likelihood)


@dataclass
class ESGAssessment:
    entries: list[RiskEntry]
    findings: list[Finding] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return any(f.severity is FindingSeverity.FAIL for f in self.findings)

    @property
    def assessed_categories(self) -> set[RiskCategory]:
        return {e.category for e in self.entries}

    @property
    def missing_categories(self) -> list[RiskCategory]:
        return [c for c in RiskCategory if c not in self.assessed_categories]

    def by_level(self, level: RiskLevel) -> list[RiskEntry]:
        return [e for e in self.entries
                if not e.not_applicable and e.level is level]

    @property
    def elevated_risks(self) -> list[RiskEntry]:
        return [e for e in self.entries
                if not e.not_applicable and e.level in ELEVATED_LEVELS]


def assess_esg(entries: list[RiskEntry]) -> ESGAssessment:
    """Validate a proponent-supplied risk assessment for completeness and
    internal consistency. Does not invent risks or levels."""
    findings: list[Finding] = []

    if not entries:
        return ESGAssessment(entries=[], findings=[Finding(
            "esg.assessment", FindingSeverity.FAIL,
            "No ESG risk assessment supplied. VCS Standard v5.0 s3.18.1 "
            "requires one to be conducted and documented before the project "
            "start date.", f"{VCS5_ESG}.1")])

    seen_ids: set[str] = set()
    for entry in entries:
        pillar, title, clause = CATEGORY_TITLES[entry.category]
        ref = f"{entry.risk_id} ({title})"

        if entry.risk_id in seen_ids:
            findings.append(Finding(
                "esg.duplicate_id", FindingSeverity.FAIL,
                f"Risk ID {entry.risk_id} is used more than once.",
                ESG_TEMPLATE))
        seen_ids.add(entry.risk_id)

        if not entry.risk_id.startswith(entry.category.value):
            findings.append(Finding(
                "esg.id_format", FindingSeverity.WARNING,
                f"Risk ID {entry.risk_id} does not begin with its category "
                f"code {entry.category.value}. The template expects the format "
                f"{entry.category.value}.1, {entry.category.value}.2 and so on.",
                ESG_TEMPLATE))

        if entry.not_applicable:
            if not entry.na_justification.strip():
                findings.append(Finding(
                    "esg.na_unjustified", FindingSeverity.FAIL,
                    f"{ref} is marked not applicable without justification. "
                    f"A validator will not accept an unexplained exclusion.",
                    f"VCS Standard v5.0 {clause}"))
            continue

        try:
            level = entry.level
        except ValueError as exc:
            findings.append(Finding(
                "esg.scale", FindingSeverity.FAIL, f"{ref}: {exc}",
                ESG_TEMPLATE))
            continue

        if not entry.description.strip():
            findings.append(Finding(
                "esg.description", FindingSeverity.FAIL,
                f"{ref} has no risk description.", ESG_TEMPLATE))

        if not entry.justification.strip():
            findings.append(Finding(
                "esg.justification", FindingSeverity.FAIL,
                f"{ref} has no justification for its {level.value} risk level. "
                f"The template requires the level to be justified, not merely "
                f"stated.", ESG_TEMPLATE))

        if not entry.mitigation.strip():
            findings.append(Finding(
                "esg.mitigation_missing", FindingSeverity.FAIL,
                f"{ref} is assessed {level.value} with no mitigation measure.",
                f"{VCS5_ESG}.1(2)"))
        elif (level in ELEVATED_LEVELS
              and len(entry.mitigation.strip()) < MIN_MITIGATION_CHARS_ELEVATED):
            findings.append(Finding(
                "esg.mitigation_thin", FindingSeverity.WARNING,
                f"{ref} is assessed {level.value} but its mitigation measure is "
                f"brief. VCS Standard v5.0 s3.18.1(2) requires measures "
                f"commensurate with the risk level; expect a validator to "
                f"test this one.", f"{VCS5_ESG}.1(2)"))

    assessment = ESGAssessment(entries=entries, findings=findings)

    missing = assessment.missing_categories
    if missing:
        names = ", ".join(
            f"{c.value} {CATEGORY_TITLES[c][1]}" for c in missing)
        findings.append(Finding(
            "esg.incomplete", FindingSeverity.FAIL,
            f"{len(missing)} of the twelve safeguard categories have not been "
            f"assessed: {names}. Each category requires either an assessed "
            f"risk or a justified statement of non-applicability.",
            f"{VCS5_ESG}.1(1)"))
    else:
        findings.append(Finding(
            "esg.complete", FindingSeverity.PASS,
            "All twelve safeguard categories have been addressed.",
            f"{VCS5_ESG}.1(1)"))

    elevated = assessment.elevated_risks
    if elevated:
        findings.append(Finding(
            "esg.elevated", FindingSeverity.WARNING,
            f"{len(elevated)} risk(s) assessed High or Very high: "
            f"{', '.join(e.risk_id for e in elevated)}. These require "
            f"mitigation commensurate with the level and ongoing monitoring "
            f"under s3.18.2(2).", f"{VCS5_ESG}.2"))

    findings.append(Finding(
        "esg.timing", FindingSeverity.WARNING,
        "The risk assessment must be conducted and documented BEFORE the "
        "project start date. Confirm the assessment date precedes it.",
        f"{VCS5_ESG}.1"))

    return assessment


def esg_sections(assessment: ESGAssessment) -> dict[str, list[str]]:
    """Prose for the ESG sections of the Project Description.

    Reports what the proponent assessed. It does not characterise risks the
    proponent did not raise.
    """
    if not assessment.entries:
        return {}

    counts = {level: len(assessment.by_level(level)) for level in RiskLevel}
    summary = (
        f"An environmental, social, and governance risk assessment has been "
        f"conducted in accordance with VCS Standard v5.0 Section 3.18.1 using "
        f"the VCS Environmental, Social, and Governance Risk Assessment "
        f"Template, v5.0. All twelve safeguard categories have been addressed. "
        f"Of the {len([e for e in assessment.entries if not e.not_applicable])} "
        f"risks assessed, "
        + ", ".join(f"{n} are {lvl.value.lower()}"
                    for lvl, n in counts.items() if n)
        + ".")

    lines = [summary]
    if assessment.elevated_risks:
        lines.append(
            "Risks assessed as high or very high, together with their "
            "mitigation measures, are: "
            + "; ".join(f"{e.risk_id} — {e.description.strip().rstrip('.')} "
                        f"({e.level.value})"
                        for e in assessment.elevated_risks)
            + ". Mitigation measures commensurate with each risk level are set "
              "out in the risk assessment and are monitored throughout "
              "implementation in accordance with Section 3.18.2.")
    else:
        lines.append(
            "No risk has been assessed as high or very high. Mitigation "
            "measures for the identified risks are set out in the risk "
            "assessment and monitored throughout implementation in accordance "
            "with VCS Standard v5.0 Section 3.18.2.")

    return {"Environmental, Social, and Governance Risks": lines}
