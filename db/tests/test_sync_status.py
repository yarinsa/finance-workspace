"""sync_status: every upsert NOTIFYs `sync_status` with the source; finance_api is read-only.

As the household, when the sync worker updates a source's live status, listeners (the
API's SSE stream) must hear about it, and the internet-facing role must not write it.
"""
import json

import psycopg
import pytest

import ledger

UPSERT = ("INSERT INTO sync_status (source, entry) VALUES (%s, %s::jsonb) "
          "ON CONFLICT (source) DO UPDATE SET entry = EXCLUDED.entry, updated_at = now()")


@pytest.fixture
def status_conn(test_url):
    c = ledger.connect_admin(test_url)   # sync_status is global (no tenant)
    c.execute("TRUNCATE sync_status")
    c.commit()
    yield c
    c.close()


def test_upsert_notifies_with_the_source(status_conn, test_url):
    with psycopg.connect(test_url, autocommit=True) as listener:
        listener.execute("LISTEN sync_status")
        status_conn.execute(UPSERT, ("cal", json.dumps({"state": "scraping"})))
        status_conn.commit()
        status_conn.execute(UPSERT, ("cal", json.dumps({"state": "done"})))
        status_conn.commit()
        notes = []
        for n in listener.notifies(timeout=2, stop_after=2):
            notes.append((n.channel, n.payload))
    assert notes == [("sync_status", "cal"), ("sync_status", "cal")]
    assert status_conn.execute("SELECT entry->>'state' FROM sync_status WHERE source='cal'").fetchone()[0] == "done"


def test_finance_api_can_select_but_not_write(status_conn):
    status_conn.execute(UPSERT, ("leumi", json.dumps({"state": "done"})))
    status_conn.commit()
    status_conn.execute("SET ROLE finance_api")
    assert status_conn.execute("SELECT count(*) FROM sync_status").fetchone()[0] == 1
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        status_conn.execute(UPSERT, ("max", json.dumps({"state": "done"})))
    status_conn.rollback()   # also undoes SET ROLE
    status_conn.execute("SET ROLE finance_api")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        status_conn.execute("UPDATE sync_status SET entry = '{}'::jsonb")
    status_conn.rollback()
