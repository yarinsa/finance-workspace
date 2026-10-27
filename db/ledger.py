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

from finance import categories as taxonomy
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
              t.get("source_category"), ids.get(t.get("category")), t.get("origin"), t.get("sources") or [], i,
              Jsonb(t), horizon_ids.get(t.get("horizon")))
             for i, t in enumerate(ledger)])


def seed_categories(cur, ledger):
    """Sync the taxonomy, add any other category the digest assigned (a source label
    nobody mapped yet, kept as "riseup"); returns {name: id} for all."""
    sync_taxonomy(cur)
    names = sorted({c for t in ledger if (c := t.get("category"))} - set(taxonomy.CATEGORY_GROUP))
    cur.executemany("INSERT INTO categories (name, source) VALUES (%s, 'riseup') "
                    "ON CONFLICT (name) DO NOTHING", [(n,) for n in names])
    return dict(cur.execute("SELECT name, id FROM categories").fetchall())


def sync_taxonomy(cur):
    """Make `category_groups` and the builtin `categories` match finance/categories.py.

    Upserts groups by key and categories by name (group, default kind, usage_based,
    position; source becomes "builtin", so a same-named "user" or "riseup" row is
    adopted). A legacy row whose name is now an alias (e.g. "עמלת דמי כרטיס - בנקים"
    -> עמלות) has its overrides and merchant rules moved to the target, then goes;
    an alias to nothing ("תשלומים") goes only when nothing human points at it."""
    cur.executemany(
        "INSERT INTO category_groups (key, name, position) VALUES (%s, %s, %s) "
        "ON CONFLICT (key) DO UPDATE SET name = EXCLUDED.name, position = EXCLUDED.position",
        [(k, n, i) for i, (k, n) in enumerate(taxonomy.GROUPS)])
    groups = dict(cur.execute("SELECT key, id FROM category_groups").fetchall())
    cur.executemany(
        "INSERT INTO categories (name, source, group_id, kind, usage_based, position) "
        "VALUES (%s, 'builtin', %s, %s, %s, %s) ON CONFLICT (name) DO UPDATE SET source = 'builtin', "
        "group_id = EXCLUDED.group_id, kind = EXCLUDED.kind, usage_based = EXCLUDED.usage_based, "
        "position = EXCLUDED.position",
        [(n, groups[g], k, n in taxonomy.USAGE_BASED, i) for i, (n, g, k) in enumerate(taxonomy.CATEGORIES)])
    aliases = {**taxonomy.SOURCE_ALIASES, **taxonomy.TRACKING_ALIASES}
    for old, new in aliases.items():
        if old in taxonomy.CATEGORY_GROUP:
            continue
        if new is not None:
            for table in ("transaction_overrides", "merchant_rules"):
                cur.execute(f"UPDATE {table} SET category_id = (SELECT id FROM categories WHERE name = %s) "
                            "WHERE category_id = (SELECT id FROM categories WHERE name = %s)", (new, old))
        cur.execute("DELETE FROM categories c WHERE name = %s AND source <> 'builtin' "
                    "AND NOT EXISTS (SELECT 1 FROM transaction_overrides o WHERE o.category_id = c.id) "
                    "AND NOT EXISTS (SELECT 1 FROM merchant_rules r WHERE r.category_id = c.id)", (old,))


def materialize(conn):
    """The `transactions` view as ledger rows, in the digested ledger's order.

    A payback the user made a קיזוז decision on carries it as `manual_offsets`
    (`[]` = "offsets nothing"); finance/offsets.py resolves them against auto."""
    rows = [r[0] for r in conn.execute("SELECT record FROM transactions ORDER BY position").fetchall()]
    links = manual_offsets(conn)
    for t in rows:
        k = key(t["date"], t["amount"])
        if k in links:
            t["manual_offsets"] = links[k]
    return rows


def manual_offsets(conn):
    """{payback ledger key: [OffsetLink dict, ...]} from `transaction_offsets`."""
    out = {}
    for pd, pa, ed, ea, amount in conn.execute(
            "SELECT payback_date, payback_abs_amount, expense_date, expense_abs_amount, amount "
            "FROM transaction_offsets ORDER BY id"):
        links = out.setdefault((pd.isoformat(), Decimal(pa)), [])
        if ed is not None:
            links.append({"date": ed.isoformat(), "abs_amount": float(ea), "amount": float(amount),
                          "kind": "manual"})
    return out


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
    if sys.argv[1:] == ["merges"]:
        from overrides import category_merges
        with connect() as conn:
            json.dump(category_merges(conn), sys.stdout, ensure_ascii=False)
        return
    if sys.argv[1:] != ["sync"]:
        raise SystemExit("usage: ledger.py sync  < ledger.json  > ledger.json\n       ledger.py migrate\n"
                         "       ledger.py merges   (merged categories as {name: into})")
    ledger = json.load(sys.stdin)
    with connect() as conn:
        out = sync(conn, ledger)
        lost = orphaned(conn)
        lost_offsets = conn.execute(
            "SELECT payback_date, payback_abs_amount, expense_date, expense_abs_amount "
            "FROM orphaned_offsets ORDER BY payback_date DESC").fetchall()
    hidden = len(ledger) - len(out)
    print(f"db: imported {len(ledger)} rows, {hidden} excluded by overrides", file=sys.stderr)
    for d, amt, *_ in lost:
        print(f"db: orphaned override {d} {amt} (no matching transaction; see `db/edit.py list --orphaned`)",
              file=sys.stderr)
    for pd, pa, ed, ea in lost_offsets:
        print(f"db: orphaned offset {pd} {pa} -> {ed} {ea} (a linked transaction is gone)", file=sys.stderr)
    json.dump(out, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
