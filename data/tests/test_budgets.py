"""Real-case tests for budgets.py (PRD 12 Phase 2), mirroring the 2026-10 RiseUp
budget (planned amounts) and the October 2026 ledger (spend, kind)."""
import json
from datetime import date

import budgets


def env(name, amount, idx=""):
    return {
        "id": f"2026-10#trackingCategory#{name}{idx}",
        "type": "trackingCategory",
        "originalAmount": amount,
        "details": {"trackingCategory": {"name": name}},
        "actuals": [],
    }


def doc(envs, start_day=1, month="2026-10"):
    return {"budgetDate": month, "cashflowStartDay": start_day, "envelopes": envs}


def row(day, description, amount, category, kind="variable", group=None, merchant=None, **kw):
    """A stamped ledger row (finance/categories.stamp output)."""
    groups = {"דלק": "תחבורה", "רכב": "תחבורה", "תיירות": "פנאי", "עציצים": "עציצים",
              "כלכלה": "אוכל", "בריאות": "בריאות וטיפוח", "דיגיטל": "מנויים", "משכורת": "הכנסות וחיסכון",
              "הלוואה": "פיננסים", "שכר דירה": "דיור"}
    t = {"date": day, "description": description, "amount": amount, "category": category,
         "category_group": group or groups.get(category), "merchant": merchant or description, **kw}
    if amount < 0 and kind:
        t["kind"] = kind
    return t


def cat(block, name):
    return next(c for c in block["categories"] if c["name"] == name)


def build(envs, ledger=(), as_of=date(2026, 10, 16), **kw):
    return budgets.build_budgets(doc(envs, **{k: kw.pop(k) for k in ("start_day",) if k in kw}),
                                 list(ledger), as_of, **kw)


# October 2026, group תחבורה: one פז fill-up and a Gett ride are the budget; Metro
# Motor's installment is fixed, so it is the fixed block's, not this line's.
TRANSPORT = [
    row("2026-10-05", "פז אפליקצית-YELLOW", -36.88, "דלק", budget_category="תחבורה"),
    row("2026-10-16", "Gett", -6.8, "רכב"),
    row("2026-10-02", "מטרו מוטור שווק (1981)בעמ", -500.0, "רכב", kind="fixed", recurring=True),
]
# October 2026 trip, in RiseUp's "חופשה ✈️" envelope: RiseUp counted ₪1,110.06 too.
TRIP = [
    row("2026-10-06", 'קינג אקספרס בע"מ', -558.06, "תיירות", budget_category="חופשה ✈️"),
    row("2026-10-13", "MIGDALOR CAFE", -156.0, "תיירות", budget_category="חופשה ✈️"),
    row("2026-10-13", "CONCIERGE", -298.0, "תיירות", budget_category="חופשה ✈️"),
    row("2026-10-14", "קפה מלון נורדוי", -98.0, "תיירות", budget_category="חופשה ✈️"),
]


class TestCategoryMath:
    def test_group_line_counts_variable_rows_only(self):
        c = cat(build([env("תחבורה", 200)], TRANSPORT), "תחבורה")
        assert c["scope"] == "group" and c["group"] == "תחבורה"
        assert c["spent"] == 43.68 and c["left"] == 156.32
        assert c["pct"] == 21.8 and not c["over"] and c["source"] == "riseup"

    def test_vacation_envelope_is_the_tourism_category(self):
        b = build([env("חופשה ✈️", 1000)], TRIP)
        c = cat(b, "תיירות")
        assert c["scope"] == "category" and c["spent"] == 1110.06 and c["over"]
        assert c["group"] == "פנאי"  # תיירות sits under פנאי on /monthly

    def test_over_plan_category(self):
        # עציצים: ₪700 planned; a ₪1,000 cash withdrawal and ₪129 on 10-13, ₪14 on 10-21
        ledger = [row("2026-10-13", "משיכת מזומן ללא כרטיס", -1000.0, "עציצים"),
                  row("2026-10-13", "קיוסק לב הנמל", -129.0, "עציצים"),
                  row("2026-10-21", 'קיוסק אלנבי 58 ת"א', -14.0, "עציצים")]
        c = cat(build([env("עציצים", 700)], ledger), "עציצים")
        assert c["over"] and c["left"] == -443

    def test_refund_subtracts_but_never_below_zero(self):
        # Sept 2026: the ₪1,096 הפול ביטוח חובה refund, with no transport spend that cycle
        refund = row("2026-10-02", "הפול ביטוח חובה", 1096.0, "רכב", kind=None, is_income=True)
        assert cat(build([env("תחבורה", 200)], [refund]), "תחבורה")["spent"] == 0
        c = cat(build([env("תחבורה", 200)], [*TRANSPORT, {**refund, "amount": 20.0}]), "תחבורה")
        assert c["spent"] == 23.68

    def test_weekly_envelopes_merge_by_name(self):
        envs = [env("כלכלה", 200, "#1"), env("כלכלה", 400, "#2")]
        ledger = [row("2026-10-04", "PM:AM אלנבי 56", -49.2, "כלכלה"),
                  row("2026-10-12", 'ויקטורי אלנבי ת"א', -177.02, "כלכלה")]
        c = cat(build(envs, ledger), "כלכלה")
        assert c["planned"] == 600 and c["spent"] == 226.22

    def test_card_bill_and_other_cycles_do_not_count(self):
        ledger = [row("2026-10-11", "דיינרס קלו,חיוב", -7393.89, "כלכלה", kind=None, card_bill_payment=True),
                  row("2026-09-30", "PM:AM אלנבי 56", -49.2, "כלכלה")]
        assert cat(build([env("כלכלה", 600)], ledger), "כלכלה")["spent"] == 0

    def test_hidden_saving_category_skipped(self):
        assert build([env("__saving-hidden-category__", 0)])["categories"] == []

    def test_sorted_by_planned_desc_and_totals(self):
        b = build([env("עציצים", 100), env("תחבורה", 300)], TRANSPORT)
        assert [c["name"] for c in b["categories"]] == ["תחבורה", "עציצים"]
        assert (b["total_planned"], b["total_spent"], b["left"]) == (400, 43.68, 356.32)


class TestOverrides:
    def test_override_replaces_planned_and_marks_source(self):
        b = build([env("תחבורה", 200)], TRANSPORT, overrides={"תחבורה": 40})
        c = cat(b, "תחבורה")
        assert c["planned"] == 40 and c["source"] == "override" and c["over"]

    def test_override_under_the_old_riseup_name_still_applies(self):
        c = cat(build([env("חופשה ✈️", 1000)], TRIP, overrides={"חופשה ✈️": 1500}), "תיירות")
        assert c["planned"] == 1500 and not c["over"]

    def test_override_adds_a_line_riseup_does_not_have(self):
        c = cat(build([env("תחבורה", 200)], TRIP, overrides={"תיירות": 2000}), "תיירות")
        assert c["source"] == "override" and c["spent"] == 1110.06


class TestCycle:
    def test_calendar_month_when_start_day_1(self):
        b = build([env("פנאי", 100)])
        assert (b["cycle_start"], b["cycle_end"]) == ("2026-10-01", "2026-10-31")
        assert b["days_left"] == 16

    def test_start_day_10_crosses_months(self):
        b = build([env("פנאי", 100)], start_day=10)
        assert (b["cycle_start"], b["cycle_end"]) == ("2026-10-10", "2026-11-09")
        assert b["days_left"] == 25

    def test_per_day_only_when_money_left(self):
        assert build([env("פנאי", 1600)])["per_day"] == 100
        assert build([env("עציצים", 100)], [row("2026-10-13", "קיוסק לב הנמל", -129.0, "עציצים")])["per_day"] is None

    def test_no_budget_returns_none(self):
        assert budgets.build_budgets(None, [], date(2026, 10, 16)) is None


class TestHistory:
    # July 2026: the הפול ביטוח חובה policy bought (₪1,512 + ₪1,673 + 2 × ₪207) and
    # partly refunded (₪1,512 + ₪207) — the line's July spend is the ₪1,880 net.
    JULY = [row("2026-07-09", "הפול בטוח חובה", -207.0, "רכב"),
            row("2026-07-19", "הפול בטוח חובה", -207.0, "רכב"),
            row("2026-07-26", "הפול בטוח חובה", -1512.0, "רכב"),
            row("2026-07-26", "הפול בטוח חובה", -1673.0, "רכב"),
            row("2026-07-27", "הפול ביטוח חובה", 1512.0, "רכב", kind=None, is_income=True),
            row("2026-07-28", "הפול ביטוח חובה", 207.0, "רכב", kind=None, is_income=True)]

    def test_last_four_covered_cycles_oldest_first(self):
        ledger = [row(f"2026-{m:02d}-05", "פז אפליקצית-YELLOW", -100.0 * m, "דלק") for m in range(3, 10)]
        c = cat(build([env("תחבורה", 200)], ledger + self.JULY), "תחבורה")
        assert c["history"] == [{"cycle": "2026-06", "spent": 600}, {"cycle": "2026-07", "spent": 2580},
                                {"cycle": "2026-08", "spent": 800}, {"cycle": "2026-09", "spent": 900}]

    def test_estimate_is_the_median_of_six_cycles(self):
        ledger = [row(f"2026-{m:02d}-05", "פז אפליקצית-YELLOW", -100.0 * m, "דלק") for m in range(3, 10)]
        # cycles 04..09 spend 400..900 -> median 650
        assert cat(build([env("תחבורה", 200)], ledger), "תחבורה")["estimate"] == 650

    def test_too_little_history_gives_no_estimate(self):
        ledger = [row("2026-09-05", "פז אפליקצית-YELLOW", -100.0, "דלק")]
        c = cat(build([env("תחבורה", 200)], ledger), "תחבורה")
        assert c["estimate"] is None and c["history"] == [{"cycle": "2026-09", "spent": 100}]

    def test_load_history_dedupes_overlapping_dumps(self, tmp_path):
        a = doc([env("x", 500)], month="2026-08"); a["lastUpdatedAt"] = "2026-09-01"
        b = doc([env("x", 500)], month="2026-08"); b["lastUpdatedAt"] = "2026-10-01"
        (tmp_path / "budget_2026-09_6.json").write_text(json.dumps([a]))
        (tmp_path / "budget_2026-10_6.json").write_text(json.dumps([b]))
        docs = budgets.load_history(tmp_path)
        assert len(docs) == 1 and docs[0]["lastUpdatedAt"] == "2026-10-01"


class TestFixedItems:
    """The month's fixed expenses: what hit, plus the monthly ones still to come."""

    HEALTH = [row("2026-08-28", "כלל ב.בריאות ה.ק", -128.77, "בריאות", kind="fixed", recurring=True),
              row("2026-09-28", "כלל ב.בריאות ה.ק", -129.14, "בריאות", kind="fixed", recurring=True)]
    # Spotify moved from CAL (SpotifyIL) to AMEX (SPOTIFY P47D8D…) in October.
    SPOTIFY = [row("2026-08-09", "SpotifyIL", -43.9, "דיגיטל", kind="fixed", recurring=True),
               row("2026-09-09", "SpotifyIL", -43.9, "דיגיטל", kind="fixed", recurring=True),
               row("2026-10-10", "SPOTIFY P47D8D0286 684488", -43.9, "דיגיטל", kind="fixed",
                   merchant="SPOTIFY P47D8D")]

    def test_monthly_charge_not_seen_yet_is_expected(self):
        items = budgets.fixed_items(self.HEALTH, "2026-10")
        assert [(i["description"], i["amount"], i["expected"]) for i in items] == \
            [("כלל ב.בריאות ה.ק", -129.14, True)]

    def test_charge_that_already_hit_is_not_expected_again(self):
        ledger = self.HEALTH + [row("2026-10-28", "כלל ב.בריאות ה.ק", -129.14, "בריאות", kind="fixed")]
        assert [i["expected"] for i in budgets.fixed_items(ledger, "2026-10")] == [False]

    def test_a_service_that_moved_card_is_not_expected_twice(self):
        items = budgets.fixed_items(self.SPOTIFY, "2026-10")
        assert [(i["merchant"], i["expected"]) for i in items] == [("SPOTIFY P47D8D", False)]

    def test_needs_both_previous_cycles(self):
        # only September: could be a bi-monthly bill in its off month
        assert budgets.fixed_items(self.HEALTH[1:], "2026-10") == []

    def test_variable_rows_are_not_fixed_items(self):
        assert budgets.fixed_items(TRANSPORT[:2], "2026-10") == []


class TestSummary:
    LEDGER = [
        row("2026-10-08", "העברת משכורת", 26144.0, "משכורת", kind=None, is_income=True),
        row("2026-10-11", 'הו"ק לעיין ניהול נכסי,לסניף 20-406', -6800.0, "שכר דירה", kind="fixed"),
        row("2026-10-02", "פרעון הלוואה", -1844.42, "הלוואה", kind="fixed", recurring=True),
        *TestFixedItems.HEALTH,
        *TRANSPORT[:2],
    ]

    def summary(self, **kw):
        return build([env("תחבורה", 200)], self.LEDGER, **kw)["summary"]

    def test_three_blocks_and_left(self):
        s = self.summary(expected_income=27163.8)
        assert s["income"] == {"actual": 26144.0, "expected": 27163.8, "value": 27163.8}
        assert s["fixed"] == {"actual": 6800.0, "expected": 6929.14, "value": 6929.14}
        assert s["debt_savings"]["value"] == 1844.42
        assert s["variable"]["actual"] == 43.68 and s["variable"]["estimate"] is None
        assert s["variable"]["planned"] == 200
        # free money: what is not planned for anything (the ₪200 transport line is planned)
        assert s["left"] == round(27163.8 - 6929.14 - 1844.42 - 200, 2)
        assert s["projected_end"] == round(27163.8 - 6929.14 - 1844.42 - 43.68, 2)

    def test_variable_projection_scales_the_estimate_by_days_left(self):
        """With a ₪3,000 usual month and 4 of 31 days left, the rest of the cycle adds
        about ₪387, not the whole ₪3,000 a trip-heavy median would."""
        past = [row(f"2026-{m:02d}-10", "WOLT", -3000.0, "אוכל בחוץ") for m in (5, 6, 7, 8, 9)]
        cur = [row("2026-10-10", "WOLT", -1000.0, "אוכל בחוץ")]
        s = build([env("אוכל בחוץ", 2500)], past + cur, as_of=date(2026, 10, 28))["summary"]
        v = s["variable"]
        assert (v["estimate"], v["days_left"]) == (3000.0, 4)
        assert v["projected"] == round(1000 + 3000 * 4 / 31, 2)

    def test_actual_income_counts_when_above_the_forecast(self):
        assert self.summary(expected_income=20000)["income"]["value"] == 26144.0
        assert self.summary()["income"]["expected"] is None


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

    def test_riseup_envelope_name_is_stored_as_our_category(self, tmp_path):
        store = tmp_path / "b.json"
        budgets.save_overrides({"חופשה ✈️": 900.0}, store)
        rc, calls = self.run(store, "set", "חופשה ✈️", "1500")
        assert rc == 0 and calls == [1, "תיירות"]
        assert budgets.load_overrides(store) == {"תיירות": 1500}


class TestPlanBaseline:
    def test_seed_copies_riseup_plans_and_keeps_set_lines(self, tmp_path, monkeypatch):
        store = tmp_path / "budgets.json"
        budgets.save_overrides({"אוכל בחוץ": 1500}, store)
        monkeypatch.setattr(budgets, "load_budget", lambda: doc([env("אוכל בחוץ", 1000), env("עציצים", 700),
                                                                   env("חופשה ✈️", 1000)]))
        assert budgets.main(["seed"], store=store, rebuild=lambda: None, show=lambda c: None) == 0
        assert budgets.load_overrides(store) == {"אוכל בחוץ": 1500, "עציצים": 700, "תיירות": 1000}

    def test_variable_category_without_a_plan_shows_at_zero_with_its_average(self):
        """דייטים has spending every cycle but no budget line: shown unplanned, not 'over'."""
        ledger = [row(f"2026-{m:02d}-12", "גילי קופי האוס", -150.0, "דייטים", group="פנאי") for m in range(5, 11)]
        c = next(c for c in build([env("אוכל בחוץ", 1000)], ledger)["categories"] if c["name"] == "דייטים")
        assert (c["source"], c["planned"], c["over"], c["estimate"]) == ("unplanned", 0, False, 150.0)

    def test_a_group_line_covers_its_categories(self):
        """The תחבורה line covers דלק, so דלק is not listed again as unplanned."""
        ledger = [row(f"2026-{m:02d}-05", "פז אפליקצית-YELLOW", -36.0, "דלק") for m in range(5, 11)]
        names = [c["name"] for c in build([env("תחבורה", 200)], ledger)["categories"]]
        assert names == ["תחבורה"]


    def test_a_line_removed_from_the_seeded_plan_is_not_riseups_again(self):
        """After seeding, דייטים's ₪1 RiseUp placeholder was removed: it shows only as
        unplanned with its average, never as "₪1, over budget"."""
        ledger = [row(f"2026-{m:02d}-12", "גילי קופי האוס", -150.0, "דייטים", group="פנאי") for m in range(5, 11)]
        b = build([env("דייטים", 1), env("אוכל בחוץ", 1000)], ledger, overrides={"אוכל בחוץ": 1000})
        c = next(c for c in b["categories"] if c["name"] == "דייטים")
        assert (c["source"], c["planned"], c["over"]) == ("unplanned", 0, False)


class TestMergedCategories:
    def test_a_merged_category_plan_adds_to_its_target(self):
        """אלכוהול (₪255.70) merged into אוכל בחוץ (₪1,000): one ₪1,255.70 line; the ledger
        already says אוכל בחוץ for the beer."""
        ledger = [row("2026-10-12", "בירה בזאר", -153.4, "אוכל בחוץ", group="אוכל")]
        b = budgets.build_budgets(doc([env("אוכל בחוץ", 1)]), ledger, date(2026, 10, 16),
                                  overrides={"אוכל בחוץ": 1000, "אלכוהול": 255.7},
                                  merges={"אלכוהול": "אוכל בחוץ"})
        names = [c["name"] for c in b["categories"]]
        assert "אלכוהול" not in names
        assert (cat(b, "אוכל בחוץ")["planned"], cat(b, "אוכל בחוץ")["spent"]) == (1255.7, 153.4)
