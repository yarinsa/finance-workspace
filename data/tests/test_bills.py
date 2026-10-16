"""Real-case tests for the bills block (PRD 12, Phase 1).

- Rent `הו"ק לעיין ניהול נכסי` has an actual on 10-11 -> paid.
- Electricity `חב החשמל-דן` has no actual and its day (16th) has passed -> overdue.
- `מענק בנק לאומי` is an income envelope -> not a bill.
- `הו"ק לששון ירין` goes to our own business account -> not a bill.
"""
from datetime import date

import bills


def env(name, amount, category, tx_date, actual=None):
    return {"type": "fixed", "originalAmount": amount,
            "details": {"businessName": name, "expense": category, "transactionDate": tx_date},
            "actuals": [{"transactionDate": actual}] if actual else []}


BUDGET = {"budgetDate": "2026-10", "cashflowStartDay": 1, "envelopes": [
    env('הו"ק לעיין ניהול נכסי,לסניף 20-406', 6800, "דיור", "2026-10-06T00:00:00.000Z", "2026-10-11"),
    env("חב החשמל-דן תש אינט'", 536.61, "חשמל", "2026-10-16T00:00:00.000Z"),
    env("פרטנר תקשורת בע\"מ", 135.14, "תקשורת", "2026-10-25T00:00:00.000Z"),
    env("מענק בנק לאומי", -323.24, "העברות", "2026-10-02T00:00:00.000Z", "2026-10-02"),
    env('הו"ק לששון ירין,לסניף 11-034', 452, "תשלומים", "2026-10-10T00:00:00.000Z", "2026-10-11"),
    env("SpotifyIL", 43.9, "דיגיטל", "2026-10-09T00:00:00.000Z", "2026-10-10"),
    env("רשת ללא היסטוריה", 20, "ספר", "2026-09-05T00:00:00.000Z"),
    {"type": "trackingCategory", "originalAmount": 900, "details": {"businessName": "food"}, "actuals": []},
]}
AS_OF = date(2026, 10, 20)


def by_name(block, frag):
    return next(i for i in block["items"] if frag in i["name"])


def test_rent_paid():
    r = by_name(bills.build_bills(BUDGET, [], AS_OF), "ניהול נכסי")
    assert r["status"] == "paid" and r["paid_on"] == "2026-10-11" and r["due_day"] == 11
    assert r["name"] == 'הו"ק לעיין ניהול נכסי'


def test_electricity_overdue():
    b = bills.build_bills(BUDGET, [], AS_OF)
    e = by_name(b, "החשמל")
    assert e["status"] == "overdue" and e["due_day"] == 16
    assert b["overdue_total"] == 536.61


def test_income_and_own_transfer_excluded():
    names = [i["name"] for i in bills.build_bills(BUDGET, [], AS_OF)["items"]]
    assert not any("מענק" in n or "ששון" in n for n in names)


def test_upcoming_and_totals_and_order():
    b = bills.build_bills(BUDGET, [], AS_OF)
    assert by_name(b, "פרטנר")["status"] == "upcoming"
    assert b["paid_total"] == round(6800 + 43.9, 2)
    assert b["upcoming_total"] == round(135.14 + 20, 2)
    assert b["items"][-1]["due_day"] is None  # no day known -> last
    days = [i["due_day"] for i in b["items"] if i["due_day"]]
    assert days == sorted(days)


def test_due_day_from_ledger_recurrence():
    tx = [{"date": "2026-09-14", "description": "חב החשמל-דן תש אינט'", "amount": -500}]
    budget = {"budgetDate": "2026-10", "envelopes": [env("חב החשמל-דן תש אינט'", 536.61, "חשמל", "2026-09-01T00:00:00.000Z")]}
    assert bills.build_bills(budget, tx, date(2026, 10, 1))["items"][0]["due_day"] == 14


def test_no_budget():
    assert bills.build_bills(None, [], AS_OF) is None
