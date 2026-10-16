"""Real-case tests for actions.py (home "לטיפול" list)."""
from datetime import date, datetime, timedelta, timezone

import actions

AS_OF = date(2026, 10, 16)

RUNWAY = {
    "overdraft_limit": 10000, "first_limit_breach": "2026-11-11", "safe_to_spend": -5968.84,
    "next_payday": {"date": "2026-11-08"},
    "liquid_buffer": [{"label": "נזיל יומי+", "balance": 2490.2}],
    "days": [{"date": "2026-11-10", "balance": -4994.74},
             {"date": "2026-11-11", "balance": -11694.74},
             {"date": "2026-11-12", "balance": -11000.0}],
    "events": [
        {"date": "2026-11-10", "name": "אמריקן אקס,חיוב", "amount": -8339.89, "kind": "card"},
        {"date": "2026-11-10", "name": "דיינרס קלו,חיוב", "amount": -7393.89, "kind": "card"},
        {"date": "2026-11-02", "name": "פרעון הלוואה", "amount": -1844.42, "kind": "loan"},
    ],
}
BUDGETS = {"cycle_start": "2026-10-01", "categories": [
    {"name": "פנאי", "planned": 1200.0, "spent": 1763.0, "over": True},
    {"name": "גינה", "planned": 1.0, "spent": 40.0, "over": True},
    {"name": "כלכלה", "planned": 1500.0, "spent": 900.0, "over": False},
]}
BILLS = {"items": [
    {"name": "מי אביבים חיוב תקופת", "amount": 266.7, "due_date": "2026-10-11", "status": "overdue"},
    {"name": "Microsoft", "amount": 10.0, "due_date": "2026-10-01", "status": "paid"},
]}
FIXED = {"month": "2026-10", "groups": [{"items": [
    {"name": "APPLE.COM/BILL CORK IRL", "amount": 59.5, "duplicate": True, "duplicate_reason": "אותו ספק כמה פעמים"},
    {"name": "APPLE.COM/BILL CORK IRL", "amount": 49.9, "duplicate": True, "duplicate_reason": "אותו ספק כמה פעמים"},
    {"name": "SpotifyIL", "amount": 43.9, "duplicate": False, "duplicate_reason": None},
]}]}
SYNCS = [{"source": "amex", "last_synced": "2026-10-16T09:17:17+03:00"},
         {"source": "discount-business", "last_synced": "2026-10-07T09:00:00+03:00"}]


def build(**kw):
    args = dict(runway=RUNWAY, bills=BILLS, budgets=BUDGETS, fixed_expenses=FIXED,
                syncs=SYNCS, as_of=AS_OF)
    args.update(kw)
    return actions.build_actions(**args)


def by_id(acts, prefix):
    return [a for a in acts if a["id"].startswith(prefix)]


def test_limit_breach_is_critical_with_buffer_hint():
    a = by_id(build(), "limit-breach:")[0]
    assert a["id"] == "limit-breach:2026-11-11"
    assert a["severity"] == "critical"
    assert a["title"] == "חריגה מהמסגרת ב-11/11"
    assert "₪11,695" in a["detail"] and "₪10,000" in a["detail"]
    assert "אפשר להעביר ₪2,490 מנזיל יומי+" in a["detail"]
    assert a["cta"] == {"label": "לתוכנית התזרים", "to": "/runway"}


def test_short_until_payday_is_high():
    a = by_id(build(), "short-until-payday:")[0]
    assert a["severity"] == "high" and a["title"] == "חסרים ₪5,969 עד המשכורת"


def test_budget_over_skips_placeholder():
    acts = build()
    ids = [a["id"] for a in by_id(acts, "budget-over")]
    assert ids == ["budget-over:פנאי:2026-10"]
    a = by_id(acts, "budget-over")[0]
    assert a["severity"] == "high" and a["detail"] == "₪1,763 מתוך ₪1,200 (+₪563)"


def test_budget_over_caps_at_three_and_groups_rest():
    cats = [{"name": f"c{i}", "planned": 100.0, "spent": 200.0 + i, "over": True} for i in range(5)]
    acts = build(budgets={"cycle_start": "2026-10-01", "categories": cats})
    assert len([a for a in acts if a["id"].startswith("budget-over:")]) == 3
    more = by_id(acts, "budget-over-more:")[0]
    assert more["severity"] == "medium" and more["title"] == "עוד 2 קטגוריות בחריגה"


def test_overdue_water_bill_is_medium():
    a = by_id(build(), "bill-overdue:")[0]
    assert a["id"] == "bill-overdue:מי אביבים חיוב תקופת:2026-10"
    assert a["severity"] == "medium" and a["detail"] == "₪267 · היה צפוי ב-11/10"


def test_card_events_summed_per_date_within_window():
    assert by_id(build(), "card-bills:") == []  # 11-10 is 25 days out
    a = by_id(build(as_of=date(2026, 11, 1)), "card-bills:")[0]
    assert a["id"] == "card-bills:2026-11-10" and a["title"] == "חיובי אשראי ₪15,734 ב-10/11"
    assert "אמריקן אקס ₪8,340" in a["detail"]


def test_duplicate_service_is_low():
    a = by_id(build(), "dup:")[0]
    assert a["id"] == "dup:APPLE.COM/BILL CORK IRL:2026-10" and a["severity"] == "low"
    assert a["amount"] == 109.4


NOON = datetime(2026, 10, 16, 12, 0, tzinfo=timezone(timedelta(hours=3)))


def test_stale_source_nine_days():
    # discount-business: daily target, last scraped 10-07 -> overdue; amex today -> fine.
    a = by_id(build(as_of=NOON), "stale:")[0]
    assert a["id"] == "stale:discount-business" and a["severity"] == "low"
    assert "discount-business (9 ימים, יעד 24 שעות, באיחור 8 ימים)" in a["detail"]
    assert "amex" not in a["detail"]
    assert a["cta"]["to"] == "/syncs"


def test_stale_uses_per_source_targets():
    syncs = [
        {"source": "harel", "last_synced": "2026-09-26T09:00:00+03:00"},               # 20d, monthly: fresh
        {"source": "amex", "last_synced": "2026-10-14T09:00:00+03:00"},                # 51h, daily: overdue
        {"source": "discount-mortgage", "last_synced": "2026-10-10T09:00:00+03:00"},   # 6d, weekly: fresh
        {"source": "riseup", "last_synced": "2026-08-01T09:00:00+03:00"},              # no target: ignored
    ]
    [a] = by_id(build(syncs=syncs, as_of=NOON), "stale:")
    assert a["id"] == "stale:amex"
    assert a["detail"] == "amex (2 ימים, יעד 24 שעות, באיחור 27 שעות)"


def test_no_stale_action_when_everything_is_within_target():
    syncs = [{"source": "amex", "last_synced": "2026-10-16T08:00:00+03:00"},
             {"source": "analyst", "last_synced": "2026-10-01T08:00:00+03:00"}]
    assert by_id(build(syncs=syncs), "stale:") == []


def test_ordering_critical_first_then_amount_desc():
    acts = build()
    sev = [actions.SEVERITY_ORDER[a["severity"]] for a in acts]
    assert sev == sorted(sev)
    assert acts[0]["severity"] == "critical"
    highs = [a["amount"] for a in acts if a["severity"] == "high"]
    assert highs == sorted(highs, reverse=True)


def test_ids_stable_and_unique():
    ids = [a["id"] for a in build()]
    assert ids == [a["id"] for a in build()] and len(ids) == len(set(ids))


def test_empty_inputs():
    assert actions.build_actions(None, None, None, None, [], AS_OF) == []


def test_named_reason_groups_across_merchants_and_single_generic_skipped():
    fixed = {"month": "2026-10", "groups": [{"items": [
        {"name": "אקספון 018 בע\"מ", "amount": 34.9, "duplicate": True, "duplicate_reason": "שיחות לחו״ל"},
        {"name": "טלזר 019", "amount": 10.0, "duplicate": True, "duplicate_reason": "שיחות לחו״ל"},
        {"name": "מטרו", "amount": 125.0, "duplicate": True, "duplicate_reason": "אותו ספק כמה פעמים"},
    ]}]}
    acts = by_id(build(fixed_expenses=fixed), "dup:")
    assert [a["id"] for a in acts] == ["dup:שיחות לחו״ל:2026-10"]
    assert acts[0]["title"] == "שירות כפול: שיחות לחו״ל" and acts[0]["amount"] == 44.9


def test_validation_failures_join_the_list_by_severity():
    """A failing card-statement check from validate.py lands in "לטיפול" next to the
    built-in actions, sorted by severity like everything else."""
    failing = {"id": "validation:card_statements.amex:2026-10", "severity": "high",
               "title": "חיובי כרטיס חסרים", "detail": "29 raw vouchers missing from the ledger",
               "cta": {"label": "לסנכרונים", "to": "/syncs"}, "amount": 5212.89}
    out = actions.build_actions(None, None, None, [], [], date(2026, 10, 16), [failing])
    assert out == [failing]
