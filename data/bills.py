"""Bills & subscriptions for the current RiseUp cycle (the ``bills`` block of cashflow.json).

One row per ``fixed`` budget envelope: what it is, what it costs, the day it
lands, and whether it is already ``paid`` this cycle, still ``upcoming``, or
``overdue`` (its day has passed with no matching charge). Income envelopes
(negative amounts, e.g. salary or the Leumi loan-interest refund) and transfers
between our own accounts are not bills and are dropped.

What comes from where:

- **The list and the expected amount**: RiseUp's ``fixed`` envelopes. They hold a
  predicted amount for usage-priced bills (electricity) and the bi-monthly ones
  (water, gas) that the ledger's recurrence rules do not call fixed.
- **Category and kind**: the taxonomy (finance/categories.py). The category is the
  ledger's for the same merchant (so the household's edits apply), else the
  payee's merchant default or RiseUp's label through ``SOURCE_ALIASES``; ``kind``
  is ``categories.bill_kind`` (loan / subscription / bill).
- **Paid**: an envelope actual, or a ledger charge in the cycle from the same
  merchant (amount within ±15%, any amount for a usage-priced category) — RiseUp
  misses card charges it has not matched yet (the 10-25 פרטנר on CAL).

Read-only over ``riseup/raw/budget_current.json`` and the ledger.
"""
import calendar
import json
import os
import re
from datetime import date, timedelta

import digest
from finance import categories
from finance.merchants import merchant_name
from runway import posting_date

HERE = os.path.dirname(os.path.abspath(__file__))
BUDGET = os.path.join(HERE, "riseup", "raw", "budget_current.json")

PAID_TOLERANCE = 0.15


def load_budget(path=BUDGET):
    """The raw RiseUp budget dump, or None when it has not been scraped."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _norm(s):
    return " ".join((s or "").split())


def clean_name(business_name):
    """'הו"ק לעיין ניהול נכסי,לסניף 20-406' -> 'הו"ק לעיין ניהול נכסי'."""
    return _norm(re.split(r",\s*(?:ל|מ)?סניף|,\s*חיוב", business_name or "")[0])


def cycle_bounds(budget_date, start_day=1):
    """('2026-10', 1) -> (2026-10-01, 2026-10-31)."""
    y, m = map(int, budget_date.split("-"))
    start = date(y, m, min(start_day, calendar.monthrange(y, m)[1]))
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    nxt = date(ny, nm, min(start_day, calendar.monthrange(ny, nm)[1]))
    return start, nxt - timedelta(days=1)


def _ledger_day(name, transactions, cycle_start):
    """Day-of-month this payee last hit the ledger before the cycle (None if unseen)."""
    key = _norm(name)
    days = [t["date"][:10] for t in transactions
            if t.get("date") and t["date"][:10] < cycle_start.isoformat()
            and float(t.get("amount") or 0) < 0
            and _norm(t.get("description")).startswith(key)]
    return date.fromisoformat(max(days)).day if days else None


def _ledger_payment(merchant, category, amount, transactions, start, end, used):
    """Date of a ledger charge in [start, end] that pays this bill, or None.

    Same merchant, the closest amount within PAID_TOLERANCE (any amount for a
    usage-priced category); each charge pays one bill (``used`` holds their ids)."""
    lo, hi = start.isoformat(), end.isoformat()
    best = None
    for t in transactions:
        d = (t.get("date") or "")[:10]
        a = -float(t.get("amount") or 0)
        if (not lo <= d <= hi or a <= 0 or id(t) in used
                or (t.get("merchant") or merchant_name(t.get("description"))) != merchant):
            continue
        gap = abs(a - amount)
        if (gap <= amount * PAID_TOLERANCE or category in categories.USAGE_BASED) \
                and (best is None or gap < best[0]):
            best = (gap, t)
    if best is None:
        return None
    used.add(id(best[1]))
    return best[1]["date"][:10]


def _in_cycle(day_clamped, start, end):
    """Place day-of-month inside [start, end]; None when it cannot be."""
    for y, m in {(start.year, start.month), (end.year, end.month)}:
        d = date(y, m, min(day_clamped, calendar.monthrange(y, m)[1]))
        if start <= d <= end:
            return d
    return None


def build_bills(budget, transactions, as_of):
    """Bills block for the budget's cycle; None without a budget dump."""
    if not budget or not budget.get("budgetDate"):
        return None
    start, end = cycle_bounds(budget["budgetDate"], budget.get("cashflowStartDay") or 1)
    known = categories.ledger_categories(transactions)
    bills = []
    for e in budget.get("envelopes", []):
        if e.get("type") != "fixed":
            continue
        amount = float(e.get("originalAmount") or 0)
        d = e.get("details") or {}
        raw_name = d.get("businessName") or ""
        if amount <= 0 or digest.is_internal_transfer({"description": raw_name}):
            continue
        merchant = merchant_name(raw_name)
        category = known.get(merchant) or categories.label_category(raw_name, d.get("expense"))
        actual_dates = [(a.get("transactionDate") or a.get("billingDate") or "")[:10]
                        for a in e.get("actuals") or []]
        bills.append((amount, d, raw_name, merchant, category, [x for x in actual_dates if x]))

    # A charge RiseUp already matched to an envelope cannot pay another one too.
    used = set()
    for amount, _, _, merchant, category, actual_dates in bills:
        if actual_dates:
            _ledger_payment(merchant, category, amount, transactions, start, end, used)

    items = []
    for amount, d, raw_name, merchant, category, actual_dates in bills:
        name = clean_name(raw_name)
        paid_on = max(actual_dates) if actual_dates else \
            _ledger_payment(merchant, category, amount, transactions, start, end, used)

        if paid_on:
            due = date.fromisoformat(paid_on)
        else:
            due = None
            day = _ledger_day(name, transactions, start)
            if day:
                due = _in_cycle(day, start, end)
                due = posting_date(due) if due else None
            if due is None and (d.get("transactionDate") or "")[:10]:
                guess = date.fromisoformat(d["transactionDate"][:10])
                due = guess if start <= guess <= end else None

        if paid_on:
            status = "paid"
        elif due and due < as_of:
            status = "overdue"
        else:
            status = "upcoming"
        items.append({
            "name": name, "category": category, "group": categories.group_of(category),
            "kind": categories.bill_kind(category),
            "amount": round(amount, 2),
            "due_day": due.day if due else None,
            "due_date": due.isoformat() if due else None,
            "status": status, "paid_on": paid_on,
        })

    items.sort(key=lambda i: (i["due_date"] is None, i["due_date"] or "", -i["amount"]))
    total = lambda s: round(sum(i["amount"] for i in items if i["status"] == s), 2)
    return {
        "month": budget["budgetDate"],
        "cycle_start": start.isoformat(), "cycle_end": end.isoformat(),
        "paid_total": total("paid"), "upcoming_total": total("upcoming"),
        "overdue_total": total("overdue"),
        "items": items,
    }


if __name__ == "__main__":
    tx = json.load(open(os.path.join(HERE, "digested", "transactions.json"), encoding="utf-8"))
    tx = tx["transactions"] if isinstance(tx, dict) else tx
    out = build_bills(load_budget(), tx, date.today())
    print(json.dumps(out, ensure_ascii=False, indent=2))
