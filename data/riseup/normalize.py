#!/usr/bin/env python3
"""Normalize RiseUp raw dumps -> riseup/normalized/*.json

Common envelope written for every entity:
    {"source", "entity", "generated_at", "records": [...]}

Entities emitted: accounts, credit_cards, income, subscription.
Self-contained; safe to re-run after each scrape.
"""
import json, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent          # .../data/riseup
RAW = HERE / "raw"
OUT = HERE / "normalized"
OUT.mkdir(exist_ok=True)
SOURCE = "riseup"
NOW = datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def load(name):
    return json.load(open(RAW / name, encoding="utf-8"))


def emit(entity, records):
    path = OUT / f"{entity}.json"
    path.write_text(json.dumps(
        {"source": SOURCE, "entity": entity, "generated_at": NOW, "records": records},
        ensure_ascii=False, indent=2))
    print(f"  {SOURCE}/{path.name}: {len(records)} records")


# ---- accounts (bank balances) ----
accounts = []
for b in load("current-balance.json"):
    accounts.append({
        "institution": b["source"],
        "account_id": b["accountNumberPiiValue"],
        "label": b.get("credentialsName"),
        "kind": "loan_account" if "הלוואה" in (b.get("credentialsName") or "") else "checking",
        "balance": round(b["balance"], 2),
        "currency": "ILS",
    })
emit("accounts", accounts)

# ---- credit cards ----
cards = []
for c in load("current-credit-card-debt.json"):
    cards.append({
        "issuer": c["source"],
        "holder": c["name"],
        "last4": c["accountNumberPiiValue"],
        "owed": round(-c["amount"], 2),   # store as positive amount owed
        "currency": "ILS",
    })
emit("credit_cards", cards)

# ---- income (detected salary transfers from insights) ----
income = []
for ins in load("insights_all.json"):
    if ins.get("incomeAmount"):
        income.append({
            "label": ins.get("businessName") or "salary",
            "monthly_amount": round(ins["incomeAmount"], 2),
            "currency": "ILS",
            "detail": {"date": ins.get("transactionDate"), "insight": ins.get("insightName")},
        })
emit("income", income)

# ---- transactions (RiseUp's category-tagged copy of every source's txns) ----
# budget_current.json carries the real scraped transactions in two places:
#   envelopes[].actuals[]  -> transactions already reconciled into a budget envelope
#   excluded[]             -> transactions RiseUp chose to exclude from the budget
# Each record is tagged with its origin `source` (discount/cal/amex/leumi…) and a
# spending `expense` category, which the raw per-source dumps don't have. These are
# the higher-priority copies used for cross-source dedup in digest.py.
# (Envelopes WITHOUT actuals are forecast/planned amounts, not real txns — skipped.)
def _tx(t, excluded):
    inc = t.get("incomeAmount")
    if inc is not None:                          # income -> positive
        amount = round(inc, 2)
    else:                                        # expense -> negative
        amt = t.get("billingAmount")
        if amt is None:
            amt = t.get("originalAmount", 0) or 0
        amount = round(-amt, 2)
    return {
        "id": t.get("transactionId"),
        "origin": t.get("source"),               # which institution it was scraped from
        "account_type": t.get("sourceType"),     # checkingAccount / creditCard …
        "date": (t.get("transactionDate") or t.get("billingDate") or "")[:10],
        "amount": amount,
        "currency": "ILS",
        "description": (t.get("businessName") or "").strip(),
        "category": (t.get("expense") or "").strip() or None,
        "is_income": bool(t.get("isIncome")),
        "excluded": excluded,
    }

def collect_txns(budgets):
    """Flatten every budget month's actuals + excluded into id -> record.

    `budget_current.json` holds only the month in progress, which is nearly empty
    right after a month rolls over (on the 1st it can be 3 records). The multi-month
    `budget_<YYYY-MM>_<n>.json` dumps carry the populated history, so we read every
    available month and let transactionId dedupe the overlap.
    """
    txns = {}
    for budget in budgets:
        for env in budget.get("envelopes", []):
            for a in env.get("actuals", []):
                r = _tx(a, excluded=False)
                if r["id"]:
                    txns[r["id"]] = r
        for x in budget.get("excluded", []):
            r = _tx(x, excluded=True)
            if r["id"]:
                txns[r["id"]] = r
    return txns


def load_budgets():
    """Every budget month on disk, oldest file first; current month read last so it wins."""
    budgets = []
    for path in sorted(RAW.glob("budget_[0-9]*.json")):
        data = json.load(open(path, encoding="utf-8"))
        budgets.extend(data if isinstance(data, list) else [data])
    budgets.append(load("budget_current.json"))
    return budgets


txns = collect_txns(load_budgets())
emit("transactions", sorted(txns.values(), key=lambda r: r["date"]))

# ---- subscription state ----
sub = load("subscription-state-simplified.json")
emit("subscription", [{
    "service": "riseup",
    "active": not sub.get("isDormant", False) and not sub.get("isFree", True),
    "since": sub.get("since"),
    "until": sub.get("until"),
    "auto_renew": sub.get("isAutoRenewalOn"),
}])
