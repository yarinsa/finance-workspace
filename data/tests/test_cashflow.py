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


def _freeze_now(monkeypatch, year, month, day):
    """Patch cashflow.datetime so now() returns a fixed date."""
    class _Now:
        @staticmethod
        def now(tz=None):
            from datetime import datetime as real, timezone
            dt = real(year, month, day)
            if tz is not None:
                dt = real(year, month, day, tzinfo=timezone.utc)
            return dt
    monkeypatch.setattr(cashflow, "datetime", _Now)


class TestPickCurrentMonth:
    def test_returns_current_calendar_month_when_it_has_data(self, monkeypatch):
        # Real case: 2026-07-26, July has 157 transactions — should return July,
        # not June. The old "always exclude current calendar month" design was
        # systematically one month behind whenever the current month was active.
        _freeze_now(monkeypatch, 2026, 7, 26)
        months = {
            "2026-05": {"count": 94},
            "2026-06": {"count": 152},
            "2026-07": {"count": 157},
        }
        assert cashflow.pick_current_month(months) == "2026-07"

    def test_falls_back_to_previous_month_when_current_month_is_empty(self, monkeypatch):
        # First day of the month: the current month has no transactions yet.
        # Fall back to the previous (complete) month.
        _freeze_now(monkeypatch, 2026, 7, 1)
        months = {
            "2026-05": {"count": 94},
            "2026-06": {"count": 152},
            # 2026-07 absent: no data yet
        }
        assert cashflow.pick_current_month(months) == "2026-06"

    def test_none_when_empty(self):
        assert cashflow.pick_current_month({}) is None


class TestBuildPace:
    """Wallet header: month-to-date vs. the previous month cut at the same day."""

    def test_previous_month_is_cut_at_same_day_not_compared_in_full(self):
        # Real case (2026-10-15): October looked ₪40k "better" than September
        # only because September was compared whole. Cut both at day 15.
        pace = cashflow.build_pace([
            {"date": "2026-10-09", "amount": -12.0, "description": "ביתא", "category": "פנאי"},
            {"date": "2026-10-15", "amount": -500.0, "category": "uncategorized"},
            {"date": "2026-09-10", "amount": -800.0, "category": "uncategorized"},
            {"date": "2026-09-28", "amount": -6800.0, "description": 'הו"ק לעיין ניהול נכסי', "category": "דיור"},
        ], "2026-10")
        assert pace["as_of_day"] == 15
        assert pace["current"]["expense"] == 512.0
        assert pace["previous"]["expense"] == 800.0          # rent on the 28th excluded
        assert pace["previous"]["month_expense"] == 7600.0   # but still visible as full month
        assert len(pace["current"]["daily_expense"]) == 15
        assert len(pace["previous"]["daily_expense"]) == 30
        assert pace["current"]["daily_expense"][8] == 12.0   # cumulative on the 9th

    def test_transfers_card_bills_and_savings_are_not_pace(self):
        pace = cashflow.build_pace([
            {"date": "2026-10-02", "amount": -8000.0, "card_bill_payment": True},
            {"date": "2026-10-02", "amount": -5000.0, "internal_transfer": True},
            {"date": "2026-10-03", "amount": -1000.0, "savings": True},
            {"date": "2026-10-04", "amount": 26428.43, "description": "העברת משכורת", "is_income": True},
        ], "2026-10")
        assert pace["current"]["expense"] == 0.0
        assert pace["current"]["income"] == 26428.43

    def test_day_31_clamps_to_shorter_previous_month(self):
        pace = cashflow.build_pace([
            {"date": "2026-10-31", "amount": -10.0},
            {"date": "2026-09-30", "amount": -20.0},
        ], "2026-10")
        assert pace["previous"]["expense"] == 20.0

    def test_january_compares_to_previous_december(self):
        pace = cashflow.build_pace([
            {"date": "2027-01-05", "amount": -10.0},
            {"date": "2026-12-03", "amount": -20.0},
        ], "2027-01")
        assert pace["previous"]["month"] == "2026-12"
        assert pace["previous"]["expense"] == 20.0
