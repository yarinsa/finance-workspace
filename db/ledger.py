#!/usr/bin/env python3
"""The transactions database: import the digested ledger, apply overrides.

    scraped_transactions   machine layer, replaced in full on each import
    transaction_overrides  human layer (category / note / excluded), kept forever
    transactions           view: the ledger with overrides applied

`python3 db/ledger.py sync` is how data/digest.py uses it: the consolidated
ledger arrives as JSON on stdin, is imported, and the `transactions` view comes
back on stdout in the same order. Rows are keyed on the ledger's dedup key,
(date, abs(amount)).
"""
import json
import os
import re
import sys
from decimal import Decimal
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

from finance.models import LedgerTransaction

REPO = Path(__file__).resolve().parent.parent
ALEMBIC_INI = Path(__file__).resolve().parent / "alembic.ini"


def database_url(env_file=REPO / ".env"):
    """DATABASE_URL from the environment, else from .env (read literally)."""
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("DATABASE_URL="):
                return line.split("=", 1)[1].strip().strip("'\"")
    return None


def sqlalchemy_url(url):
    """The same URL (or libpq key=value conninfo) for SQLAlchemy, on the psycopg 3 driver."""
    if "://" not in url:
        from psycopg.conninfo import conninfo_to_dict
        from sqlalchemy.engine import URL
        c = conninfo_to_dict(url)
        return URL.create("postgresql+psycopg", username=c.get("user"), password=c.get("password"),
                          host=c.get("host"), port=int(c["port"]) if c.get("port") else None,
                          database=c.get("dbname"))
    return re.sub(r"^postgres(ql)?(\+\w+)?://", "postgresql+psycopg://", url)


def migrate(url):
    """`alembic upgrade head` (db/migrations) against this database."""
    from alembic import command
    from alembic.config import Config
    cfg = Config(str(ALEMBIC_INI))
    cfg.attributes["url"] = url
    command.upgrade(cfg, "head")


def connect(url=None):
    """Open a connection and make sure the schema is migrated to head."""
    url = url or database_url()
    if not url:
        raise SystemExit("DATABASE_URL is not set (env or .env)")
    migrate(url)
    return psycopg.connect(url)


def key(date, amount):
    """The ledger's dedup key as it is stored: (date, abs amount to the agora)."""
    return date, round(abs(Decimal(str(amount))), 2)


def load(conn, ledger):
    """Replace scraped_transactions with this ledger. Overrides are untouched.

    Every row is validated as a LedgerTransaction first, so the jsonb `record`
    always has the shape finance/models.py declares."""
    ledger = [LedgerTransaction.model_validate(t).model_dump(mode="json", exclude_unset=True)
              for t in ledger]
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("TRUNCATE scraped_transactions")
        cur.executemany(
            """INSERT INTO scraped_transactions
                   (txn_date, abs_amount, amount, description, category, origin,
                    sources, position, record)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            [(*key(t["date"], t["amount"]), t["amount"], t.get("description") or "",
              t.get("category"), t.get("origin"), t.get("sources") or [], i,
              Jsonb(t))
             for i, t in enumerate(ledger)])


def materialize(conn):
    """The `transactions` view as ledger rows, in the digested ledger's order."""
    rows = conn.execute("SELECT record FROM transactions ORDER BY position").fetchall()
    return [r[0] for r in rows]


def orphaned(conn):
    return conn.execute(
        "SELECT txn_date, abs_amount, category, note, excluded FROM orphaned_overrides "
        "ORDER BY txn_date DESC").fetchall()


def sync(conn, ledger):
    """Import the ledger and return it with overrides applied."""
    load(conn, ledger)
    return materialize(conn)


def main():
    if sys.argv[1:] != ["sync"]:
        raise SystemExit("usage: ledger.py sync  < ledger.json  > ledger.json")
    ledger = json.load(sys.stdin)
    with connect() as conn:
        out = sync(conn, ledger)
        lost = orphaned(conn)
    hidden = len(ledger) - len(out)
    print(f"db: imported {len(ledger)} rows, {hidden} excluded by overrides", file=sys.stderr)
    for d, amt, *_ in lost:
        print(f"db: orphaned override {d} {amt} (no matching transaction; see `db/edit.py list --orphaned`)",
              file=sys.stderr)
    json.dump(out, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
