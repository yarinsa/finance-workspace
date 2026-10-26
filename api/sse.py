"""Live sync status over Server-Sent Events.

`SyncBroadcaster` owns one dedicated Postgres connection running `LISTEN sync_status`
(the table's trigger does `pg_notify('sync_status', source)` on every write). Each notify
re-reads that row and fans `{"source", "entry"}` out to the subscribers, one bounded queue
per open `GET /api/sync/events` stream. The API role only SELECTs; it never writes status.

A subscriber whose queue fills is a slow client and is dropped; when the LISTEN connection
drops, every subscriber is ended after reconnecting. Either way the client reconnects and
starts again from a fresh snapshot, so no change can be silently missed.
"""
import asyncio
import json
import logging

import psycopg

log = logging.getLogger("finance_api")

CHANNEL = "sync_status"
QUEUE_SIZE = 100
BACKOFF_START, BACKOFF_MAX = 1.0, 30.0

END = object()   # queued to tell a stream to finish (dropped, resync, or shutdown)


class Subscription:
    """One stream's inbox. `get()` returns a change dict, or END when the stream must close."""

    def __init__(self, size=QUEUE_SIZE):
        self.queue = asyncio.Queue(maxsize=size)

    async def get(self):
        return await self.queue.get()

    def end(self):
        """Close this subscription now, discarding whatever is queued."""
        while not self.queue.empty():
            self.queue.get_nowait()
        self.queue.put_nowait(END)


def _read_all(rows):
    sources = {source: entry for source, entry, _ in rows}
    stamps = [u for _, _, u in rows if u is not None]
    return {"updated_at": max(stamps).isoformat() if stamps else None, "sources": sources}


class SyncBroadcaster:
    def __init__(self, database_url, queue_size=QUEUE_SIZE):
        self.database_url = database_url
        self.queue_size = queue_size
        self.subscribers = set()
        self._task = None

    # --- subscribers ---------------------------------------------------------------

    def subscribe(self):
        """A new subscription; starts the LISTEN task on the first one. Call from the event loop."""
        self._ensure_running()
        sub = Subscription(self.queue_size)
        self.subscribers.add(sub)
        return sub

    def unsubscribe(self, sub):
        self.subscribers.discard(sub)

    def publish(self, change):
        for sub in list(self.subscribers):
            try:
                sub.queue.put_nowait(change)
            except asyncio.QueueFull:
                log.warning("dropping a slow sync-status subscriber")
                self.subscribers.discard(sub)
                sub.end()

    def resync_all(self):
        """End every stream so clients reconnect and take a new snapshot."""
        for sub in list(self.subscribers):
            self.subscribers.discard(sub)
            sub.end()

    # --- reads ---------------------------------------------------------------------

    async def snapshot(self):
        """Every row as `{"updated_at", "sources": {source: entry}}` (the data/sync-status.json shape)."""
        async with await psycopg.AsyncConnection.connect(self.database_url, autocommit=True) as conn:
            cur = await conn.execute("SELECT source, entry, updated_at FROM sync_status")
            return _read_all(await cur.fetchall())

    async def _read_source(self, source):
        async with await psycopg.AsyncConnection.connect(self.database_url, autocommit=True) as conn:
            cur = await conn.execute("SELECT entry FROM sync_status WHERE source = %s", (source,))
            row = await cur.fetchone()
        return row[0] if row else None

    # --- the LISTEN task -----------------------------------------------------------

    def _ensure_running(self):
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self._run(), name="sync-status-listen")

    async def start(self):
        self._ensure_running()

    async def stop(self):
        task, self._task = self._task, None
        if task:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        self.resync_all()

    async def _run(self):
        backoff, first = BACKOFF_START, True
        while True:
            try:
                async with await psycopg.AsyncConnection.connect(self.database_url, autocommit=True) as conn:
                    await conn.execute(f"LISTEN {CHANNEL}")
                    backoff = BACKOFF_START
                    if not first:
                        self.resync_all()   # changes may have been missed while we were away
                    first = False
                    async for note in conn.notifies():
                        await self._on_notify(note.payload)
                raise psycopg.OperationalError("listen connection closed")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("sync-status listener lost (%s); retrying in %.0fs", type(e).__name__, backoff)
                first = False
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, BACKOFF_MAX)

    async def _on_notify(self, source):
        try:
            entry = await self._read_source(source)
        except Exception:
            log.exception("could not read sync status for %s", source)
            self.resync_all()
            return
        if entry is not None:
            self.publish({"source": source, "entry": entry})


def sse(event, data):
    """One SSE frame. Compact JSON has no raw newlines, so it always fits on one `data:` line."""
    return f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'), ensure_ascii=False, default=str)}\n\n"
