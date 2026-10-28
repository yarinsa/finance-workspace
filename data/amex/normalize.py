#!/usr/bin/env python3
"""Normalize American Express (Isracard/ICC) dumps -> amex/normalized/*.json

Reads:
    raw/cardList.json              -> the cards + their next/last billing totals
    raw/transactions_<suffix>_*.json -> per-card monthly transaction pulls

AMEX puts every statement transaction (domestic + foreign) in one list:
    data.israelAbroadVouchers.vouchers.israelAbroadVouchersList
and the ones billed on their own date (cash withdrawals, tax-free refunds,
credit repayments) under data.israelAbroadVouchers.outOfStatementChargeDateVouchers
[].immediateVouchersCurrencyDate. `isIsraelDeal` distinguishes domestic/foreign; `billingAmount`/`ilsAmount` is the ₪ charge.
Charges are stored as NEGATIVE amounts (money out) to match the other sources.

Entities emitted: credit_cards, transactions.
Common envelope: {"source", "entity", "generated_at", "records": [...]}
Self-contained; safe to re-run after each scrape.
"""
import json, datetime, glob, re
from finance.models import write_envelope
from pathlib import Path

HERE = Path(__file__).resolve().parent          # .../data/amex
RAW = HERE / "raw"
OUT = HERE / "normalized"
OUT.mkdir(exist_ok=True)
SOURCE = "amex"
NOW = datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def emit(entity, records):
    """Validate through finance.models and write the common envelope."""
    write_envelope(OUT, SOURCE, entity, NOW, records)


def iso(dmy):
    """'08/06/2026' -> '2026-06-08' (purchaseDate is DD/MM/YYYY)."""
    if not dmy:
        return ""
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", dmy)
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else dmy[:10]


# ---- credit cards ----
cards = []
card_name = {}                                   # suffix -> display name
billing_day = {}                                 # suffix -> day of the month the card is charged
cl = json.load(open(RAW / "cardList.json", encoding="utf-8"))["data"]
for c in cl.get("cardsList", []):
    suffix = c["cardSuffix"]
    card_name[suffix] = c["cardName"]
    for k in ("cardChargeNext", "cardChargeLast"):        # '10/11/2026' -> the card bills on the 10th
        day = ((c.get(k) or {}).get("billingDate") or "")[:2]
        if day.isdigit() and suffix not in billing_day:
            billing_day[suffix] = int(day)
    cards.append({
        "issuer": "amex",
        "holder": f"{c.get('firstName','').strip()} {c.get('lastName','').strip()}".strip(),
        "name": c["cardName"],
        "last4": suffix,
        "active": bool(c.get("isActive")),
        "currency": "ILS",
    })
emit("credit_cards", cards)


# ---- transactions (deduped across the monthly pulls) ----
def vouchers_of(data):
    """(voucher, immediate billing date or None) for every voucher in one pull.

    The statement list holds the cycle's charges. Charges AMEX bills on their own
    date - cash withdrawals, tax-free refunds, early credit repayments - sit apart,
    under outOfStatementChargeDateVouchers, and are real card movements too.
    """
    block = data.get("israelAbroadVouchers") or {}
    for t in ((block.get("vouchers") or {}).get("israelAbroadVouchersList")) or []:
        yield t, None
    for grp in block.get("outOfStatementChargeDateVouchers") or []:
        billed = (grp.get("totalVouchersCurrencyDate") or {}).get("dateImmediateVouchers")
        for t in grp.get("immediateVouchersCurrencyDate") or []:
            yield t, billed


def statement_date(suffix, month_file):
    """The day a card's statement of `transactions_<suffix>_<MM>-<YYYY>.json` is charged: the
    pull of month M is the statement billed in M, on the card's billing day (None when unknown)."""
    m = re.match(r"transactions_\w+?_(\d{2})-(\d{4})\.json$", month_file)
    day = billing_day.get(suffix)
    if not m or not day:
        return None
    month, year = int(m.group(1)), int(m.group(2))
    last = (datetime.date(year + month // 12, month % 12 + 1, 1) - datetime.timedelta(days=1)).day
    return datetime.date(year, month, min(day, last)).isoformat()


txns = {}                                         # voucher id -> record
for fp in sorted(glob.glob(str(RAW / "transactions_*.json"))):
    suffix = Path(fp).name.split("_")[1]          # transactions_<suffix>_<month>.json
    stmt_date = statement_date(suffix, Path(fp).name)
    data = json.load(open(fp, encoding="utf-8")).get("data") or {}
    for t, billed in vouchers_of(data):
        # stable id; fall back to a composite when missing
        vid = t.get("seqVoucherNumber") or f"{suffix}:{t.get('purchaseDate')}:{t.get('voucherNumber')}"
        ils = t.get("billingAmount")
        if ils is None:
            ils = t.get("ilsAmount", 0)
        txns[vid] = {
            "id": str(vid),
            "card_last4": suffix,
            "card_name": card_name.get(suffix),
            "date": iso(t.get("purchaseDate")),
            "billing_date": iso(billed) if billed else stmt_date,
            "amount": round(-ils, 2),             # charge = money out
            "currency": "ILS",
            "original_amount": t.get("originalAmount"),
            "original_currency": t.get("originalCurrencyIso"),
            "description": (t.get("businessName") or "").strip(),
            "category": (t.get("transactionDescription") or "").strip() or None,
            "is_abroad": not t.get("isIsraelDeal", False),
        }

emit("transactions", sorted(txns.values(), key=lambda r: r["date"]))
