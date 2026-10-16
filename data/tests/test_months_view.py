"""Months view: real October-2026 decisions (salary, rent, loan, card bill, Wolt)."""
from datetime import date

import months_view as mv

AS_OF = date(2026, 10, 16)


def tx(d, desc, amount, category=None, **flags):
    return {"date": d, "description": desc, "amount": amount, "category": category, **flags}


RENT = 'הו"ק לעיין ניהול נכסי'
LEDGER = [
    tx("2026-10-01", "העברת משכורת", 26144, "משכורת", is_income=True),
    tx("2026-10-02", RENT, -6800, "דיור"),
    tx("2026-10-03", "פרעון הלוואה", -1844.42, "הלוואה"),
    tx("2026-10-04", "אמריקן אקס,חיוב", -3000, None, card_bill_payment=True),
    tx("2026-10-05", "WOLT", -85, "אוכל בחוץ"),
    tx("2026-10-22", "WOLT", -999, "אוכל בחוץ"),          # RiseUp future-dated card row
    tx("2026-10-06", "הפקדה לקרן", -500, "השקעה וחיסכון", savings=True),
    tx("2026-09-02", RENT, -6800, "דיור"),
    tx("2026-09-05", "WOLT", -60, "אוכל בחוץ"),
]
FORECAST = {
    "current_month": {
        "forecast_month": "2026-10",
        "income": {"total": 27000, "items": []},
        "expenses": {"total": 20000, "fixed_total": 13000, "discretionary_total": 7000,
                     "fixed_items": [
                         {"name": RENT, "category": "דיור", "amount": 6800},
                         {"name": "פרעון הלוואה", "category": "הלוואה", "amount": 1844.42},
                         {"name": "משכנתא", "category": "משכנתא", "amount": 4355.58}]},
    },
    "months": [{
        "forecast_month": "2026-11",
        "income": {"total": 27163.8, "items": []},
        "expenses": {"total": 27620.76, "fixed_total": 19679.08, "discretionary_total": 7941.68,
                     "fixed_items": [
                         {"name": RENT, "category": "דיור", "amount": 6800},
                         {"name": "משכנתא — full", "category": "משכנתא", "amount": 5817.26}]},
    }],
}


def build():
    return mv.build_months_view(LEDGER, FORECAST, [], AS_OF)


def month(view, key):
    return next(m for m in view["months"] if m["month"] == key)


def actual(m, key):
    return next(g for g in m["groups"] if g["key"] == key)["actual"]


def test_ordering_and_kinds():
    v = build()
    assert v["current"] == "2026-10"
    assert [m["month"] for m in v["months"]] == [
        "2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09",
        "2026-10", "2026-11", "2026-12", "2027-01"]
    assert [m["kind"] for m in v["months"]] == ["actual"] * 6 + ["current"] + ["projected"] * 3
    assert [g["key"] for g in v["months"][0]["groups"]] == ["income", "fixed", "variable", "debt_savings"]


def test_october_classification():
    m = month(build(), "2026-10")
    assert actual(m, "income") == 26144          # salary
    assert actual(m, "fixed") == 6800            # rent (recurring + דיור)
    assert actual(m, "debt_savings") == 1844.42 + 500   # loan + savings deposit
    assert actual(m, "variable") == 85           # WOLT, future-dated one ignored
    assert m["expense"] == 6800 + 1844.42 + 500 + 85
    assert m["net"] == round(26144 - m["expense"], 2)


def test_card_bill_and_future_row_excluded():
    m = month(build(), "2026-10")
    assert [c for c in m["categories"] if c["name"] == "אוכל בחוץ"] == [
        {"name": "אוכל בחוץ", "amount": 85.0, "count": 1}]
    assert m["expense"] < 10000                  # 3,000 card bill not counted


def test_projected_month_mortgage_is_debt_expected():
    m = month(build(), "2026-11")
    g = {x["key"]: x for x in m["groups"]}
    assert g["debt_savings"]["expected"] == 5817.26
    assert g["fixed"]["expected"] == round(19679.08 - 5817.26, 2)
    assert g["variable"]["expected"] == 7941.68
    assert all(x["actual"] is None for x in m["groups"])
    assert (m["income"], m["expense"], m["categories"]) == (27163.8, 27620.76, [])
    assert month(build(), "2026-12")["income"] is None   # forecast gap, not invented


def test_projected_end_current_month():
    pe = month(build(), "2026-10")["projected_end"]
    # income 27000 vs actual 26144 -> expected; fixed 6800 seen; debt 1844.42+4355.58
    # expected vs 2344.42 actual -> remainder; variable max(85, 7000)
    assert pe["income"] == 27000
    assert pe["expense"] == round(6800 + 2344.42 + (6200 - 2344.42) + 7000, 2)


def test_past_month_expected_from_budget_doc():
    doc = {"budgetDate": "2026-09", "envelopes": [
        {"type": "fixed", "originalAmount": -6800, "details": {"expense": "דיור", "businessName": RENT}},
        {"type": "fixed", "originalAmount": 26000, "details": {"isIncome": True, "expense": "משכורת", "businessName": "העברת משכורת"}},
        {"type": "fixed", "originalAmount": -1800, "details": {"expense": "הלוואה", "businessName": "פרעון הלוואה"}},
        {"type": "trackingCategory", "originalAmount": 300, "details": {}},
    ]}
    v = mv.build_months_view(LEDGER, FORECAST, [doc], AS_OF)
    g = {x["key"]: x for x in month(v, "2026-09")["groups"]}
    assert (g["income"]["expected"], g["fixed"]["expected"], g["debt_savings"]["expected"],
            g["variable"]["expected"]) == (26000, 6800, 1800, 300)
    assert month(v, "2026-08")["groups"][0]["expected"] is None
