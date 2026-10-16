#!/usr/bin/env python3
"""The transactions database: import the digested ledger, apply overrides.

    scraped_transactions   machine layer, replaced in full on each import
    transaction_overrides  human layer (category / note / excluded), kept forever
    transactions           view: the ledger with overrides applied

`python3 db/ledger.py migrate` only applies migrations. `python3 db/ledger.py sync` is how data/digest.py uses it: the consolidated
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
from psycopg import sql
from psycopg.types.json import Jsonb

from finance.models import LedgerTransaction

REPO = Path(__file__).resolve().parent.parent
ALEMBIC_INI = Path(__file__).resolve().parent / "alembic.ini"


def env_value(name, env_file=REPO / ".env"):
    """`name` from the environment, else from .env (read literally, no ${...} expansion)."""
    value = os.environ.get(name)
    if value:
        return value
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip().strip("'\"") or None
    return None


def database_url(env_file=REPO / ".env"):
    """DATABASE_URL from the environment, else from .env (read literally)."""
    return env_value("DATABASE_URL", env_file)


def set_api_role_password(conn, password):
    """Let the `finance_api` role log in (the migration creates it NOLOGIN).

    DDL cannot take bind parameters, so the password goes in as a quoted literal."""
    conn.execute(sql.SQL("ALTER ROLE finance_api LOGIN PASSWORD {}").format(sql.Literal(password)))
    conn.commit()


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


def orm_session(conn):
    """A SQLAlchemy ORM `Session` on this open psycopg connection (finance/tables.py entities).

    Shares the connection, its role and its transaction: `session.commit()` commits `conn`.
    Closing the session never closes `conn`, and never rolls it back: SQLAlchemy would
    otherwise roll back on first connect and on close, dropping uncommitted psycopg writes
    made earlier on `conn`. Rolling back on error stays with whoever owns `conn`."""
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool
    from sqlmodel import Session
    engine = create_engine("postgresql+psycopg://", creator=lambda: conn, poolclass=StaticPool,
                           pool_reset_on_return=None)
    engine.dialect.do_rollback = lambda dbapi_conn: None
    return Session(engine, expire_on_commit=False)


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
    conn = psycopg.connect(url)
    password = env_value("FINANCE_API_DB_PASSWORD")
    if password:
        set_api_role_password(conn, password)
    return conn


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
        ids = seed_categories(cur, ledger)
        horizon_ids = dict(cur.execute("SELECT key, id FROM horizons").fetchall())
        cur.execute("TRUNCATE scraped_transactions")
        cur.executemany(
            """INSERT INTO scraped_transactions
                   (txn_date, abs_amount, amount, description, category, category_id, origin,
                    sources, position, record, horizon_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            [(*key(t["date"], t["amount"]), t["amount"], t.get("description") or "",
              t.get("category"), ids.get(riseup_category(t)), t.get("origin"), t.get("sources") or [], i,
              Jsonb(t), horizon_ids.get(t.get("horizon")))
             for i, t in enumerate(ledger)])


def riseup_category(t):
    """The row's category when RiseUp assigned it (RiseUp wins the merge), else None."""
    return t.get("category") or None if "riseup" in (t.get("sources") or []) else None


def seed_categories(cur, ledger):
    """Add every RiseUp category in the ledger to `categories`; returns {name: id} for all."""
    names = sorted({c for t in ledger if (c := riseup_category(t))})
    cur.executemany("INSERT INTO categories (name, source) VALUES (%s, 'riseup') "
                    "ON CONFLICT (name) DO NOTHING", [(n,) for n in names])
    return dict(cur.execute("SELECT name, id FROM categories").fetchall())


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
    if sys.argv[1:] == ["migrate"]:
        connect().close()   # upgrade head, and set the finance_api login password if configured
        print("db: schema is at head", file=sys.stderr)
        return
    if sys.argv[1:] != ["sync"]:
        raise SystemExit("usage: ledger.py sync  < ledger.json  > ledger.json\n       ledger.py migrate")
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
