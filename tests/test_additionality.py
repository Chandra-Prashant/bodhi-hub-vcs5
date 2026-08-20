"""Module 2c tests — VT0008 additionality."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.domain import constants as K
from app.domain.additionality import (
    AdditionalityVerdict,
    FinancialInputs,
    assess_additionality,
    benchmark_analysis,
    build_cashflows,
    common_practice,
    irr,
    npv,
    sensitivity_analysis,
)
from app.domain.classification import Severity


def _inputs(**overrides) -> FinancialInputs:
    """50 MW solar, 87,600 MWh/yr, INR-scale figures in lakhs."""
    base = dict(
        capex=25_000.0,
        annual_opex=500.0,
        annual_generation_mwh=87_600.0,
        tariff_per_mwh=0.0300,        # 3,000 INR/MWh expressed in lakhs
        project_lifetime_years=25,
        discount_rate=0.10,
        benchmark_irr=0.14,
        credit_price_per_tco2e=0.0080,
        annual_credits_tco2e=71_248.0,
        crediting_years=K.EI_MAX_TOTAL_CREDITING_YEARS,
    )
    base.update(overrides)
    return FinancialInputs(**base)


def _finding(findings, check):
    return next(f for f in findings if f.check == check)


# --- IRR and NPV primitives ------------------------------------------------

def test_irr_of_a_known_series():
    """-100 then 60, 60: IRR is 13.066%."""
    assert abs(irr([-100, 60, 60]) - Decimal("0.13066")) < Decimal("1e-4")


def test_irr_returns_none_for_all_positive_flows():
    assert irr([100.0, 50.0, 25.0]) is None


def test_irr_returns_none_for_all_negative_flows():
    assert irr([-100.0, -50.0]) is None


def test_npv_at_the_irr_is_zero():
    flows = [-1000, 300, 400, 500]
    assert abs(npv(flows, irr(flows))) < Decimal("1e-9")


def test_npv_discounts_from_year_zero():
    assert npv([-100, 110], "0.10") == Decimal(0)


# --- crediting period cap --------------------------------------------------

def test_credit_revenue_stops_at_fifteen_years():
    """VCS v5.0 Table 8. This is the coupling that breaks migrated ACM0002
    models, which assume 7 x 3 = 21 years."""
    inputs = _inputs()
    flows, _ = build_cashflows(inputs, include_credits=True)
    credit_revenue = inputs.annual_credits_tco2e * inputs.credit_price_per_tco2e
    assert flows[15] - flows[16] == Decimal(str(credit_revenue))


def test_requesting_21_years_is_truncated_with_a_warning():
    inputs = _inputs(crediting_years=21)
    flows, findings = build_cashflows(inputs, include_credits=True)
    assert _finding(findings, "vt0008.crediting_cap").severity is Severity.WARNING
    credit_revenue = Decimal(str(inputs.annual_credits_tco2e)) * \
        Decimal(str(inputs.credit_price_per_tco2e))
    assert flows[16] == flows[20]  # no credits after year 15
    assert flows[15] - flows[16] == credit_revenue


def test_residual_value_lands_in_the_final_year():
    inputs = _inputs(residual_value=1_000.0)
    flows, _ = build_cashflows(inputs, include_credits=False)
    assert flows[25] - flows[24] == Decimal(1_000)


# --- benchmark analysis, s5.4.2 -------------------------------------------

def test_project_below_benchmark_without_credits_is_additional():
    result = benchmark_analysis(_inputs())
    assert result.irr_without_credits < result.benchmark_irr
    assert result.passes_step3


def test_project_above_benchmark_without_credits_fails_step3():
    """A project that already clears the benchmark unaided is not additional."""
    result = benchmark_analysis(_inputs(capex=8_000.0))
    assert result.irr_without_credits > result.benchmark_irr
    assert not result.passes_step3
    assert _finding(result.findings, "vt0008.step3.benchmark").severity is Severity.FAIL


def test_credits_that_do_not_reach_the_benchmark_flag_ccp_ineligibility():
    """s5.4.2 note: still additional, but may lose CCP label eligibility."""
    result = benchmark_analysis(_inputs(credit_price_per_tco2e=0.0001))
    assert result.passes_step3
    assert not result.meets_ccp_conditions
    assert _finding(result.findings, "vt0008.step3.ccp").severity is Severity.WARNING


def test_credits_lifting_irr_above_benchmark_meet_ccp_conditions():
    result = benchmark_analysis(_inputs(credit_price_per_tco2e=0.0300))
    assert result.passes_step3
    assert result.meets_ccp_conditions


def test_uneconomic_project_with_no_sign_change_is_handled():
    result = benchmark_analysis(
        _inputs(annual_opex=10_000.0, tariff_per_mwh=0.0001))
    assert result.irr_without_credits is None
    assert result.passes_step3
    assert _finding(result.findings, "vt0008.step3.irr").severity is Severity.WARNING


# --- sensitivity, s5.4.2(3) ------------------------------------------------

def test_sensitivity_passes_for_a_clearly_uneconomic_project():
    robust, findings = sensitivity_analysis(_inputs(capex=40_000.0))
    assert robust
    assert _finding(findings, "vt0008.step3.sensitivity").severity is Severity.PASS


def test_sensitivity_catches_a_marginal_project():
    """A project sitting just under the benchmark flips when capex drops 10%."""
    inputs = _inputs(capex=25_000.0, benchmark_irr=0.075)
    robust, findings = sensitivity_analysis(inputs)
    if not robust:
        assert any(f.severity is Severity.FAIL for f in findings)


# --- common practice, s5.5.2 ----------------------------------------------

def test_f_factor_formula():
    result = common_practice(n_all=10, n_diff=2, project_capacity_mw=50.0)
    assert result.f_factor == pytest.approx(0.8)
    assert result.is_common_practice  # F 80% > 20% and 8 > 3


def test_low_f_is_not_common_practice():
    result = common_practice(n_all=10, n_diff=9, project_capacity_mw=50.0)
    assert result.f_factor == pytest.approx(0.1)
    assert not result.is_common_practice


def test_footnote_17_high_f_but_too_few_projects():
    """F = 50% but N_all - N_diff = 3, which is not MORE than 3."""
    result = common_practice(n_all=6, n_diff=3, project_capacity_mw=50.0)
    assert result.f_factor == pytest.approx(0.5)
    assert not result.is_common_practice
    assert _finding(
        result.findings, "vt0008.step4.footnote17").severity is Severity.WARNING


def test_capacity_band_is_plus_minus_fifty_percent():
    result = common_practice(n_all=0, n_diff=0, project_capacity_mw=50.0)
    msg = _finding(result.findings, "vt0008.step4.capacity_band").message
    assert "25" in msg and "75" in msg


def test_no_similar_projects_is_not_common_practice():
    result = common_practice(n_all=0, n_diff=0, project_capacity_mw=50.0)
    assert not result.is_common_practice


def test_ndiff_exceeding_nall_is_blocked():
    result = common_practice(n_all=3, n_diff=5, project_capacity_mw=50.0)
    assert _finding(result.findings, "vt0008.step4").severity is Severity.FAIL


# --- full sequence ---------------------------------------------------------

def test_additional_project_end_to_end():
    result = assess_additionality(
        _inputs(capex=40_000.0), n_all=10, n_diff=9,
        project_capacity_mw=50.0, regulatory_surplus=True)
    assert result.verdict is AdditionalityVerdict.ADDITIONAL


def test_common_practice_overrides_a_passing_investment_analysis():
    result = assess_additionality(
        _inputs(capex=40_000.0), n_all=10, n_diff=1,
        project_capacity_mw=50.0, regulatory_surplus=True)
    assert result.verdict is AdditionalityVerdict.NOT_ADDITIONAL


def test_missing_regulatory_surplus_blocks_everything():
    result = assess_additionality(
        _inputs(capex=40_000.0), n_all=10, n_diff=9,
        project_capacity_mw=50.0, regulatory_surplus=False)
    assert result.verdict is AdditionalityVerdict.NOT_ADDITIONAL
    assert _finding(
        result.findings, "vcs.regulatory_surplus").severity is Severity.FAIL


def test_barrier_analysis_exclusion_is_recorded():
    """VMR0017 s5.3.2 — must appear in the traceability record."""
    result = assess_additionality(
        _inputs(), n_all=0, n_diff=0,
        project_capacity_mw=50.0, regulatory_surplus=True)
    assert _finding(result.findings, "vt0008.barrier_analysis")


def test_all_findings_carry_a_source():
    result = assess_additionality(
        _inputs(), n_all=5, n_diff=4,
        project_capacity_mw=50.0, regulatory_surplus=True)
    assert all(f.source for f in result.findings)



# --- why this arithmetic is Decimal ---------------------------------------

def test_the_float_equivalent_is_not_exact():
    """The reason, stated as a test. In binary floating point 0.1 + 0.2 is not
    0.3, and an IRR sits on a chain of such operations."""
    assert 0.1 + 0.2 != 0.3
    assert Decimal("0.1") + Decimal("0.2") == Decimal("0.3")


def test_npv_at_zero_discount_is_the_plain_sum():
    """Exactly, with no residue. The float version leaves a remainder around
    1e-13, which is invisible until it lands next to a threshold."""
    assert npv([Decimal("0.1")] * 3, 0) == Decimal("0.3")


def test_the_verdict_is_reproducible():
    """Same inputs, same verdict, every run — the property a VVB relies on
    when re-performing a calculation."""
    inputs = _inputs()
    results = {benchmark_analysis(inputs).irr_without_credits
               for _ in range(25)}
    assert len(results) == 1


def test_a_project_exactly_at_the_benchmark_is_not_additional():
    """The boundary case. VT0008 s5.4.2(2)(a) requires the IRR to fall BELOW
    the benchmark, so equality fails the condition — and equality is only a
    meaningful concept because the comparison is exact."""
    inputs = _inputs(capex=25_000.0)
    computed = benchmark_analysis(inputs).irr_without_credits
    at_benchmark = _inputs(capex=25_000.0, benchmark_irr=computed)
    assert not benchmark_analysis(at_benchmark).passes_step3


def test_a_hair_above_the_computed_irr_passes():
    inputs = _inputs(capex=25_000.0)
    computed = benchmark_analysis(inputs).irr_without_credits
    just_above = _inputs(capex=25_000.0,
                         benchmark_irr=computed + Decimal("1e-9"))
    assert benchmark_analysis(just_above).passes_step3


def test_decimal_and_float_inputs_agree():
    """Callers pass floats through JSON; conversion goes via str() so the
    decimal value the user typed is what is used."""
    as_float = benchmark_analysis(_inputs(benchmark_irr=0.14))
    as_string = benchmark_analysis(_inputs(benchmark_irr="0.14"))
    assert as_float.benchmark_irr == as_string.benchmark_irr
    assert as_float.passes_step3 == as_string.passes_step3


# --- additionality without a known credit volume --------------------------

def test_condition_a_is_testable_without_credit_volume():
    """VT0008 s5.4.2(2)(a) tests the return WITHOUT credit revenue, so it does
    not depend on grid dispatch data. Withholding it until dispatch data
    arrives hides a result the engine can already produce."""
    result = benchmark_analysis(_inputs(annual_credits_tco2e=None))
    assert result.irr_without_credits is not None
    assert result.passes_step3 is not None


def test_the_with_credits_leg_is_omitted_rather_than_guessed():
    result = benchmark_analysis(_inputs(annual_credits_tco2e=None))
    assert result.irr_with_credits is None


def test_unknown_credits_are_not_treated_as_zero():
    """Zero credits would report irr_with_credits equal to irr_without and
    evaluate the CCP conditions against a meaningless number."""
    unknown = benchmark_analysis(_inputs(annual_credits_tco2e=None))
    zero = benchmark_analysis(_inputs(annual_credits_tco2e=0))
    assert unknown.irr_with_credits is None
    assert zero.irr_with_credits is not None


def test_the_omission_is_reported():
    result = benchmark_analysis(_inputs(annual_credits_tco2e=None))
    assert any(f.check == "vt0008.credits_unknown" for f in result.findings)


def test_ccp_is_not_claimed_without_credit_volume():
    result = benchmark_analysis(_inputs(annual_credits_tco2e=None))
    assert not result.meets_ccp_conditions


def test_an_out_of_range_return_is_reported_not_silently_dropped():
    """Mixed units make revenue thousands of times the investment; the solver
    cannot bracket the rate and previously returned None with no explanation."""
    result = benchmark_analysis(_inputs(capex=40_000.0, tariff_per_mwh=3_000.0))
    assert result.irr_without_credits is None
    assert any(f.check == "vt0008.irr_out_of_range" for f in result.findings)


# --- an unsearched count is not a favourable finding -----------------------

def test_no_search_supplied_is_not_reported_as_not_common_practice():
    """Zero means somebody looked and found none. None means nobody looked.
    Reporting the second as "not common practice" turns a missing input into a
    favourable finding."""
    from app.domain.additionality import common_practice

    result = common_practice(n_all=None, n_diff=0, project_capacity_mw=50.0)
    assert not result.assessed
    assert result.f_factor is None
    finding = next(f for f in result.findings if f.check == "vt0008.step4")
    assert finding.severity is Severity.WARNING
    assert "has not been assessed" in finding.message


def test_a_search_that_found_nothing_is_a_real_finding():
    from app.domain.additionality import common_practice

    result = common_practice(n_all=0, n_diff=0, project_capacity_mw=50.0)
    assert result.assessed
    assert result.f_factor == 0.0
    finding = next(f for f in result.findings if f.check == "vt0008.step4")
    assert finding.severity is Severity.PASS


def test_the_two_cases_are_distinguishable_downstream():
    from app.domain.additionality import common_practice

    unsearched = common_practice(n_all=None, n_diff=0, project_capacity_mw=50.0)
    searched = common_practice(n_all=0, n_diff=0, project_capacity_mw=50.0)
    assert unsearched.assessed is not searched.assessed
