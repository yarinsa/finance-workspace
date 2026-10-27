#!/usr/bin/env python3
"""Month spending explorer model (PRD 12, Phase 3).

``build_spending(transactions)`` turns the unified ledger into the ``spending``
block of ``cashflow.json`` behind the app's ``/monthly`` screen: for each of the
last N months with data, the real spending broken down by category and merchant,
the individual transactions, ``by_line`` (spend per section — fixed / variable /
debt_savings, see ``block`` — category group and category, for the group-by list), the change vs. the previous month, and an
``excluded`` block that explains what was *not* counted as spending.

Exclusion semantics match ``cashflow.aggregate_by_month`` so the two screens agree:
card-bill settlements and internal transfers are not spending (the underlying
purchases are already in the ledger), savings deposits are saved rather than spent,
and positive amounts / ``is_income`` rows are income. A row is counted in exactly
one bucket, in that precedence order.

Pure (merchant keys come from finance/merchants.py); imported by ``cashflow.build()``. Running it directly prints
a summary of the real ledger.
"""

import json
import os
from collections import defaultdict
from datetime import date

from finance.categories import DEBT_CATEGORIES
from finance.merchants import merchant_name

HERE = os.path.dirname(os.path.abspath(__file__))
TRANSACTIONS = os.path.join(HERE, "digested", "transactions.json")

MONTHS = 6
MAX_TX_PER_MONTH = 300   # keep the cashflow.json payload small
MAX_MERCHANTS = 40

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


def block(t):
    """The month screen's section for one spend row, the same rule as
    ``months_view.classify_expense``: loans and the mortgage are ``debt_savings``,
    otherwise the ledger's (household-editable) ``kind``; a kindless expense (a
    pension debit, deposit tax) is debt/savings too."""
    if t.get("savings") or (t.get("category") or "").strip() in DEBT_CATEGORIES:
        return "debt_savings"
    return t.get("kind") or "debt_savings"


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
        "lines": defaultdict(lambda: [0.0, 0]),
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
        group = t.get("category_group")
        sec = block(t)
        line = b["lines"][(sec, group, cat)]
        line[0] += spent
        line[1] += 1
        # `amount` stays the real charge (it is the row's ledger key); totals above count
        # the net, after a payback offset (finance/offsets.py) took `offset` off it.
        row = {"date": d, "merchant": merchant, "amount": round(-float(t.get("gross_amount", amount)), 2),
               "category": cat, "group": group, "block": sec}
        if t.get("kind"):
            row["kind"] = t["kind"]
        if t.get("offset_amount"):
            row["offset"] = t["offset_amount"]
            row["offsets"] = [{"date": str(o["date"])[:10], "description": o.get("description"),
                               "amount": o["amount"], "kind": o["kind"]} for o in t.get("offsets") or []]
        if t.get("overridden"):
            row["overridden"] = True          # edited in the ledger DB; the app marks it
        if t.get("tags"):
            row["tags"] = t["tags"]           # from the ledger DB's transaction_tags
        b["tx"].append(row)

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
        by_line = sorted(
            ({"block": k[0], "group": k[1], "category": k[2], "amount": round(v[0], 2), "count": v[1]}
             for k, v in b["lines"].items()),
            key=lambda x: -x["amount"])
        txs = sorted(b["tx"], key=lambda x: (x["date"], x["amount"]), reverse=True)[:MAX_TX_PER_MONTH]
        out.append({
            "month": ym,
            "total": round(total, 2),
            "vs_prev": round(total - prev["total"], 2) if prev else None,
            "partial": ym == this_month,
            "by_category": by_cat,
            "by_merchant": by_merchant,
            "by_line": by_line,
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
