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
