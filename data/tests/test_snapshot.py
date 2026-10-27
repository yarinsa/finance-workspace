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
