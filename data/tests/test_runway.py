"""Real-case tests for runway.py (balance runway / safe-to-spend)."""
from datetime import date

from finance.views import runway

AS_OF = date(2026, 10, 16)
RENT = 'הו"ק לעיין ניהול נכסי,לסניף 20-406'
MORT = "דסק-משכנתא,חיוב"


def tx(d, amount, desc, origin="discount", **kw):
    return {"date": d, "amount": amount, "description": desc, "origin": origin,
            "category": kw.pop("category", "כללי"), **kw}


def events(rows, as_of=AS_OF):
    items = runway.infer_recurring(rows, as_of)
    return runway.project_events(items, rows, as_of, date(2026, 11, 30))


def by_name(evs, name):
    return [e for e in evs if e["name"] == name]


def test_rent_projects_to_nov_11():
    rows = [tx("2026-09-06", -6800, RENT, category="העברות"),
            tx("2026-10-11", -6800, RENT, category="העברות")]
    (e,) = by_name(events(rows), RENT)
    assert e["date"] == "2026-11-11" and e["amount"] == -6800 and e["kind"] == "housing"


def test_mortgage_sunday_shift_corrected_to_day_10():
    rows = [tx("2026-09-10", -5875.97, MORT, category="משכנתא"),
            tx("2026-10-11", -5717.0, MORT, category="משכנתא")]
    (e,) = by_name(events(rows), MORT)
    assert e["date"] == "2026-11-10" and e["kind"] == "loan"


def test_internal_transfer_and_cash_never_projected():
    rows = [tx("2026-09-08", -22500, "העברת משכור700", internal_transfer=True),
            tx("2026-10-08", -22500, "העברת משכור700", internal_transfer=True),
            tx("2026-09-12", -500, "משיכת מזומן ללא כרטיס"),
            tx("2026-10-12", -500, "משיכת מזומן ללא כרטיס")]
    assert events(rows) == []


def test_key_seen_in_one_month_not_projected():
    assert events([tx("2026-10-03", -120, "חיוב חד פעמי")]) == []


def test_saturday_due_posts_next_sunday():
    # day 14 of Nov 2026 is Saturday -> Sunday 15th
    rows = [tx("2026-09-14", -300, "חיוב קבוע"), tx("2026-10-14", -300, "חיוב קבוע")]
    (e,) = by_name(events(rows), "חיוב קבוע")
    assert e["date"] == "2026-11-15"


def test_two_loans_differing_only_by_id_both_project():
    a, b = "פירעון הלוואה 10800100014", "פירעון הלוואה 15500316168"
    rows = [tx(f"2026-{m}-02", -667, a) for m in ("09", "10")] + \
           [tx(f"2026-{m}-02", -306, b) for m in ("09", "10")]
    evs = events(rows)
    assert len(by_name(evs, a)) == 1 and len(by_name(evs, b)) == 1
    assert by_name(evs, a)[0]["kind"] == "loan"


def test_leumi_mastercard_is_card_kind():
    rows = [tx("2026-09-10", -2256.7, "ל.מאסטרקארד", origin="leumi"),
            tx("2026-10-11", -1914, "ל.מאסטרקארד", origin="leumi")]
    (e,) = events(rows)
    assert e["kind"] == "card" and e["amount"] == -1914 and e["date"] == "2026-11-10"


def test_runway_payday_and_safe_to_spend():
    sal = "העברת משכורת"
    rows = [tx("2026-09-08", 26145, sal, origin="leumi", category="משכורת"),
            tx("2026-10-08", 26144, sal, origin="leumi", category="משכורת"),
            tx("2026-09-06", -6800, RENT, category="העברות"),
            tx("2026-10-11", -6800, RENT, category="העברות")]
    accounts = [{"institution": "discount", "kind": "checking", "balance": -5831.15,
                 "overdraft_limit": 10000},
                {"institution": "leumi", "kind": "checking", "balance": 2813.94},
                {"institution": "discount-business", "kind": "business_checking", "balance": 38.09}]
    savings = [{"label": "נזיל יומי+", "liquid": True, "balance": 2490.2},
               {"label": "pension", "liquid": False, "balance": 1}]
    r = runway.build_runway(rows, accounts, savings, AS_OF)
    assert r["start_balance"] == -3017.21 and r["overdraft_limit"] == 10000
    assert r["liquid_buffer"] == [{"label": "נזיל יומי+", "balance": 2490.2}]
    assert r["next_payday"]["date"] == "2026-11-08"
    assert r["days_to_payday"] == 23
    # rent on the 11th is after payday, so the low before payday is today's balance
    assert r["low_before_payday"] == {"date": "2026-10-16", "balance": -3017.21}
    assert r["safe_to_spend"] == -3017.21 and r["safe_per_day"] is None
    assert r["headroom_to_limit"] == 6982.79
    assert r["first_floor_breach"] == "2026-10-16" and r["first_limit_breach"] is None
    assert r["days"][0]["date"] == "2026-10-16" and r["days"][-1]["date"] == "2026-11-30"
    assert r["events"][-1]["balance_after"] == r["days"][-1]["balance"]


def test_safe_per_day_when_positive_and_bill_before_payday():
    bill = "חיוב קבוע"
    rows = [tx("2026-09-20", -1000, bill), tx("2026-10-20", -1000, bill),
            tx("2026-09-08", 5000, "העברת משכורת", origin="leumi", category="משכורת"),
            tx("2026-10-08", 5000, "העברת משכורת", origin="leumi", category="משכורת")]
    accounts = [{"institution": "leumi", "kind": "checking", "balance": 4000}]
    r = runway.build_runway(rows, accounts, [], AS_OF)
    # bill on Nov 20 is after payday Nov 8; none before -> low is start
    assert r["safe_to_spend"] == 4000 and r["safe_per_day"] == round(4000 / 23, 2)


def test_stopped_income_and_small_salary_tagged_refund_ignored():
    # real: partner's standing order stopped in Oct; fee refunds are tagged משכורת
    so = 'הו"ק מבללי אסף,מסניף 11-034'
    rows = [tx("2026-08-02", 3400, so), tx("2026-09-01", 3400, so),
            tx("2026-09-04", 80, "החזר דיסקונט עמלות וריביות", category="משכורת"),
            tx("2026-10-05", 112.95, "החזר דיסקונט עמלות וריביות", category="משכורת")]
    evs = events(rows)
    assert not by_name(evs, so)
    accounts = [{"institution": "leumi", "kind": "checking", "balance": 1000}]
    assert runway.build_runway(rows, accounts, [], AS_OF)["next_payday"] is None
