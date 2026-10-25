"""קיזוז: paybacks netted against the expenses they pay back (finance/offsets.py),
and PayBox round trips (digest.mark_round_trips). Every case is a real ledger row."""
import digest
import spending
from finance import offsets

ROOMMATE_RULE = [{"payer": "בללי אסף", "against": ["לעיין ניהול"]}]


def tx(date, amount, description, origin="discount", **kw):
    return {"date": date, "amount": amount, "description": description, "origin": origin,
            "is_income": amount > 0, "sources": [origin], **kw}


def run(ledger, rules=()):
    offsets.suggest(ledger, rules)
    return offsets.resolve(ledger)


# --- merchant refunds (auto) --------------------------------------------------

def test_ticketing_refund_nets_against_the_march_purchase():
    """As the household, the ₪1,255.01 TicketingPayments credit on 2026-07-13 is a
    refund of the ₪1,514.93 tickets on 2026-03-30: March spending is ₪259.92 and
    July has no ₪1,255 'income'."""
    buy = tx("2026-03-30", -1514.93, "TicketingPayments", "cal", category="כללי")
    refund = tx("2026-07-13", 1255.01, "TicketingPayments", "cal", category="כללי")
    run([buy, refund])
    assert buy["offset_amount"] == 1255.01 and refund["offset_amount"] == 1255.01
    assert offsets.net_amount(buy) == -259.92
    assert buy["offsets"][0] == {"date": "2026-07-13", "abs_amount": 1255.01, "amount": 1255.01,
                                 "kind": "refund", "description": "TicketingPayments"}
    view = offsets.cashflow_view([buy, refund])
    assert [(t["date"], t["amount"], t["gross_amount"]) for t in view] == [("2026-03-30", -259.92, -1514.93)]


def test_booking_partial_refund_leaves_the_rest_of_the_hotel_in_may():
    hotel = tx("2026-05-30", -1682.07, "Booking.com Hotel", "cal", category="תיירות")
    back = tx("2026-06-07", 531.75, "Booking.com Hotel", "cal")
    run([hotel, back])
    assert offsets.net_amount(hotel) == -1150.32
    assert offsets.net_amount(back) == 0


def test_wolt_refund_takes_the_latest_order_that_can_absorb_it():
    """WOLT +₪24.70 on 2026-10-13 refunds that day's order, not the 10-07 one."""
    older = tx("2026-10-07", -82.95, "WOLT", "cal")
    same_day = tx("2026-10-13", -84.0, "WOLT", "cal")
    refund = tx("2026-10-13", 24.7, "WOLT", "cal")
    run([older, same_day, refund])
    assert same_day.get("offset_amount") == 24.7 and "offset_amount" not in older


def test_an_exact_amount_purchase_wins_over_a_later_bigger_one():
    """מטרו +₪250.28 on 09-22 is the 08-28 charge of exactly ₪250.28 reversed."""
    exact = tx("2026-08-28", -250.28, "מטרו", "amex")
    later = tx("2026-09-02", -414.25, "מטרו", "amex")
    refund = tx("2026-09-22", 250.28, "מטרו", "amex")
    run([exact, later, refund])
    assert exact["offset_amount"] == 250.28 and "offset_amount" not in later


def test_bank_income_is_never_auto_offset_as_a_refund():
    """`החזר דיסקונט עמלות וריביות` is a bank credit, not a card refund; only a
    manual link can offset it."""
    fee = tx("2026-09-30", -62.95, "החזר דיסקונט עמלות וריביות")
    credit = tx("2026-10-05", 112.95, "החזר דיסקונט עמלות וריביות")
    run([fee, credit])
    assert "offsets" not in credit


def test_a_refund_bigger_than_any_purchase_stays_income():
    """GLOBAL BLUE (tax-free VAT refund) has no purchase of its own to net against."""
    vat = tx("2026-06-20", 60.0, "GLOBAL BLUE HELLAS SA 608", "cal")
    run([tx("2026-06-07", -749.1, "VIVA*234 SYGGROU AVENUE S", "amex"), vat])
    assert "offsets" not in vat


# --- household rule: the roommate's share of the rent ------------------------

def test_roommate_transfers_offset_that_months_rent():
    """As the household, Asaf's ₪3,400 on 2026-09-01 and ₪400 on 09-25 were his share
    of the ₪6,800 rent paid 09-06: September rent counts ₪3,000, and neither transfer
    is income."""
    rent = tx("2026-09-06", -6800.0, 'הו"ק לעיין ניהול נכסי,לסניף 20-406', category="העברות")
    half = tx("2026-09-01", 3400.0, 'הו"ק מבללי אסף,מסניף 11-034', category="העברות")
    bills = tx("2026-09-25", 400.0, 'הו"ק מבללי אסף,מסניף 11-034', category="העברות")
    run([rent, half, bills], ROOMMATE_RULE)
    assert offsets.net_amount(rent) == -3000.0
    assert [o["kind"] for o in rent["offsets"]] == ["rule", "rule"]
    assert offsets.cashflow_view([rent, half, bills]) == [{**rent, "amount": -3000.0, "gross_amount": -6800.0}]


def test_roommate_payment_prefers_the_same_months_rent():
    """The ₪3,400 on 2026-08-02 belongs to August's rent (08-05), not July's (07-05)."""
    july = tx("2026-07-05", -6800.0, 'הו"ק לעיין ניהול נכסי,לסניף 20-406')
    aug = tx("2026-08-05", -6800.0, 'הו"ק לעיין ניהול נכסי,לסניף 20-406')
    pay = tx("2026-08-02", 3400.0, 'הו"ק מבללי אסף,מסניף 11-034')
    run([july, aug, pay], ROOMMATE_RULE)
    assert aug["offset_amount"] == 3400.0 and "offset_amount" not in july


def test_october_rent_after_the_move_out_is_paid_in_full():
    """Asaf moved out in Sep 2026: October's ₪6,800 has nothing to net against."""
    oct_rent = tx("2026-10-11", -6800.0, 'הו"ק לעיין ניהול נכסי,לסניף 20-406', category="שכר דירה")
    run([oct_rent, tx("2026-09-25", 400.0, 'הו"ק מבללי אסף,מסניף 11-034'),
         tx("2026-09-06", -6800.0, 'הו"ק לעיין ניהול נכסי,לסניף 20-406')], ROOMMATE_RULE)
    assert offsets.net_amount(oct_rent) == -6800.0


# --- manual links ---------------------------------------------------------------

def test_a_manual_link_replaces_the_auto_one():
    """The user says the ₪531.75 Booking credit refunds the Amex hotel, not the CAL one."""
    cal = tx("2026-05-30", -1682.07, "Booking.com Hotel", "cal")
    amex = tx("2026-06-06", -508.84, "HOTEL ON BOOKING.COM", "amex")
    back = tx("2026-06-07", 531.75, "Booking.com Hotel", "cal")
    offsets.suggest([cal, amex, back])
    back["manual_offsets"] = [{"date": "2026-06-06", "abs_amount": 508.84, "amount": 531.75, "kind": "manual"}]
    offsets.resolve([cal, amex, back])
    assert "offsets" not in cal
    assert amex["offset_amount"] == 508.84            # clamped to the expense
    assert offsets.net_amount(back) == 22.91          # the rest is still income
    assert amex["offsets"][0]["kind"] == "manual"


def test_an_empty_manual_decision_turns_auto_off():
    buy = tx("2026-03-30", -1514.93, "TicketingPayments", "cal")
    refund = tx("2026-07-13", 1255.01, "TicketingPayments", "cal")
    offsets.suggest([buy, refund])
    refund["manual_offsets"] = []
    offsets.resolve([buy, refund])
    assert "offsets" not in buy and "offsets" not in refund


def test_manual_links_get_the_shekels_before_auto_ones():
    """A Bit from a friend linked by hand to dinner keeps its ₪ even when an
    auto refund later wants the same expense."""
    dinner = tx("2026-05-03", -532.0, "רוטשילד 142 בע\"מ", "cal")
    friend = tx("2026-05-10", 450.0, "מפייבוקס ש", manual_offsets=[
        {"date": "2026-05-03", "abs_amount": 532.0, "amount": 450.0, "kind": "manual"}])
    refund = tx("2026-05-12", 200.0, "רוטשילד 142 בע\"מ", "cal")
    run([dinner, friend, refund])
    assert dinner["offset_amount"] == 450.0          # refund (₪200) no longer fits in the ₪82 left
    assert "offsets" not in refund and offsets.net_amount(refund) == 200.0


def test_a_link_to_a_vanished_expense_is_dropped():
    back = tx("2026-06-07", 531.75, "Booking.com Hotel", "cal", manual_offsets=[
        {"date": "2026-05-30", "abs_amount": 1682.07, "amount": 531.75, "kind": "manual"}])
    offsets.resolve([back])
    assert "offsets" not in back and offsets.net_amount(back) == 531.75


def test_candidates_for_dinner_put_same_merchant_and_nearest_first():
    dinner = tx("2026-05-03", -532.0, "רוטשילד 142 בע\"מ", "cal")
    bit = tx("2026-05-10", 450.0, "מפייבוקס ש")
    early = tx("2026-04-19", 90.0, "מפייבוקס ש")
    salary = tx("2026-05-08", 26144.0, "העברת משכורת")
    used = tx("2026-05-14", 450.0, "מפייבוקס ש", offset_amount=450.0)
    far = tx("2026-12-01", 100.0, "מפייבוקס ש")
    got = offsets.candidates([dinner, bit, early, salary, used, far], dinner)
    assert [t["date"] for t in got] == ["2026-05-08", "2026-05-10", "2026-04-19"]


# --- PayBox round trips ---------------------------------------------------------

def test_paybox_load_and_cash_out_are_a_round_trip():
    """As the household, `PAYBOX` −₪1,000 on Amex (2026-09-28) and `מפייבוקס ש`
    +₪1,000 at Discount the next day are our own money going around."""
    load = tx("2026-09-28", -1000.0, "PAYBOX", "amex", category="העברות")
    out = tx("2026-09-29", 1000.0, "מפייבוקס ש", "discount")
    digest.mark_round_trips([load, out])
    assert load["internal_transfer"] and out["internal_transfer"] and load["round_trip"]
    assert spending.classify(load) == "transfers"


def test_paybox_to_leumi_two_days_later_is_a_round_trip_too():
    load = tx("2026-08-21", -1000.0, "PAYBOX", "amex")
    out = tx("2026-08-23", 1000.0, "מפייבוקס שלי-י", "leumi")
    digest.mark_round_trips([load, out])
    assert out.get("round_trip")


def test_paying_someone_through_paybox_stays_spend():
    """`PAYBOX` −₪1,000 on 2026-06-13 has no cash-out: real money to someone."""
    load = tx("2026-06-13", -1000.0, "PAYBOX", "amex")
    other = tx("2026-06-15", 745.0, "מפייבוקס ש", "discount")
    digest.mark_round_trips([load, other])
    assert "round_trip" not in load and "round_trip" not in other


def test_each_cash_out_pairs_with_one_load():
    a = tx("2026-08-07", -1000.0, "PAYBOX", "amex")
    b = tx("2026-08-08", -1000.0, "PAYBOX", "amex")
    out = tx("2026-08-09", 1000.0, "מפייבוקס שלי-י", "leumi")
    digest.mark_round_trips([a, b, out])
    assert a.get("round_trip") and not b.get("round_trip")


# --- downstream: spending explorer ----------------------------------------------

def test_spending_counts_the_net_but_keeps_the_charge_as_the_row_key():
    buy = tx("2026-03-30", -1514.93, "TicketingPayments", "cal", category="כללי")
    refund = tx("2026-07-13", 1255.01, "TicketingPayments", "cal", category="כללי")
    run([buy, refund])
    months = spending.build_spending(offsets.cashflow_view([buy, refund]))["months"]
    march = next(m for m in months if m["month"] == "2026-03")
    assert march["total"] == 259.92
    row = march["transactions"][0]
    assert row["amount"] == 1514.93 and row["offset"] == 1255.01
    assert row["offsets"][0]["date"] == "2026-07-13"
    assert not any(m["month"] == "2026-07" for m in months)    # the refund is not July income
