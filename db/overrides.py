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

FIELDS = ("category", "note", "excluded", "horizon", "goal_id", "kind")
HORIZONS = ("current", "near", "future")   # data/horizons.py; the `horizons` table's keys
KINDS = ("fixed", "variable")              # finance/categories.py: קבוע / משתנה
BLANK = {"category": None, "note": None, "excluded": False, "horizon": None, "goal_id": None, "kind": None}

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
        WHERE (tt.txn_date, tt.abs_amount) = (s.txn_date, s.abs_amount)) AS tags,
       tk.category_group, tk.kind, tk.kind_source, s.record->>'merchant' AS merchant
FROM scraped_transactions s
JOIN transaction_kinds tk USING (txn_date, abs_amount)
LEFT JOIN transaction_overrides o USING (txn_date, abs_amount)
LEFT JOIN categories sc ON sc.id = s.category_id
LEFT JOIN categories c  ON c.id = tk.category_id
LEFT JOIN horizons h    ON h.id = COALESCE(o.horizon_id, s.horizon_id)
LEFT JOIN goals g       ON g.id = o.goal_id
"""


def _row(r):
    (date, abs_amount, amount, description, category, scraped, note, excluded, overridden, origin, sources,
     horizon, scraped_horizon, goal_id, goal, tags, category_group, kind, kind_source, merchant) = r
    return {"date": date.isoformat(), "abs_amount": f"{Decimal(abs_amount):.2f}",
            "amount": float(amount), "description": description, "category": category,
            "scraped_category": scraped, "note": note, "excluded": excluded,
            "overridden": overridden, "origin": origin, "sources": list(sources or []),
            "horizon": horizon, "scraped_horizon": scraped_horizon,
            "goal_id": goal_id, "goal": goal, "tags": list(tags or []),
            "category_group": category_group, "kind": kind, "kind_source": kind_source, "merchant": merchant}


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
    """The stored override as {category, note, excluded, horizon, goal_id, kind}, or None."""
    r = conn.execute("SELECT c.name, o.note, o.excluded, h.key, o.goal_id, o.kind FROM transaction_overrides o "
                     "LEFT JOIN categories c ON c.id = o.category_id "
                     "LEFT JOIN horizons h ON h.id = o.horizon_id "
                     "WHERE (o.txn_date, o.abs_amount) = (%s, %s)", k).fetchone()
    return dict(zip(FIELDS, r)) if r else None


def _audit(conn, actor, k, field, old, new):
    conn.execute("INSERT INTO override_audit (actor, txn_date, abs_amount, field, old, new) "
                 "VALUES (%s, %s, %s, %s, %s, %s)", (actor, *k, field, Jsonb(old), Jsonb(new)))


def patch(conn, k, changes, actor):
    """Apply `changes` ({category|note|excluded|horizon|goal_id|kind: value}) to the override for `k`.

    A None value clears that field (for `excluded`, back to false). Fields whose value
    does not change write nothing. Each real change writes an `override_audit` row with
    the old and new value. An override left with nothing in it is deleted. Returns the
    row afterwards (None if no scraped transaction has this key, e.g. an orphan)."""
    unknown = set(changes) - set(FIELDS)
    if unknown:
        raise ValueError(f"unknown override fields: {sorted(unknown)}")
    if changes.get("horizon") not in (None, *HORIZONS):
        raise ValueError(f"horizon must be one of {HORIZONS}, not {changes['horizon']!r}")
    if changes.get("kind") not in (None, *KINDS):
        raise ValueError(f"kind must be one of {KINDS}, not {changes['kind']!r}")
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
                       (txn_date, abs_amount, category_id, note, excluded, horizon_id, goal_id, kind)
                   VALUES (%s, %s, %s, %s, %s, (SELECT id FROM horizons WHERE key = %s), %s, %s)
                   ON CONFLICT (tenant_id, txn_date, abs_amount)
                   DO UPDATE SET category_id = EXCLUDED.category_id, note = EXCLUDED.note,
                                 excluded = EXCLUDED.excluded, horizon_id = EXCLUDED.horizon_id,
                                 goal_id = EXCLUDED.goal_id, kind = EXCLUDED.kind, updated_at = now()""",
                (*k, category_id(conn, after["category"]), after["note"], after["excluded"], after["horizon"],
                 after["goal_id"], after["kind"]))
            for field in diff:
                _audit(conn, actor, k, field, before[field], after[field])
            _prune(conn, k)
    return get_row(conn, k)


def _prune(conn, k):
    """An override with nothing left in it is deleted rather than kept empty."""
    conn.execute("DELETE FROM transaction_overrides WHERE (txn_date, abs_amount) = (%s, %s) "
                 "AND category_id IS NULL AND note IS NULL AND NOT excluded "
                 "AND horizon_id IS NULL AND goal_id IS NULL AND kind IS NULL", k)


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
    conn.execute("INSERT INTO categories (name, source) VALUES (%s, 'user') ON CONFLICT (tenant_id, name) DO NOTHING",
                 (name,))
    return conn.execute("SELECT id FROM categories WHERE name = %s", (name,)).fetchone()[0]


def categories(conn):
    """Every category in the `categories` table, by name."""
    return [r[0] for r in conn.execute("SELECT name FROM categories ORDER BY name").fetchall()]


def category_tree(conn):
    """The taxonomy as [{key, name, categories: [{name, kind, usage_based}]}] in display
    order; categories with no group (unmapped source labels, user-typed) last, key None."""
    rows = conn.execute(
        "SELECT g.key, g.name, c.name, c.kind, c.usage_based FROM categories c "
        "LEFT JOIN category_groups g ON g.id = c.group_id "
        "ORDER BY g.position NULLS LAST, c.position, c.name").fetchall()
    out = []
    for gkey, gname, name, kind, usage in rows:
        if not out or out[-1]["key"] != gkey:
            out.append({"key": gkey, "name": gname, "categories": []})
        out[-1]["categories"].append({"name": name, "kind": kind, "usage_based": usage})
    return out


def merge_category(conn, name, into, actor):
    """Merge category `name` into `into` (None unmerges): its rows, overrides and merchant
    rules keep their category, and `transaction_kinds` counts them as `into`. One level:
    categories already merged into `name` move to `into` with it; `into` may not itself be
    merged. Audited as "category.merged_into:<name>". Returns the target's name or None."""
    with conn.transaction():
        row = conn.execute("SELECT c.id, t.name FROM categories c LEFT JOIN categories t "
                           "ON t.id = c.merged_into_id WHERE c.name = %s", (name,)).fetchone()
        if row is None:
            raise ValueError(f"no such category: {name}")
        cid, before = row
        target = None
        if into is not None:
            t = conn.execute("SELECT id, merged_into_id FROM categories WHERE name = %s", (into,)).fetchone()
            if t is None:
                raise ValueError(f"no such category: {into}")
            if t[0] == cid:
                raise ValueError("a category can't be merged into itself")
            if t[1] is not None:
                raise ValueError(f"{into} is itself merged into another category")
            target = t[0]
        if before == into:
            return before
        conn.execute("UPDATE categories SET merged_into_id = %s WHERE id = %s", (target, cid))
        if target is not None:
            conn.execute("UPDATE categories SET merged_into_id = %s WHERE merged_into_id = %s", (target, cid))
        conn.execute("INSERT INTO override_audit (actor, field, old, new) VALUES (%s, %s, %s, %s)",
                     (actor, f"category.merged_into:{name}", Jsonb(before), Jsonb(into)))
    return into


def category_merges(conn):
    """{merged category name: the category it counts as}."""
    return dict(conn.execute("SELECT c.name, t.name FROM categories c "
                             "JOIN categories t ON t.id = c.merged_into_id").fetchall())


RULE_FIELDS = ("category", "kind")


def get_merchant_rule(conn, merchant):
    """The rule for `merchant` as {category, kind}, or None."""
    r = conn.execute("SELECT c.name, r.kind FROM merchant_rules r LEFT JOIN categories c ON c.id = r.category_id "
                     "WHERE r.merchant = %s", (merchant,)).fetchone()
    return dict(zip(RULE_FIELDS, r)) if r else None


def set_merchant_rule(conn, merchant, changes, actor):
    """Apply `changes` ({category|kind: value, None clears}) to the rule for `merchant`
    (a finance/merchants.py key, as on the ledger row's `merchant`): every transaction of
    that merchant follows it unless it has its own override. Audited with no ledger key
    and the field as "merchant_rule.<field>:<merchant>"; an empty rule is deleted.
    Returns the rule afterwards (None when empty)."""
    unknown = set(changes) - set(RULE_FIELDS)
    if unknown:
        raise ValueError(f"unknown merchant rule fields: {sorted(unknown)}")
    if changes.get("kind") not in (None, *KINDS):
        raise ValueError(f"kind must be one of {KINDS}, not {changes['kind']!r}")
    with conn.transaction():
        before = get_merchant_rule(conn, merchant) or {"category": None, "kind": None}
        after = {**before, **changes}
        diff = [f for f in RULE_FIELDS if before[f] != after[f]]
        if diff:
            conn.execute(
                "INSERT INTO merchant_rules (merchant, category_id, kind) VALUES (%s, %s, %s) "
                "ON CONFLICT (tenant_id, merchant) DO UPDATE SET category_id = EXCLUDED.category_id, "
                "kind = EXCLUDED.kind, updated_at = now()",
                (merchant, category_id(conn, after["category"]), after["kind"]))
            for field in diff:
                conn.execute("INSERT INTO override_audit (actor, field, old, new) VALUES (%s, %s, %s, %s)",
                             (actor, f"merchant_rule.{field}:{merchant}", Jsonb(before[field]),
                              Jsonb(after[field])))
            conn.execute("DELETE FROM merchant_rules WHERE merchant = %s AND category_id IS NULL "
                         "AND kind IS NULL", (merchant,))
    return get_merchant_rule(conn, merchant)


def merchant_rules(conn):
    """Every merchant rule: [{merchant, category, kind, transactions}] by merchant."""
    rows = conn.execute(
        "SELECT r.merchant, c.name, r.kind, (SELECT count(*) FROM scraped_transactions s "
        "WHERE s.record->>'merchant' = r.merchant) FROM merchant_rules r "
        "LEFT JOIN categories c ON c.id = r.category_id ORDER BY r.merchant").fetchall()
    return [{"merchant": m, "category": c, "kind": k, "transactions": n} for m, c, k, n in rows]


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
