#!/usr/bin/env python3
"""Normalize CAL (cal-online) credit-card dumps -> cal/normalized/*.json

Reads:
    raw/account_init.json            -> the card roster (last4, issuer, description)
    raw/cardTransactions_<last4>_*.json -> per-card transaction pulls

Each cardTransactions file:
    result.bankAccounts[].debitDates[].transactions[]
with fields trnIntId (stable id), merchantName, trnPurchaseDate, trnAmt,
amtBeforeConvAndIndex, debCrdDate (billing date). Charges are stored as NEGATIVE
(money out); refunds (refundInd) stay positive.

`trnAmt` is NOT always ₪: for foreign purchases it is the original-currency
figure and for installment deals it is the whole deal total. The ₪ charged this
cycle is `amtBeforeConvAndIndex` (see charge_amount, issue #35); rows it bills at
₪0 (waived fee, loyalty accrual) are dropped. An installment deal repeats its
trnIntId every cycle, so the id is trnIntId + "_<payment n>".

Entities emitted: credit_cards, transactions.
Common envelope: {"source", "entity", "generated_at", "records": [...]}
Self-contained; safe to re-run after each scrape.
"""
import json, datetime, glob
from finance.models import write_envelope
from pathlib import Path

from finance.paths import source_dir  # noqa: E402

HERE = Path(__file__).resolve().parent          # .../data/cal
SRC = source_dir(HERE)       # this tenant's copy of the source (finance/paths.py)
RAW = SRC / "raw"
OUT = SRC / "normalized"
OUT.mkdir(parents=True, exist_ok=True)
SOURCE = "cal"
NOW = datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def emit(entity, records):
    """Validate through finance.models and write the common envelope."""
    write_envelope(OUT, SOURCE, entity, NOW, records)


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


def charge_amount(t):
    """₪ charged this billing cycle for one CAL transaction (unsigned; refunds < 0).

    `amtBeforeConvAndIndex` is the ₪ CAL bills this cycle: Σ of it over a cycle is
    the statement total. It is the right figure for FX purchases and installment
    payments, and it is 0 when nothing is charged - a waived card fee ("...לפטור מלא
    מעמלת דמי כרטיס ולכן לא חויבת") or a CashPro accrual to the loyalty club.
    `trnAmt` is only a fallback for rows that lack it.
    """
    billed = t.get("amtBeforeConvAndIndex")
    if billed is None:
        amt = abs(t.get("trnAmt", 0))
        return -amt if t.get("refundInd") else amt
    return billed


def add_months(iso_day, n):
    """'2025-07-02' + 15 -> '2026-10-02' (day clamped to the month's end)."""
    y, m, d = (int(x) for x in iso_day.split("-"))
    y, m = divmod(y * 12 + m - 1 + n, 12)
    last = (datetime.date(y + (m + 1) // 12, (m + 1) % 12 + 1, 1) - datetime.timedelta(days=1)).day
    return f"{y:04d}-{m + 1:02d}-{min(d, last):02d}"


def raw_files(raw=RAW):
    """Per-card pulls oldest-first, so the newest pull of a row wins the dedupe.

    CAL renumbers its card index when the roster changes, which leaves old
    cardTransactions_<last4>_<oldidx>.json files beside the fresh ones; by name a
    stale _9 sorts after a fresh _10.
    """
    files = glob.glob(str(raw / "cardTransactions_*.json"))
    return sorted(files, key=lambda f: (Path(f).stat().st_mtime, f))


# ---- transactions (deduped across pulls by trnIntId + installment number) ----
txns = {}                                         # id -> record
for fp in raw_files():
    last4 = Path(fp).name.split("_")[1]           # cardTransactions_<last4>_<idx>[_next].json
    data = json.load(open(fp, encoding="utf-8"))
    for acc in data.get("result", {}).get("bankAccounts", []):
        for dd in acc.get("debitDates", []):
            for t in dd.get("transactions", []):
                billed = charge_amount(t)
                if not billed:
                    continue                      # nothing charged (waived fee, club accrual)
                purchase = (t.get("trnPurchaseDate") or "")[:10]
                # One installment deal keeps its trnIntId in every cycle; payment n is
                # its own charge, dated purchase + (n-1) months as RiseUp dates it.
                n = (t.get("curPaymentNum") or 0) if (t.get("numOfPayments") or 0) > 0 else 0
                tid = t.get("trnIntId") or f"{last4}:{t.get('trnPurchaseDate')}:{t.get('trnAmt', 0)}"
                if n:
                    tid = f"{tid}_{n}"
                txns[tid] = {
                    "id": str(tid),
                    "card_last4": last4,
                    "card_name": card_name.get(last4),
                    "date": add_months(purchase, n - 1) if n and purchase else purchase,
                    "billing_date": (t.get("debCrdDate") or "")[:10],
                    "amount": round(-billed, 2),
                    "currency": "ILS",
                    "original_amount": t.get("trnAmt"),
                    "original_currency": t.get("trnCurrencySymbol") or "₪",
                    "description": (t.get("merchantName") or "").strip(),
                    "category": (t.get("branchCodeDesc") or "").strip() or None,
                    "installments": t.get("numOfPayments") or None,
                    "is_abroad": bool(t.get("isAbroadTransaction")),
                }

emit("transactions", sorted(txns.values(), key=lambda r: r["date"]))
