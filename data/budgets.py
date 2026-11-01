#!/usr/bin/env python3
"""
Budgets — Mint-style "left this month" per category (docs/plangram-prd/12, Phase 2),
and the month's three blocks: fixed, variable and what is left.

Lines are **our categories** (finance/categories.py). The *planned* amount still
comes from RiseUp's budget document (data/riseup/raw/budget_current.json): every
`trackingCategory` envelope is a planned amount for one budget line (weekly lines
such as כלכלה are split into several envelopes sharing a name), its name read
through `categories.tracking_category` (חופשה ✈️ -> תיירות; תחבורה is a whole
group). The *spent* amount is the ledger's: the cycle's expense rows of that
category (or group) whose `kind` is variable — fixed charges are the fixed block,
not a budget line — minus refunds (a positive row in that category). Offsets are
already netted by `offsets.cashflow_view`.

Optional user overrides: the `budget_lines` table `{category: amount}` replaces
RiseUp's planned amount, or adds a line RiseUp does not have (db/budget_store.py).
Old keys holding a RiseUp envelope name still work.

Cycle bounds come from `cashflowStartDay` (not the calendar month): the cycle of
budget month YYYY-MM runs from day N of that month to day N-1 of the next. Every
ledger row dated inside the cycle counts, including card purchases RiseUp dates
at their coming billing day.

`summary` — the month in three blocks (plus debt service), split the way
months_view splits a month (`months_view.classify_expense`):

    fixed         kind=fixed rows (loans and the mortgage excluded), actual so far;
                  expected = actual + the recurring fixed charges of the previous
                  two cycles that have not hit yet (`fixed_items`)
    variable      kind=variable rows, actual so far; estimate = Σ over variable
                  categories of the median spend of the last 3-6 cycles; planned =
                  the budget lines' total; projected = actual + estimate × the share
                  of the cycle still ahead (a daily run-rate, so a trip-heavy
                  median does not swamp the last days of the cycle)
    debt_savings  loans, the mortgage and savings deposits; expected like fixed
    income        actual so far; expected = the forecast's income for this month
    left          free money: income - fixed - debt_savings - the variable PLAN.
                  Not planned for anything; the household aims for ~0 (every
                  shekel assigned). Fixed / debt at expected, income at
                  max(actual, expected).
    projected_end where the cycle is heading: the same, with variable at
                  `projected` instead of the plan

Pure `build_budgets` is called from cashflow.build(); the module is also
importable on its own. Read-only over scraped data.
"""
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

from finance import categories
from finance.paths import data_root
from finance.views.budgets import (  # noqa: F401 — re-exported: the compute lives in finance.views
    ESTIMATE_CYCLES, HISTORY_CYCLES, MATCH_TOLERANCE, MIN_ESTIMATE_CYCLES,
    build_budgets, build_summary, cycle_bounds, fixed_items, fold_merges, line_spent,
    planned_lines, set_override, shift_month, unset_override,
)

CODE = Path(__file__).resolve().parent
ROOT = data_root()
BUDGET = ROOT / "riseup" / "raw" / "budget_current.json"
OVERRIDES = ROOT / "budgets" / "budgets.json"
RAW = ROOT / "riseup" / "raw"
TRANSACTIONS = ROOT / "digested" / "transactions.json"


def load_budget(path=BUDGET):
    """The current RiseUp budget doc, or None when not scraped yet."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None



def _db(run):
    """`run(budget_store, conn)` against the database (db/budget_store.py); None when no
    database is configured or it is unreachable."""
    import digest
    url = digest.database_url()
    if not url:
        return None
    db = str(CODE.parent / "db")
    sys.path.insert(0, db)
    try:
        import budget_store
        from ledger import connect
        with connect(url) as conn:
            return run(budget_store, conn)
    except Exception as e:   # noqa: BLE001 — a dead DB must not stop the digest
        print(f"budgets: database unavailable ({e})", file=sys.stderr)
        return None
    finally:
        sys.path.remove(db)


def _load_file(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): float(v) for k, v in data.items() if isinstance(v, (int, float))}


def load_overrides(path=None):
    """The household's `{category: amount}` planned amounts; {} when there are none.

    Read from the `budget_lines` table. With `path` (tests), or when the database is
    unreachable, or while it is still empty and the old JSON store exists (before
    `budget_store.py import`), read that JSON file instead."""
    if path is not None:
        return _load_file(path)
    lines = _db(lambda m, conn: m.all_lines(conn))
    if lines:
        return lines
    legacy = _load_file(OVERRIDES)
    if legacy and lines is not None:
        print("budgets: budget_lines is empty; using data/budgets/budgets.json "
              "(run db/budget_store.py import)", file=sys.stderr)
    return legacy


def load_history(raw_dir=RAW):
    """All budget docs from the budget_YYYY-MM_6.json history dumps (each is a
    list of ~7 monthly docs), de-duplicated by budgetDate keeping the freshest.
    months_view reads their planned envelopes for past months' expectations."""
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


def save_overrides(overrides, path=None):
    """Store the `{category: amount}` plan: in `budget_lines`, or in the JSON file at `path` (tests).

    Raises when there is no database: writing the old JSON file would be ignored once the
    table has lines."""
    if path is not None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(overrides, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return
    if _db(lambda m, conn: m.replace(conn, overrides)) is None:
        raise SystemExit("budgets: no database to save to (set DATABASE_URL and start Postgres)")



def _rebuild():
    """Regenerate cashflow.json so the app picks up the change."""
    subprocess.run([sys.executable, str(CODE / "cashflow.py")], check=True)


def _ledger():
    from finance import offsets
    doc = json.loads(TRANSACTIONS.read_text(encoding="utf-8"))
    ledger = doc.get("transactions", []) if isinstance(doc, dict) else doc
    return offsets.cashflow_view(ledger), ledger


def _print_line(category):
    view, ledger = _ledger()
    b = build_budgets(load_budget(), view, date.today(), load_overrides(), ledger=ledger)
    c = next((c for c in (b or {}).get("categories", []) if c["name"] == category), None)
    if not c:
        print(f"{category}: no such category in the current budget")
        return
    tag = " (override)" if c["source"] == "override" else ""
    print(f"{c['name']}: planned {c['planned']:g}{tag}, spent {c['spent']:g}, left {c['left']:g}")


def main(argv, store=None, rebuild=_rebuild, show=_print_line):
    """CLI: `set <category> <amount>` | `unset <category>` | `list` | `seed`. A RiseUp
    envelope name is stored as our category (`חופשה ✈️` -> `תיירות`). `seed` copies
    RiseUp's planned amounts into the store as the household's own baseline (lines
    already set are kept), so the plan no longer depends on RiseUp."""
    usage = "usage: budgets.py set <category> <amount> | unset <category> | list | seed"
    cmd = argv[0] if argv else ""
    ov = load_overrides(store)
    name = (categories.tracking_category(argv[1]) or argv[1]) if len(argv) > 1 else None
    if cmd == "list" and len(argv) == 1:
        for k, v in sorted(ov.items()):
            print(f"{k}: {v:g}")
        return 0
    if cmd == "seed" and len(argv) == 1:
        added = {k: round(v, 2) for k, v in planned_lines(load_budget() or {}).items() if k not in ov}
        save_overrides({**ov, **added}, store)
        for k, v in sorted(added.items()):
            print(f"{k}: {v:g}")
        print(f"seeded {len(added)} line(s) from RiseUp")
        rebuild()
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
        save_overrides(set_override(unset_override(ov, argv[1]), name, amount), store)
    elif cmd == "unset" and len(argv) == 2:
        save_overrides(unset_override(unset_override(ov, argv[1]), name), store)
    else:
        print(usage)
        return 2
    rebuild()
    show(name)
    return 0


if __name__ == "__main__":
    from finance.tenancy import use_cli_tenant
    use_cli_tenant()
    if len(sys.argv) > 1:
        sys.exit(main(sys.argv[1:]))
    view, ledger = _ledger()
    b = build_budgets(load_budget(), view, date.today(), load_overrides(), ledger=ledger)
    print(json.dumps(b, ensure_ascii=False, indent=2) if b else "no budget doc")
