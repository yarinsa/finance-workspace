"""Bills built from the ledger: real October-2026 series (rent, loans, subscriptions
RiseUp never had, bi-monthly water, electricity)."""
from datetime import date

from finance.views import bills

AS_OF = date(2026, 10, 20)
BUDGET = {"budgetDate": "2026-10", "cashflowStartDay": 1}


def tx(day, description, amount, category, kind="fixed", kind_source="recurring", **kw):
    return {"date": day, "description": description, "amount": amount, "category": category,
            "kind": kind, "kind_source": kind_source, **kw}


def monthly(description, amount, category, months, day=2, **kw):
    return [tx(f"2026-{m:02d}-{day:02d}", description, amount, category, **kw) for m in months]


RENT = 'הו"ק לעיין ניהול נכסי,לסניף 20-406'


def build(ledger, as_of=AS_OF, budget=BUDGET):
    return bills.build_bills(budget, ledger, as_of)


def by_name(block, frag):
    return next(i for i in block["items"] if frag in i["name"])


def test_rent_paid_this_cycle():
    b = build(monthly(RENT, -6800.0, "שכר דירה", range(7, 11), day=11, kind_source="merchant"))
    rent = by_name(b, "ניהול נכסי")
    assert (rent["status"], rent["paid_on"], rent["amount"], rent["kind"]) == ("paid", "2026-10-11", 6800.0, "bill")
    assert rent["name"] == 'הו"ק לעיין ניהול נכסי'


def test_subscription_riseup_never_had_is_a_bill():
    """SUPERHUMAN MAIL ₪95.51 on amex every month, not in any RiseUp envelope."""
    b = build(monthly("SUPERHUMAN MAIL", -95.51, "דיגיטל", range(7, 10), day=27))
    s = by_name(b, "SUPERHUMAN")
    assert (s["kind"], s["status"], s["due_date"]) == ("subscription", "upcoming", "2026-10-27")


def test_missing_monthly_charge_is_overdue():
    """SpotifyIL ₪43.90 lands on the 11th; by the 20th with no charge it is overdue."""
    b = build(monthly("SpotifyIL", -43.9, "דיגיטל", range(6, 10), day=11))
    assert by_name(b, "Spotify")["status"] == "overdue"


def test_two_apple_subscriptions_are_two_bills():
    ledger = (monthly("APPLE.COM/BILL         CORK          IRL", -39.9, "דיגיטל", range(7, 11), day=13)
              + monthly("APPLE.COM/BILL         CORK          IRL", -59.5, "דיגיטל", range(7, 11), day=14))
    assert sorted(i["amount"] for i in build(ledger)["items"]) == [39.9, 59.5]


def test_mortgage_step_up_keeps_only_the_current_series():
    """דסק-משכנתא went ₪1,707.54 -> ₪5,817.25: the old amount is no longer a bill."""
    ledger = (monthly("דסק-משכנתא,חיוב", -1707.54, "משכנתא", (4, 5, 6), day=10)
              + monthly("דסק-משכנתא,חיוב", -5817.25, "משכנתא", (7, 8, 9, 10), day=11))
    items = build(ledger)["items"]
    assert [(i["amount"], i["kind"]) for i in items] == [(5817.25, "loan")]


def test_arrears_payoff_fixed_only_by_category_is_not_a_bill():
    """סילוק פיגור ₪1,507 twice: הלוואה defaults to fixed, but it is no bill."""
    ledger = monthly("סילוק פיגור", -1507.22, "הלוואה", (8, 9), day=11, kind_source="category")
    assert build(ledger)["items"] == []


def test_one_off_and_variable_rows_are_not_bills():
    ledger = monthly("WOLT", -85.0, "אוכל בחוץ", range(7, 11), kind="variable", kind_source="category")
    ledger.append(tx("2026-10-12", "פירעון הלוואה 15500316168", -52312.43, "הלוואה",
                     kind="variable", kind_source="one_off"))
    assert build(ledger)["items"] == []


def test_stale_series_is_dropped():
    """A subscription last charged in June is cancelled, not overdue."""
    assert build(monthly("help.hbomax.com", -49.9, "דיגיטל", (3, 4, 5, 6), day=3))["items"] == []


def test_bimonthly_water_is_estimated_in_its_month():
    """מי אביבים bills every two months: due in October after August, estimated from
    the median of the last three."""
    water = "מי אביבים 2010 בע\"מ חיוב תקופתי"
    ledger = [tx(f"2026-{m:02d}-12", water, a, "מים", kind="variable", kind_source="category")
              for m, a in ((4, -115.0), (6, -191.0), (8, -162.32))]
    w = by_name(build(ledger), "מי אביבים")
    assert (w["estimated"], w["cadence_months"], w["amount"], w["status"]) == (True, 2, 162.32, "overdue")


def test_bimonthly_water_not_due_in_the_off_month():
    water = "מי אביבים 2010 בע\"מ חיוב תקופתי"
    ledger = [tx(f"2026-{m:02d}-12", water, -150.0, "מים", kind="variable") for m in (5, 7, 9)]
    assert build(ledger)["items"] == []


def test_electricity_paid_by_any_amount():
    ledger = [tx(f"2026-{m:02d}-18", "חב החשמל-דן תש אינט'", a, "חשמל", kind="variable")
              for m, a in ((7, -556.0), (8, -691.0), (9, -611.37), (10, -499.06))]
    e = by_name(build(ledger), "החשמל")
    assert (e["status"], e["amount"], e["estimated"]) == ("paid", 499.06, False)


def test_order_and_totals():
    ledger = (monthly(RENT, -6800.0, "שכר דירה", range(7, 11), day=11)
              + monthly("SUPERHUMAN MAIL", -95.51, "דיגיטל", range(7, 10), day=27)
              + monthly("SpotifyIL", -43.9, "דיגיטל", range(6, 10), day=11))
    b = build(ledger)
    assert [i["due_date"] for i in b["items"]] == sorted(i["due_date"] for i in b["items"])
    assert (b["paid_total"], b["upcoming_total"], b["overdue_total"]) == (6800.0, 95.51, 43.9)


def test_without_a_budget_doc_the_cycle_is_the_calendar_month():
    b = build(monthly(RENT, -6800.0, "שכר דירה", range(7, 11), day=11), budget=None)
    assert (b["month"], b["cycle_start"], b["cycle_end"]) == ("2026-10", "2026-10-01", "2026-10-31")


def test_clean_name():
    assert bills.clean_name(RENT) == 'הו"ק לעיין ניהול נכסי'
    assert bills.clean_name("דסק-משכנתא,חיוב") == "דסק-משכנתא"


def test_merchant_fixed_by_decision_is_one_bill_whatever_the_amount():
    """The barber (גורביץ מרק) is fixed by a merchant default; ₪120–240 is one bill."""
    ledger = [tx(f"2026-{m:02d}-20", "גורביץ מרק", a, "ספר", kind_source="merchant")
              for m, a in ((7, -160.0), (8, -240.0), (9, -200.0))]
    b = build(ledger)
    assert [(i["name"], i["amount"], i["status"]) for i in b["items"]] == [("גורביץ מרק", 200.0, "upcoming")]


def test_electricity_under_two_payee_names_is_one_bill():
    """חב החשמל-דן (Aug, Sep) and חברת החשמל לישראל ₪499.06 on 2026-10-10 are one
    electricity bill, paid this cycle."""
    ledger = [tx("2026-08-18", "חב החשמל-דן תש אינט'", -691.0, "חשמל", kind="variable"),
              tx("2026-09-18", "חב החשמל-דן תש אינט'", -611.37, "חשמל", kind="variable"),
              tx("2026-10-10", 'חברת החשמל לישראל בע"מ', -499.06, "חשמל", kind="variable")]
    items = build(ledger)["items"]
    assert [(i["category"], i["status"], i["amount"]) for i in items] == [("חשמל", "paid", 499.06)]
