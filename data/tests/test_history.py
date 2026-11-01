"""finance/views/history.py: the home screen's cash and debt history, from the real 2026-10-27 dumps."""
from datetime import date

from finance.models import balance_days
from finance.views import history


def measured(ops):
    """A chain as the normalizers store it (the balance_days entity): {date: end-of-day balance}."""
    days = balance_days([{**o, "date": o["date"].isoformat()} for o in ops])
    return {date.fromisoformat(d["date"]): d["balance"] for d in days}

# Discount's running-balance chain starts on 2026-10-05 (raw/transactions.json, oldest first).
DISCOUNT_OPS = [
    {"date": date(2026, 10, 5), "amount": -450.0, "balance_after": 822.92, "description": "הע. לדקלה בלמס בסניף 20-433"},
    {"date": date(2026, 10, 5), "amount": 112.95, "balance_after": 935.87, "description": "החזר דיסקונט עמלות וריביות"},
    {"date": date(2026, 10, 5), "amount": 450.0, "balance_after": 1385.87, "description": "העברה מירין ששון חשבון ב.הפועלים-ביט משיכה לחשבון בנק"},
    {"date": date(2026, 10, 5), "amount": 200.0, "balance_after": 1585.87, "description": "העברה מירין ששון חשבון ב.הפועלים-ביט משיכה לחשבון בנק"},
    {"date": date(2026, 10, 5), "amount": -99.88, "balance_after": 1485.99, "description": "קרן מכבי חיוב"},
    {"date": date(2026, 10, 6), "amount": -12.38, "balance_after": 1473.61, "description": "מקס איט פי חיוב"},
]
# The normalized ledger before the chain.
DISCOUNT_ROWS = [
    {"date": "2026-10-01", "amount": -700.0, "description": "משיכת מזומן ללא כרטיס"},
    {"date": "2026-10-02", "amount": -306.47, "description": "פירעון הלוואה 15500316168"},
    {"date": "2026-10-02", "amount": -666.72, "description": "פירעון הלוואה 10800100014"},
    {"date": "2026-10-04", "amount": -700.0, "description": "אמריקן אקס חיוב"},
]
AS_OF = date(2026, 10, 8)


def test_chain_days_are_the_banks_own_balances_and_today_is_the_current_balance():
    bal, start = history.account_balances(measured(DISCOUNT_OPS), DISCOUNT_ROWS, 1473.61, AS_OF, days=10)
    assert start == date(2026, 10, 5)
    assert bal[date(2026, 10, 5)] == 1485.99          # end of day = the day's last operation
    assert bal[date(2026, 10, 6)] == 1473.61
    assert bal[date(2026, 10, 7)] == 1473.61          # no operation: carried
    assert bal[AS_OF] == 1473.61


def test_days_before_the_chain_walk_back_through_the_ledger():
    """Opening of 10-05 is 822.92 + 450 = 1,272.92 (end of 10-04). Undoing the AMEX bill
    gives 1,972.92 at the end of 10-03, both loan payments 2,946.11 at the end of 10-01,
    and the cash withdrawal 3,646.11 at the end of 09-30 — as far as the ledger reaches."""
    bal, _ = history.account_balances(measured(DISCOUNT_OPS), DISCOUNT_ROWS, 1473.61, AS_OF, days=30)
    assert bal[date(2026, 10, 4)] == 1272.92
    assert bal[date(2026, 10, 3)] == 1972.92
    assert bal[date(2026, 10, 2)] == 1972.92
    assert bal[date(2026, 10, 1)] == 2946.11
    assert bal[date(2026, 9, 30)] == 3646.11
    assert date(2026, 9, 29) not in bal


def test_pool_lists_only_days_both_banks_know_and_says_where_measurement_starts():
    """Leumi's chain (from 07-08) ends on 10-18 at 2,413.94 after the salary forward."""
    leumi_ops = [
        {"date": date(2026, 10, 1), "amount": -10.0, "balance_after": 1083.94},
        {"date": date(2026, 10, 8), "amount": 26144.0, "balance_after": 27227.94},
    ]
    discount = history.account_balances(measured(DISCOUNT_OPS), DISCOUNT_ROWS, 1473.61, AS_OF, days=10)
    leumi = history.account_balances(measured(leumi_ops), [], 27227.94, AS_OF, days=10)
    pool = history.cash_history([discount, leumi], AS_OF)
    assert pool["days"][0] == {"date": "2026-09-30", "balance": 3646.11 + 1093.94}
    assert pool["days"][-1] == {"date": "2026-10-08", "balance": round(1473.61 + 27227.94, 2)}
    assert pool["measured_from"] == "2026-10-05"     # Discount's chain starts last


def test_debt_series_counts_a_loan_once_and_ends_it_on_schedule():
    """The Discount consumer loan (5.75%, ₪308.25/mo, 99 left) and the 0% שעורין loan (₪666.72/mo,
    23 left). The duplicated Leumi record is counted once."""
    loans = [
        {"lender": "Bank Discount", "loan_id": "0034015500316168", "category": "consumer", "balance": 24443.65,
         "rate_pct": 5.75, "payments_remaining": 99, "payments_total": 120, "monthly_payment": 308.25},
        {"lender": "Bank Discount", "loan_id": "0034010800100014", "category": "consumer", "balance": 15332.64,
         "rate_pct": 0.0001, "payments_remaining": 23, "payments_total": 36, "monthly_payment": 666.72},
        {"lender": "Bank Leumi", "loan_id": "25290013", "category": "consumer", "balance": 43894.94,
         "rate_pct": 8.0, "payments_remaining": 26, "payments_total": 26, "monthly_payment": 1844.42},
        {"lender": "Bank Leumi", "loan_id": "25290013", "category": "consumer", "balance": 43894.94,
         "rate_pct": 8.0, "payments_remaining": 26, "payments_total": 26, "monthly_payment": 1844.42},
    ]
    s = history.debt_series(loans, date(2026, 10, 27), back=2, ahead=30)
    now = next(p for p in s if p["kind"] == "actual")
    assert now["month"] == "2026-10"
    assert now["total"] == round(24443.65 + 15332.64 + 43894.94, 2)
    assert now["mortgage"] == 0
    # Two months ago every loan was higher (paid down since). Leumi's page has no schedule, so
    # it reports 26 of 26 left: "none made" there means unknown, and it is reverse-amortized too.
    assert s[0]["kind"] == "estimated" and s[0]["month"] == "2026-08"
    assert s[0]["total"] > now["total"]
    # A loan whose payments are all known to be ahead of it did not exist before: the שעורין
    # loan made 13 of 36, so 14 months back it is gone.
    old = history.debt_series(loans[1:2], date(2026, 10, 27), back=14, ahead=0)
    assert old[0]["total"] == 0 and old[1]["total"] > 0
    # 26 months on, Leumi and the 23-payment loan are paid off; only the 5.75% loan remains.
    later = next(p for p in s if p["month"] == "2029-01")
    assert later["kind"] == "projected"
    assert 0 < later["total"] < 24443.65


def test_position_of_reads_the_snapshot_totals():
    totals = {"bank_balances_sum": 2936.59, "credit_card_debt": 4092.23, "consumer_loan_balance": 114240.26,
              "mortgage_balance": 1418853.49, "long_term_savings": 639880.88,
              "net_position_with_savings": -894368.51, "property_value": None, "net_worth_with_property": None}
    p = history.position_of({"totals": totals})
    assert p["net_worth"] == -894368.51          # no property yet: net worth incl. savings
    totals.update(property_value=2400000.0, net_worth_with_property=1505631.49)
    assert history.position_of({"totals": totals})["net_worth"] == 1505631.49


def _published(generated_at, consumer, loans, savings):
    return {"generated_at": generated_at,
            "bank_accounts": [{"institution": "discount", "account_id": "0034"},
                              {"institution": "leumi", "account_id": "806-6719/63"}],
            "loans": loans, "savings": savings,
            "totals": {"bank_balances_sum": -1913.0, "credit_card_debt": 4092.23, "consumer_loan_balance": consumer,
                       "mortgage_balance": 1418443.0, "long_term_savings": 639880.88,
                       "net_position_with_savings": -912122.0}}


def test_backfill_skips_published_days_whose_totals_cover_different_accounts():
    # Before 10-24 the Leumi loan 66730014 was not read, so consumer debt was ₪13.6k lower:
    # recording 10-17 would draw a ₪13.6k drop in net worth that never happened.
    loans = [{"lender": "Discount", "loan_id": "9001"}, {"lender": "Bank Leumi", "loan_id": "66730014"}]
    savings = [{"institution": "harel", "topic_id": "70", "label": "קרנות פנסיה"}]
    oct17 = _published("2026-10-17T08:26:00+03:00", 113930.0, loans[:1], savings)
    oct24_night = _published("2026-10-25T01:49:00+03:00", 127555.0, loans, savings)   # local 10-25
    oct24 = _published("2026-10-24T20:10:00+03:00", 127555.0, loans, savings)
    # RiseUp's copy of the same Leumi account, as published until direct scrapes won (10-27).
    oct24["bank_accounts"][1] = {"institution": "leumiBank", "account_id": "806-671963"}
    today = _published("2026-10-27T21:51:00+03:00", 127566.17, loans, savings)

    days = history.backfill_days([oct24_night, oct17, oct24], today)

    assert sorted(days) == [date(2026, 10, 24), date(2026, 10, 25)]
    assert days[date(2026, 10, 24)]["consumer_loans"] == 127555.0


def test_snapshot_day_is_the_local_date():
    assert history.snapshot_day({"generated_at": "2026-10-24T22:49:00+00:00"}) == date(2026, 10, 25)


def test_positions_recorded_before_the_card_debt_switch_have_no_comparable_net_worth():
    """The 10-27 row was recorded with RiseUp's ₪4,092 of card debt; from 10-28 it is the issuers'
    ₪11,263. Net worth across that switch would show a ₪7k dip that never happened."""
    rows = [{"date": "2026-10-27", "cash": 3584.68, "card_debt": 4092.23, "savings": 639880.88, "net_worth": 1292953.67},
            {"date": "2026-10-28", "cash": 3500.0, "card_debt": 11263.4, "savings": 639880.88, "net_worth": 1286000.0}]
    old, new = history.comparable(rows)
    assert old["card_debt"] is None and old["net_worth"] is None
    assert old["savings"] == 639880.88 and old["cash"] == 3584.68          # unaffected components stay
    assert new == rows[1]
