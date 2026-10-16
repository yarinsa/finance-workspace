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
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUDGET = ROOT / "riseup" / "raw" / "budget_current.json"
OVERRIDES = ROOT / "budgets" / "budgets.json"
RAW = ROOT / "riseup" / "raw"
HISTORY_CYCLES = 4


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


def load_history(raw_dir=RAW):
    """All budget docs from the budget_YYYY-MM_6.json history dumps (each is a
    list of ~7 monthly docs), de-duplicated by budgetDate keeping the freshest."""
    docs = {}
    for f in sorted(Path(raw_dir).glob("budget_20*_6.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for d in data if isinstance(data, list) else [data]:
            key = d.get("budgetDate") if isinstance(d, dict) else None
            if key and (key not in docs or (d.get("lastUpdatedAt") or "") >= (docs[key].get("lastUpdatedAt") or "")):
                docs[key] = d
    return list(docs.values())


def _category_totals(budget):
    """{name: {"planned", "spent"}} for the trackingCategory envelopes of one doc."""
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
    return cats


def category_history(history_docs, current_month, n=HISTORY_CYCLES):
    """{name: [{cycle, spent}, ...]} oldest->newest for the last `n` cycles
    before `current_month` ('YYYY-MM'). A category absent from a cycle counts 0."""
    docs = sorted((d for d in history_docs or [] if (d.get("budgetDate") or "") < current_month),
                  key=lambda d: d["budgetDate"])[-n:]
    per = [(d["budgetDate"], _category_totals(d)) for d in docs]
    names = {name for _, t in per for name in t}
    return {name: [{"cycle": m, "spent": round(t.get(name, {}).get("spent", 0.0), 2)} for m, t in per]
            for name in names}


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


def build_budgets(budget, as_of, overrides=None, history_docs=None):
    """Budget block for the app, or None when there is no budget doc.

    `as_of` is a date. Categories are merged by name and sorted by planned desc.
    `history_docs` are earlier monthly budget docs (see load_history) feeding each
    category's `history`; None loads them from the raw dumps (cashflow.py relies
    on this), pass [] to skip.
    """
    if not budget:
        return None
    overrides = overrides or {}
    month = budget.get("budgetDate") or as_of.strftime("%Y-%m")
    start, end = cycle_bounds(month, int(budget.get("cashflowStartDay") or 1))
    cats = _category_totals(budget)
    hist = category_history(load_history() if history_docs is None else history_docs, month)

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
            "history": hist.get(name, []),
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


def save_overrides(overrides, path=OVERRIDES):
    """Write the `{category: amount}` store, creating the directory if missing."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(overrides, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def set_override(overrides, category, amount):
    """New overrides dict with `category` planned at `amount` (pure)."""
    return {**overrides, category: float(amount)}


def unset_override(overrides, category):
    """New overrides dict without `category` (pure)."""
    return {k: v for k, v in overrides.items() if k != category}


def _rebuild():
    """Regenerate cashflow.json so the app picks up the change."""
    subprocess.run([sys.executable, str(ROOT / "cashflow.py")], check=True)


def _print_line(category):
    b = build_budgets(load_budget(), date.today(), load_overrides())
    c = next((c for c in (b or {}).get("categories", []) if c["name"] == category), None)
    if not c:
        print(f"{category}: no such category in the current budget")
        return
    tag = " (override)" if c["source"] == "override" else ""
    print(f"{c['name']}: planned {c['planned']:g}{tag}, spent {c['spent']:g}, left {c['left']:g}")


def main(argv, store=OVERRIDES, rebuild=_rebuild, show=_print_line):
    """CLI: `set <category> <amount>` | `unset <category>` | `list`."""
    usage = "usage: budgets.py set <category> <amount> | unset <category> | list"
    cmd = argv[0] if argv else ""
    ov = load_overrides(store)
    if cmd == "list" and len(argv) == 1:
        for k, v in sorted(ov.items()):
            print(f"{k}: {v:g}")
        return 0
    if cmd == "set" and len(argv) == 3:
        try:
            amount = float(argv[2])
        except ValueError:
            print(usage)
            return 2
        if amount < 0:
            print("amount must be >= 0")
            return 2
        save_overrides(set_override(ov, argv[1], amount), store)
    elif cmd == "unset" and len(argv) == 2:
        save_overrides(unset_override(ov, argv[1]), store)
    else:
        print(usage)
        return 2
    rebuild()
    show(argv[1])
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1:
        sys.exit(main(sys.argv[1:]))
    b = build_budgets(load_budget(), date.today(), load_overrides())
    print(json.dumps(b, ensure_ascii=False, indent=2) if b else "no budget doc")
