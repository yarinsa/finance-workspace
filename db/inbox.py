#!/usr/bin/env python3
"""The notifications inbox: the digest's "לטיפול" actions plus the household's state on them.

    python3 db/inbox.py sync < actions.json     (what data/cashflow.py does after a digest)

One code path for every writer, like db/overrides.py: the digest (`sync`) and the ledger
API (`update`, the bulk helpers, `select`) all go through here. Every function takes an
open psycopg connection and leaves committing to the caller; `now` is injectable so
visibility and snoozing are testable.

Two owners, never mixed. The digest owns the content columns and `resolved_at`: `sync`
upserts the current actions and stamps `resolved_at` on rows that dropped out of the list.
The household owns `read_at`, `snoozed_until_at` and `archived_at`: `sync` never touches
them.

Visible = not archived, not resolved, and not snoozed past `now`. Unread = visible and
`read_at` is null. Snoozing clears `read_at`, so the item comes back unread.
"""
import datetime as dt
import json
import sys

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

COLUMNS = ("id", "type", "category", "severity", "title", "detail", "amount", "cta", "subject",
           "created_at", "updated_at", "read_at", "snoozed_until_at", "archived_at", "resolved_at")
HOUSEHOLD_FIELDS = ("read_at", "snoozed_until_at", "archived_at")
SEVERITY_RANK = "CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END"
VISIBLE = ("archived_at IS NULL AND resolved_at IS NULL "
           "AND (snoozed_until_at IS NULL OR snoozed_until_at <= %(now)s)")


def _now(now):
    return now or dt.datetime.now(dt.timezone.utc)


def sync(conn, actions, now=None):
    """Make the inbox mirror `actions` (data/actions.py shape); returns {"upserted", "resolved"}.

    A row is rewritten, and `updated_at` moved, only when its content changed, so a digest
    that produces the same list changes nothing (and notifies no one). A row that dropped
    out of the list gets `resolved_at`; one that returns has it cleared."""
    now = _now(now)
    with conn.cursor() as cur:
        for a in actions:
            cur.execute(
                """INSERT INTO notifications
                       (id, type, category, severity, title, detail, amount, cta, subject, created_at, updated_at)
                   VALUES (%(id)s, %(type)s, %(category)s, %(severity)s, %(title)s, %(detail)s, %(amount)s,
                           %(cta)s, %(subject)s, %(now)s, %(now)s)
                   ON CONFLICT (id) DO UPDATE SET
                       type = EXCLUDED.type, category = EXCLUDED.category, severity = EXCLUDED.severity,
                       title = EXCLUDED.title, detail = EXCLUDED.detail, amount = EXCLUDED.amount,
                       cta = EXCLUDED.cta, subject = EXCLUDED.subject, updated_at = EXCLUDED.updated_at,
                       resolved_at = NULL
                   WHERE (notifications.type, notifications.category, notifications.severity, notifications.title,
                          notifications.detail, notifications.amount, notifications.cta, notifications.subject,
                          notifications.resolved_at)
                         IS DISTINCT FROM
                         (EXCLUDED.type, EXCLUDED.category, EXCLUDED.severity, EXCLUDED.title, EXCLUDED.detail,
                          EXCLUDED.amount, EXCLUDED.cta, EXCLUDED.subject, NULL)""",
                {"id": a["id"], "type": a.get("type") or "generic", "category": a.get("category") or "INFO",
                 "severity": a["severity"], "title": a["title"], "detail": a.get("detail"),
                 "amount": a.get("amount"), "cta": Jsonb(a["cta"]) if a.get("cta") else None,
                 "subject": Jsonb(a["subject"]) if a.get("subject") else None, "now": now})
        gone = cur.execute(
            "UPDATE notifications SET resolved_at = %s WHERE resolved_at IS NULL AND id <> ALL(%s)",
            (now, [a["id"] for a in actions])).rowcount
    return {"upserted": len(actions), "resolved": gone}


# --- reading -------------------------------------------------------------------------------

def select(conn, category=None, unread=None, include_archived=False, include_resolved=False,
           include_snoozed=False, now=None):
    """Notifications as dicts, most severe first, then most recently updated, then id.

    `category` is a list to match (None = all). `unread` True/False keeps only unread / only
    read ones. The `include_*` flags lift one visibility rule each."""
    where = []
    if not include_archived:
        where.append("archived_at IS NULL")
    if not include_resolved:
        where.append("resolved_at IS NULL")
    if not include_snoozed:
        where.append("(snoozed_until_at IS NULL OR snoozed_until_at <= %(now)s)")
    if category is not None:
        where.append("category = ANY(%(category)s)")
    if unread is not None:
        where.append("read_at IS NULL" if unread else "read_at IS NOT NULL")
    query = (f"SELECT {', '.join(COLUMNS)} FROM notifications "
             + (f"WHERE {' AND '.join(where)} " if where else "")
             + f"ORDER BY {SEVERITY_RANK}, updated_at DESC, id")
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(query, {"now": _now(now), "category": category}).fetchall()


def get(conn, id_):
    """One notification by id regardless of visibility, or None."""
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(f"SELECT {', '.join(COLUMNS)} FROM notifications WHERE id = %s", (id_,)).fetchone()


def unread_count(conn, category=None, now=None):
    return conn.execute(
        f"SELECT count(*) FROM notifications WHERE {VISIBLE} AND read_at IS NULL "
        "AND (%(category)s::text[] IS NULL OR category = ANY(%(category)s))",
        {"now": _now(now), "category": category}).fetchone()[0]


# --- the household's state -----------------------------------------------------------------

def update(conn, id_, changes, now=None):
    """Set `read_at` / `snoozed_until_at` / `archived_at` (a datetime, or None to clear).

    Snoozing (a non-null `snoozed_until_at`) also clears `read_at` unless the caller sets it,
    so the item resurfaces unread. Only fields whose value changes are written.
    Returns the notification, or None when `id_` does not exist."""
    unknown = set(changes) - set(HOUSEHOLD_FIELDS)
    if unknown:
        raise ValueError(f"cannot change {sorted(unknown)}; the household owns {list(HOUSEHOLD_FIELDS)}")
    now = _now(now)
    with conn.cursor(row_factory=dict_row) as cur:
        old = cur.execute(f"SELECT {', '.join(HOUSEHOLD_FIELDS)} FROM notifications WHERE id = %s FOR UPDATE",
                          (id_,)).fetchone()
        if old is None:
            return None
        changes = dict(changes)
        if changes.get("snoozed_until_at") is not None:
            changes.setdefault("read_at", None)
        changes = {f: v for f, v in changes.items() if old[f] != v}
        if changes:
            cur.execute(f"UPDATE notifications SET {', '.join(f'{f} = %({f})s' for f in changes)} "
                        "WHERE id = %(id)s", {**changes, "id": id_})
    return get(conn, id_)


def _bulk(conn, category, sets, now, where="true"):
    """Apply `sets` ({field: value}) to every visible notification (in `category`, if given, and
    matching the extra SQL condition `where`).

    Returns the number changed."""
    assignments = ", ".join(f"{f} = %({f})s" for f in sets)
    return conn.execute(
        f"""UPDATE notifications SET {assignments}
            WHERE id IN (SELECT id FROM notifications
                         WHERE {VISIBLE} AND {where} AND (%(category)s::text[] IS NULL OR category = ANY(%(category)s))
                         FOR UPDATE)""",
        {**sets, "now": now, "category": category}).rowcount


def mark_all_read(conn, category=None, now=None):
    """Read every visible notification that is unread."""
    now = _now(now)
    return _bulk(conn, category, {"read_at": now}, now, where="read_at IS NULL")


def archive_all(conn, category=None, now=None):
    """Archive every visible notification."""
    now = _now(now)
    return _bulk(conn, category, {"archived_at": now}, now)


def snooze_all(conn, until, category=None, now=None):
    """Snooze every visible notification until `until`; they come back unread."""
    now = _now(now)
    return _bulk(conn, category, {"snoozed_until_at": until, "read_at": None}, now)


# --- CLI -----------------------------------------------------------------------------------

def main():
    if sys.argv[1:] != ["sync"]:
        raise SystemExit("usage: inbox.py sync  < actions.json")
    from ledger import connect
    actions = json.load(sys.stdin)
    with connect() as conn:
        out = sync(conn, actions)
    print(f"inbox: {out['upserted']} notifications, {out['resolved']} resolved", file=sys.stderr)


if __name__ == "__main__":
    main()
