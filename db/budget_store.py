"""Budget lines (`budget_lines`): the planned monthly amount per category.

Used by data/budgets.py (the digest and its CLI). Every function takes an open psycopg
connection scoped to a tenant (`ledger.connect`) and commits its writes.

    .venv/bin/python db/budget_store.py list
    .venv/bin/python db/budget_store.py import [data/budgets/budgets.json]   # one-time move from the JSON store
"""
import datetime as dt
import json
import sys
from decimal import Decimal
from pathlib import Path

from sqlmodel import select

from finance.tables import BudgetLine
from ledger import orm_session

STORE = Path(__file__).resolve().parent.parent / "data" / "budgets" / "budgets.json"


def all_lines(conn):
    """Every line as `{category: amount}` (floats), this tenant's only."""
    with orm_session(conn) as s:
        return {r.category: float(r.amount) for r in s.exec(select(BudgetLine)).all()}


def replace(conn, lines):
    """Make the stored lines exactly `lines` ({category: amount}): upsert what changed, delete the rest.

    Raises ValueError for a negative amount, before writing anything."""
    if any(v < 0 for v in lines.values()):
        raise ValueError("a budget line cannot be negative")
    now = dt.datetime.now(dt.timezone.utc)
    with orm_session(conn) as s:
        have = {r.category: r for r in s.exec(select(BudgetLine)).all()}
        for category, row in have.items():
            if category not in lines:
                s.delete(row)
        for category, amount in lines.items():
            amount = Decimal(str(round(amount, 2)))
            row = have.get(category)
            if row is None:
                s.add(BudgetLine(category=category, amount=amount))
            elif row.amount != amount:
                row.amount, row.updated_at = amount, now
        s.commit()
    return all_lines(conn)


def import_json(conn, path=STORE):
    """Copy the JSON store's lines into the database; categories that already have a line are
    left alone. Returns the number added."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    stored = {str(k): float(v) for k, v in data.items() if isinstance(v, (int, float))}
    have = all_lines(conn)
    new = {k: v for k, v in stored.items() if k not in have}
    replace(conn, {**have, **new})
    return len(new)


def main(argv):
    from finance.tenancy import use_cli_tenant
    from ledger import connect
    use_cli_tenant()
    with connect() as conn:
        if argv == ["list"]:
            for k, v in sorted(all_lines(conn).items()):
                print(f"{k}: {v:g}")
            return 0
        if argv[:1] == ["import"] and len(argv) <= 2:
            n = import_json(conn, *(argv[1:] or []))
            print(f"imported {n} budget line(s)")
            return 0
    print("usage: budget_store.py list | import [FILE]")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
