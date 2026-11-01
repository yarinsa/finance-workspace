"""Read one of the household's stores (db/*_store.py) from Postgres, best-effort.

`from_db(read)` runs `read(module, conn)` on this tenant's database and returns its result, or
None when there is no database to read: DATABASE_URL unset, `--no-db` on the command line,
FINANCE_NO_DB=1 (set for the data tests, so they never reach the live database), or an
unreachable server (printed to stderr, so a dead DB never stops the pipeline).
"""
import importlib
import os
import sys
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "db"


def database_url():
    sys.path.insert(0, str(DB))
    try:
        from ledger import database_url as url
        return url()
    finally:
        sys.path.remove(str(DB))


def from_db(store, read, what=None):
    """`read(<db/store.py module>, conn)` on this tenant's database, or None without one."""
    if "--no-db" in sys.argv or os.environ.get("FINANCE_NO_DB") or not (os.environ.get("DATABASE_URL") or database_url()):
        return None
    sys.path.insert(0, str(DB))
    try:
        module = importlib.import_module(store)
        from ledger import connect
        with connect() as conn:
            return read(module, conn)
    except Exception as e:   # noqa: BLE001 — a dead DB must not stop the pipeline
        print(f"{what or store}: database unavailable ({e})", file=sys.stderr)
        return None
    finally:
        sys.path.remove(str(DB))
