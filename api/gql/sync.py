"""SyncSource: one row of Postgres `sync_status` (the worker's latest entry per source), with the
source's manifest label and its latest dump on disk (`source_dumps`, written by the digest)."""
import datetime as dt
from dataclasses import dataclass, field
from functools import lru_cache

from finance import manifest, vault
from api.rebuild import resume_point

# A run that has not written for this long is a dead worker, not a sync in progress.
SYNCING = frozenset({"starting", "checking_session", "scraping", "validating", "digesting", "publishing",
                     "waiting_for_login", "waiting_for_otp"})
SYNCING_FRESH = dt.timedelta(minutes=15)


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
    label: str | None = None
    last_dumped_at: dt.datetime | None = None
    raw_files: int | None = None
    latest_txn_date: dt.date | None = None
    entities: list[dict] = field(default_factory=list)   # [{entity, records}]

    @classmethod
    def from_row(cls, source, entry, updated_at, dump=None):
        """`dump` is the source's `(SourceDump, {entity: records})` from db/snapshot_store.dumps."""
        entry = entry or {}
        d, counts = dump or (None, {})
        m = _manifests().get(source)
        return cls(source=source, status=entry.get("status") or "unknown", message=entry.get("message"),
                   step=entry.get("step"), total_steps=entry.get("total_steps"), error=entry.get("error"),
                   started_at=_ts(entry.get("started_at")), updated_at=updated_at or _ts(entry.get("updated_at")),
                   retry_from=resume_point(entry), label=m.label if m else None,
                   last_dumped_at=d and d.dumped_at, raw_files=d and d.raw_files,
                   latest_txn_date=d and d.latest_txn_date,
                   entities=[{"entity": e, "records": n} for e, n in counts.items()])

    @property
    def syncing(self):
        """True while a run is in progress (and the worker wrote recently)."""
        if self.status not in SYNCING:
            return False
        if self.updated_at is None:
            return True
        now = dt.datetime.now(self.updated_at.tzinfo)
        return now - self.updated_at < SYNCING_FRESH

    @classmethod
    def get(cls, conn, source):
        row = conn.execute("SELECT source, entry, updated_at FROM sync_status WHERE source = %s", (source,)).fetchone()
        return cls.from_row(*row, _dumps(conn).get(source)) if row else None

    @classmethod
    def all(cls, conn):
        rows = conn.execute("SELECT source, entry, updated_at FROM sync_status ORDER BY source").fetchall()
        dumps = _dumps(conn)
        return [cls.from_row(*r, dumps.get(r[0])) for r in rows]


def _dumps(conn):
    import snapshot_store   # db/, on the path once api.gql.resolvers is imported
    return snapshot_store.dumps(conn)


class SecretsError(Exception):
    """A secrets request the household can act on (unknown source or name, vault not set up, vault down).
    The message is safe to show: it never carries a value."""


@lru_cache(maxsize=1)
def _manifests():
    return manifest.load_all()


def connection_fields(source: str) -> list[dict]:
    """A source's connection variables from its manifest: name (the `x-env`), title and whether it is masked."""
    m = _manifests().get(source)
    if m is None:
        raise SecretsError("unknown source")
    return [{"name": p["x-env"], "title": p.get("title") or p["x-env"], "masked": bool(p.get("writeOnly"))}
            for p in m.connection["properties"].values()]


def secrets_view(tenant_id, source: str, env=None) -> dict:
    """The `SyncSourceSecrets` of one source for this tenant: which fields the vault holds, never their values.
    A household without a vault write identity gets the fields without a state and `can_edit` false."""
    fields = connection_fields(source)
    can_edit = vault.can_write(tenant_id, env)
    try:
        held = vault.secret_status(tenant_id, env) if can_edit else {}
    except vault.VaultError as e:
        raise SecretsError(f"vault: {e}") from None
    return {"source": source, "can_edit": can_edit, "fields": [
        {**f, "is_set": f["name"] in held, "updated_at": _ts(held.get(f["name"]))} for f in fields]}


def set_secret(tenant_id, source: str, name: str, value: str, env=None) -> dict:
    """Store one of the source's connection variables in the tenant's vault; returns the refreshed view."""
    if name not in {f["name"] for f in connection_fields(source)}:
        raise SecretsError("that is not one of this source's connection fields")
    if not vault.can_write(tenant_id, env):
        raise SecretsError("this household's vault is not set up for editing secrets from the app")
    try:
        vault.set_secret(tenant_id, name, value, env)
    except vault.VaultError as e:
        raise SecretsError(f"vault: {e}") from None
    return secrets_view(tenant_id, source, env)
