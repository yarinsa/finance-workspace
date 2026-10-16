"""Real-case tests for forecast fixed-bill hygiene and the bank's mortgage schedule.

Bug stories (2026-10-15 dashboard audit):
- As the household, when I see `הו"ק לששון ירין,לסניף 11-034` for ₪452 among the
  forecast's fixed bills, it should be dropped: it's a standing order from our
  personal Discount account to our own business account (which then pays the AMEX
  bills already counted in the ledger), not a cost.
- As the household, the Jan-2027 forecast mortgage line should step up from ~₪5.8k
  to ~₪8.3k, per the bank's own amortization schedule (לוח סילוקין) — not carry
  the current installment forward forever.
"""
import forecast
import projection

# The bank's schedule as supplied by the user on 2026-09-06 (see MEMORY.md).
SCHEDULE = [
    {"from": "2026-09", "to": "2026-12", "payment": 5717},
    {"from": "2027-01", "to": "2027-01", "payment": 8190},
    {"from": "2027-02", "to": "2028-12", "payment": 8154},
    {"from": "2029-01", "to": "2029-12", "payment": 7158},
    {"from": "2030-01", "to": "2053-08", "payment": 6446},
]


class TestFixedBillSelfTransfer:
    def test_standing_order_to_own_business_account_is_dropped(self):
        assert forecast.is_internal_fixed({"name": 'הו"ק לששון ירין,לסניף 11-034', "amount": 452})

    def test_rent_standing_order_is_kept(self):
        assert not forecast.is_internal_fixed({"name": 'הו"ק לעיין ניהול נכסי,לסניף 20-406', "amount": 6800})

    def test_loan_repayment_is_kept(self):
        assert not forecast.is_internal_fixed({"name": "פירעון הלוואה 10800100014", "amount": 666.72})


class TestScheduledPayment:
    def test_lookup_inside_and_outside_the_schedule(self):
        assert forecast.scheduled_payment(SCHEDULE, "2026-11") == 5717
        assert forecast.scheduled_payment(SCHEDULE, "2027-01") == 8190
        assert forecast.scheduled_payment(SCHEDULE, "2031-06") == 6446
        assert forecast.scheduled_payment(SCHEDULE, "2053-09") == 0.0   # paid off
        assert forecast.scheduled_payment(SCHEDULE, "2026-08") is None  # before it starts
        assert forecast.scheduled_payment([], "2027-01") is None

    def test_step_up_keeps_the_index_linkage_offset(self):
        # Today's real installment (5,817.26 from the dump) runs ~₪100 over the
        # schedule's 5,717 — index linkage on the 2.09% linked track. Carry that
        # offset into Jan 2027 rather than snapping to the schedule's base figure.
        jan = forecast.schedule_adjusted(5817.26, "2026-11", "2027-01", SCHEDULE)
        assert jan == round(5817.26 + 8190 - 5717, 2)

    def test_same_band_and_no_schedule_fall_back_to_current(self):
        assert forecast.schedule_adjusted(5817.26, "2026-11", "2026-12", SCHEDULE) == 5817.26
        assert forecast.schedule_adjusted(5817.26, "2026-11", "2027-01", []) == 5817.26

    def test_after_final_payment_mortgage_costs_nothing(self):
        assert forecast.schedule_adjusted(5817.26, "2026-11", "2053-09", SCHEDULE) == 0.0


class TestProjectionUsesSchedule:
    SNAPSHOT = {
        "totals": {"bank_balances_sum": 0, "credit_card_debt": 0, "long_term_savings": 0,
                   "liquid_savings": 0, "illiquid_savings": 0},
        "loans": [{"name": "דיור", "category": "mortgage", "balance": 1_400_000,
                   "rate_pct": 3.5, "monthly_payment": 5817.26, "payments_remaining": 322}],
    }
    CFG = {**projection.CONFIG, "monthly_surplus": 0, "retirement_drawdown": 0,
           "real_return": 0.0, "borrow_rate": 0.0}

    def test_mortgage_cash_follows_the_bank_schedule(self):
        cfg = {**self.CFG, "mortgage_schedule": SCHEDULE, "start_month": "2026-11"}
        sim = projection.simulate(self.SNAPSHOT, cfg)
        cash = {r["month"]: r["mortgage_paid"] for r in sim["mortgage_cash"]}
        assert cash[1] == 5817.26                          # Dec 2026: current band
        assert cash[2] == round(5817.26 + 8190 - 5717, 2)  # Jan 2027 step-up
        assert cash[3] == round(5817.26 + 8154 - 5717, 2)  # Feb 2027
