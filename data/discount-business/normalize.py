#!/usr/bin/env python3
"""Normalize Discount BUSINESS dumps -> discount-business/normalized/*.json

The business telebank dump is split one-file-per-endpoint (unlike the personal
Discount scrape). Reads:
    raw/infoAndBalance.json   -> current-account balance
    raw/liabilities.json      -> credit cards (with balance owed)
    raw/transactions.json     -> current-account operations

Many endpoints (loans, deposits, credit line, FX) return an Error envelope when
nothing is active; those are simply skipped.

Emits:
    accounts.json      -> the business current account
    credit_cards.json  -> cards carrying a balance
    transactions.json  -> flattened operation list

Common envelope: {"source", "entity", "generated_at", "records": [...]}
Self-contained; safe to re-run after each scrape.
"""
import json, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent          # .../data/discount-business
RAW = HERE / "raw"
OUT = HERE / "normalized"
OUT.mkdir(exist_ok=True)
SOURCE = "discount-business"
NOW = datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def load(name):
    """Load a raw file, returning None if it is missing or an Error envelope."""
    fp = RAW / name
    if not fp.exists():
        return None
    data = json.load(open(fp, encoding="utf-8"))
    if isinstance(data, dict) and "Error" in data:
        return None
    return data


def emit(entity, records):
    path = OUT / f"{entity}.json"
    path.write_text(json.dumps(
        {"source": SOURCE, "entity": entity, "generated_at": NOW, "records": records},
        ensure_ascii=False, indent=2))
    print(f"  {SOURCE}/{path.name}: {len(records)} records")


def ymd(s):
    """'20260302' -> '2026-03-02'."""
    s = (s or "")[:8]
    return f"{s[0:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 else None


# ---- account balance ----
accounts = []
info = load("infoAndBalance.json")
if info:
    a = info["AccountInfoAndBalance"]
    accounts.append({
        "institution": "discount-business",
        "account_id": a.get("AccountName"),          # no account number in this payload
        "label": f"{a.get('AccountName')} ({a.get('HandlingBranchName')})",
        "kind": "business_checking",
        "balance": round(a.get("AccountBalance", 0), 2),
        "available_balance": round(a.get("AccountAvailableBalance", 0), 2),
        "currency": a.get("AccountCurrencyCode", "ILS"),
    })
emit("accounts", accounts)

# ---- credit cards (only those carrying a balance) ----
cards = []
liab = load("liabilities.json")
if liab:
    cc = liab["Liabilities"].get("CreditCards", {})
    for c in cc.get("CardsBlock", {}).get("CardEntry", []):
        owed = round(c.get("NextDebit", {}).get("NextDebitAmount", 0)
                     + c.get("FutureDebits", {}).get("FutureDebitsAmount", 0), 2)
        if owed:
            cards.append({
                "issuer": c.get("CardFamilyDescription") or "discount-business",
                "holder": "discount-business",
                "last4": c.get("CardNumber"),
                "owed": owed,
                "currency": "ILS",
            })
emit("credit_cards", cards)

# ---- transactions ----
txns = []
tx = load("transactions.json")
if tx:
    for op in tx["CurrentAccountLastTransactions"].get("OperationEntry", []):
        txns.append({
            "account_id": (info or {}).get("AccountInfoAndBalance", {}).get("AccountName"),
            "date": ymd(op.get("OperationDate")),
            "processed_date": ymd(op.get("ValueDate")),
            "amount": round(op.get("OperationAmount", 0), 2),
            "currency": "ILS",
            "description": op.get("OperationDescriptionToDisplay") or op.get("OperationDescription"),
            "balance_after": round(op.get("BalanceAfterOperation", 0), 2),
            "status": "completed",
        })
emit("transactions", sorted(txns, key=lambda r: r["date"] or ""))
