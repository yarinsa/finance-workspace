"""Real-case tests for budgets.py (PRD 12 Phase 2), mirroring the 2026-10 RiseUp budget."""
from datetime import date

import budgets


def env(name, amount, actuals=(), idx=""):
    return {
        "id": f"2026-10#trackingCategory#{name}{idx}",
        "type": "trackingCategory",
        "originalAmount": amount,
        "details": {"trackingCategory": {"name": name}},
        "actuals": [{"billingAmount": a, "isIncome": False} for a in actuals],
    }


def doc(envs, start_day=1, month="2026-10"):
    return {"budgetDate": month, "cashflowStartDay": start_day, "envelopes": envs}


def cat(block, name):
    return next(c for c in block["categories"] if c["name"] == name)


class TestCategoryMath:
    def test_transport_200_with_one_actual(self):
        # תחבורה: ₪200 planned, one פז charge of ₪36.88 on 2026-10-05
        b = budgets.build_budgets(doc([env("תחבורה", 200, [36.88])]), date(2026, 10, 16))
        c = cat(b, "תחבורה")
        assert c["spent"] == 36.88 and c["left"] == 163.12
        assert c["pct"] == 18.4 and not c["over"] and c["source"] == "riseup"

    def test_over_plan_category(self):
        # עציצים: ₪700 planned, ₪1000 + ₪129 charged on 2026-10-13
        b = budgets.build_budgets(doc([env("עציצים", 700, [1000, 129])]), date(2026, 10, 16))
        c = cat(b, "עציצים")
        assert c["over"] and c["left"] == -429

    def test_weekly_envelopes_merge_by_name(self):
        envs = [env("כלכלה", 200, [49.2], "#1"), env("כלכלה", 400, [177.02], "#2")]
        c = cat(budgets.build_budgets(doc(envs), date(2026, 10, 16)), "כלכלה")
        assert c["planned"] == 600 and c["spent"] == 226.22

    def test_hidden_saving_category_skipped(self):
        b = budgets.build_budgets(doc([env("__saving-hidden-category__", 0, [0.03])]), date(2026, 10, 16))
        assert b["categories"] == []

    def test_sorted_by_planned_desc_and_totals(self):
        b = budgets.build_budgets(doc([env("a", 100, [40]), env("b", 300, [10])]), date(2026, 10, 16))
        assert [c["name"] for c in b["categories"]] == ["b", "a"]
        assert (b["total_planned"], b["total_spent"], b["left"]) == (400, 50, 350)


class TestOverrides:
    def test_override_replaces_planned_and_marks_source(self):
        b = budgets.build_budgets(doc([env("אוכל בחוץ", 1000, [300])]), date(2026, 10, 16),
                                  overrides={"אוכל בחוץ": 250})
        c = cat(b, "אוכל בחוץ")
        assert c["planned"] == 250 and c["source"] == "override" and c["over"]


class TestCycle:
    def test_calendar_month_when_start_day_1(self):
        b = budgets.build_budgets(doc([env("a", 100)]), date(2026, 10, 16))
        assert (b["cycle_start"], b["cycle_end"]) == ("2026-10-01", "2026-10-31")
        assert b["days_left"] == 16

    def test_start_day_10_crosses_months(self):
        b = budgets.build_budgets(doc([env("a", 100)], start_day=10), date(2026, 10, 16))
        assert (b["cycle_start"], b["cycle_end"]) == ("2026-10-10", "2026-11-09")
        assert b["days_left"] == 25

    def test_per_day_only_when_money_left(self):
        ok = budgets.build_budgets(doc([env("a", 1600)]), date(2026, 10, 16))
        assert ok["per_day"] == 100
        over = budgets.build_budgets(doc([env("a", 100, [500])]), date(2026, 10, 16))
        assert over["per_day"] is None

    def test_no_budget_returns_none(self):
        assert budgets.build_budgets(None, date(2026, 10, 16)) is None
