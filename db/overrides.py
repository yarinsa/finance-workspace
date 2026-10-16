"""The human layer of the ledger: read and write `transaction_overrides`.

One code path for every writer. `db/edit.py` (actor "cli") and the ledger API
(actor = the verified email) both call these functions, so a change is audited and
pruned the same way whoever makes it.

A transaction is addressed by its ledger key `(date, abs_amount)`; see
`ledger.key`. Every function takes an open psycopg connection and leaves committing
to the caller (the writes themselves are atomic).

A "row" here is the JSON shape in docs/ledger-api.md: the scraped transaction with
its override applied, including rows an override has hidden (`excluded: true`).
"""
from decimal import Decimal

from psycopg.types.json import Jsonb

FIELDS = ("category", "note", "excluded", "horizon", "goal_id")
HORIZONS = ("current", "near", "future")   # data/horizons.py; the `horizons` table's keys
BLANK = {"category": None, "note": None, "excluded": False, "horizon": None, "goal_id": None}

ROW_SELECT = """
SELECT s.txn_date, s.abs_amount, s.amount, s.description,
       c.name                           AS category,
       sc.name                          AS scraped_category,
       o.note,
       COALESCE(o.excluded, false)      AS excluded,
       o.txn_date IS NOT NULL           AS overridden,
       s.origin, s.sources,
       COALESCE(h.key, s.record->>'horizon') AS horizon,
       s.record->>'horizon'             AS scraped_horizon,
       g.id                             AS goal_id,
       g.description                    AS goal,
       (SELECT array_agg(t.name ORDER BY t.name) FROM transaction_tags tt JOIN tags t ON t.id = tt.tag_id
        WHERE (tt.txn_date, tt.abs_amount) = (s.txn_date, s.abs_amount)) AS tags
FROM scraped_transactions s
LEFT JOIN transaction_overrides o USING (txn_date, abs_amount)
LEFT JOIN categories sc ON sc.id = s.category_id
LEFT JOIN categories c  ON c.id = COALESCE(o.category_id, s.category_id)
LEFT JOIN horizons h    ON h.id = COALESCE(o.horizon_id, s.horizon_id)
LEFT JOIN goals g       ON g.id = o.goal_id
"""


def _row(r):
    (date, abs_amount, amount, description, category, scraped, note, excluded, overridden, origin, sources,
     horizon, scraped_horizon, goal_id, goal, tags) = r
    return {"date": date.isoformat(), "abs_amount": f"{Decimal(abs_amount):.2f}",
            "amount": float(amount), "description": description, "category": category,
            "scraped_category": scraped, "note": note, "excluded": excluded,
            "overridden": overridden, "origin": origin, "sources": list(sources or []),
            "horizon": horizon, "scraped_horizon": scraped_horizon,
            "goal_id": goal_id, "goal": goal, "tags": list(tags or [])}


def get_row(conn, k):
    """The row for key `k` with its override applied, or None if no scraped transaction has it."""
    r = conn.execute(ROW_SELECT + "WHERE (s.txn_date, s.abs_amount) = (%s, %s)", k).fetchone()
    return _row(r) if r else None


def list_rows(conn, date_from=None, date_to=None, excluded="hide"):
    """Rows in the digested ledger's order. `excluded`: "hide" (default), "include" or "only"."""
    if excluded not in ("hide", "include", "only"):
        raise ValueError(f"excluded must be hide, include or only, not {excluded!r}")
    where, params = [], []
    if date_from:
        where.append("s.txn_date >= %s")
        params.append(date_from)
    if date_to:
        where.append("s.txn_date <= %s")
        params.append(date_to)
    if excluded == "hide":
        where.append("NOT COALESCE(o.excluded, false)")
    elif excluded == "only":
        where.append("COALESCE(o.excluded, false)")
    query = ROW_SELECT + (f"WHERE {' AND '.join(where)} " if where else "") + "ORDER BY s.position"
    return [_row(r) for r in conn.execute(query, params).fetchall()]


def get_override(conn, k):
    """The stored override as {category, note, excluded, horizon, goal_id}, or None."""
    r = conn.execute("SELECT c.name, o.note, o.excluded, h.key, o.goal_id FROM transaction_overrides o "
                     "LEFT JOIN categories c ON c.id = o.category_id "
                     "LEFT JOIN horizons h ON h.id = o.horizon_id "
                     "WHERE (o.txn_date, o.abs_amount) = (%s, %s)", k).fetchone()
    return dict(zip(FIELDS, r)) if r else None


def _audit(conn, actor, k, field, old, new):
    conn.execute("INSERT INTO override_audit (actor, txn_date, abs_amount, field, old, new) "
                 "VALUES (%s, %s, %s, %s, %s, %s)", (actor, *k, field, Jsonb(old), Jsonb(new)))


def patch(conn, k, changes, actor):
    """Apply `changes` ({category|note|excluded|horizon|goal_id: value}) to the override for `k`.

    A None value clears that field (for `excluded`, back to false). Fields whose value
    does not change write nothing. Each real change writes an `override_audit` row with
    the old and new value. An override left with nothing in it is deleted. Returns the
    row afterwards (None if no scraped transaction has this key, e.g. an orphan)."""
    unknown = set(changes) - set(FIELDS)
    if unknown:
        raise ValueError(f"unknown override fields: {sorted(unknown)}")
    if changes.get("horizon") not in (None, *HORIZONS):
        raise ValueError(f"horizon must be one of {HORIZONS}, not {changes['horizon']!r}")
    goal = changes.get("goal_id")
    if goal is not None and not conn.execute("SELECT 1 FROM goals WHERE id = %s", (goal,)).fetchone():
        raise ValueError(f"no goal with id {goal}")
    with conn.transaction():
        before = get_override(conn, k) or dict(BLANK)
        after = dict(before)
        for field, value in changes.items():
            after[field] = False if field == "excluded" and value is None else value
        diff = [f for f in FIELDS if before[f] != after[f]]
        if diff:
            conn.execute(
                """INSERT INTO transaction_overrides
                       (txn_date, abs_amount, category_id, note, excluded, horizon_id, goal_id)
                   VALUES (%s, %s, %s, %s, %s, (SELECT id FROM horizons WHERE key = %s), %s)
                   ON CONFLICT (txn_date, abs_amount)
                   DO UPDATE SET category_id = EXCLUDED.category_id, note = EXCLUDED.note,
                                 excluded = EXCLUDED.excluded, horizon_id = EXCLUDED.horizon_id,
                                 goal_id = EXCLUDED.goal_id, updated_at = now()""",
                (*k, category_id(conn, after["category"]), after["note"], after["excluded"], after["horizon"],
                 after["goal_id"]))
            for field in diff:
                _audit(conn, actor, k, field, before[field], after[field])
            _prune(conn, k)
    return get_row(conn, k)


def _prune(conn, k):
    """An override with nothing left in it is deleted rather than kept empty."""
    conn.execute("DELETE FROM transaction_overrides WHERE (txn_date, abs_amount) = (%s, %s) "
                 "AND category_id IS NULL AND note IS NULL AND NOT excluded "
                 "AND horizon_id IS NULL AND goal_id IS NULL", k)


def reset(conn, k, actor):
    """Drop the whole override for `k`, auditing each field that was set. Returns the row."""
    with conn.transaction():
        before = get_override(conn, k)
        if before:
            conn.execute("DELETE FROM transaction_overrides WHERE (txn_date, abs_amount) = (%s, %s)", k)
            for field in FIELDS:
                if before[field] != BLANK[field]:
                    _audit(conn, actor, k, field, before[field], BLANK[field])
    return get_row(conn, k)


def category_id(conn, name):
    """The id of category `name`, adding it as a "user" category if new. None for None."""
    if name is None:
        return None
    conn.execute("INSERT INTO categories (name, source) VALUES (%s, 'user') ON CONFLICT (name) DO NOTHING",
                 (name,))
    return conn.execute("SELECT id FROM categories WHERE name = %s", (name,)).fetchone()[0]


def categories(conn):
    """Every category in the `categories` table, by name."""
    return [r[0] for r in conn.execute("SELECT name FROM categories ORDER BY name").fetchall()]


def orphaned(conn):
    """Overrides whose transaction no longer exists, newest first."""
    rows = conn.execute("SELECT txn_date, abs_amount, category, note, excluded, horizon FROM orphaned_overrides "
                        "ORDER BY txn_date DESC, abs_amount").fetchall()
    return [{"date": d.isoformat(), "abs_amount": f"{Decimal(a):.2f}", "category": c, "note": n,
             "excluded": e, "horizon": h} for d, a, c, n, e, h in rows]


def audit_log(conn, limit=50):
    """The most recent audit entries, newest first."""
    rows = conn.execute("SELECT at, actor, txn_date, abs_amount, field, old, new FROM override_audit "
                        "ORDER BY id DESC LIMIT %s", (limit,)).fetchall()
    return [{"at": at.isoformat(), "actor": actor, "date": d.isoformat() if d else None,
             "abs_amount": f"{Decimal(a):.2f}" if a is not None else None, "field": f, "old": o, "new": n}
            for at, actor, d, a, f, o, n in rows]
