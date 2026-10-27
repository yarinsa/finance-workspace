"""Real-case tests for cashflow.py bucketing and monthly aggregation."""
from datetime import date

import cashflow


class TestBucketing:
    def test_loan_categories_map_to_loans_bucket(self):
        assert cashflow._expense_bucket("הלוואה") == "loans"
        assert cashflow._expense_bucket("משכנתא") == "loans"

    def test_an_installment_is_running_spend_not_a_loan(self):
        # Metro Motor's ₪500 installment is the motorcycle (רכב); "תשלומים" was only
        # RiseUp saying how it was paid, and is no category any more.
        assert cashflow._expense_bucket("רכב") == "running"
        assert cashflow._expense_bucket("תשלומים") == "running"

    def test_taxes_and_fees(self):
        assert cashflow._expense_bucket("מס הכנסה") == "taxes"
        assert cashflow._expense_bucket("עמלות") == "taxes"

    def test_unmapped_expense_falls_through_to_running(self):
        assert cashflow._expense_bucket("uncategorized") == "running"
        assert cashflow._expense_bucket(None) == "running"

    def test_only_pay_is_work_income(self):
        assert cashflow._income_bucket("משכורת") == "work"        # העברת משכורת ₪26,144
        assert cashflow._income_bucket("מילואים") == "work"       # מענק מילוא ₪5,808
        assert cashflow._income_bucket("ביטוח לאומי") == "benefits"
        # the ₪4,000 אקסלנס withdrawal and the ₪3,400 rent share are not pay
        assert cashflow._income_bucket("השקעה וחיסכון") == "other"
        assert cashflow._income_bucket("העברות") == "other"
        assert cashflow._income_bucket(None) == "other"


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


class TestPaceFutureDatedRows:
    """As the household, on 2026-10-15 the Overview said "נכון ל-29 באוקטובר ·
    94% מהחודש עבר": RiseUp emits October rows dated later in the month (card
    billing dates), and as_of_day was taken from the latest row in the ledger."""

    TODAY = date(2026, 10, 15)
    ROWS = [
        {"date": "2026-10-04", "amount": 26428.43, "description": "העברת משכורת", "is_income": True},
        {"date": "2026-10-15", "amount": -500.0, "category": "uncategorized"},
        {"date": "2026-10-22", "amount": 250.29, "description": "מטרו"},
        {"date": "2026-10-29", "amount": -230.75, "description": "ח.י אלקטרוניקה -טרקלין חש"},
        {"date": "2026-10-29", "amount": -105.0, "description": "מחסני חשמל-אילת"},
        {"date": "2026-09-10", "amount": -800.0, "category": "uncategorized"},
        {"date": "2026-09-28", "amount": -6800.0, "description": 'הו"ק לעיין ניהול נכסי'},
        {"date": "2026-08-12", "amount": -400.0, "category": "uncategorized"},
        {"date": "2026-08-20", "amount": -3000.0, "category": "uncategorized"},
    ]

    def pace(self, rows=None, key="2026-10", today=TODAY):
        return cashflow.build_pace(self.ROWS if rows is None else rows, key, today=today)

    def test_as_of_day_is_capped_at_today(self):
        p = self.pace()
        assert p["as_of_day"] == 15
        assert len(p["current"]["daily_expense"]) == 15

    def test_future_dated_rows_are_not_month_to_date_yet(self):
        cur = self.pace()["current"]
        assert cur["expense"] == 500.0            # not + 230.75 + 105 (29th)
        assert cur["income"] == 26428.43          # not + 250.29 מטרו (22nd)
        assert cur["month_expense"] == 500.0

    def test_previous_and_average_cut_at_the_capped_day(self):
        p = self.pace()
        assert p["previous"]["expense"] == 800.0   # rent on 09-28 is after day 15
        assert p["average"]["expense"] == 600.0    # (800 + 400) / 2, both cut at 15

    def test_stale_ledger_still_uses_its_own_latest_date(self):
        # Last scrape cleared through the 10th — compare 1–10, not 1–15.
        rows = [{"date": "2026-10-10", "amount": -50.0}, {"date": "2026-09-12", "amount": -20.0}]
        p = self.pace(rows)
        assert p["as_of_day"] == 10
        assert p["previous"]["expense"] == 0.0

    def test_past_month_shown_is_not_capped(self):
        # Fallback to a completed month (e.g. first hour of November).
        p = self.pace([{"date": "2026-10-29", "amount": -105.0}], today=date(2026, 11, 1))
        assert p["as_of_day"] == 29
        assert p["current"]["expense"] == 105.0


class TestSavingsPct:
    """As the household, with October income 27,741.45 and expense 28,245.34
    (net -503.89) the savings% tile showed 0% — it should show the real ≈ -1.8%."""

    def test_negative_net_gives_negative_savings_pct(self):
        metrics = cashflow.build_metrics(
            {"income": 27741.45, "expense": 28245.34, "net": -503.89}, {})
        m = next(m for m in metrics if m["key"] == "savings_pct")
        assert m["value"] == -1.8
        assert m["rank"] == "bad"


class TestExpectedForMonth:
    """The wallet card's "actual of expected" comes from forecast.py's current_month."""

    FORECAST = {
        "based_on_budget": "2026-10",
        "current_month": {
            "forecast_month": "2026-10", "based_on_budget": "2026-10",
            "income": {"total": 27163.8}, "expenses": {"total": 31461.65},
        },
    }

    def test_current_budget_month_becomes_expected(self):
        exp = cashflow.expected_for_month(self.FORECAST, "2026-10")
        assert exp["income"] == 27163.8
        assert exp["expense"] == 31461.65
        assert exp["net"] == -4297.85

    def test_stale_forecast_is_not_this_months_target(self):
        # Forecast last built from September's budget; it's now October.
        stale = {"current_month": {**self.FORECAST["current_month"], "forecast_month": "2026-09"}}
        assert cashflow.expected_for_month(stale, "2026-10") is None

    def test_missing_forecast_or_old_format(self):
        assert cashflow.expected_for_month(None, "2026-10") is None
        assert cashflow.expected_for_month({"months": []}, "2026-10") is None


class TestCategoryDonut:
    """Spending-by-category donut on the Overview, month-to-date."""

    def test_october_categories_rank_and_fold_into_other(self):
        # Real October 2026 rows (abridged): rent transfer, mortgage, loans, dining…
        pace = cashflow.build_pace([
            {"date": "2026-10-11", "amount": -6800.0, "description": 'הו"ק לעיין ניהול נכסי', "category": "העברות"},
            {"date": "2026-10-10", "amount": -5817.25, "category": "משכנתא"},
            {"date": "2026-10-02", "amount": -1844.42, "category": "הלוואה"},
            {"date": "2026-10-05", "amount": -120.0, "category": "אוכל בחוץ"},
            {"date": "2026-10-09", "amount": -12.0, "description": "ביתא", "category": "פנאי"},
            {"date": "2026-10-07", "amount": -40.0, "category": "קניות"},
            {"date": "2026-10-08", "amount": -30.0},                              # no category
            {"date": "2026-10-04", "amount": 26428.43, "is_income": True},        # income ignored
            {"date": "2026-10-03", "amount": -5000.0, "internal_transfer": True},  # not spending
        ], "2026-10")
        cats = pace["current"]["by_category"]
        assert [c["name"] for c in cats][:3] == ["העברות", "משכנתא", "הלוואה"]
        assert cats[-1] == {"name": "אחר", "amount": 42.0}   # פנאי 12 + ללא קטגוריה 30
        assert len(cats) == 6

    def test_top_categories_without_a_tail_has_no_other(self):
        assert cashflow.top_categories({"משכנתא": 100.0, "פנאי": 5.0}) == [
            {"name": "משכנתא", "amount": 100.0}, {"name": "פנאי", "amount": 5.0}]


class TestTrailingAverage:
    """Wallet header's "vs. your 12-month average" — same-day cut, covered months only."""

    def test_average_is_cut_at_same_day_over_covered_months(self):
        # Real case: September 2026 was an outlier (partner moving out), so October
        # vs. September alone overstated the improvement. Average Aug+Sep instead.
        pace = cashflow.build_pace([
            {"date": "2026-10-09", "amount": -900.0},
            {"date": "2026-09-05", "amount": -1500.0},
            {"date": "2026-09-25", "amount": -6800.0},   # after day 9 — excluded
            {"date": "2026-08-03", "amount": -500.0},
            # July 2026 has no rows (no scrape) — must not count as a ₪0 month
        ], "2026-10")
        avg = pace["average"]
        assert avg["months"] == 2
        assert avg["expense"] == 1000.0               # (1500 + 500) / 2
        assert avg["month_expense"] == 4400.0         # (8300 + 500) / 2
        assert len(avg["daily_expense"]) == 31
        assert avg["daily_expense"][8] == 1000.0      # by the 9th

    def test_window_is_twelve_months(self):
        pace = cashflow.build_pace([
            {"date": "2026-10-01", "amount": -10.0},
            {"date": "2025-10-01", "amount": -100.0},   # 12 months back — in
            {"date": "2025-09-01", "amount": -9999.0},  # 13 months back — out
        ], "2026-10")
        assert pace["average"]["months"] == 1
        assert pace["average"]["expense"] == 100.0

    def test_no_history_means_no_average(self):
        pace = cashflow.build_pace([{"date": "2026-10-01", "amount": -10.0}], "2026-10")
        assert pace["average"] is None


def fx_row(day, description, amount, category, merchant=None, **kw):
    """A stamped fixed ledger row (finance/categories.stamp output)."""
    return {"date": day, "description": description, "amount": amount, "category": category,
            "merchant": merchant or description, "kind": "fixed", **kw}


class TestFixedExpenses:
    """Cashflow page's "הוצאות קבועות" review — real October 2026 fixed ledger rows."""

    LEDGER = [
        fx_row("2026-10-11", 'הו"ק לעיין ניהול נכסי,לסניף 20-406', -6800, "שכר דירה",
               merchant='הו"ק לעיין ניהול נכסי'),
        fx_row("2026-10-11", "דסק-משכנתא,חיוב", -5817.25, "משכנתא", merchant="דסק-משכנתא"),
        fx_row("2026-10-02", "פרעון הלוואה", -1844.42, "הלוואה"),
        fx_row("2026-10-04", "פרעון הלוואה", -867.8, "הלוואה"),
        fx_row("2026-10-25", 'פרטנר תקשורת בע"מ', -135.14, "תקשורת"),
        fx_row("2026-10-13", "APPLE.COM/BILL         CORK    ", -59.5, "דיגיטל", merchant="APPLE.COM/BILL"),
        fx_row("2026-10-13", "APPLE.COM/BILL         CORK    ", -39.9, "דיגיטל", merchant="APPLE.COM/BILL"),
        fx_row("2026-10-10", "SPOTIFY P47D8D0286 684488", -43.9, "דיגיטל", merchant="SPOTIFY P47D8D"),
        fx_row("2026-10-13", 'אקספון 018 בע"מ', -34.9, "תקשורת"),
        fx_row("2026-10-11", "טלזר 019 שירותי תקשורת בינלאומ", -10, "תקשורת",
               merchant="טלזר 019 שירותי תקשורת בינלאומים"),
        fx_row("2026-10-23", "דמי כרטיס /הנפקה", -102.38, "עמלות"),
        fx_row("2026-10-02", "מטרו מוטור שווק (1981)בעמ", -500, "רכב", source_category="תשלומים"),
        fx_row("2026-10-07", "ליברה עסקאות ביטוח", -30, "ביטוח", source_category="תשלומים"),
        # September's Clal health premium: monthly, not charged yet in October
        fx_row("2026-08-28", "כלל ב.בריאות ה.ק", -128.77, "בריאות", recurring=True),
        fx_row("2026-09-28", "כלל ב.בריאות ה.ק", -129.14, "בריאות", recurring=True),
        # not fixed: the review leaves it out
        {"date": "2026-10-05", "description": "פז אפליקצית-YELLOW", "amount": -36.88, "category": "דלק",
         "merchant": "פז אפליקצית-YELLOW", "kind": "variable"},
    ]

    def fx(self):
        return cashflow.fixed_expenses(self.LEDGER, "2026-10")

    def items(self):
        return {i["name"]: i for g in self.fx()["groups"] for i in g["items"]}

    def test_groups_in_review_order_cheapest_win_first(self):
        keys = [g["key"] for g in self.fx()["groups"]]
        assert keys == ["fees", "subscriptions", "bills", "installments", "committed"]

    def test_rent_and_loans_are_committed_not_cuts(self):
        committed = next(g for g in self.fx()["groups"] if g["key"] == "committed")
        assert committed["total"] == round(6800 + 5817.25 + 1844.42 + 867.8, 2)
        assert committed["ease"] == "committed"

    def test_metro_installment_waits_but_an_insurance_premium_is_a_bill(self):
        groups = {g["key"]: [i["name"] for i in g["items"]] for g in self.fx()["groups"]}
        assert groups["installments"] == ["מטרו מוטור שווק (1981)בעמ"]
        assert "ליברה עסקאות ביטוח" in groups["bills"]

    def test_cuttable_is_fees_plus_subscriptions(self):
        assert self.fx()["cuttable_total"] == round(102.38 + 59.5 + 39.9 + 43.9, 2)

    def test_still_expected_monthly_charge_is_listed(self):
        clal = self.items()["כלל ב.בריאות ה.ק"]
        assert clal["expected"] and clal["amount"] == 129.14 and clal["category"] == "בריאות"
        assert not self.items()['פרטנר תקשורת בע"מ']["expected"]

    def test_repeated_apple_billing_and_two_call_plans_are_duplicates(self):
        items = self.items()
        assert items["APPLE.COM/BILL CORK"]["duplicate"]
        assert items['אקספון 018 בע"מ']["duplicate_reason"] == "שיחות לחו״ל"
        assert items["טלזר 019 שירותי תקשורת בינלאומ"]["duplicate"]
        assert not items["SPOTIFY P47D8D0286 684488"]["duplicate"]

    def test_loans_sharing_a_prefix_are_not_duplicates(self):
        committed = next(g for g in self.fx()["groups"] if g["key"] == "committed")
        assert not any(i["duplicate"] for i in committed["items"])

    def test_last_charged_comes_from_the_ledger(self):
        items = self.items()
        assert items["טלזר 019 שירותי תקשורת בינלאומ"]["last_charged"] == "2026-10-11"
        assert items["כלל ב.בריאות ה.ק"]["last_charged"] == "2026-09-28"

    def test_items_carry_group_and_month_section(self):
        # /monthly lists rent under קבוע · דיור and the mortgage under הלוואות וחיסכון
        items = self.items()
        rent = items['הו"ק לעיין ניהול נכסי']
        assert (rent["group"], rent["block"]) == ("דיור", "fixed")
        assert items["דסק-משכנתא"]["block"] == "debt_savings"

    def test_month_without_fixed_rows_gives_nothing(self):
        assert cashflow.fixed_expenses(self.LEDGER, "2027-01") is None


def test_inbox_sync_never_stops_the_digest(monkeypatch, capsys):
    """No database configured, or one that is down: the digest carries on."""
    import goals
    model = {"actions": [{"id": "stale:amex", "severity": "low", "title": "נתונים לא עדכניים"}]}
    monkeypatch.setattr(goals, "database_url", lambda: None)
    assert cashflow.sync_inbox(model) is None
    monkeypatch.setattr(goals, "database_url", lambda: "postgresql://nobody@127.0.0.1:1/none?connect_timeout=1")
    assert cashflow.sync_inbox(model) is None
    assert "inbox: database unavailable" in capsys.readouterr().err
