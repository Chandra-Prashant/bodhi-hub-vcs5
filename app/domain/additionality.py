"""
Module 2c — Additionality (VT0008 v1.0).

VMR0017 v1.0 s5.3.2 removes Step 2 (barrier analysis) from the available
routes. The sequence for a grid-connected solar or wind project is therefore:

    Step 1  Identification of alternative scenarios  (supplied by VMR0017)
    Step 3  Investment analysis  -- benchmark analysis, VT0008 s5.4.2
    Step 4  Common practice analysis, VT0008 s5.5.2

VT0008 s5.4.2 mandates the IRR (project or equity) as the financial indicator
for benchmark analysis, and footnote 11 names a grid-connected solar power
plant as the archetypal case for it.

CRITICAL COUPLING: the credit revenue stream must terminate at the VCS v5.0
E&I crediting cap -- 5 years, renewable twice, 15 years maximum (VCS Standard
v5.0 Table 8). A model carrying 21 years of credit revenue, as older ACM0002
PDDs do, overstates the with-credits IRR and can flip a genuinely additional
project into a non-additional verdict, or vice versa. `build_cashflows`
enforces the cap.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, getcontext
from enum import Enum

# The additionality verdict is a comparison of IRR against a benchmark. A
# project sitting near the benchmark flips on a difference far smaller than
# binary floating point can represent reliably — structurally the same failure
# the PRD describes for profit and loss, where "a single wrong calculation can
# flip a farm's profit/loss outcome".
#
# So the arithmetic that produces the verdict is Decimal end to end. Callers
# may still pass floats (JSON has no other numeric type) and they are converted
# through str(), which recovers the decimal value the user actually typed
# rather than the binary approximation stored for it.
getcontext().prec = 34


def _d(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    # str() first: Decimal(0.1) is 0.1000000000000000055511151231257827,
    # Decimal(str(0.1)) is exactly 0.1.
    return Decimal(str(value))

from app.domain import constants as K
from app.domain.classification import Finding, Severity

VT0008 = "VT0008 v1.0"
VMR0017_ADD = "VMR0017 v1.0 s5.3.2"


class AdditionalityVerdict(str, Enum):
    ADDITIONAL = "ADDITIONAL"
    NOT_ADDITIONAL = "NOT_ADDITIONAL"
    INCONCLUSIVE = "INCONCLUSIVE"


@dataclass
class FinancialInputs:
    """Project financial model inputs, all in one currency."""
    capex: float                          # total upfront capital cost
    annual_opex: float                    # operating and maintenance cost
    annual_generation_mwh: float
    tariff_per_mwh: float                 # power purchase agreement price
    project_lifetime_years: int           # technical life (may exceed crediting)
    discount_rate: float                  # for NPV
    benchmark_irr: float                  # required financial benchmark
    credit_price_per_tco2e: float = 0.0
    # None means "not yet known" — distinct from zero. Without grid dispatch
    # data there is no credit volume, but condition (a) of VT0008 s5.4.2 is the
    # return WITHOUT credit revenue and can still be tested. Treating unknown
    # as zero would silently report irr_with_credits equal to irr_without and
    # evaluate the CCP conditions against a number that means nothing.
    annual_credits_tco2e: float | None = 0.0
    crediting_years: int = K.EI_MAX_TOTAL_CREDITING_YEARS
    residual_value: float = 0.0


IRR_TOLERANCE = Decimal("1e-12")


def irr(cashflows, tol: Decimal | None = None,
        max_iter: int = 400) -> Decimal | None:
    """Internal rate of return by bisection, in Decimal.

    Bisection rather than Newton: it cannot diverge, and a financial figure a
    VVB will scrutinise should fail by returning None rather than silently
    landing on a spurious root.

    The tolerance is tighter than the float version could meaningfully hold —
    the point is that a project whose IRR differs from the benchmark in the
    ninth decimal place gets the same verdict every run, on every machine.
    """
    flows = [_d(c) for c in cashflows]
    tol = tol if tol is not None else IRR_TOLERANCE

    if not flows or all(c >= 0 for c in flows) or all(c <= 0 for c in flows):
        return None

    def npv_at(rate: Decimal) -> Decimal:
        return sum((cf / (Decimal(1) + rate) ** t
                    for t, cf in enumerate(flows)), Decimal(0))

    low, high = Decimal("-0.9999"), Decimal(10)
    f_low, f_high = npv_at(low), npv_at(high)
    if f_low * f_high > 0:
        return None

    two = Decimal(2)
    for _ in range(max_iter):
        mid = (low + high) / two
        f_mid = npv_at(mid)
        if abs(f_mid) < tol or (high - low) < tol:
            return mid
        if f_low * f_mid < 0:
            high, f_high = mid, f_mid
        else:
            low, f_low = mid, f_mid
    return (low + high) / two


def npv(cashflows, discount_rate) -> Decimal:
    rate = _d(discount_rate)
    return sum((_d(cf) / (Decimal(1) + rate) ** t
                for t, cf in enumerate(cashflows)), Decimal(0))


def build_cashflows(
    inputs: FinancialInputs,
    include_credits: bool,
) -> tuple[list[Decimal], list[Finding]]:
    """Year 0 is capex; years 1..N are net operating cashflow.

    Credit revenue is truncated at the VCS v5.0 E&I crediting cap even when
    the caller asks for more.
    """
    findings: list[Finding] = []
    crediting_years = inputs.crediting_years

    if crediting_years > K.EI_MAX_TOTAL_CREDITING_YEARS:
        findings.append(Finding(
            "vt0008.crediting_cap", Severity.WARNING,
            f"Credit revenue requested for {crediting_years} years; truncated "
            f"to the E&I maximum of {K.EI_MAX_TOTAL_CREDITING_YEARS}.",
            K.CREDITING_PERIOD_SOURCE))
        crediting_years = K.EI_MAX_TOTAL_CREDITING_YEARS

    energy_revenue = _d(inputs.annual_generation_mwh) * _d(inputs.tariff_per_mwh)
    credit_revenue = (
        Decimal(0) if inputs.annual_credits_tco2e is None
        else _d(inputs.annual_credits_tco2e) * _d(inputs.credit_price_per_tco2e))
    opex = _d(inputs.annual_opex)
    residual = _d(inputs.residual_value)

    flows = [-_d(inputs.capex)]
    for year in range(1, inputs.project_lifetime_years + 1):
        cf = energy_revenue - opex
        if include_credits and year <= crediting_years:
            cf += credit_revenue
        if year == inputs.project_lifetime_years:
            cf += residual
        flows.append(cf)

    return flows, findings


@dataclass
class InvestmentAnalysisResult:
    """Figures are Decimal. Convert at a display boundary if a float is needed —
    the comparison that decides additionality has already happened by then."""

    irr_without_credits: Decimal | None
    irr_with_credits: Decimal | None
    npv_without_credits: Decimal
    npv_with_credits: Decimal
    benchmark_irr: Decimal
    passes_step3: bool           # s5.4.2(2)(a) — the additionality condition
    meets_ccp_conditions: bool   # s5.4.2(2)(b) and (c) — CCP label eligibility
    findings: list[Finding] = field(default_factory=list)


def benchmark_analysis(inputs: FinancialInputs) -> InvestmentAnalysisResult:
    """VT0008 s5.4.2.

    (2)(a) the project would not meet the benchmark without credit revenue
           -> this alone establishes additionality
    (2)(b) economic performance increases decisively with credit revenue
    (2)(c) credit revenue raises the indicator to or above the benchmark

    Per the note in s5.4.2: meeting (a) but not (b) and (c) is still
    additional, but the project may not be eligible for CCP labels.
    """
    flows_without, findings = build_cashflows(inputs, include_credits=False)
    flows_with, with_findings = build_cashflows(inputs, include_credits=True)
    findings.extend(f for f in with_findings if f not in findings)

    irr_without = irr(flows_without)
    credits_known = inputs.annual_credits_tco2e is not None
    irr_with = irr(flows_with) if credits_known else None
    npv_without = npv(flows_without, inputs.discount_rate)
    npv_with = npv(flows_with, inputs.discount_rate)
    benchmark = _d(inputs.benchmark_irr)

    if irr_without is None and any(c > 0 for c in flows_without) \
            and any(c < 0 for c in flows_without):
        # The cashflows do change sign, so a rate exists — it simply lies
        # outside the search range. In practice that means the inputs are on
        # different scales: capital cost in lakh against a tariff in rupees,
        # for instance, which makes revenue thousands of times the investment.
        findings.append(Finding(
            "vt0008.irr_out_of_range", Severity.FAIL,
            "The project return could not be computed: it lies outside a "
            "plausible range (-99% to 1000%). Check that capital cost, "
            "operating cost and tariff are all stated in the same units — a "
            "cost in lakh against a tariff in rupees produces exactly this.",
            f"{VT0008} s5.4.2"))

    if irr_without is None:
        findings.append(Finding(
            "vt0008.step3.irr", Severity.WARNING,
            "IRR without credit revenue is undefined — the cashflow series "
            "never changes sign. The project is uneconomic on any benchmark; "
            "state this explicitly in the PDD rather than reporting no IRR.",
            f"{VT0008} s5.4.2"))
        passes = True
    else:
        passes = irr_without < benchmark
        findings.append(Finding(
            "vt0008.step3.benchmark", Severity.PASS if passes else Severity.FAIL,
            f"IRR without credits {irr_without:.2%} vs benchmark "
            f"{benchmark:.2%} — condition (a) "
            f"{'met' if passes else 'NOT met'}.", f"{VT0008} s5.4.2(2)(a)"))

    ccp_b = (irr_with is not None and irr_without is not None
             and irr_with > irr_without)
    if not credits_known:
        findings.append(Finding(
            "vt0008.credits_unknown", Severity.WARNING,
            "Credit volume is not yet known, so the return with credit revenue "
            "and the CCP conditions (b) and (c) could not be tested. Condition "
            "(a), which governs additionality itself, does not depend on it. "
            "Supply the grid dispatch data to complete the analysis.",
            f"{VT0008} s5.4.2(2)"))

    ccp_c = credits_known and irr_with is not None and irr_with >= benchmark
    meets_ccp = bool(ccp_b and ccp_c)

    if passes and not meets_ccp:
        with_txt = "undefined" if irr_with is None else f"{irr_with:.2%}"
        findings.append(Finding(
            "vt0008.step3.ccp", Severity.WARNING,
            f"Conditions (b)/(c) not both met (IRR with credits "
            f"{with_txt} vs benchmark {benchmark:.2%}). The "
            f"project remains additional but may be ineligible for CCP labels.",
            f"{VT0008} s5.4.2 note"))
    elif meets_ccp:
        findings.append(Finding(
            "vt0008.step3.ccp", Severity.PASS,
            f"Credit revenue lifts the IRR from "
            f"{irr_without:.2%} to {irr_with:.2%}, at or above the benchmark; "
            f"conditions (b) and (c) met.", f"{VT0008} s5.4.2(2)(b),(c)"))

    return InvestmentAnalysisResult(
        irr_without_credits=irr_without,
        irr_with_credits=irr_with,
        npv_without_credits=npv_without,
        npv_with_credits=npv_with,
        benchmark_irr=benchmark,
        passes_step3=passes,
        meets_ccp_conditions=meets_ccp,
        findings=findings,
    )


def sensitivity_analysis(
    inputs: FinancialInputs,
    variations: dict[str, float] | None = None,
) -> tuple[bool, list[Finding]]:
    """VT0008 s5.4.2(3) — condition (2)(a) must hold under reasonable
    variations in the critical assumptions.

    Default +/-10% on capex, opex, tariff and generation. A single variation
    that flips the verdict makes the whole analysis unusable, so this returns
    robust=False rather than a pass rate.
    """
    variations = variations or {
        "capex": 0.10, "annual_opex": 0.10,
        "tariff_per_mwh": 0.10, "annual_generation_mwh": 0.10,
    }
    findings: list[Finding] = []
    robust = True

    for field_name, delta in variations.items():
        step = _d(delta)
        for direction, label in ((Decimal(1) + step, "+"),
                                 (Decimal(1) - step, "-")):
            perturbed = FinancialInputs(**{
                **inputs.__dict__,
                field_name: _d(getattr(inputs, field_name)) * direction,
            })
            result = benchmark_analysis(perturbed)
            if not result.passes_step3:
                robust = False
                findings.append(Finding(
                    "vt0008.step3.sensitivity", Severity.FAIL,
                    f"{label}{delta:.0%} on {field_name}: IRR without credits "
                    f"reaches {result.irr_without_credits:.2%}, meeting the "
                    f"{_d(inputs.benchmark_irr):.2%} benchmark. Condition (a) "
                    f"fails under this variation.", f"{VT0008} s5.4.2(3)"))

    if robust:
        findings.append(Finding(
            "vt0008.step3.sensitivity", Severity.PASS,
            f"Condition (a) holds across all "
            f"{2 * len(variations)} variations tested.", f"{VT0008} s5.4.2(3)"))

    return robust, findings


@dataclass
class CommonPracticeResult:
    n_all: int
    n_diff: int
    f_factor: float | None
    is_common_practice: bool

    @property
    def assessed(self) -> bool:
        """False when no search has been supplied — distinct from a search
        that found nothing."""
        return self.n_all is not None
    findings: list[Finding] = field(default_factory=list)


def common_practice(
    n_all: int | None,
    n_diff: int,
    project_capacity_mw: float,
) -> CommonPracticeResult:
    """VT0008 s5.5.2.

        F = 1 - N_diff / N_all

    Common practice where F > 20% AND (N_all - N_diff) > 3. Footnote 17 is
    explicit: F above 20% with (N_all - N_diff) of 3 or less is NOT common
    practice. Both conditions must hold.

    The caller supplies N_all and N_diff from the similar-project search over
    the +/-50% capacity band around the project's design capacity (s5.5.2(1)).
    """
    findings: list[Finding] = []
    band = (project_capacity_mw * 0.5, project_capacity_mw * 1.5)
    findings.append(Finding(
        "vt0008.step4.capacity_band", Severity.PASS,
        f"Similar-project capacity band is {band[0]:g}–{band[1]:g} MW "
        f"(±50% of {project_capacity_mw:g} MW).", f"{VT0008} s5.5.2(1)"))

    if n_all is None:
        # Not the same as zero. Zero means somebody searched and found none;
        # None means nobody has searched yet. Reporting the second as "not
        # common practice" turns a missing input into a favourable finding —
        # the failure mode this whole engine exists to prevent.
        findings.append(Finding(
            "vt0008.step4", Severity.WARNING,
            "Common practice has not been assessed: the count of similar "
            "projects in the applicable geography has not been supplied. This "
            "is a search the proponent performs; it cannot be inferred from a "
            "project document, and its absence is not evidence that no similar "
            "projects exist.",
            f"{VT0008} s5.5.2"))
        return CommonPracticeResult(None, n_diff, None, False, findings)

    if n_all <= 0:
        findings.append(Finding(
            "vt0008.step4", Severity.PASS,
            "No similar projects identified in the applicable geography; not "
            "common practice.",
            f"{VT0008} s5.5.2"))
        return CommonPracticeResult(n_all, n_diff, 0.0, False, findings)

    if n_diff > n_all:
        findings.append(Finding(
            "vt0008.step4", Severity.FAIL,
            f"N_diff ({n_diff}) cannot exceed N_all ({n_all}).",
            f"{VT0008} s5.5.2"))
        return CommonPracticeResult(n_all, n_diff, 0.0, False, findings)

    f = 1.0 - (n_diff / n_all)
    remainder = n_all - n_diff
    is_cp = (f > K.COMMON_PRACTICE_F_THRESHOLD
             and remainder > K.COMMON_PRACTICE_MIN_SIMILAR_PROJECTS)

    findings.append(Finding(
        "vt0008.step4", Severity.FAIL if is_cp else Severity.PASS,
        f"F = 1 − {n_diff}/{n_all} = {f:.1%}; N_all − N_diff = {remainder}. "
        f"{'Common practice — not additional.' if is_cp else 'Not common practice.'}",
        K.COMMON_PRACTICE_SOURCE))

    if f > K.COMMON_PRACTICE_F_THRESHOLD and not is_cp:
        findings.append(Finding(
            "vt0008.step4.footnote17", Severity.WARNING,
            f"F exceeds 20% but N_all − N_diff is {remainder} (not more than "
            f"{K.COMMON_PRACTICE_MIN_SIMILAR_PROJECTS}), so footnote 17 "
            f"applies and the project is not common practice. Expect the VVB "
            f"to test this.", K.COMMON_PRACTICE_SOURCE))

    return CommonPracticeResult(n_all, n_diff, f, is_cp, findings)


@dataclass
class AdditionalityResult:
    verdict: AdditionalityVerdict
    investment: InvestmentAnalysisResult
    sensitivity_robust: bool
    common_practice_result: CommonPracticeResult
    findings: list[Finding] = field(default_factory=list)


def assess_additionality(
    inputs: FinancialInputs,
    n_all: int | None,
    n_diff: int,
    project_capacity_mw: float,
    regulatory_surplus: bool,
) -> AdditionalityResult:
    """Full VT0008 sequence as narrowed by VMR0017 s5.3.2 (no barrier analysis)."""
    findings: list[Finding] = []

    if not K.BARRIER_ANALYSIS_ALLOWED_UNDER_VMR0017:
        findings.append(Finding(
            "vt0008.barrier_analysis", Severity.PASS,
            "Barrier analysis (Step 2) is not available under VMR0017; the "
            "assessment runs regulatory surplus → investment analysis → "
            "common practice.", VMR0017_ADD))

    investment = benchmark_analysis(inputs)
    robust, sens_findings = sensitivity_analysis(inputs)
    cp = common_practice(n_all, n_diff, project_capacity_mw)
    findings.extend([*investment.findings, *sens_findings, *cp.findings])

    if not regulatory_surplus:
        findings.append(Finding(
            "vcs.regulatory_surplus", Severity.FAIL,
            "Regulatory surplus not demonstrated: the activity is mandated by "
            "law or regulation that is systematically enforced.",
            "VCS Standard v5.0 / VT0008 s3"))
        verdict = AdditionalityVerdict.NOT_ADDITIONAL
    elif cp.is_common_practice:
        verdict = AdditionalityVerdict.NOT_ADDITIONAL
    elif not investment.passes_step3:
        verdict = AdditionalityVerdict.NOT_ADDITIONAL
    elif not robust:
        findings.append(Finding(
            "vt0008.verdict", Severity.WARNING,
            "Investment analysis passes at central assumptions but fails under "
            "sensitivity. Not defensible at validation without revised "
            "assumptions.", f"{VT0008} s5.4.2(3)"))
        verdict = AdditionalityVerdict.INCONCLUSIVE
    else:
        verdict = AdditionalityVerdict.ADDITIONAL

    findings.append(Finding(
        "vt0008.verdict", Severity.PASS
        if verdict is AdditionalityVerdict.ADDITIONAL else Severity.FAIL,
        f"Additionality verdict: {verdict.value}.", VT0008))

    return AdditionalityResult(
        verdict=verdict,
        investment=investment,
        sensitivity_robust=robust,
        common_practice_result=cp,
        findings=findings,
    )
