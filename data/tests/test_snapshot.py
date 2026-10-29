"""digest.build_snapshot: which copy of an account counts, and the property asset.

Real records from the 2026-10-27 digest."""
import digest

DISCOUNT_DIRECT = {"institution": "discount", "account_id": "0034", "kind": "checking", "balance": 522.65,
                   "available_balance": 10522.65, "overdraft_limit": 10000.0, "currency": "ILS",
                   "_source": "discount"}
DISCOUNT_RISEUP = {"institution": "discount", "account_id": "0123444499", "kind": "checking",
                   "balance": -5871.05, "currency": "ILS", "label": "Yarin Sasson", "_source": "riseup"}
LEUMI_DIRECT = {"institution": "leumi", "account_id": "806-6719/63", "kind": "checking", "balance": 2413.94,
                "currency": "ILS", "label": "806-6719/63", "_source": "leumi"}
LEUMI_RISEUP = {"institution": "leumiBank", "account_id": "806-671963", "kind": "loan_account",
                "balance": 2813.94, "currency": "ILS", "label": "חשבון הלוואה", "_source": "riseup"}


def snap(accounts=(), loans=(), savings=(), assets=None):
    e = {"accounts": [dict(a) for a in accounts], "credit_cards": [], "income": [],
         "savings": list(savings), "loans": list(loans)}
    return digest.build_snapshot(e, assets=assets)


def test_direct_leumi_checking_beats_riseups_stale_loan_account_copy():
    """As the household, when RiseUp reports Leumi 806-671963 as a 'loan_account' with ₪2,813.94
    and the Leumi scrape says checking 806-6719/63 holds ₪2,413.94, the snapshot keeps the direct
    checking account, so the runway's Discount + Leumi pool includes Leumi."""
    s = snap([DISCOUNT_RISEUP, DISCOUNT_DIRECT, LEUMI_RISEUP, LEUMI_DIRECT])
    by_inst = {a["institution"]: a for a in s["bank_accounts"]}
    assert by_inst["leumi"]["kind"] == "checking"
    assert by_inst["leumi"]["balance"] == 2413.94
    assert by_inst["discount"]["balance"] == 522.65
    assert s["totals"]["bank_balances_sum"] == 2936.59


def test_property_value_joins_net_worth_but_not_the_existing_totals():
    """The apartment's hand-typed value adds `property_value` and `net_worth_with_property`;
    tracked_net_position and net_position_with_savings keep their meaning."""
    loans = [{"lender": "Bank Discount", "loan_id": "m", "category": "mortgage", "balance": 1418853.49,
              "monthly_payment": 5817.26}]
    savings = [{"label": "הראל פנסיה", "balance": 639880.88}]
    assets = [{"id": 1, "kind": "property", "label": "דירה", "value": 2400000.0,
               "valued_at": "2026-10-27", "valuation_source": "manual"}]
    t = snap([DISCOUNT_DIRECT], loans, savings, assets)["totals"]
    assert t["net_position_with_savings"] == round(522.65 - 1418853.49 + 639880.88, 2)
    assert t["property_value"] == 2400000.0
    assert t["net_worth_with_property"] == round(t["net_position_with_savings"] + 2400000.0, 2)


def test_no_property_recorded_leaves_the_property_totals_empty():
    t = snap([DISCOUNT_DIRECT])["totals"]
    assert t["property_value"] is None
    assert t["net_worth_with_property"] is None


# ---- credit cards: the issuers' next charge, not RiseUp's balance --------------------------
import datetime

RISEUP_CARDS = [   # RiseUp's 2026-10-16 view: stale, and it never saw card 6417 or Max 3819
    {"issuer": "cal", "last4": "9947", "holder": "ירין ששון", "owed": 1798.13, "_source": "riseup"},
    {"issuer": "americanexpress", "last4": "7696", "holder": "אמריקן", "owed": 1779.85, "_source": "riseup"},
    {"issuer": "isracard", "last4": "6250", "holder": "הוט", "owed": 100.0, "_source": "riseup"},
    {"issuer": "leumicard", "last4": "9613", "holder": "ירין ששון", "owed": 414.25, "_source": "riseup"},
]
ROSTER = [{"issuer": "cal", "last4": "9947", "name": "דיינרס מסטרקארד משולב", "_source": "cal"},
          {"issuer": "amex", "last4": "7696", "name": "AMEX PLATINUM", "_source": "amex"},
          {"issuer": "amex", "last4": "6417", "name": "AMEX PLATINUM", "_source": "amex"},
          {"issuer": "max", "last4": "3819", "name": "מקס 3819", "_source": "max"}]


def _row(source, last4, billing, amount):
    return {"_source": source, "card_last4": last4, "billing_date": billing, "amount": amount,
            "date": "2026-10-20", "description": "x"}


TXNS = [   # the 2026-10-28 dumps: each card's rows grouped by the day its card is charged
    _row("cal", "9947", "2026-10-10", -7393.89),             # already debited
    _row("cal", "9947", "2026-11-10", -2000.0), _row("cal", "9947", "2026-11-10", -1144.32),
    _row("amex", "7696", "2026-11-10", -4506.30),            # = AMEX's own cardChargeNext
    _row("amex", "6250", "2026-11-10", -1985.06),
    _row("amex", "6417", "2026-11-02", -973.47),
    _row("max", "9613", "2026-10-11", -1639.25), _row("max", "9613", "2026-11-10", -414.25),
    _row("max", "3819", "2026-11-10", -240.0),
]


def cards_snap(as_of, txns=TXNS, riseup=RISEUP_CARDS):
    e = {"accounts": [], "credit_cards": [dict(c) for c in riseup + ROSTER], "income": [], "savings": [],
         "loans": [], "transactions": [dict(t) for t in txns]}
    return digest.build_snapshot(e, as_of=as_of)


def test_each_card_owes_the_issuers_next_charge_not_riseups_stale_balance():
    """As the household, when CAL's own rows say Diners 9947 will charge ₪3,144.32 on 10.11 and AMEX
    says 7696 ₪4,506.30, the home must not show RiseUp's 16-October ₪1,798.13 / ₪1,779.85, and it
    must list the cards RiseUp never saw (6417, billed on the 2nd; Max 3819)."""
    s = cards_snap(datetime.date(2026, 10, 28))
    owed = {c["last4"]: (c["owed"], c["next_charge_date"]) for c in s["credit_cards"]}
    assert owed == {"9947": (3144.32, "2026-11-10"), "7696": (4506.30, "2026-11-10"),
                    "6250": (1985.06, "2026-11-10"), "9613": (414.25, "2026-11-10"),
                    "6417": (973.47, "2026-11-02"), "3819": (240.0, "2026-11-10")}
    assert s["totals"]["credit_card_debt"] == 11263.40
    assert {c["last4"]: c["issuer"] for c in s["credit_cards"]}["7696"] == "americanexpress"   # RiseUp's label kept


def test_a_charge_posts_on_its_billing_day_rolled_to_sunday():
    """A charge on Friday 2026-10-30 posts Sunday 11-01: still owed on Saturday, in the bank by Sunday."""
    txns = [_row("amex", "7696", "2026-10-30", -500.0)]
    assert cards_snap(datetime.date(2026, 10, 31), txns, [])["totals"]["credit_card_debt"] == 500.0
    assert cards_snap(datetime.date(2026, 11, 1), txns, [])["totals"]["credit_card_debt"] == 0


def test_a_card_the_direct_sources_never_saw_keeps_riseups_figure():
    """The business card (discount-business) has no direct card dump: its `owed` stays."""
    biz = {"issuer": "discount-business", "last4": "5555", "owed": 321.0, "_source": "discount-business"}
    s = cards_snap(datetime.date(2026, 10, 28), riseup=RISEUP_CARDS + [biz])
    assert {c["last4"]: c["owed"] for c in s["credit_cards"]}["5555"] == 321.0
    assert s["totals"]["credit_card_debt"] == 11263.40 + 321.0


def test_without_card_rows_riseup_is_still_the_answer():
    assert cards_snap(datetime.date(2026, 10, 28), txns=[])["totals"]["credit_card_debt"] == 4092.23
