"""Real-case tests for digest.loan_profile — the mortgage card's avg interest and rate mix."""
import digest

# The household's Discount mortgage as scraped 2026-10-29: three large tracks
# plus three subsidised מתווה tranches carried at a 0.0001% placeholder rate.
MORTGAGE = [
    {"name": 'הלוואה צמודת מדד בריבית משתנה אג"ח- דיור', "balance": 484652.12, "rate_pct": 2.09,
     "rate_type": "variable", "index_linked": True, "monthly_payment": 843.86,
     "payments_remaining": 322, "final_date": "20530810"},
    {"name": "הלואה לא צמודה ר.משתנה - דיור רגילות", "balance": 442265.25, "rate_pct": 4.35,
     "rate_type": "variable", "index_linked": False, "monthly_payment": 1600.43,
     "payments_remaining": 320, "final_date": "20530810"},
    {"name": "הלואה לא צמודה ר.קבועה - דיור", "balance": 439511.01, "rate_pct": 4.55,
     "rate_type": "fixed", "index_linked": False, "monthly_payment": 1665.43,
     "payments_remaining": 322, "final_date": "20530810"},
    {"name": "הלואה לא צמודה ר.קבועה - דיור מתווה", "balance": 14311.34, "rate_pct": 0.0001,
     "rate_type": "fixed", "monthly_payment": 461.59, "payments_remaining": 31, "final_date": "20290510"},
    {"name": "הלואה לא צמודה ר.קבועה - דיור מתווה", "balance": 20445.17, "rate_pct": 0.0001,
     "rate_type": "fixed", "monthly_payment": 659.51, "payments_remaining": 31, "final_date": "20290510"},
    {"name": "הלואה לא צמודה ר.קבועה - דיור מתווה", "balance": 18179.16, "rate_pct": 0.0001,
     "rate_type": "fixed", "monthly_payment": 586.44, "payments_remaining": 31, "final_date": "20290510"},
]


class TestLoanProfile:
    def test_mortgage_avg_rate_is_balance_weighted(self):
        p = digest.loan_profile(MORTGAGE)
        # (484,652×2.09 + 442,265×4.35 + 439,511×4.55) / 1,419,364 — not the 2.75% simple mean
        assert p["avg_rate_pct"] == 3.48
        assert p["balance"] == 1419364.05
        assert p["tracks"] == 6

    def test_monthly_payment_matches_full_next_installment(self):
        # forecast.py's "משכנתא — full next installment" for 2026-11 is ₪5,817.26
        assert digest.loan_profile(MORTGAGE)["monthly_payment"] == 5817.26

    def test_matveh_placeholder_rate_counts_as_zero(self):
        mix = digest.loan_profile(MORTGAGE)["rate_mix"]
        assert mix["zero_rate"] == round(52935.67 / 1419364.05, 4)
        assert mix["index_linked"] == round(484652.12 / 1419364.05, 4)

    def test_end_date_mixes_discount_and_leumi_formats(self):
        p = digest.loan_profile(MORTGAGE + [
            {"balance": 43894.94, "rate_pct": 8.0, "final_date": "2028-12-02"},
        ])
        assert p["final_date"] == "2053-08-10"
        assert p["payments_remaining"] == 322

    def test_empty_or_paid_off_is_none(self):
        assert digest.loan_profile([]) is None
        assert digest.loan_profile([{"balance": 0, "rate_pct": 5}]) is None
