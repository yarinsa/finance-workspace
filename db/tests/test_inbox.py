"""db/inbox.py: the digest mirrors "לטיפול" into the inbox without touching the household's state.

As the household, when I read, snooze or archive an item, the next digest must not undo it;
when the situation goes away the item resolves, and when it comes back it is the same row.
"""
import datetime as dt
import json

import psycopg
import pytest

from finance.tenancy import DEFAULT_TENANT_ID

import inbox

UTC = dt.timezone.utc
T0 = dt.datetime(2026, 10, 16, 9, 0, tzinfo=UTC)
LATER = T0 + dt.timedelta(hours=6)

LIMIT = {"id": "limit-breach:2026-11-11", "severity": "critical", "category": "PROBLEM", "type": "limitBreach",
         "title": "חריגה מהמסגרת ב-11/11", "detail": "היתרה תרד למינוס ₪11,695", "amount": 1694.74,
         "cta": {"label": "לתוכנית התזרים", "to": "/monthly?view=forecast"},
         "subject": {"kind": "cashflow", "date": "2026-11-11"}}
BUDGET = {"id": "budget-over:פנאי:2026-10", "severity": "high", "category": "WARNING", "type": "budgetOver",
          "title": "חריגה בתקציב פנאי", "detail": "₪1,763 מתוך ₪1,200 (+₪563)", "amount": 563.0,
          "cta": {"label": "לתקציב", "to": "/monthly?section=variable"},
          "subject": {"kind": "budget", "categories": ["פנאי"], "cycle_start": "2026-10-01"}}
WATER = {"id": "bill-overdue:מי אביבים חיוב תקופת:2026-10", "severity": "medium", "category": "WARNING",
         "type": "billOverdue", "title": "לא נמצא תשלום לחיוב מי אביבים", "detail": "₪267 · היה צפוי ב-11/10",
         "amount": 266.7, "cta": None,
         "subject": {"kind": "bill", "name": "מי אביבים חיוב תקופת", "due_date": "2026-10-11"}}
STALE = {"id": "stale:discount-business", "severity": "low", "category": "REMINDER", "type": "staleData",
         "title": "נתונים לא עדכניים", "detail": None, "amount": None, "cta": None,
         "subject": {"kind": "sync", "sources": ["discount-business"]}}


def row(conn, id_):
    return inbox.get(conn, id_)


def ids(rows):
    return [r["id"] for r in rows]


def test_sync_inserts_actions_with_their_content(conn):
    assert inbox.sync(conn, [LIMIT, STALE], now=T0) == {"upserted": 2, "resolved": 0}
    r = row(conn, LIMIT["id"])
    assert (r["category"], r["type"], r["severity"]) == ("PROBLEM", "limitBreach", "critical")
    assert r["cta"] == LIMIT["cta"] and r["subject"] == LIMIT["subject"] and float(r["amount"]) == 1694.74
    assert r["created_at"] == r["updated_at"] == T0
    assert r["read_at"] is r["snoozed_until_at"] is r["archived_at"] is r["resolved_at"] is None
    assert row(conn, STALE["id"])["cta"] is None


def test_sync_refreshes_content_but_never_the_households_state(conn):
    inbox.sync(conn, [BUDGET], now=T0)
    inbox.update(conn, BUDGET["id"], {"read_at": T0}, now=T0)
    worse = {**BUDGET, "detail": "₪1,900 מתוך ₪1,200 (+₪700)", "amount": 700.0}
    inbox.sync(conn, [worse], now=LATER)
    r = row(conn, BUDGET["id"])
    assert r["detail"] == worse["detail"] and float(r["amount"]) == 700.0
    assert r["updated_at"] == LATER and r["created_at"] == T0
    assert r["read_at"] == T0


def test_an_unchanged_digest_rewrites_nothing(conn, test_url):
    inbox.sync(conn, [LIMIT], now=T0)
    conn.commit()
    with psycopg.connect(test_url, autocommit=True) as listener:
        listener.execute("LISTEN notifications")
        inbox.sync(conn, [LIMIT], now=LATER)
        conn.commit()
        assert list(listener.notifies(timeout=0.5, stop_after=1)) == []
    assert row(conn, LIMIT["id"])["updated_at"] == T0


def test_actions_that_disappear_resolve_and_come_back_as_the_same_row(conn):
    inbox.sync(conn, [LIMIT, WATER], now=T0)
    inbox.update(conn, WATER["id"], {"archived_at": T0}, now=T0)
    out = inbox.sync(conn, [LIMIT], now=LATER)
    assert out == {"upserted": 1, "resolved": 1}
    assert row(conn, WATER["id"])["resolved_at"] == LATER
    assert row(conn, LIMIT["id"])["resolved_at"] is None
    inbox.sync(conn, [LIMIT, WATER], now=LATER + dt.timedelta(days=1))
    back = row(conn, WATER["id"])
    assert back["resolved_at"] is None and back["created_at"] == T0
    assert back["archived_at"] == T0   # the household's archive survives the round trip


def test_resolving_keeps_the_first_resolved_time(conn):
    inbox.sync(conn, [WATER], now=T0)
    inbox.sync(conn, [], now=LATER)
    inbox.sync(conn, [], now=LATER + dt.timedelta(days=1))
    assert row(conn, WATER["id"])["resolved_at"] == LATER


def test_select_orders_by_severity_then_recency_and_hides_by_default(conn):
    inbox.sync(conn, [STALE, WATER], now=T0)
    inbox.sync(conn, [STALE, WATER, LIMIT, BUDGET], now=LATER)
    assert ids(inbox.select(conn, now=LATER)) == [LIMIT["id"], BUDGET["id"], WATER["id"], STALE["id"]]
    inbox.update(conn, LIMIT["id"], {"archived_at": LATER}, now=LATER)
    inbox.update(conn, BUDGET["id"], {"snoozed_until_at": LATER + dt.timedelta(days=1)}, now=LATER)
    inbox.sync(conn, [STALE, LIMIT, BUDGET], now=LATER)   # WATER resolves
    assert ids(inbox.select(conn, now=LATER)) == [STALE["id"]]
    assert ids(inbox.select(conn, include_archived=True, now=LATER)) == [LIMIT["id"], STALE["id"]]
    assert ids(inbox.select(conn, include_resolved=True, now=LATER)) == [WATER["id"], STALE["id"]]
    assert ids(inbox.select(conn, include_snoozed=True, now=LATER)) == [BUDGET["id"], STALE["id"]]
    # the snooze lapses by itself
    assert BUDGET["id"] in ids(inbox.select(conn, now=LATER + dt.timedelta(days=1)))


def test_filters_by_category_and_read_state(conn):
    inbox.sync(conn, [LIMIT, BUDGET, STALE], now=T0)
    inbox.update(conn, BUDGET["id"], {"read_at": T0}, now=T0)
    assert ids(inbox.select(conn, category=["WARNING", "REMINDER"], now=T0)) == [BUDGET["id"], STALE["id"]]
    assert ids(inbox.select(conn, unread=True, now=T0)) == [LIMIT["id"], STALE["id"]]
    assert ids(inbox.select(conn, unread=False, now=T0)) == [BUDGET["id"]]
    assert inbox.unread_count(conn, now=T0) == 2
    assert inbox.unread_count(conn, category=["REMINDER"], now=T0) == 1
    assert inbox.unread_count(conn, category=["INFO"], now=T0) == 0


def test_snoozing_clears_read(conn):
    inbox.sync(conn, [STALE], now=T0)
    inbox.update(conn, STALE["id"], {"read_at": T0}, now=T0)
    until = T0 + dt.timedelta(days=3)
    r = inbox.update(conn, STALE["id"], {"snoozed_until_at": until}, now=LATER)
    assert r["read_at"] is None and r["snoozed_until_at"] == until


def test_update_rejects_digest_owned_fields_and_unknown_ids(conn):
    inbox.sync(conn, [STALE], now=T0)
    with pytest.raises(ValueError):
        inbox.update(conn, STALE["id"], {"resolved_at": T0})
    assert inbox.update(conn, "nope", {"read_at": T0}) is None


def test_bulk_helpers_only_touch_visible_items(conn):
    inbox.sync(conn, [LIMIT, BUDGET, WATER, STALE], now=T0)
    inbox.update(conn, WATER["id"], {"archived_at": T0}, now=T0)
    assert inbox.mark_all_read(conn, ["WARNING"], now=T0) == 1   # BUDGET; WATER is archived
    assert row(conn, BUDGET["id"])["read_at"] == T0 and row(conn, WATER["id"])["read_at"] is None
    assert inbox.mark_all_read(conn, now=T0) == 2   # LIMIT and STALE; BUDGET was already read
    until = T0 + dt.timedelta(days=1)
    assert inbox.snooze_all(conn, until, ["REMINDER"], now=T0) == 1
    stale = row(conn, STALE["id"])
    assert stale["snoozed_until_at"] == until and stale["read_at"] is None
    assert inbox.archive_all(conn, now=T0) == 2   # LIMIT and BUDGET; STALE is snoozed
    assert row(conn, STALE["id"])["archived_at"] is None
    assert inbox.unread_count(conn, now=T0) == 0


def test_cli_sync_reads_actions_from_stdin(conn, test_url, monkeypatch, capsys):
    import io
    conn.commit()
    monkeypatch.setenv("DATABASE_URL", test_url)
    monkeypatch.setattr("sys.argv", ["inbox.py", "sync"])
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps([LIMIT, STALE])))
    inbox.main()
    assert "2 notifications" in capsys.readouterr().err
    assert ids(inbox.select(conn)) == [LIMIT["id"], STALE["id"]]


def test_every_write_notifies_with_the_id(conn, test_url):
    with psycopg.connect(test_url, autocommit=True) as listener:
        listener.execute("LISTEN notifications")
        inbox.sync(conn, [LIMIT], now=T0)
        conn.commit()   # one NOTIFY per transaction: Postgres folds identical ones
        inbox.update(conn, LIMIT["id"], {"read_at": T0}, now=T0)
        conn.commit()
        notes = [(n.channel, n.payload) for n in listener.notifies(timeout=2, stop_after=2)]
    assert notes == [("notifications", f"{DEFAULT_TENANT_ID}:{LIMIT['id']}")] * 2   # 0018: tenant first


def test_finance_api_changes_only_the_households_columns(conn):
    inbox.sync(conn, [LIMIT], now=T0)
    conn.commit()
    conn.execute("SET ROLE finance_api")
    assert inbox.update(conn, LIMIT["id"], {"read_at": T0, "archived_at": T0})["read_at"] == T0
    conn.commit()
    for bad in ("UPDATE notifications SET title = 'x'", "UPDATE notifications SET resolved_at = now()",
                "DELETE FROM notifications", "INSERT INTO notifications (id, type, category, severity, title) "
                "VALUES ('x', 't', 'INFO', 'low', 't')"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(bad)
        conn.rollback()
        conn.execute("SET ROLE finance_api")
    conn.rollback()


def test_unpushed_lists_visible_rows_of_the_categories_until_marked_pushed(conn):
    inbox.sync(conn, [LIMIT, BUDGET, WATER, STALE], now=T0)
    inbox.update(conn, WATER["id"], {"archived_at": T0}, now=T0)
    assert ids(inbox.unpushed(conn, ("PROBLEM", "WARNING"), now=T0)) == [LIMIT["id"], BUDGET["id"]]
    assert ids(inbox.unpushed(conn, ("REMINDER",), now=T0)) == [STALE["id"]]
    assert inbox.mark_pushed(conn, [LIMIT["id"], "unknown"], now=LATER) == 1
    assert ids(inbox.unpushed(conn, ("PROBLEM", "WARNING"), now=T0)) == [BUDGET["id"]]
    assert inbox.mark_pushed(conn, [LIMIT["id"]], now=LATER + dt.timedelta(hours=1)) == 0   # keeps the first stamp
    assert conn.execute("SELECT pushed_at FROM notifications WHERE id = %s", (LIMIT["id"],)).fetchone()[0] == LATER


def test_a_pushed_item_stays_pushed_when_the_digest_refreshes_it(conn):
    inbox.sync(conn, [BUDGET], now=T0)
    inbox.mark_pushed(conn, [BUDGET["id"]], now=T0)
    inbox.sync(conn, [{**BUDGET, "detail": "₪1,900 מתוך ₪1,200 (+₪700)"}], now=LATER)
    assert inbox.unpushed(conn, ("WARNING",), now=LATER) == []


def test_finance_api_cannot_write_pushed_at(conn):
    inbox.sync(conn, [LIMIT], now=T0)
    conn.commit()
    conn.execute("SET ROLE finance_api")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("UPDATE notifications SET pushed_at = now()")
    conn.rollback()


def test_the_category_and_severity_are_checked(conn):
    with pytest.raises(psycopg.errors.CheckViolation):
        inbox.sync(conn, [{**LIMIT, "category": "URGENT"}], now=T0)
    conn.rollback()
    with pytest.raises(psycopg.errors.CheckViolation):
        inbox.sync(conn, [{**LIMIT, "severity": "blocker"}], now=T0)
    conn.rollback()
