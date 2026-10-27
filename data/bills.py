"""Bills & subscriptions for the current cycle (the ``bills`` block of cashflow.json).

Built from the ledger, not RiseUp's envelopes. A bill is a **series**: one merchant
at one amount (±15%), so the several Apple subscriptions stay apart and a
mortgage step-up starts a new series. Two kinds of series are bills:

- **Fixed**: rows whose ``kind`` is ``fixed`` (finance/categories.py, household
  edits included), seen in at least 2 of the 3 cycles before this one, or before
  and in this one. A series fixed only by its category's default (no recurrence,
  merchant, RiseUp or manual signal) needs all 3 — the mortgage-arrears payoffs
  (סילוק פיגור) are הלוואה but not a bill. Expected amount = the latest charge; day = its day of month.
  This is what brings in AWS, SUPERHUMAN or ANTHROPIC, which RiseUp never had.
- **Utilities** (``UTILITIES``: electricity, water, gas, ארנונה): usage-priced and
  often bi-monthly, so never ``fixed``. Their cadence (1 or 2 months) is the median
  gap between charges; the next one is the last + cadence; the amount is the median
  of the last three (``estimated``).

Each item is ``paid`` (a charge of the series in the cycle; any amount for a
utility), ``upcoming`` or ``overdue`` (its day passed with no charge). RiseUp's
budget doc only gives the cycle's start day (``cashflowStartDay``); without it the
cycle is the calendar month.

Read-only over the ledger.
"""
import calendar
import json
import os
import re
from collections import defaultdict
from datetime import date, timedelta
from statistics import median

from finance import categories
from finance.merchants import merchant_name
from runway import posting_date

HERE = os.path.dirname(os.path.abspath(__file__))
BUDGET = os.path.join(HERE, "riseup", "raw", "budget_current.json")

SERIES_TOLERANCE = 0.15   # same series: within ±15% of the series' median amount
LOOKBACK_CYCLES = 3       # a fixed series is active when seen in >= MIN_CYCLES of these
MIN_CYCLES = 2
UTILITIES = {"חשמל", "מים", "גז", "ארנונה"}
UTILITY_HISTORY = 6       # charges looked at for a utility's cadence and amount


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


def _month_index(d):
    return d.year * 12 + d.month - 1


def _cycle_index(d, start_day):
    """Which cycle a date is in: the month its cycle started (a cycle runs from day N)."""
    return _month_index(d) - (1 if d.day < start_day else 0)


def _expense_rows(transactions):
    for t in transactions:
        if t.get("kind") and len(t.get("date") or "") >= 10 and float(t.get("amount") or 0) < 0:
            yield t


def _series(rows):
    """Split one merchant's rows into amount clusters (each within SERIES_TOLERANCE
    of the cluster's median), oldest first inside each."""
    clusters = []
    for t in sorted(rows, key=lambda t: -float(t["amount"])):
        a = -float(t["amount"])
        for c in clusters:
            m = median(-float(x["amount"]) for x in c)
            if abs(a - m) <= m * SERIES_TOLERANCE:
                c.append(t)
                break
        else:
            clusters.append([t])
    return [sorted(c, key=lambda t: t["date"]) for c in clusters]


def _in_cycle(day_clamped, start, end):
    """Place day-of-month inside [start, end]; None when it cannot be."""
    for y, m in sorted({(start.year, start.month), (end.year, end.month)}):
        d = date(y, m, min(day_clamped, calendar.monthrange(y, m)[1]))
        if start <= d <= end:
            return d
    return None


def _fixed_series(transactions, start, end, start_day):
    """[(rows, rows_in_cycle)] for the active fixed series."""
    cur = _month_index(start)
    by_merchant = defaultdict(list)
    for t in _expense_rows(transactions):
        if t.get("kind") == categories.FIXED and t.get("category") not in UTILITIES \
                and t["date"][:10] <= end.isoformat():
            by_merchant[t.get("merchant") or merchant_name(t.get("description"))].append(t)
    out = []
    for rows in by_merchant.values():
        for s in _series(rows):
            cycles = {_cycle_index(date.fromisoformat(t["date"][:10]), start_day) for t in s}
            before = {c for c in cycles if cur - LOOKBACK_CYCLES <= c < cur}
            now = [t for t in s if start.isoformat() <= t["date"][:10] <= end.isoformat()]
            evidence = any(t.get("kind_source") != "category" for t in s)
            need = MIN_CYCLES if evidence else LOOKBACK_CYCLES
            if len(before) >= need or (evidence and before and now):
                out.append((s, now))
    return out


def _utility_series(transactions, start, end):
    """[(rows, rows_in_cycle, cadence_months, next_due)] for utilities due this cycle."""
    by_merchant = defaultdict(list)
    for t in _expense_rows(transactions):
        if t.get("category") in UTILITIES and t["date"][:10] <= end.isoformat():
            by_merchant[t.get("merchant") or merchant_name(t.get("description"))].append(t)
    out = []
    for rows in by_merchant.values():
        rows.sort(key=lambda t: t["date"])
        now = [t for t in rows if start.isoformat() <= t["date"][:10] <= end.isoformat()]
        past = [t for t in rows if t["date"][:10] < start.isoformat()][-UTILITY_HISTORY:]
        if len(past) < 2:
            continue
        months = sorted({_month_index(date.fromisoformat(t["date"][:10])) for t in past})
        gaps = [b - a for a, b in zip(months, months[1:])]
        cadence = max(1, round(median(gaps))) if gaps else 1
        last = date.fromisoformat(past[-1]["date"][:10])
        nxt = _month_index(last) + cadence
        if now or nxt <= _month_index(end) and nxt >= _month_index(start) - 1:
            out.append((past, now, cadence, last.day))
    return out


def _item(name, category, amount, day, now, start, end, as_of, **extra):
    paid_on = max(t["date"][:10] for t in now) if now else None
    if paid_on:
        due = date.fromisoformat(paid_on)
    else:
        due = _in_cycle(day, start, end)
        due = posting_date(due) if due else None
    status = "paid" if paid_on else "overdue" if due and due < as_of else "upcoming"
    return {"name": name, "category": category, "group": categories.group_of(category),
            "kind": categories.bill_kind(category), "amount": round(amount, 2),
            "due_day": due.day if due else None, "due_date": due.isoformat() if due else None,
            "status": status, "paid_on": paid_on, **extra}


def build_bills(budget, transactions, as_of):
    """Bills block for the current cycle (see the module docstring)."""
    start_day = int((budget or {}).get("cashflowStartDay") or 1)
    month = (budget or {}).get("budgetDate") or as_of.strftime("%Y-%m")
    start, end = cycle_bounds(month, start_day)
    items = []
    for rows, now in _fixed_series(transactions, start, end, start_day):
        last = rows[-1]
        past = [t for t in rows if t["date"][:10] < start.isoformat()] or rows
        ref = now[-1] if now else past[-1]
        items.append(_item(clean_name(last.get("description")), last.get("category"),
                           -float(sum(float(t["amount"]) for t in now) if now else ref["amount"]),
                           date.fromisoformat(past[-1]["date"][:10]).day, now, start, end, as_of))
    for past, now, cadence, day in _utility_series(transactions, start, end):
        last = past[-1]
        amount = -sum(float(t["amount"]) for t in now) if now else \
            median(-float(t["amount"]) for t in past[-3:])
        items.append(_item(clean_name(last.get("description")), last.get("category"), amount, day,
                           now, start, end, as_of, estimated=not now, cadence_months=cadence))

    items.sort(key=lambda i: (i["due_date"] is None, i["due_date"] or "", -i["amount"]))
    total = lambda s: round(sum(i["amount"] for i in items if i["status"] == s), 2)
    return {
        "month": month,
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
