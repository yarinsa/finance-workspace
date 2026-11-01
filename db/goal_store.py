"""Horizons, goals and the three general targets, through the ORM entities in finance/tables.py
(`Horizon`, `Goal`).

Shared by data/goals.py, data/horizons.py and the ledger API: every function takes an
open psycopg connection, works on it through `ledger.orm_session`, and commits writes.
Horizons are a fixed list (seeded by migration 0006) addressed by `key`; goals are
user rows, each optionally assigned to a horizon. The three general targets
(emergency_fund_target, inheritance_target, retirement_target) are the household's default
goals: rows of `goals` with a `key`, one per target that was ever decided; unset (None or 0)
is a row of 0, while no row means not decided yet (the JSON store still applies). `all_goals`
lists the personal goals only; the defaults are read and written through the targets functions.

    .venv/bin/python db/goal_store.py list
    .venv/bin/python db/goal_store.py import [data/goals/goals.json]   # one-time move from the JSON store
    .venv/bin/python db/goal_store.py targets                          # the three general targets
    .venv/bin/python db/goal_store.py horizon SLUG current|near|future|none
"""
import datetime as dt
import json
import re
import sys
from decimal import Decimal
from pathlib import Path

from sqlmodel import col, delete, func, select

from finance.tables import Goal, Horizon, TransactionOverride
from ledger import orm_session

STORE = Path(__file__).resolve().parent.parent / "data" / "goals" / "goals.json"
TARGET_KEYS = ("emergency_fund_target", "inheritance_target", "retirement_target")
DEFAULT_NAMES = {"emergency_fund": "קרן חירום", "inheritance": "הורשה", "retirement": "פרישה"}
EDITABLE = ("description", "amount", "start_date", "end_date", "interval", "repetitions", "rise",
            "from_asset_id", "horizon")


def _horizon(h):
    return {"id": h.id, "key": h.key, "name": h.name, "target_pct": float(h.target_pct), "position": h.position}


def _goal(g, spent=0):
    return {"id": g.id, "slug": g.slug, "description": g.description, "amount": float(g.amount),
            "start_date": g.start_date.isoformat() if g.start_date else None,
            "end_date": g.end_date.isoformat() if g.end_date else None,
            "interval": g.interval, "repetitions": g.repetitions, "rise": float(g.rise),
            "from_asset_id": g.from_asset_id,
            "horizon": g.horizon_ref.key if g.horizon_ref else None,
            "transactions": spent}


def horizons(conn):
    """The horizons in order: [{id, key, name, target_pct, position}]."""
    with orm_session(conn) as s:
        return [_horizon(h) for h in s.exec(select(Horizon).order_by(Horizon.position)).all()]


def all_goals(conn):
    """Every personal goal with its horizon key and the number of transactions assigned to it."""
    with orm_session(conn) as s:
        counts = dict(s.exec(select(TransactionOverride.goal_id, func.count())
                             .where(col(TransactionOverride.goal_id).is_not(None))
                             .group_by(TransactionOverride.goal_id)).all())
        goals = s.exec(select(Goal).where(col(Goal.key).is_(None)).order_by(Goal.end_date, Goal.id)).all()
        return [_goal(g, counts.get(g.id, 0)) for g in goals]


def get_goal(conn, goal_id):
    return next((g for g in all_goals(conn) if g["id"] == goal_id), None)


def _horizon_id(s, key):
    if key is None:
        return None
    h = s.exec(select(Horizon).where(Horizon.key == key)).first()
    if not h:
        raise ValueError(f"no horizon {key!r}")
    return h.id


def _slug(s, description):
    base = re.sub(r"[^\w]+", "-", description.strip().lower()).strip("-")[:30] or "goal"
    slug, n = base, 1
    while s.exec(select(Goal).where(Goal.slug == slug)).first():
        n += 1
        slug = f"{base}-{n}"
    return slug


def _apply(g, s, fields):
    for k, v in fields.items():
        if k not in EDITABLE:
            raise ValueError(f"unknown goal field {k!r}")
        if k == "horizon":
            g.horizon_id = _horizon_id(s, v)
        elif k in ("start_date", "end_date"):
            setattr(g, k, dt.date.fromisoformat(v) if isinstance(v, str) else v)
        elif k in ("amount", "rise"):
            setattr(g, k, Decimal(str(v or 0)))
        else:
            setattr(g, k, v)


def create_goal(conn, description, amount, slug=None, **fields):
    """Add a goal; returns it. `slug` defaults to one derived from the description."""
    with orm_session(conn) as s:
        g = Goal(slug=slug or _slug(s, description), description=description, amount=Decimal(str(amount)))
        _apply(g, s, fields)
        s.add(g)
        s.commit()
        s.refresh(g)
        return _goal(g)


def update_goal(conn, goal_id, **fields):
    """Change a goal's fields (`horizon` by key, None to unassign); returns it, or None if missing."""
    with orm_session(conn) as s:
        g = s.get(Goal, goal_id)
        if not g:
            return None
        _apply(g, s, fields)
        s.commit()
        s.refresh(g)
    return get_goal(conn, goal_id)


def delete_goal(conn, goal_id):
    """Delete a goal; False if it did not exist. Transactions assigned to it are unassigned,
    and an override left with nothing in it is deleted (as db/overrides.py prunes).

    Raises ValueError for a default goal (the general targets are unset, not deleted)."""
    with orm_session(conn) as s:
        g = s.get(Goal, goal_id)
        if not g:
            return False
        if g.key:
            raise ValueError(f"{g.key!r} is a default goal and cannot be deleted")
        s.delete(g)
        s.flush()
        s.exec(delete(TransactionOverride).where(
            col(TransactionOverride.category_id).is_(None), col(TransactionOverride.note).is_(None),
            col(TransactionOverride.excluded).is_(False), col(TransactionOverride.horizon_id).is_(None),
            col(TransactionOverride.goal_id).is_(None)))
        s.commit()
        return True


def stored_targets(conn):
    """Only the targets that have a row: {"emergency_fund_target": float, ...}, 0 included.

    A missing row means "never decided" (the JSON store may still hold a value); a row with
    amount 0 means "deliberately unset"."""
    with orm_session(conn) as s:
        have = {g.key: float(g.amount) for g in s.exec(select(Goal).where(col(Goal.key).is_not(None))).all()}
    return {k: have[k.removesuffix("_target")] for k in TARGET_KEYS if k.removesuffix("_target") in have}


def get_targets(conn):
    """The general targets: {"emergency_fund_target": float|None, ...}; None = unset
    (a 0 row and a missing row both read as unset)."""
    have = stored_targets(conn)
    return {k: have.get(k) or None for k in TARGET_KEYS}


def set_targets(conn, **fields):
    """Set any subset of the targets; None or 0 unsets (upserts a row of 0). Returns `get_targets`.

    Raises ValueError for an unknown key or a negative amount, before writing anything."""
    for k, v in fields.items():
        if k not in TARGET_KEYS:
            raise ValueError(f"unknown target {k!r}")
        if v is not None and Decimal(str(v)) < 0:
            raise ValueError(f"{k} cannot be negative")
    with orm_session(conn) as s:
        for k, v in fields.items():
            key, amount = k.removesuffix("_target"), Decimal(str(v or 0))
            row = s.exec(select(Goal).where(Goal.key == key)).first()   # RLS: this tenant's row
            if row:
                row.amount = amount
            else:
                s.add(Goal(key=key, slug=f"default-{key}", description=DEFAULT_NAMES[key], amount=amount))
        s.commit()
    return get_targets(conn)


def import_json(conn, path=STORE):
    """Copy the `goals` list and the three targets of the JSON store into the database;
    existing slugs and targets that already have a row (even a 0 one) are left alone.

    Returns the number of goals added."""
    store = json.loads(Path(path).read_text(encoding="utf-8"))
    have = stored_targets(conn)
    set_targets(conn, **{k: store[k] for k in TARGET_KEYS if k not in have and store.get(k) is not None})
    added = 0
    with orm_session(conn) as s:
        have = set(s.exec(select(Goal.slug)).all())
        for r in store.get("goals", []):
            if r["id"] in have:
                continue
            g = Goal(slug=r["id"], description=r["description"], amount=Decimal(str(r["amount"])))
            _apply(g, s, {k: r.get(k) for k in ("start_date", "end_date", "interval", "from_asset_id")})
            g.repetitions = r.get("repetitions") or 1
            g.rise = Decimal(str(r.get("rise") or 0))
            g.horizon_id = _horizon_id(s, r.get("horizon") or "near")
            s.add(g)
            added += 1
        s.commit()
    return added


def main(argv):
    from ledger import connect
    from finance.tenancy import use_cli_tenant
    use_cli_tenant()
    cmd, *rest = argv or ["list"]
    with connect() as conn:
        if cmd == "list":
            for g in all_goals(conn):
                print(f"{g['slug']:<24} ₪{g['amount']:>10,.0f}  {g['end_date'] or '-':<10}  "
                      f"{g['horizon'] or '-':<8} {g['transactions']} tx  {g['description']}")
        elif cmd == "import":
            print(f"imported {import_json(conn, rest[0] if rest else STORE)} goal(s)")
        elif cmd == "targets":
            for k, v in get_targets(conn).items():
                print(f"{k:<22} {'-' if v is None else f'₪{v:,.0f}'}")
        elif cmd == "horizon" and len(rest) == 2:
            gid = conn.execute("SELECT id FROM goals WHERE slug = %s", (rest[0],)).fetchone()
            if not gid:
                raise SystemExit(f"no goal {rest[0]!r}")
            update_goal(conn, gid[0], horizon=None if rest[1] == "none" else rest[1])
            print(get_goal(conn, gid[0]))
        else:
            raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
