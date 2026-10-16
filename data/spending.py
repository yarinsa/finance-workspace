#!/usr/bin/env python3
"""Month spending explorer model (PRD 12, Phase 3).

``build_spending(transactions)`` turns the unified ledger into the ``spending``
block of ``cashflow.json`` behind the app's ``/spending`` screen: for each of the
last N months with data, the real spending broken down by category and merchant,
the individual transactions, the change vs. the previous month, and an
``excluded`` block that explains what was *not* counted as spending.

Exclusion semantics match ``cashflow.aggregate_by_month`` so the two screens agree:
card-bill settlements and internal transfers are not spending (the underlying
purchases are already in the ledger), savings deposits are saved rather than spent,
and positive amounts / ``is_income`` rows are income. A row is counted in exactly
one bucket, in that precedence order.

Pure and stdlib-only; imported by ``cashflow.build()``. Running it directly prints
a summary of the real ledger.
"""

import json
import os
import re
from collections import defaultdict
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
TRANSACTIONS = os.path.join(HERE, "digested", "transactions.json")

MONTHS = 6
MAX_TX_PER_MONTH = 300   # keep the cashflow.json payload small
MAX_MERCHANTS = 40

# Trailing ISO-ish country codes that card processors append after the city.
_COUNTRY = re.compile(r"\s+(?:[A-Z]{3}|[A-Z]{2})$")
_TRAILING_DIGITS = re.compile(r"[\s\-*#]*\d{3,}[\d\-/ ]*$")


def merchant_name(description):
    """Collapse a raw ledger description into a merchant key.

    Card processors pad fields with runs of spaces ("APPLE.COM/BILL     CORK    IRL"),
    so a run of 2+ spaces splits name from city/country and only the first field is
    kept. When the city is single-spaced ("APPLE.COM/BILL CUPERTINO USA") a trailing
    country code and one trailing all-caps Latin city token are stripped. Bank rows
    carry comma-separated memo fields ("העברה מירין ששון,חשבון ...") — only the
    first is the counterparty. Trailing reference numbers are dropped.
    """
    s = (description or "").strip()
    if not s:
        return "ללא תיאור"
    s = s.split(",")[0]
    parts = [p for p in re.split(r"\s{2,}", s) if p.strip()]
    if len(parts) > 1 and not any("\u0590" <= ch <= "\u05ff" for ch in " ".join(parts[1:])):
        s = parts[0]   # padded Latin city/country fields follow the name
    s = " ".join(s.split())
    if len(parts) == 1 and not s.count("  ") and re.search(r"[A-Za-z]", s):
        stripped = _COUNTRY.sub("", s)
        tokens = stripped.split()
        if stripped != s and len(tokens) >= 3 and re.fullmatch(r"[A-Z.]+", tokens[-1]):
            tokens = tokens[:-1]
        s = " ".join(tokens)
    s = _TRAILING_DIGITS.sub("", s).strip()
    return s or "ללא תיאור"


def classify(t):
    """Which bucket a ledger row belongs to: ``spend`` or one of the excluded keys
    ``card_bills`` / ``transfers`` / ``savings`` / ``income``."""
    if t.get("card_bill_payment"):
        return "card_bills"
    if t.get("internal_transfer"):
        return "transfers"
    if t.get("savings"):
        return "savings"
    amount = float(t.get("amount") or 0)
    if t.get("is_income") or amount > 0:
        return "income"
    return "spend"


def _prev_month(ym):
    y, m = int(ym[:4]), int(ym[5:7])
    return f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"


def build_spending(transactions, months=MONTHS, today=None):
    """Spending explorer blocks for the last ``months`` months with data, newest first.

    ``today`` (a ``date``) drops rows dated after it — RiseUp emits card purchases at
    their future billing date, and money that hasn't moved isn't spent yet. Months
    flagged ``partial`` are the calendar month of ``today`` (``vs_prev`` then compares
    a part-month to a whole one).
    """
    buckets = defaultdict(lambda: {
        "total": 0.0,
        "cats": defaultdict(lambda: [0.0, 0]),
        "merchants": defaultdict(lambda: [0.0, 0]),
        "tx": [],
        "excluded": {k: {"amount": 0.0, "count": 0}
                     for k in ("card_bills", "transfers", "savings", "income")},
    })
    cutoff = today.isoformat() if today else None
    for t in transactions:
        d = t.get("date") or ""
        if len(d) < 10 or (cutoff and d > cutoff):
            continue
        b = buckets[d[:7]]
        amount = float(t.get("amount") or 0)
        kind = classify(t)
        if kind != "spend":
            e = b["excluded"][kind]
            e["amount"] += abs(amount)
            e["count"] += 1
            continue
        spent = -amount
        cat = (t.get("category") or "").strip() or "אחר"
        merchant = merchant_name(t.get("description"))
        b["total"] += spent
        b["cats"][cat][0] += spent
        b["cats"][cat][1] += 1
        b["merchants"][merchant][0] += spent
        b["merchants"][merchant][1] += 1
        b["tx"].append({"date": d, "merchant": merchant, "amount": round(spent, 2), "category": cat})

    this_month = today.isoformat()[:7] if today else None
    out = []
    for ym in sorted(buckets, reverse=True)[:months]:
        b = buckets[ym]
        total = b["total"]
        prev = buckets.get(_prev_month(ym))
        by_cat = sorted(
            ({"name": k, "amount": round(v[0], 2), "pct": round(v[0] / total * 100, 1) if total else 0.0,
              "count": v[1]} for k, v in b["cats"].items()),
            key=lambda c: -c["amount"])
        by_merchant = sorted(
            ({"name": k, "amount": round(v[0], 2), "count": v[1]} for k, v in b["merchants"].items()),
            key=lambda m: -m["amount"])[:MAX_MERCHANTS]
        txs = sorted(b["tx"], key=lambda x: (x["date"], x["amount"]), reverse=True)[:MAX_TX_PER_MONTH]
        out.append({
            "month": ym,
            "total": round(total, 2),
            "vs_prev": round(total - prev["total"], 2) if prev else None,
            "partial": ym == this_month,
            "by_category": by_cat,
            "by_merchant": by_merchant,
            "transactions": txs,
            "excluded": {k: {"amount": round(v["amount"], 2), "count": v["count"]}
                         for k, v in b["excluded"].items()},
        })
    return {"months": out}


def main():
    with open(TRANSACTIONS, encoding="utf-8") as f:
        txs = json.load(f)["transactions"]
    for m in build_spending(txs, today=date.today())["months"]:
        print(f'{m["month"]}  total ₪{m["total"]:,.0f}  vs_prev {m["vs_prev"]}  partial={m["partial"]}')
        for c in m["by_category"][:5]:
            print(f'    {c["name"]:<20} ₪{c["amount"]:>9,.0f}  {c["pct"]:>5}%  x{c["count"]}')
        print("    excluded:", {k: (v["amount"], v["count"]) for k, v in m["excluded"].items()})


if __name__ == "__main__":
    main()
