"""SyncSource: one row of Postgres `sync_status` (the worker's latest entry per source)."""
import datetime as dt
from dataclasses import dataclass

from api.rebuild import resume_point


def _ts(v):
    try:
        return dt.datetime.fromisoformat(v) if v else None
    except (TypeError, ValueError):
        return None


@dataclass
class SyncSource:
    TYPENAME = "SyncSource"
    source: str
    status: str
    message: str | None
    step: int | None
    total_steps: int | None
    error: str | None
    started_at: dt.datetime | None
    updated_at: dt.datetime | None
    retry_from: str | None

    @classmethod
    def from_row(cls, source, entry, updated_at):
        entry = entry or {}
        return cls(source=source, status=entry.get("status") or "unknown", message=entry.get("message"),
                   step=entry.get("step"), total_steps=entry.get("total_steps"), error=entry.get("error"),
                   started_at=_ts(entry.get("started_at")), updated_at=updated_at or _ts(entry.get("updated_at")),
                   retry_from=resume_point(entry))

    @classmethod
    def get(cls, conn, source):
        row = conn.execute("SELECT source, entry, updated_at FROM sync_status WHERE source = %s", (source,)).fetchone()
        return cls.from_row(*row) if row else None

    @classmethod
    def all(cls, conn):
        rows = conn.execute("SELECT source, entry, updated_at FROM sync_status ORDER BY source").fetchall()
        return [cls.from_row(*r) for r in rows]
