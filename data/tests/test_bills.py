"""Real-case tests for the bills block (PRD 12, Phase 1).

- Rent `הו"ק לעיין ניהול נכסי` has an actual on 10-11 -> paid.
- Electricity `חב החשמל-דן` has no actual and its day (16th) has passed -> overdue.
- `מענק בנק לאומי` is an income envelope -> not a bill.
- `הו"ק לששון ירין` goes to our own business account -> not a bill.
- Category and kind come from the taxonomy, not RiseUp's label: rent (RiseUp "דיור")
  is שכר דירה, a bill; the loan a loan; Spotify (group מנויים) a subscription.
- `פרטנר` was charged on CAL on 10-25 but RiseUp had not matched it -> paid from the ledger.
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


def test_category_and_kind_come_from_the_taxonomy():
    budget = {"budgetDate": "2026-10", "envelopes": [
        env("פרעון הלוואה", 1844.42, "הלוואה", "2026-10-02T00:00:00.000Z", "2026-10-02"),
        env("גורביץ מרק", 120, "ספר", "2026-10-07T00:00:00.000Z")]}
    b = bills.build_bills({**budget, "envelopes": BUDGET["envelopes"] + budget["envelopes"]}, [], AS_OF)
    rent = by_name(b, "ניהול נכסי")
    assert (rent["category"], rent["group"], rent["kind"]) == ("שכר דירה", "דיור", "bill")
    assert by_name(b, "פרעון הלוואה")["kind"] == "loan"
    assert by_name(b, "Spotify")["kind"] == "subscription"
    assert (by_name(b, "גורביץ")["category"], by_name(b, "גורביץ")["kind"]) == ("ספר", "bill")


def test_category_follows_the_ledger_for_the_same_payee():
    # the household re-filed the Partner line as a business expense
    tx = [{"date": "2026-09-25", "description": 'פרטנר תקשורת בע"מ', "amount": -135.14,
           "category": "הוצאות עסק", "merchant": 'פרטנר תקשורת בע"מ'}]
    assert by_name(bills.build_bills(BUDGET, tx, AS_OF), "פרטנר")["category"] == "הוצאות עסק"


def test_ledger_charge_riseup_has_not_matched_pays_the_bill():
    tx = [{"date": "2026-10-25", "description": 'פרטנר תקשורת בע"מ', "amount": -135.14},
          # the card fee went up from ₪98.40 to ₪102.38: still the same bill
          {"date": "2026-10-23", "description": "דמי כרטיס /הנפקה", "amount": -102.38}]
    budget = {**BUDGET, "envelopes": BUDGET["envelopes"] + [
        env("דמי כרטיס /הנפקה", 98.4, "עמלות", "2026-10-25T00:00:00.000Z")]}
    b = bills.build_bills(budget, tx, date(2026, 10, 27))
    assert by_name(b, "פרטנר")["status"] == "paid" and by_name(b, "פרטנר")["paid_on"] == "2026-10-25"
    assert by_name(b, "דמי כרטיס")["status"] == "paid"


def test_a_different_amount_from_the_same_payee_does_not_pay_it():
    # the barber: ₪120 standing visit expected, a ₪240 visit on 10-18 is something else
    tx = [{"date": "2026-10-18", "description": "גורביץ מרק", "amount": -240.0}]
    budget = {"budgetDate": "2026-10", "envelopes": [env("גורביץ מרק", 120, "ספר", "2026-10-07T00:00:00.000Z")]}
    assert bills.build_bills(budget, tx, AS_OF)["items"][0]["status"] == "overdue"


def test_electricity_is_paid_by_any_amount():
    tx = [{"date": "2026-10-16", "description": "חב החשמל-דן תש אינט'", "amount": -611.37, "category": "חשמל"}]
    assert by_name(bills.build_bills(BUDGET, tx, AS_OF), "החשמל")["status"] == "paid"


def test_one_charge_pays_one_bill():
    # two Apple envelopes; RiseUp matched the ₪59.50 one, the ledger has only that charge
    budget = {"budgetDate": "2026-10", "envelopes": [
        env("APPLE.COM/BILL         CORK          IRL", 59.5, "דיגיטל", "2026-10-15T00:00:00.000Z", "2026-10-15"),
        env("APPLE.COM/BILL         CORK          IRL", 55.0, "דיגיטל", "2026-10-15T00:00:00.000Z")]}
    tx = [{"date": "2026-10-15", "description": "APPLE.COM/BILL", "amount": -59.5}]
    statuses = sorted(i["status"] for i in bills.build_bills(budget, tx, AS_OF)["items"])
    assert statuses == ["overdue", "paid"]
