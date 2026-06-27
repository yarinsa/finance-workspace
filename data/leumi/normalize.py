#!/usr/bin/env python3
"""Normalize Bank Leumi dumps -> leumi/normalized/*.json

The Leumi gateway (Broker.svc) wraps every payload as
    {"ProcessRequestResult": 0, "jsonResp": {...}}
Reads:
    raw/accounts.json      -> account list (number, type)
    raw/summary.json       -> per-type totals (CHECKING balance, LOAN balance)
    raw/transactions.json  -> current-account history

Emits:
    accounts.json      -> the checking account (balance from summary)
    loans.json         -> aggregate loan balance from the summary (one record)
    transactions.json  -> flattened, deduped current-account transactions

Common envelope: {"source", "entity", "generated_at", "records": [...]}
Self-contained; safe to re-run after each scrape.
"""
import json, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent          # .../data/leumi
RAW = HERE / "raw"
OUT = HERE / "normalized"
OUT.mkdir(exist_ok=True)
SOURCE = "leumi"
NOW = datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def load(name):
    """Load a raw Leumi file and unwrap the jsonResp envelope."""
    fp = RAW / name
    if not fp.exists():
        return None
    data = json.load(open(fp, encoding="utf-8"))
    if isinstance(data, dict) and "jsonResp" in data:
        return data["jsonResp"]
    return data


def emit(entity, records):
    path = OUT / f"{entity}.json"
    path.write_text(json.dumps(
        {"source": SOURCE, "entity": entity, "generated_at": NOW, "records": records},
        ensure_ascii=False, indent=2))
    print(f"  {SOURCE}/{path.name}: {len(records)} records")


def iso(date_so):
    """'10/06/2026' -> '2026-06-10'."""
    try:
        d, m, y = date_so.split("/")
        return f"{y}-{m}-{d}"
    except (AttributeError, ValueError):
        return None


# ---- per-type totals from the summary ----
summary = load("summary.json") or {}
totals = {t["accountType"]: t["totalPerAccountType"]
          for t in summary.get("TotalPerTypeItems", [])}

# ---- accounts (the checking account, balance taken from the summary) ----
accounts = []
acc_data = load("accounts.json") or {}
checking_id = None
for a in acc_data.get("AccountsItems", []):
    if a.get("Type") == "CHECKING":
        checking_id = a.get("MaskedNumber")
        accounts.append({
            "institution": "leumi",
            "account_id": checking_id,
            "label": a.get("DisplayName") or checking_id,
            "kind": "checking",
            "balance": round(totals.get("CHECKING", 0), 2),
            "currency": "ILS",
        })
emit("accounts", accounts)

# ---- loans (Leumi only exposes an aggregate LOAN total here) ----
loans = []
if totals.get("LOAN"):
    loans.append({
        "lender": "Bank Leumi",
        "loan_id": "leumi-loans",
        "name": "Leumi loans (aggregate)",
        "category": "consumer",
        "original_amount": None,
        "balance": round(abs(totals["LOAN"]), 2),
        "rate_pct": None,
        "rate_type": "variable",
        "index_linked": False,
        "payments_remaining": 0,
        "payments_total": 0,
        "monthly_payment": 0,
        "final_date": None,
        "currency": "ILS",
    })
emit("loans", loans)

# ---- transactions ----
txns = {}
tx = load("transactions.json") or {}
for t in tx.get("HistoryTransactionsItems", []):
    key = t.get("FITID") or (t.get("DateSO"), t.get("ReferenceNumberLong"), t.get("Amount"))
    txns[key] = {
        "account_id": checking_id,
        "date": iso(t.get("DateSO")),
        "processed_date": iso(t.get("EffectiveDateSO")),
        "amount": round(t.get("Amount", 0), 2),
        "currency": "ILS",
        "description": t.get("Description"),
        "balance_after": round(t.get("RunningBalance", 0), 2),
        "status": "completed",
    }
emit("transactions", sorted(txns.values(), key=lambda r: r["date"] or ""))
