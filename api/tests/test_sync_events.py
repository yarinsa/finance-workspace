"""GET /api/sync/events: auth, event framing, pings, the stream cap and cleanup.

No database: the app gets a fake broadcaster. A stream's lifetime is shortened so the
response ends by itself and the test client can read it to the end.
"""
import asyncio

from finance.tenancy import DEFAULT_TENANT_ID
import json

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.auth import COOKIE, TokenVerifier
from api.sse import END, Event, Subscription, SyncBroadcaster
from api.tests.conftest import SECRET, FakeJwks, settings

SNAPSHOT = {"updated_at": "2026-10-26T06:20:00+00:00",
            "sources": {"cal": {"state": "done", "label": "כאל"}}}
CHANGE = {"source": "leumi", "entry": {"state": "scraping"}}


class FakeBroadcaster:
    def __init__(self, preload=()):
        self.preload = list(preload)
        self.subs, self.unsubscribed = [], []
        self.fail = False

    def subscribe(self):
        sub = Subscription()
        for item in self.preload:
            sub.queue.put_nowait(item)
        self.subs.append(sub)
        return sub

    def unsubscribe(self, sub):
        self.unsubscribed.append(sub)

    async def snapshot(self):
        if self.fail:
            raise RuntimeError("db down")
        return SNAPSHOT

    async def stop(self):
        pass


@pytest.fixture
def make_client(key_pair, make_token, pool, owner):
    def make(broadcaster, **state):
        s = settings()
        app = create_app(s, pool=pool, rebuilder=object(), broadcaster=broadcaster,
                         verifier=TokenVerifier(s, jwk_client=FakeJwks(key_pair)))
        app.state.sse_lifetime = 0.3
        app.state.sse_tick = 0.05
        for k, v in state.items():
            setattr(app.state, k, v)
        c = TestClient(app)
        c.headers.update({"X-Origin-Secret": SECRET})
        c.cookies.set(COOKIE, make_token())
        return c
    return make


def frames(text):
    return [f for f in text.split("\n\n") if f]


def test_stream_needs_a_session(make_client):
    c = make_client(FakeBroadcaster())
    c.cookies.clear()
    r = c.get("/api/sync/events")
    assert r.status_code == 401
    assert r.json()["error"] == "unauthenticated"


def test_stream_needs_the_origin_secret(make_client):
    c = make_client(FakeBroadcaster())
    c.headers.pop("X-Origin-Secret")
    assert c.get("/api/sync/events").status_code == 403


def test_snapshot_comes_first_then_changes_as_source_events(make_client):
    b = FakeBroadcaster(preload=[CHANGE])
    r = make_client(b).get("/api/sync/events")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert r.headers["cache-control"] == "no-cache"
    assert r.headers["x-accel-buffering"] == "no"
    f = frames(r.text)
    assert f[0] == "retry: 5000"
    assert f[1].startswith("event: snapshot\ndata: ")
    assert json.loads(f[1].split("data: ")[1]) == SNAPSHOT
    assert f[2].startswith("event: source\ndata: ")
    assert json.loads(f[2].split("data: ")[1]) == CHANGE
    assert all(line.count("\n") == 1 for line in f[1:3])   # compact: one data line each


def test_inbox_changes_are_framed_as_notification_events(make_client):
    b = FakeBroadcaster(preload=[Event("notification", {"id": "budget-over:פנאי:2026-10"}), CHANGE])
    f = frames(make_client(b).get("/api/sync/events").text)
    assert f[2] == 'event: notification\ndata: {"id":"budget-over:פנאי:2026-10"}'
    assert f[3].startswith("event: source\ndata: ")   # source events are unchanged


def test_a_quiet_stream_gets_pings(make_client):
    r = make_client(FakeBroadcaster(), sse_ping=0.1).get("/api/sync/events")
    assert ": ping" in frames(r.text)


def test_stream_ends_when_the_broadcaster_drops_it(make_client):
    b = FakeBroadcaster(preload=[END])
    r = make_client(b, sse_lifetime=30).get("/api/sync/events")   # would hang for 30 s if END were ignored
    assert [f.split("\n")[0] for f in frames(r.text)] == ["retry: 5000", "event: snapshot"]


def test_every_stream_unsubscribes_when_it_ends(make_client):
    b = FakeBroadcaster()
    c = make_client(b)
    c.get("/api/sync/events")
    assert b.unsubscribed == b.subs and len(b.subs) == 1
    assert c.app.state.sse_streams == 0


def test_too_many_streams_is_503(make_client):
    b = FakeBroadcaster()
    c = make_client(b, sse_max_streams=2)
    c.app.state.sse_streams = 2   # two streams already open
    r = c.get("/api/sync/events")
    assert r.status_code == 503
    assert r.json()["error"] == "too_many_streams"
    assert b.subs == []


def test_snapshot_failure_is_503_and_frees_the_slot(make_client):
    b = FakeBroadcaster()
    b.fail = True
    c = make_client(b)
    assert c.get("/api/sync/events").status_code == 503
    assert c.app.state.sse_streams == 0
    assert b.unsubscribed == b.subs


# --- the broadcaster itself (no database: _read_source / LISTEN are not involved) ------

def test_a_full_queue_drops_only_the_slow_subscriber():
    async def go():
        b = SyncBroadcaster("", queue_size=2)
        slow, fast = Subscription(2), Subscription(2)
        b.subscribers |= {slow, fast}
        for i in range(2):
            b.publish({"n": i})
        fast.queue.get_nowait(), fast.queue.get_nowait()
        b.publish({"n": 2})   # slow is full -> dropped and ended; fast keeps going
        assert slow not in b.subscribers and fast in b.subscribers
        assert slow.queue.get_nowait() is END
        assert fast.queue.get_nowait() == {"n": 2}
    asyncio.run(go())


def test_resync_ends_every_stream():
    async def go():
        b = SyncBroadcaster("")
        a, c = Subscription(), Subscription()
        b.subscribers |= {a, c}
        b.publish({"n": 1})
        b.resync_all()
        assert not b.subscribers
        assert a.queue.get_nowait() is END and c.queue.get_nowait() is END
    asyncio.run(go())


# --- real LISTEN/NOTIFY (skips without a database) -------------------------------------

def test_notify_reaches_a_subscriber(test_url):
    import psycopg
    from psycopg.conninfo import make_conninfo  # noqa: F401

    with psycopg.connect(test_url, autocommit=True) as admin:
        try:
            admin.execute("SELECT 1 FROM sync_status LIMIT 1")
        except psycopg.errors.UndefinedTable:
            pytest.skip("sync_status migration not applied")
        admin.execute("DELETE FROM sync_status WHERE source = 'sse-test'")

        async def go():
            b = SyncBroadcaster(test_url)
            sub = b.subscribe()
            try:
                await asyncio.sleep(0.5)   # let LISTEN start
                admin.execute("INSERT INTO sync_status(source, entry, updated_at) VALUES "
                              "('sse-test', '{\"state\":\"done\"}', now())")
                got = await asyncio.wait_for(sub.get(), 5)
                assert got == {"source": "sse-test", "entry": {"state": "done"}}
                assert "sse-test" in (await b.snapshot())["sources"]
            finally:
                await b.stop()
        try:
            asyncio.run(go())
        finally:
            admin.execute("DELETE FROM sync_status WHERE source = 'sse-test'")


def test_inbox_notify_reaches_a_subscriber_as_a_notification_event(test_url):
    import psycopg

    with psycopg.connect(test_url, autocommit=True) as admin:
        try:
            admin.execute("SELECT 1 FROM notifications LIMIT 1")
        except psycopg.errors.UndefinedTable:
            pytest.skip("notifications migration not applied")

        async def go():
            b = SyncBroadcaster(test_url)
            sub = b.subscribe()
            try:
                await asyncio.sleep(0.5)   # let LISTEN start
                admin.execute("INSERT INTO notifications (tenant_id, id, type, category, severity, title) "
                              "VALUES (%s, 'sse-test', 'staleData', 'REMINDER', 'low', 't')", (DEFAULT_TENANT_ID,))
                assert await asyncio.wait_for(sub.get(), 5) == Event(
                    "notification", {"id": "sse-test"}, tenant=str(DEFAULT_TENANT_ID))
            finally:
                await b.stop()
        try:
            asyncio.run(go())
        finally:
            admin.execute("DELETE FROM notifications WHERE id = 'sse-test'")
