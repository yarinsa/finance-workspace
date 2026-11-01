#!/usr/bin/env python3
"""The transactions database: import the digested ledger, apply overrides.

    scraped_transactions   machine layer, replaced in full on each import
    accounts, credit_cards, loans, savings_holdings, source_dumps(+_entities)
                           the position's machine layer, replaced in the same transaction
    digest_runs            one row per import; the newest is the data's as-of time
    transaction_overrides  human layer (category / note / excluded), kept forever
    transactions           view: the ledger with overrides applied

`python3 db/ledger.py migrate` only applies migrations. `python3 db/ledger.py sync` is how data/digest.py uses it:
`{"ledger", "position", "dumps", "run"}` arrives as JSON on stdin (a bare ledger list is
still accepted), is imported in one transaction, and the `transactions` view comes back on
stdout in the ledger's order. Rows are keyed on the ledger's dedup key, (date, abs(amount)).
"""
import json
import uuid
import os
import re
import sys
from decimal import Decimal
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from finance import categories as taxonomy
from finance.models import (AccountFields, BalanceDayFields, CreditCardFields, LedgerTransaction, LoanFields, SavingsFields,
                            holding_id)
from finance.tenancy import resolve_tenant_id, scope_connection, use_cli_tenant

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


def connect_admin(url=None):
    """Open a privileged connection (owner role, bypasses RLS) and migrate the schema to head.

    Only for migrations and `db/tenants.py`. Everything that reads or writes customer data
    uses `connect`, which is tenant-scoped."""
    url = url or database_url()
    if not url:
        raise SystemExit("DATABASE_URL is not set (env or .env)")
    migrate(url)
    conn = psycopg.connect(url)
    password = env_value("FINANCE_API_DB_PASSWORD")
    if password:
        set_api_role_password(conn, password)
    return conn


def scope(conn, tenant_id):
    """Drop `conn` to the RLS-bound role `finance_app` and pin it to `tenant_id` for the session.

    The owner role bypasses RLS, so a host job takes `finance_app` (no BYPASSRLS, owns nothing)
    right after connecting. Committed here, so a later rollback cannot undo it."""
    return scope_connection(conn, tenant_id)


def connect(url=None, tenant_id=None):
    """A connection scoped to one tenant (finance/tenancy.py `resolve_tenant_id`), schema at head.

    Row-Level Security applies: queries see and write only that tenant's rows. Raises
    TenantContextMissing when no tenant is given or bound."""
    tenant_id = resolve_tenant_id(tenant_id)
    return scope(connect_admin(url), tenant_id)


def key(date, amount):
    """The ledger's dedup key as it is stored: (date, abs amount to the agora)."""
    return date, round(abs(Decimal(str(amount))), 2)


def load(conn, ledger, position=None, dumps=None, run=None):
    """Replace scraped_transactions with this ledger, and (when given) the position's tables
    with `position` (finance/views/snapshot.reconcile) and source_dumps with `dumps`
    (digest.source_syncs), all in one transaction. `run` ({started_at, normalized}) records
    the import in digest_runs. Overrides are untouched.

    Every row is validated as a LedgerTransaction first, so the jsonb `record`
    always has the shape finance/models.py declares."""
    ledger = [LedgerTransaction.model_validate(t).model_dump(mode="json", exclude_unset=True)
              for t in ledger]
    with conn.transaction(), conn.cursor() as cur:
        if position is not None:
            load_position(cur, position)
        if dumps is not None:
            load_dumps(cur, dumps)
        if run is not None:
            cur.execute("INSERT INTO digest_runs (started_at, normalized, transactions) VALUES (%s, %s, %s)",
                        (run["started_at"], run["normalized"], len(ledger)))
        ids = seed_categories(cur, ledger)
        horizon_ids = dict(cur.execute("SELECT key, id FROM horizons").fetchall())
        cur.execute("DELETE FROM scraped_transactions")   # RLS: this tenant's rows only
        cur.executemany(
            """INSERT INTO scraped_transactions
                   (txn_date, abs_amount, amount, description, category, category_id, origin,
                    sources, position, record, horizon_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            [(*key(t["date"], t["amount"]), t["amount"], t.get("description") or "",
              t.get("source_category"), ids.get(t.get("category")), t.get("origin"), t.get("sources") or [], i,
              Jsonb(t), horizon_ids.get(t.get("horizon")))
             for i, t in enumerate(ledger)])


def _replace(cur, table, rows):
    """Delete this tenant's rows of `table` (RLS) and insert `rows` (dicts with the same keys)."""
    cur.execute(f"DELETE FROM {table}")
    if rows:
        cols = list(rows[0])
        cur.executemany(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
                        [[r[c] for c in cols] for r in rows])


def _fields(model, record, **extra):
    """`record` through the entity's field list: every declared column, typed (Money -> Decimal)."""
    return {**model.model_validate(record).model_dump(), **extra}


def load_position(cur, position):
    """The reconciled accounts, cards, loans and savings, each validated through its `*Fields`."""
    _replace(cur, "accounts", [_fields(AccountFields, a) for a in position["bank_accounts"]])
    _replace(cur, "credit_cards", [_fields(CreditCardFields, c, next_charge_date=c.get("next_charge_date"))
                                   for c in position["credit_cards"]])
    _replace(cur, "loans", [_fields(LoanFields, l, position=i) for i, l in enumerate(position["loans"])])
    _replace(cur, "savings_holdings", [_fields(SavingsFields, s, holding_id=holding_id(s))
                                       for s in position["savings"]])
    _replace(cur, "account_balance_days", [_fields(BalanceDayFields, b) for b in position.get("balance_days", [])])


def load_dumps(cur, dumps):
    """Each source's latest dump (digest.source_syncs) and its per-entity record counts."""
    cur.execute("DELETE FROM source_dump_entities")
    _replace(cur, "source_dumps", [{"source": d["source"], "dumped_at": d["last_synced"],
                                    "raw_files": d["raw_files"], "latest_txn_date": d.get("latest_txn_date")}
                                   for d in dumps])
    _replace(cur, "source_dump_entities", [{"source": d["source"], "entity": e, "records": n}
                                           for d in dumps for e, n in d.get("entities", {}).items()])


def seed_categories(cur, ledger):
    """Sync the taxonomy, add any other category the digest assigned (a source label
    nobody mapped yet, kept as "riseup"); returns {name: id} for all."""
    sync_taxonomy(cur)
    names = sorted({c for t in ledger if (c := t.get("category"))} - set(taxonomy.CATEGORY_GROUP))
    cur.executemany("INSERT INTO categories (name, source) VALUES (%s, 'riseup') "
                    "ON CONFLICT (tenant_id, name) DO NOTHING", [(n,) for n in names])
    return dict(cur.execute("SELECT name, id FROM categories").fetchall())


def sync_taxonomy(cur):
    """Make `category_groups` and the builtin `categories` match finance/categories.py.

    Upserts groups by key and categories by name (group, default kind, usage_based,
    position; source becomes "builtin", so a same-named "user" or "riseup" row is
    adopted). A legacy row whose name is now an alias (e.g. "עמלת דמי כרטיס - בנקים"
    -> עמלות, or a dropped builtin like רכב -> תחבורה) has its overrides and merchant rules
    moved to the target, then goes;
    an alias to nothing ("תשלומים") goes only when nothing human points at it."""
    cur.executemany(
        "INSERT INTO category_groups (key, name, position) VALUES (%s, %s, %s) "
        "ON CONFLICT (key) DO UPDATE SET name = EXCLUDED.name, position = EXCLUDED.position",
        [(k, n, i) for i, (k, n) in enumerate(taxonomy.GROUPS)])
    groups = dict(cur.execute("SELECT key, id FROM category_groups").fetchall())
    # a builtin category dropped from the taxonomy (רכב, folded into תחבורה) is a legacy row now
    cur.execute("UPDATE categories SET source = 'riseup' WHERE source = 'builtin' AND NOT (name = ANY(%s))",
                ([n for n, _, _ in taxonomy.CATEGORIES],))
    cur.executemany(
        "INSERT INTO categories (name, source, group_id, kind, usage_based, position) "
        "VALUES (%s, 'builtin', %s, %s, %s, %s) ON CONFLICT (tenant_id, name) DO UPDATE SET source = 'builtin', "
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


def sync(conn, ledger, position=None, dumps=None, run=None):
    """Import the ledger (and the position, see `load`) and return it with overrides applied."""
    load(conn, ledger, position, dumps, run)
    return materialize(conn)


def main():
    use_cli_tenant()
    if sys.argv[1:] == ["migrate"]:
        connect_admin().close()   # upgrade head, and set the finance_api login password if configured
        print("db: schema is at head", file=sys.stderr)
        return
    if sys.argv[1:] == ["merges"]:
        from overrides import category_merges
        with connect() as conn:
            json.dump(category_merges(conn), sys.stdout, ensure_ascii=False)
        return
    if sys.argv[1:] != ["sync"]:
        raise SystemExit("usage: ledger.py sync  < digest.json  > ledger.json\n       ledger.py migrate\n"
                         "       ledger.py merges   (merged categories as {name: into})")
    payload = json.load(sys.stdin)
    if isinstance(payload, list):
        payload = {"ledger": payload}
    ledger = payload["ledger"]
    with connect() as conn:
        out = sync(conn, ledger, payload.get("position"), payload.get("dumps"), payload.get("run"))
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
