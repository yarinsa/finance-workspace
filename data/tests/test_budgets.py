"""Real-case tests for budgets.py (PRD 12 Phase 2), mirroring the 2026-10 RiseUp budget."""
import json
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


def hdoc(month, name, actuals):
    return doc([env(name, 500, actuals)], month=month)


class TestHistory:
    def test_last_four_cycles_oldest_first_excluding_current(self):
        docs = [hdoc("2026-04", "כלכלה", [100]), hdoc("2026-05", "כלכלה", [200]),
                hdoc("2026-06", "כלכלה", [300]), hdoc("2026-07", "כלכלה", [400]),
                hdoc("2026-08", "כלכלה", [500]), hdoc("2026-10", "כלכלה", [999])]
        b = budgets.build_budgets(doc([env("כלכלה", 600, [50])]), date(2026, 10, 16), history_docs=docs)
        assert cat(b, "כלכלה")["history"] == [
            {"cycle": "2026-05", "spent": 200}, {"cycle": "2026-06", "spent": 300},
            {"cycle": "2026-07", "spent": 400}, {"cycle": "2026-08", "spent": 500}]

    def test_missing_category_in_a_cycle_is_zero_and_refunds_subtract(self):
        refund = env("תחבורה", 200, [])
        refund["actuals"] = [{"billingAmount": 80, "isIncome": False}, {"billingAmount": 30, "isIncome": True}]
        docs = [hdoc("2026-08", "כלכלה", [10]), doc([refund], month="2026-09")]
        b = budgets.build_budgets(doc([env("תחבורה", 200)]), date(2026, 10, 16), history_docs=docs)
        assert cat(b, "תחבורה")["history"] == [{"cycle": "2026-08", "spent": 0}, {"cycle": "2026-09", "spent": 50}]

    def test_no_history_docs_gives_empty_list(self):
        b = budgets.build_budgets(doc([env("a", 100)]), date(2026, 10, 16), history_docs=[])
        assert cat(b, "a")["history"] == []

    def test_load_history_dedupes_overlapping_dumps(self, tmp_path):
        a = hdoc("2026-08", "x", [1]); a["lastUpdatedAt"] = "2026-09-01"
        b = hdoc("2026-08", "x", [2]); b["lastUpdatedAt"] = "2026-10-01"
        (tmp_path / "budget_2026-09_6.json").write_text(json.dumps([a]))
        (tmp_path / "budget_2026-10_6.json").write_text(json.dumps([b]))
        docs = budgets.load_history(tmp_path)
        assert len(docs) == 1 and docs[0]["lastUpdatedAt"] == "2026-10-01"


class TestCli:
    def run(self, store, *argv):
        calls = []
        rc = budgets.main(list(argv), store=store, rebuild=lambda: calls.append(1), show=lambda c: calls.append(c))
        return rc, calls

    def test_set_unset_round_trip(self, tmp_path):
        store = tmp_path / "budgets" / "budgets.json"
        rc, calls = self.run(store, "set", "אוכל בחוץ", "250")
        assert rc == 0 and calls == [1, "אוכל בחוץ"]
        assert budgets.load_overrides(store) == {"אוכל בחוץ": 250}
        self.run(store, "set", "תחבורה", "120.5")
        self.run(store, "unset", "אוכל בחוץ")
        assert budgets.load_overrides(store) == {"תחבורה": 120.5}

    def test_bad_args_do_not_touch_store_or_rebuild(self, tmp_path):
        store = tmp_path / "b.json"
        for argv in (["set", "a"], ["set", "a", "x"], ["set", "a", "-5"], ["nope"], []):
            rc, calls = self.run(store, *argv)
            assert rc == 2 and calls == [] and not store.exists()

    def test_list_does_not_rebuild(self, tmp_path):
        store = tmp_path / "b.json"
        budgets.save_overrides({"a": 1.0}, store)
        assert self.run(store, "list") == (0, [])
