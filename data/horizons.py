#!/usr/bin/env python3
"""Current me / Near-future me / Future me: who each shekel out is for.

Every expense in the ledger carries a ``horizon``:

    current   living now (rent, food, bills, mortgage, interest)
    near      the next few years (deposits, study funds, investments, loan principal)
    future    retirement (pension, gemel, managers' insurance)

``default_horizon(rec)`` is the rule-based default that ``digest.py`` stamps on each
row; a manual override (``db/edit.py horizon`` or the ledger API) replaces it through
the ``transactions`` view. ``build_horizons(transactions)`` is the ``horizons`` block
of ``cashflow.json``: per month, each bucket as a share of net income against the
~33% target, with the remainder shown as ``unallocated``.

Pure and stdlib-only. Running it directly prints the split of the real ledger.
"""

import json
import os
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
TRANSACTIONS = os.path.join(HERE, "digested", "transactions.json")

HORIZONS = ("current", "near", "future")
TARGET_PCT = round(100 / len(HORIZONS), 1)
MONTHS = 6
TOP_PER_BUCKET = 5

# Retirement vehicles. Checked before NEAR_PHRASES: "גמל" beats a generic "הפקדה".
# Not a bare "הראל": Harel also sells health/car insurance, which is "current".
FUTURE_PHRASES = ("פנסיה", "פנסיוני", "גמל", "ביטוח מנהלים", "אנליסט")
# Medium-term savings and paying down loan principal. Interest stays "current":
# it buys nothing for later.
NEAR_PHRASES = ("קרן השתלמות", "השתלמות", "פיקדון", "פקדון", "אקסלנס", "ניהול השק",
                "השקעות", "פירעון הלוואה", "פרעון הלוואה", "סילוק", "סלוק")


def is_expense(rec):
    """Money that left the household: not income, a transfer between our own
    accounts, or a card-bill settlement (its purchases are already in the ledger)."""
    if rec.get("internal_transfer") or rec.get("card_bill_payment"):
        return False
    return float(rec.get("amount") or 0) < 0 and not rec.get("is_income")


def default_horizon(rec):
    """The rule-based horizon for an expense row, or None for a row that is not one."""
    if not is_expense(rec):
        return None
    desc = rec.get("description") or ""
    if any(p in desc for p in FUTURE_PHRASES):
        return "future"
    if any(p in desc for p in NEAR_PHRASES):
        return "near"
    if rec.get("savings") or rec.get("category") == "השקעה וחיסכון":
        return "near"
    return "current"


def is_income(rec):
    """Net income as cashflow.aggregate_by_month counts it."""
    if rec.get("internal_transfer") or rec.get("card_bill_payment") or rec.get("savings"):
        return False
    return bool(rec.get("is_income")) or float(rec.get("amount") or 0) > 0


def _pct(part, whole):
    return round(100 * part / whole, 1) if whole > 0 else None


def build_horizons(transactions, months=MONTHS, meta=None, goals=None):
    """The ``horizons`` block: the last ``months`` months with data, newest first.

    Each month has ``income``, a ``buckets`` entry per horizon (amount, pct of income,
    gap to its target in points, the largest rows) and ``unallocated`` = income minus all
    three. A row's own ``horizon`` (override or digest default) wins; rows without one
    fall back to ``default_horizon``.

    ``meta`` is the ``horizons`` table (db/goal_store.py ``horizons``: key, name, target_pct);
    without it every bucket targets ``TARGET_PCT``. ``goals`` (db/goal_store.py ``all_goals``)
    are listed under the horizon each is assigned to."""
    targets = {h["key"]: float(h["target_pct"]) for h in meta or []}
    names = {h["key"]: h["name"] for h in meta or []}
    by_month = defaultdict(lambda: {"income": 0.0, "rows": defaultdict(list)})
    for t in transactions:
        ym = (t.get("date") or "")[:7]
        if len(ym) != 7:
            continue
        if is_income(t):
            by_month[ym]["income"] += float(t["amount"])
            continue
        h = t.get("horizon") if is_expense(t) else None
        h = h if h in HORIZONS else default_horizon(t)
        if h:
            by_month[ym]["rows"][h].append(t)

    out = []
    for ym in sorted(by_month, reverse=True)[:months]:
        m = by_month[ym]
        income = round(m["income"], 2)
        buckets, spent = {}, 0.0
        for h in HORIZONS:
            rows = m["rows"][h]
            amount = round(sum(-float(r["amount"]) for r in rows), 2)
            spent += amount
            pct = _pct(amount, income)
            top = sorted(rows, key=lambda r: float(r["amount"]))[:TOP_PER_BUCKET]
            buckets[h] = {
                "amount": amount, "pct": pct,
                "target_pct": targets.get(h, TARGET_PCT),
                "gap_pts": round(pct - targets.get(h, TARGET_PCT), 1) if pct is not None else None,
                "count": len(rows),
                # `amount` is the real charge (the row's ledger key); `offset` was paid back
                "top": [{"date": r["date"], "description": r.get("description", ""),
                         "amount": r.get("gross_amount", r["amount"]), "category": r.get("category"),
                         "overridden": bool(r.get("overridden")), "tags": r.get("tags") or [],
                         "goal": r.get("goal"),
                         **({"offset": r["offset_amount"]} if r.get("offset_amount") else {})}
                        for r in top],
            }
        left = round(income - spent, 2)
        out.append({"month": ym, "income": income, "buckets": buckets,
                    "unallocated": {"amount": left, "pct": _pct(left, income)}})
    by_horizon = {h: [{"id": g.get("goal_id", g["id"]), "description": g["description"], "amount": g["amount"],
                       "end_date": g.get("end_date")}
                      for g in goals or [] if g.get("horizon") == h] for h in HORIZONS}
    return {"target_pct": TARGET_PCT, "horizons": list(HORIZONS), "names": names,
            "targets": {h: targets.get(h, TARGET_PCT) for h in HORIZONS}, "goals": by_horizon, "months": out}


def main():
    with open(TRANSACTIONS, encoding="utf-8") as f:
        doc = json.load(f)
    txns = doc["transactions"] if isinstance(doc, dict) else doc
    block = build_horizons(txns)
    print(f"target {block['target_pct']}% of net income per bucket")
    for m in block["months"]:
        cells = "  ".join(f"{h}: ₪{m['buckets'][h]['amount']:>9,.0f} ({m['buckets'][h]['pct']}%)"
                          for h in HORIZONS)
        print(f"{m['month']}  income ₪{m['income']:>9,.0f}  {cells}  "
              f"left ₪{m['unallocated']['amount']:,.0f}")


if __name__ == "__main__":
    main()
