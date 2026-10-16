#!/usr/bin/env python3
"""
Budgets — Mint-style "left this month" per category (docs/plangram-prd/12, Phase 2).

Reads RiseUp's budget document (data/riseup/raw/budget_current.json): every
`trackingCategory` envelope is a planned amount for one category (weekly
categories such as כלכלה are split into several envelopes sharing a name), and
its `actuals[]` are the matched transactions (`billingAmount` is POSITIVE for an
expense here; `isIncome` rows are refunds and reduce spend). The category name
lives in `envelope.details.trackingCategory.name`.

Optional user overrides: data/budgets/budgets.json `{category: amount}` replaces
RiseUp's planned amount (gitignored store, same pattern as data/goals/).

Cycle bounds come from `cashflowStartDay` (not the calendar month): the cycle of
budget month YYYY-MM runs from day N of that month to day N-1 of the next.

Pure `build_budgets` is called from cashflow.build(); the module is also
importable on its own. Read-only over scraped data.
"""
import json
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUDGET = ROOT / "riseup" / "raw" / "budget_current.json"
OVERRIDES = ROOT / "budgets" / "budgets.json"


def load_budget(path=BUDGET):
    """The current RiseUp budget doc, or None when not scraped yet."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def load_overrides(path=OVERRIDES):
    """User `{category: amount}` planned-amount overrides; {} when absent."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): float(v) for k, v in data.items() if isinstance(v, (int, float))}


def _start_in(year, month, day):
    """`day` of the month, clamped to the month's length (start day 31 in June)."""
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    last = (nxt - timedelta(days=1)).day
    return date(year, month, min(day, last))


def cycle_bounds(budget_date, start_day):
    """(start, end) inclusive for budget month 'YYYY-MM' with a cashflow start day."""
    y, m = int(budget_date[:4]), int(budget_date[5:7])
    start = _start_in(y, m, start_day)
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    return start, _start_in(ny, nm, start_day) - timedelta(days=1)


def _spent(envelope):
    """Net expense of an envelope's actuals (refunds subtract)."""
    total = 0.0
    for a in envelope.get("actuals") or []:
        amt = abs(float(a.get("billingAmount") or 0))
        total += -amt if a.get("isIncome") else amt
    return total


def build_budgets(budget, as_of, overrides=None):
    """Budget block for the app, or None when there is no budget doc.

    `as_of` is a date. Categories are merged by name and sorted by planned desc.
    """
    if not budget:
        return None
    overrides = overrides or {}
    start, end = cycle_bounds(budget.get("budgetDate") or as_of.strftime("%Y-%m"),
                              int(budget.get("cashflowStartDay") or 1))
    cats = {}
    for e in budget.get("envelopes") or []:
        if e.get("type") != "trackingCategory":
            continue
        name = ((e.get("details") or {}).get("trackingCategory") or {}).get("name", "").strip()
        if not name or name.startswith("__"):
            continue
        c = cats.setdefault(name, {"planned": 0.0, "spent": 0.0})
        c["planned"] += float(e.get("originalAmount") or 0)
        c["spent"] += _spent(e)

    rows = []
    for name, c in cats.items():
        source = "override" if name in overrides else "riseup"
        planned = overrides[name] if source == "override" else c["planned"]
        spent = c["spent"]
        rows.append({
            "name": name,
            "planned": round(planned, 2),
            "spent": round(spent, 2),
            "left": round(planned - spent, 2),
            "pct": round(spent / planned * 100, 1) if planned > 0 else None,
            "over": spent > planned,
            "source": source,
        })
    rows.sort(key=lambda r: -r["planned"])

    planned = round(sum(r["planned"] for r in rows), 2)
    spent = round(sum(r["spent"] for r in rows), 2)
    left = round(planned - spent, 2)
    days_left = max((end - as_of).days + 1, 0)
    return {
        "cycle_start": start.isoformat(),
        "cycle_end": end.isoformat(),
        "days_left": days_left,
        "total_planned": planned,
        "total_spent": spent,
        "left": left,
        "per_day": round(left / days_left, 2) if left > 0 and days_left else None,
        "categories": rows,
    }


if __name__ == "__main__":
    b = build_budgets(load_budget(), date.today(), load_overrides())
    print(json.dumps(b, ensure_ascii=False, indent=2) if b else "no budget doc")
