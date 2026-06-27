#!/usr/bin/env python3
"""Normalize American Express (Isracard/ICC) dumps -> amex/normalized/*.json

Reads:
    raw/cardList.json              -> the cards + their next/last billing totals
    raw/transactions_<suffix>_*.json -> per-card monthly transaction pulls

AMEX puts EVERY transaction (domestic + foreign) in one list:
    data.israelAbroadVouchers.vouchers.israelAbroadVouchersList
`isIsraelDeal` distinguishes the two; `billingAmount`/`ilsAmount` is the ₪ charge.
Charges are stored as NEGATIVE amounts (money out) to match the other sources.

Entities emitted: credit_cards, transactions.
Common envelope: {"source", "entity", "generated_at", "records": [...]}
Self-contained; safe to re-run after each scrape.
"""
import json, datetime, glob, re
from pathlib import Path

HERE = Path(__file__).resolve().parent          # .../data/amex
RAW = HERE / "raw"
OUT = HERE / "normalized"
OUT.mkdir(exist_ok=True)
SOURCE = "amex"
NOW = datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def emit(entity, records):
    path = OUT / f"{entity}.json"
    path.write_text(json.dumps(
        {"source": SOURCE, "entity": entity, "generated_at": NOW, "records": records},
        ensure_ascii=False, indent=2))
    print(f"  {SOURCE}/{path.name}: {len(records)} records")


def iso(dmy):
    """'08/06/2026' -> '2026-06-08' (purchaseDate is DD/MM/YYYY)."""
    if not dmy:
        return ""
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", dmy)
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else dmy[:10]


# ---- credit cards ----
cards = []
card_name = {}                                   # suffix -> display name
cl = json.load(open(RAW / "cardList.json", encoding="utf-8"))["data"]
for c in cl.get("cardsList", []):
    suffix = c["cardSuffix"]
    card_name[suffix] = c["cardName"]
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
txns = {}                                         # voucher id -> record
for fp in sorted(glob.glob(str(RAW / "transactions_*.json"))):
    suffix = Path(fp).name.split("_")[1]          # transactions_<suffix>_<month>.json
    data = json.load(open(fp, encoding="utf-8")).get("data") or {}
    voucher = (((data.get("israelAbroadVouchers") or {})
               .get("vouchers") or {})
               .get("israelAbroadVouchersList")) or []
    for t in voucher:
        # stable id; fall back to a composite when missing
        vid = t.get("seqVoucherNumber") or f"{suffix}:{t.get('purchaseDate')}:{t.get('voucherNumber')}"
        ils = t.get("billingAmount")
        if ils is None:
            ils = t.get("ilsAmount", 0)
        txns[vid] = {
            "card_last4": suffix,
            "card_name": card_name.get(suffix),
            "date": iso(t.get("purchaseDate")),
            "amount": round(-ils, 2),             # charge = money out
            "currency": "ILS",
            "original_amount": t.get("originalAmount"),
            "original_currency": t.get("originalCurrencyIso"),
            "description": (t.get("businessName") or "").strip(),
            "category": (t.get("transactionDescription") or "").strip() or None,
            "is_abroad": not t.get("isIsraelDeal", False),
        }

emit("transactions", sorted(txns.values(), key=lambda r: r["date"]))
