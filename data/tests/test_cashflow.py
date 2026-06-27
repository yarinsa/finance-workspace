"""Real-case tests for cashflow.py bucketing and monthly aggregation."""
import cashflow


class TestBucketing:
    def test_loan_categories_map_to_loans_bucket(self):
        assert cashflow._expense_bucket("הלוואה") == "loans"
        assert cashflow._expense_bucket("משכנתא") == "loans"
        assert cashflow._expense_bucket("תשלומים") == "loans"

    def test_unmapped_expense_falls_through_to_running(self):
        assert cashflow._expense_bucket("uncategorized") == "running"
        assert cashflow._expense_bucket(None) == "running"

    def test_benefits_income_is_classified(self):
        assert cashflow._income_bucket("ביטוח לאומי") == "benefits"
        assert cashflow._income_bucket(None) == "work"     # default income bucket


class TestAggregateByMonth:
    def test_groups_by_year_month_and_splits_income_expense(self):
        months = cashflow.aggregate_by_month([
            {"date": "2026-06-01", "amount": 20000.0, "is_income": True, "category": "work"},
            {"date": "2026-06-05", "amount": -1200.0, "category": "uncategorized"},
            {"date": "2026-05-20", "amount": -300.0, "category": "uncategorized"},
        ])
        assert set(months) == {"2026-05", "2026-06"}
        jun = months["2026-06"]
        assert jun["income"] == 20000.0
        assert jun["expense"] == 1200.0
        assert jun["net"] == 18800.0

    def test_excluded_rows_are_skipped(self):
        months = cashflow.aggregate_by_month([
            {"date": "2026-06-01", "amount": -8000.0, "card_bill_payment": True},
            {"date": "2026-06-02", "amount": -5000.0, "internal_transfer": True},
            {"date": "2026-06-03", "amount": -100.0, "category": "uncategorized"},
        ])
        assert months["2026-06"]["expense"] == 100.0
        assert months["2026-06"]["count"] == 1

    def test_savings_is_separated_from_expense_but_stays_in_net(self):
        months = cashflow.aggregate_by_month([
            {"date": "2026-06-01", "amount": 10000.0, "is_income": True, "category": "work"},
            {"date": "2026-06-02", "amount": -2000.0, "savings": True, "category": "השקעה וחיסכון"},
        ])
        jun = months["2026-06"]
        assert jun["saved"] == 2000.0
        assert jun["expense"] == 0.0
        assert jun["net"] == 8000.0          # savings still left the account

    def test_rows_without_a_usable_date_are_dropped(self):
        months = cashflow.aggregate_by_month([
            {"date": "", "amount": -100.0},
            {"amount": -100.0},
        ])
        assert months == {}


class TestPickCurrentMonth:
    def test_picks_latest_complete_month_not_the_accruing_one(self, monkeypatch):
        # Freeze "now" to 2026-06 so the result is deterministic: 06 is still
        # accruing, so the latest *complete* month is 05.
        class _Now:
            @staticmethod
            def now(tz=None):
                from datetime import datetime as real
                return real(2026, 6, 15)
        monkeypatch.setattr(cashflow, "datetime", _Now)
        months = {"2026-04": {}, "2026-05": {}, "2026-06": {}}
        assert cashflow.pick_current_month(months) == "2026-05"

    def test_none_when_empty(self):
        assert cashflow.pick_current_month({}) is None
