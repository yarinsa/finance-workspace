"""Real-case tests for projection.py's loan amortization.

User story: as the household, when the lifetime net-worth chart projects my
Discount mortgage — whose tracks all end 2053-08-10 — the projected loan balance
should pay down to ₪0 by Aug 2053, not sit flat at ~₪1.37M until age 90 because
today's reduced (≈interest-only) installment was extrapolated forever.
"""
import copy

import projection

# The household's loans as scraped 2026-10 (data/digested/snapshot.json).
# The three big Discount tracks are on reduced installments right now: the 2.09%
# CPI-linked track pays ₪843.86 on ₪484,652 — interest only, it never amortizes.
LOANS = [
    {"name": 'הלוואה צמודת מדד בריבית משתנה אג"ח- דיור', "category": "mortgage",
     "balance": 484652.12, "monthly_payment": 843.86, "rate_pct": 2.09,
     "payments_remaining": 322, "final_date": "20530810"},
    {"name": "הלואה לא צמודה ר.משתנה - דיור רגילות", "category": "mortgage",
     "balance": 442265.25, "monthly_payment": 1600.43, "rate_pct": 4.35,
     "payments_remaining": 320, "final_date": "20530810"},
    {"name": "הלואה לא צמודה ר.קבועה - דיור", "category": "mortgage",
     "balance": 439511.01, "monthly_payment": 1665.43, "rate_pct": 4.55,
     "payments_remaining": 322, "final_date": "20530810"},
    {"name": "הלואה לא צמודה ר.קבועה - דיור מתווה", "category": "mortgage",
     "balance": 14311.34, "monthly_payment": 461.59, "rate_pct": 0.0001,
     "payments_remaining": 31, "final_date": "20290510"},
    {"name": "הלואה לא צמודה ר.קבועה - דיור מתווה", "category": "mortgage",
     "balance": 20445.17, "monthly_payment": 659.51, "rate_pct": 0.0001,
     "payments_remaining": 31, "final_date": "20290510"},
    {"name": "הלואה לא צמודה ר.קבועה - דיור מתווה", "category": "mortgage",
     "balance": 18179.16, "monthly_payment": 586.44, "rate_pct": 0.0001,
     "payments_remaining": 31, "final_date": "20290510"},
    {"name": "הלואה לא צמודה ברבית משתנה", "category": "consumer",
     "balance": 24393.24, "monthly_payment": 308.25, "rate_pct": 5.75,
     "payments_remaining": 99, "final_date": "20350101"},
    {"name": "הלואה לא צמודה ברבית משתנה הנתנת לשעורין", "category": "consumer",
     "balance": 15332.64, "monthly_payment": 666.72, "rate_pct": 0.0001,
     "payments_remaining": 23, "final_date": "20280901"},
    {"name": "‏ללא ריבית הצטרפות ‏ ‎2529-1/3‎", "category": "consumer",
     "balance": 43894.94, "monthly_payment": 1844.42, "rate_pct": 8.0,
     "payments_remaining": 26, "final_date": "2028-12-02"},
    {"name": "‏מילואים‏ ‎6673-1/4‎", "category": "consumer",
     "balance": 30297.77, "monthly_payment": 867.8, "rate_pct": 2.0,
     "payments_remaining": 36, "final_date": "2029-10-04"},
]

SNAPSHOT = {"totals": {"bank_balances_sum": 0, "credit_card_debt": 0}, "loans": LOANS}


def _sim():
    return projection.simulate(copy.deepcopy(SNAPSHOT))


class TestAmortizeLoans:
    def test_interest_only_track_gets_annuity_payment(self):
        # ₪484,652 at 2.09% over 322 months needs ≈₪1,967/mo, not ₪843.86.
        linked = projection.amortize_loans(LOANS)[0]
        assert 1950 < linked["payment"] < 1985

    def test_payment_that_already_amortizes_is_kept(self):
        # Leumi 2529 pays ₪1,844.42 — more than the 26-month annuity, so keep it.
        l2529 = projection.amortize_loans(LOANS)[8]
        assert l2529["payment"] == 1844.42

    def test_big_tracks_land_near_bank_schedule(self):
        # MEMORY.md: the bank's own לוח סילוקין is ~₪6,446/mo for 2030–2053.
        # Re-amortizing today over the remaining term should land within ~5%.
        big = projection.amortize_loans(LOANS)[:3]
        total = sum(l["payment"] for l in big)
        assert 6446 * 0.95 < total < 6446 * 1.05


class TestSimulateLoanPaydown:
    def test_mortgage_paid_off_by_aug_2053(self):
        # Every mortgage track's final_date is 2053-08-10; all consumer loans end
        # by 2035 — so from Sep 2053 the projected loan balance must be ₪0.
        after = [p for p in _sim()["timeline"] if p["date"] >= "2053-09-01"]
        assert after, "projection horizon should extend past 2053"
        assert all(p["loan_val"] == 0 for p in after)

    def test_total_loan_balance_falls_over_time(self):
        tl = _sim()["timeline"]
        vals = [p["loan_val"] for p in tl]
        assert all(b <= a for a, b in zip(vals, vals[1:]))
        mid = next(p["loan_val"] for p in tl if p["date"] >= "2040-01-01")
        assert mid < 1_000_000  # not flat at ~₪1.37M

    def test_every_loan_retires_as_a_payoff_event(self):
        events = [f for f in _sim()["focal_points"] if f["name"].startswith("סיום הלוואה")]
        assert len(events) == len(LOANS)


# ---------------------------------------------------------------------------
# User story (2026-10-15): as the household, with net worth at -₪1,540,121, a
# forecast month of -₪1,026 and ₪46.2k/mo spending against ₪35.6k income, the
# lifetime chart showed ₪6.56M at retirement, ₪21.9M at age 90, "growth 7.1%"
# and "balance score 90". The projection ignored the monthly deficit, had no
# living cost after retirement, and left out ₪646,524 of pension/study funds.
# ---------------------------------------------------------------------------

# snapshot.json totals as digested 2026-10-15.
HOUSEHOLD_TOTALS = {
    "bank_balances_sum": -2979.12,
    "credit_card_debt": 3859.65,
    "total_debt": 1537142.29,
    "tracked_net_position": -1540121.41,
    "long_term_savings": 646524.08,
    "liquid_savings": 2490.2,
    "illiquid_savings": 644033.88,
    "monthly_loan_service": 9504.45,
    "detected_monthly_salary": 22500,
}
HOUSEHOLD = {"totals": HOUSEHOLD_TOTALS, "loans": LOANS}

# forecast.json current_month (RiseUp budget 2026-10): income ₪27,163.80,
# expenses ₪28,189.56 -> expected net -₪1,025.76 (= cashflow.json pace.expected).
FORECAST = {"current_month": {"forecast_month": "2026-10", "based_on_budget": "2026-10",
                              "income": {"total": 27163.8},
                              "expenses": {"total": 28189.56}}}

# Fixed age so results don't drift with today's date.
BASE_CFG = {**projection.CONFIG, "current_age": 28}


def _cfg(**over):
    return {**BASE_CFG, **over}


def _household(**over):
    return projection.build(copy.deepcopy(HOUSEHOLD), _cfg(**over), forecast=FORECAST)


def _metric(p, key):
    return next(m for m in p["metrics"] if m["key"] == key)


class TestBaselineSurplus:
    def test_surplus_defaults_to_forecast_expected_net(self):
        cfg = projection.resolve_config(BASE_CFG, HOUSEHOLD, FORECAST)
        assert cfg["monthly_surplus"] == -1025.76

    def test_injected_surplus_wins_over_forecast(self):
        cfg = projection.resolve_config(_cfg(monthly_surplus=500), HOUSEHOLD, FORECAST)
        assert cfg["monthly_surplus"] == 500

    def test_negative_surplus_erodes_liquid_balance(self):
        # Same snapshot, only the surplus differs: a -₪1,026/mo month must leave
        # the liquid pool at least 12 × ₪1,026 lower after the first year.
        flat = projection.simulate(copy.deepcopy(HOUSEHOLD), _cfg(monthly_surplus=0))
        short = projection.simulate(copy.deepcopy(HOUSEHOLD), _cfg(monthly_surplus=-1025.76))
        y1 = lambda s: s["timeline"][0]["invested"]
        assert y1(flat) - y1(short) >= 12 * 1025

    def test_overdraft_costs_interest(self):
        # No loans, no savings, -₪1,000/mo: after a year the debt must exceed the
        # ₪12,000 of raw deficit because the negative balance is borrowed.
        snap = {"totals": {"bank_balances_sum": 0, "credit_card_debt": 0}, "loans": []}
        sim = projection.simulate(snap, _cfg(monthly_surplus=-1000, borrow_rate=0.08))
        assert sim["timeline"][0]["invested"] < -12_300


class TestLongTermSavings:
    def test_savings_are_in_todays_net_worth(self):
        # -1,540,121.41 tracked + 646,524.08 long-term savings.
        assert _household()["net_worth_today"] == -893597

    def test_savings_grow_at_real_return(self):
        snap = {"totals": {"bank_balances_sum": 0, "credit_card_debt": 0,
                           "long_term_savings": 644033.88, "liquid_savings": 0},
                "loans": []}
        sim = projection.simulate(snap, _cfg(monthly_surplus=0, real_return=0.04))
        y10 = sim["timeline"][9]
        assert abs(y10["savings"] - 644033.88 * (1 + 0.04 / 12) ** 120) < 1


class TestRetirementDrawdown:
    def test_default_drawdown_is_todays_spending_minus_loan_service(self):
        # Loans are gone by 67, so living cost = ₪28,189.56 - ₪9,504.45.
        cfg = projection.resolve_config(BASE_CFG, HOUSEHOLD, FORECAST)
        assert cfg["retirement_drawdown"] == 18685.11

    def test_estate_shrinks_after_retirement(self):
        p = _household()
        estate = p["focal_points"][-1]["net_val"]
        assert estate < p["net_worth_at_retirement"]


class TestHouseholdRegression:
    def test_retirement_figure_reflects_the_deficit(self):
        # The -₪1,025.76/mo forecast month must cost at least its undiscounted
        # sum over the 468 working months (it was ignored entirely before).
        with_deficit = _household()["net_worth_at_retirement"]
        no_deficit = _household(monthly_surplus=0)["net_worth_at_retirement"]
        assert no_deficit - with_deficit >= 1025.76 * 468
        assert with_deficit < 6_562_692  # the old figure, deficit-blind

    def test_age_90_estate_is_not_compounding_unchecked(self):
        # Was ₪21.9M = 3.3× the retirement figure: no living cost after 67. A
        # ₪18.7k/mo drawdown over 23 years must eat at least the pot's return.
        p = _household()
        assert p["focal_points"][-1]["net_val"] <= p["net_worth_at_retirement"]
        assert p["focal_points"][-1]["net_val"] < 21_903_065 / 3

    def test_deficit_household_does_not_score_good(self):
        score = _metric(_household(), "balance_score")
        assert score["value"] < 70 and score["rank"] != "good"  # was 90 / good

    def test_property_is_flagged_as_not_modelled(self):
        limits = " ".join(_household()["config"]["limitations"])
        assert "property" in limits.lower()


class TestMetricsOnDecline:
    """A household whose net worth falls must never read as growing/balanced."""

    def _declining(self):
        snap = {"totals": {"bank_balances_sum": 50_000, "credit_card_debt": 0}, "loans": []}
        return projection.build(snap, _cfg(monthly_surplus=-5_000, retirement_drawdown=5_000),
                                forecast=None)

    def test_growth_is_negative_and_not_good(self):
        g = _metric(self._declining(), "growth")
        assert g["value"] < 0 and g["rank"] != "good"

    def test_balance_score_is_not_good(self):
        s = _metric(self._declining(), "balance_score")
        assert s["value"] < 70 and s["rank"] != "good"

    def test_growth_is_measured_from_today(self):
        # 5 years of -₪5,000/mo from +₪50,000 at 8% overdraft cost: from today the
        # slope is about -(300k + interest)/50k/5 ≈ -130%/yr, not from year 1.
        sim = projection.simulate(
            {"totals": {"bank_balances_sum": 50_000, "credit_card_debt": 0}, "loans": []},
            _cfg(monthly_surplus=-5_000))
        g = _metric({"metrics": projection.metrics(sim, _cfg())}, "growth")
        y5 = next(p for p in sim["timeline"] if p["month"] == 60)["net_val"]
        assert g["value"] == round((y5 - 50_000) / 50_000 / 5 * 100, 1)
