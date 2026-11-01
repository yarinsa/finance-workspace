"""History CLI and loaders: reads the measured balance days and Postgres for the home screen's lenses.

The builders (cash, debt and position series) are ``finance/views/history.py``; this
file reads the banks' measured end-of-day balances (`account_balance_days`, else the
normalized `balance_days` entity), records/reads ``position_snapshots`` (best-effort) and
runs ``backfill``. ``build`` keeps its old signature for callers that want the whole block.
"""
import json
import sys
from datetime import date
from pathlib import Path

import stores
from finance.paths import data_root
from finance.views.history import (  # noqa: F401 — re-exported for scripts and tests
    CARD_DEBT_COMPARABLE_FROM, CASH_DAYS, DEBT_MONTHS_AHEAD, DEBT_MONTHS_BACK, LOCAL_TZ,
    account_balances, backfill_days, cash_history, comparable, coverage, debt_series,
    position_of, snapshot_day)
from finance.views.history import build as build_view

HERE = Path(__file__).resolve().parent


def data_dir():
    return data_root()


def load_cash(snapshot, as_of, root=None):
    """The pool accounts' measured days and ledgers -> ``[account_balances]``.

    The measured end-of-day balances are `account_balance_days` (db/snapshot_store.py), else each
    bank's normalized ``balance_days.json`` (with ``root``, tests and other checkouts, always the files)."""
    from finance.views import runway
    root = Path(root or data_dir())

    def read(*parts):
        p = root.joinpath(*parts)
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    stored = None if root != Path(data_dir()) else stores.from_db(
        "snapshot_store", lambda m, conn: m.balance_days(conn), "balance days")
    accounts = []
    for a in snapshot.get("bank_accounts", []):
        inst = a.get("institution")
        if inst not in runway.POOL_INSTITUTIONS or a.get("kind") != "checking":
            continue
        measured = (stored or {}).get(inst) or {
            date.fromisoformat(r["date"]): r["balance"]
            for r in (read(inst, "normalized", "balance_days.json") or {}).get("records", [])}
        rows = (read(inst, "normalized", "transactions.json") or {}).get("records", [])
        # One checking account per pool bank; its ledger ids differ by scraper (Discount's
        # MCP rows say 0123444499, the snapshot 0034), so take the bank's whole ledger.
        rows = [r for r in rows if r.get("date")]
        accounts.append(account_balances(measured, rows, a.get("balance"), as_of))
    return [x for x in accounts if x[0]]


def positions(snapshot, as_of):
    """Record today's position, return every recorded day (oldest first).

    Best-effort: with no database configured, or an unreachable one, this prints
    to stderr and returns [] so the digest carries on."""
    import goals
    url = goals.database_url()
    if not url:
        return []
    db = str(HERE.parent / "db")
    sys.path.insert(0, db)
    try:
        import position_store
        from ledger import connect
        with connect(url) as conn:
            position_store.record(conn, as_of, **position_of(snapshot))
            return comparable(position_store.series(conn))
    except Exception as e:   # noqa: BLE001 — a dead DB must not stop the digest
        print(f"history: database unavailable ({e})", file=sys.stderr)
        return []
    finally:
        sys.path.remove(db)


def backfill(paths, reference_path=None):
    """Record the comparable days among ``paths`` that position_snapshots does not have yet."""
    import goals
    url = goals.database_url()
    if not url:
        sys.exit("history backfill: DATABASE_URL is not set")
    ref = Path(reference_path) if reference_path else data_dir() / "digested" / "snapshot.json"
    snaps = [json.loads(Path(p).read_text(encoding="utf-8")) for p in paths]
    days = backfill_days(snaps, json.loads(ref.read_text(encoding="utf-8")))
    sys.path.insert(0, str(HERE.parent / "db"))
    import position_store
    from ledger import connect
    with connect(url) as conn:
        have = {p["date"] for p in position_store.series(conn)}
        for day, pos in sorted(days.items()):
            if day.isoformat() in have:
                print(f"  {day}  kept (already recorded)")
                continue
            position_store.record(conn, day, **pos)
            print(f"  {day}  net worth {pos['net_worth']:>14,.2f}  savings {pos['savings']:>12,.2f}")
    print(f"{len(days)} of {len(snaps)} snapshots comparable with {ref.name}")


def build(snapshot, as_of, root=None, record=True):
    """The ``cashflow.json`` -> ``history`` block."""
    return build_view(snapshot, as_of, load_cash(snapshot, as_of, root),
                      positions(snapshot, as_of) if record else [])


if __name__ == "__main__":
    from finance.tenancy import use_cli_tenant
    use_cli_tenant()
    if sys.argv[1:2] == ["backfill"]:
        # poetry run python data/history.py backfill SNAPSHOT.json ...  (see the docstring of backfill)
        backfill(sys.argv[2:])
        sys.exit(0)
    snap = json.loads((data_dir() / "digested" / "snapshot.json").read_text(encoding="utf-8"))
    h = build(snap, date.today(), record=False)
    c = h["cash"]
    print(f"cash: {len(c['days'])} days, measured from {c['measured_from']}")
    for p in c["days"][::7]:
        print(f"  {p['date']}  {p['balance']:>12,.2f}")
    print("debt:")
    for p in h["debt"][::6]:
        print(f"  {p['month']}  {p['total']:>14,.2f}  {p['kind']}")
