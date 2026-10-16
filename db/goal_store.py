"""Horizons and goals, through the ORM entities in finance/tables.py (`Horizon`, `Goal`).

Shared by data/goals.py, data/horizons.py and the ledger API: every function takes an
open psycopg connection, works on it through `ledger.orm_session`, and commits writes.
Horizons are a fixed list (seeded by migration 0006) addressed by `key`; goals are
user rows, each optionally assigned to a horizon.

    .venv/bin/python db/goal_store.py list
    .venv/bin/python db/goal_store.py import [data/goals/goals.json]   # one-time move from the JSON store
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
    """Every goal with its horizon key and the number of transactions assigned to it."""
    with orm_session(conn) as s:
        counts = dict(s.exec(select(TransactionOverride.goal_id, func.count())
                             .where(col(TransactionOverride.goal_id).is_not(None))
                             .group_by(TransactionOverride.goal_id)).all())
        goals = s.exec(select(Goal).order_by(Goal.end_date, Goal.id)).all()
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
    and an override left with nothing in it is deleted (as db/overrides.py prunes)."""
    with orm_session(conn) as s:
        g = s.get(Goal, goal_id)
        if not g:
            return False
        s.delete(g)
        s.flush()
        s.exec(delete(TransactionOverride).where(
            col(TransactionOverride.category_id).is_(None), col(TransactionOverride.note).is_(None),
            col(TransactionOverride.excluded).is_(False), col(TransactionOverride.horizon_id).is_(None),
            col(TransactionOverride.goal_id).is_(None)))
        s.commit()
        return True


def import_json(conn, path=STORE):
    """Copy the `goals` list of the JSON store into the table; existing slugs are left alone.

    Returns the number of goals added."""
    store = json.loads(Path(path).read_text(encoding="utf-8"))
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
    cmd, *rest = argv or ["list"]
    with connect() as conn:
        if cmd == "list":
            for g in all_goals(conn):
                print(f"{g['slug']:<24} ₪{g['amount']:>10,.0f}  {g['end_date'] or '-':<10}  "
                      f"{g['horizon'] or '-':<8} {g['transactions']} tx  {g['description']}")
        elif cmd == "import":
            print(f"imported {import_json(conn, rest[0] if rest else STORE)} goal(s)")
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
