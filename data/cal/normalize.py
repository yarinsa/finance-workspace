#!/usr/bin/env python3
"""Normalize CAL (cal-online) credit-card dumps -> cal/normalized/*.json

Reads:
    raw/account_init.json            -> the card roster (last4, issuer, description)
    raw/cardTransactions_<last4>_*.json -> per-card transaction pulls

Each cardTransactions file:
    result.bankAccounts[].debitDates[].transactions[]
with fields trnIntId (stable id), merchantName, trnPurchaseDate, trnAmt (₪),
debCrdDate (billing date). Charges are stored as NEGATIVE (money out); refunds
(refundInd) stay positive.

Entities emitted: credit_cards, transactions.
Common envelope: {"source", "entity", "generated_at", "records": [...]}
Self-contained; safe to re-run after each scrape.
"""
import json, datetime, glob
from pathlib import Path

HERE = Path(__file__).resolve().parent          # .../data/cal
RAW = HERE / "raw"
OUT = HERE / "normalized"
OUT.mkdir(exist_ok=True)
SOURCE = "cal"
NOW = datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def emit(entity, records):
    path = OUT / f"{entity}.json"
    path.write_text(json.dumps(
        {"source": SOURCE, "entity": entity, "generated_at": NOW, "records": records},
        ensure_ascii=False, indent=2))
    print(f"  {SOURCE}/{path.name}: {len(records)} records")


# ---- credit cards ----
cards = []
card_name = {}                                   # last4 -> display name
init = json.load(open(RAW / "account_init.json", encoding="utf-8"))
for c in init.get("result", {}).get("cards", []):
    last4 = c["last4Digits"]
    name = " ".join(x for x in (c.get("companyDescription"), c.get("cardDescription")) if x)
    card_name[last4] = name
    cards.append({
        "issuer": "cal",
        "name": name,
        "last4": last4,
        "active": "חסום" not in (c.get("statusForDisplay") or ""),
        "currency": "ILS",
    })
emit("credit_cards", cards)


# ---- transactions (deduped across pulls by trnIntId) ----
txns = {}                                         # trnIntId -> record
for fp in sorted(glob.glob(str(RAW / "cardTransactions_*.json"))):
    last4 = Path(fp).name.split("_")[1]           # cardTransactions_<last4>_<idx>.json
    data = json.load(open(fp, encoding="utf-8"))
    for acc in data.get("result", {}).get("bankAccounts", []):
        for dd in acc.get("debitDates", []):
            for t in dd.get("transactions", []):
                amt = t.get("trnAmt", 0)
                signed = round(amt if t.get("refundInd") else -amt, 2)
                tid = t.get("trnIntId") or f"{last4}:{t.get('trnPurchaseDate')}:{amt}"
                txns[tid] = {
                    "card_last4": last4,
                    "card_name": card_name.get(last4),
                    "date": (t.get("trnPurchaseDate") or "")[:10],
                    "billing_date": (t.get("debCrdDate") or "")[:10],
                    "amount": signed,
                    "currency": "ILS",
                    "description": (t.get("merchantName") or "").strip(),
                    "category": (t.get("branchCodeDesc") or "").strip() or None,
                    "installments": t.get("numOfPayments") or None,
                    "is_abroad": bool(t.get("isAbroadTransaction")),
                }

emit("transactions", sorted(txns.values(), key=lambda r: r["date"]))
