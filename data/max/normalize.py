#!/usr/bin/env python3
"""Normalize Max (ex-Leumi Card) dumps -> max/normalized/*.json

Reads:
    raw/categories.json              -> categoryId -> Hebrew category name
    raw/transactions_<YYYY-MM>.json  -> getTransactionsAndGraphs, one BILLING month each
                                        (the newest file is next month: future charges)

Each monthly file holds every card of the account in one list:
    result.transactions[]
with fields arn (stable per deal), shortCardNumber, merchantName, purchaseDate,
paymentDate (billing date; null while pending), originalAmount/originalCurrency
(the deal in its own currency - for installments the WHOLE deal),
actualPaymentAmount (the ₪ charged this cycle; negative on a credit),
planName/planTypeId and comments ("תשלום 16 מתוך 20" on installments).

Mapping (same rules as israeli-bank-scrapers' max.js):
- amount = -actualPaymentAmount: charges are NEGATIVE (money out), refunds and
  cancellations ("ביטול עסקה") come out positive.
- id = arn, plus "_<n>" for installment n, so one deal's monthly payments stay
  distinct while re-scrapes of the same month collapse onto one record.
- An installment is dated purchaseDate + (n-1) months - the way RiseUp ("leumicard")
  dates them - instead of the original purchase date. Otherwise every payment of a
  deal shares one date+amount, collapses into one ledger row, and lands in the
  month of the original purchase.
- Rows with no planName (summary rows) and rows that charge ₪0 (a disputed deal,
  "עסקה בבירור", is repeated every month at 0) are dropped.

There is no card-roster endpoint in the dump, so `credit_cards` is derived from the
transactions: a card is `active` when it has a row in one of the three newest
billing months.

Entities emitted: credit_cards, transactions.
Common envelope: {"source", "entity", "generated_at", "records": [...]}
Self-contained; safe to re-run after each scrape.
"""
import json, datetime, glob, re, calendar
from finance.models import write_envelope
from pathlib import Path

HERE = Path(__file__).resolve().parent          # .../data/max
RAW = HERE / "raw"
OUT = HERE / "normalized"
SOURCE = "max"
ACTIVE_MONTHS = 3                               # card seen in the newest N billing files
INSTALLMENT_RE = re.compile(r"(\d+)\s*מתוך\s*(\d+)")


def add_months(iso_day, n):
    """'2025-01-13' + 2 -> '2025-03-13', clamping to the month's last day."""
    y, m, d = (int(x) for x in iso_day.split("-"))
    m0 = m - 1 + n
    y, m = y + m0 // 12, m0 % 12 + 1
    return f"{y:04d}-{m:02d}-{min(d, calendar.monthrange(y, m)[1]):02d}"


def installment_info(comments):
    """'תשלום 16 מתוך 20' -> (16, 20); None when the row is not an installment."""
    m = INSTALLMENT_RE.search(comments or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def txn_id(t, inst):
    """Stable per-transaction id: the deal's ARN (+ installment number)."""
    arn = (t.get("dealData") or {}).get("arn") or t.get("arn")
    if not arn or arn == "0":                   # disputed/adjustment rows carry arn "0"
        return ":".join(str(x) for x in (
            t.get("shortCardNumber"), (t.get("purchaseDate") or "")[:10],
            (t.get("paymentDate") or "")[:10], t.get("actualPaymentAmount"),
            (t.get("merchantName") or "").strip()))
    return f"{arn}_{inst[0]}" if inst else arn


def to_record(t, category_name):
    """One raw Max transaction -> a Transaction record, or None to drop it."""
    if not t.get("planName"):
        return None
    charged = t.get("actualPaymentAmount") or 0
    if not charged:
        return None
    inst = installment_info(t.get("comments"))
    purchase = (t.get("purchaseDate") or "")[:10]
    orig_ccy = t.get("originalCurrency") or "ILS"
    rec = {
        "id": txn_id(t, inst),
        "card_last4": t.get("shortCardNumber"),
        "card_name": f"מקס {t.get('shortCardNumber')}",
        "date": add_months(purchase, inst[0] - 1) if inst else purchase,
        "billing_date": (t.get("paymentDate") or "")[:10],
        "amount": round(-charged, 2),
        "currency": "ILS",
        "original_amount": t.get("originalAmount"),
        "original_currency": orig_ccy,
        "description": (t.get("merchantName") or "").strip(),
        "category": category_name.get(t.get("categoryId")),
        "installments": inst[1] if inst else None,
        "is_abroad": orig_ccy != "ILS" or 'חו"ל' in (t.get("comments") or ""),
    }
    if not t.get("paymentDate"):
        rec["status"] = "pending"
    return rec


def monthly_files(raw=RAW):
    return sorted(glob.glob(str(Path(raw) / "transactions_*.json")))


def load_categories(raw=RAW):
    path = Path(raw) / "categories.json"
    if not path.exists():
        return {}
    return {c["id"]: c["name"] for c in json.load(open(path, encoding="utf-8")).get("result") or []}


def normalize(raw=RAW):
    """-> (credit_cards, transactions) from every monthly file, deduped by id.

    Files are read oldest -> newest, so a re-pulled month's latest copy wins.
    """
    category_name = load_categories(raw)
    files = monthly_files(raw)
    txns, holder, seen_in = {}, {}, {}
    for i, fp in enumerate(files):
        body = json.load(open(fp, encoding="utf-8"))
        for t in ((body.get("result") or {}).get("transactions") or []):
            last4 = t.get("shortCardNumber")
            if last4:
                holder.setdefault(last4, ((t.get("dealData") or {}).get("userName") or "").strip())
                seen_in[last4] = i
            rec = to_record(t, category_name)
            if rec:
                txns[rec["id"]] = rec
    newest = len(files) - 1
    cards = [{
        "issuer": "max",
        "name": f"מקס {last4}",
        "holder": holder[last4] or None,
        "last4": last4,
        "active": newest - seen_in[last4] < ACTIVE_MONTHS,
        "currency": "ILS",
    } for last4 in sorted(seen_in)]
    return cards, sorted(txns.values(), key=lambda r: (r["date"], r["id"]))


def main():
    OUT.mkdir(exist_ok=True)
    now = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    cards, txns = normalize()
    write_envelope(OUT, SOURCE, "credit_cards", now, cards)
    write_envelope(OUT, SOURCE, "transactions", now, txns)


if __name__ == "__main__":
    main()
