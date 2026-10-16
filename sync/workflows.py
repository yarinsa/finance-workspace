"""FinanceSyncWorkflow: refresh every requested source -> digest -> publish, without
ever logging in.

  preflight   check every requested session first
  login       if any are dead, ONE notification listing them (grouped by login), then wait
              up to 12h for the `session_refreshed` signal (sync/resume.py)
  scrape      live (and unknown) sources in registry order; one failing never stops the rest
  gate        validate_dump after each scrape; a rejected dump does not count
  finish      digest once, publish once, if at least one source scraped
"""
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError

with workflow.unsafe.imports_passed_through():
    import sources

TASK_QUEUE = "finance-sync"
LOGIN_WAIT = timedelta(hours=12)

QUICK = dict(
    start_to_close_timeout=timedelta(minutes=3),
    retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=10)),
)
# Retrying cannot fix a dead session or a moved endpoint, so those never retry.
SCRAPE = dict(
    start_to_close_timeout=timedelta(minutes=10),
    heartbeat_timeout=timedelta(seconds=60),
    retry_policy=RetryPolicy(maximum_attempts=2, non_retryable_error_types=["SessionExpired", "ScrapeFailed"]),
)
VALIDATE = dict(
    start_to_close_timeout=timedelta(minutes=3),
    heartbeat_timeout=timedelta(seconds=60),
    retry_policy=RetryPolicy(maximum_attempts=1),
)
DIGEST = dict(
    start_to_close_timeout=timedelta(minutes=10),
    heartbeat_timeout=timedelta(seconds=60),
    retry_policy=RetryPolicy(maximum_attempts=2),
)
PUBLISH = dict(
    start_to_close_timeout=timedelta(minutes=5),
    heartbeat_timeout=timedelta(seconds=60),
    retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=30)),
)
NOTIFY = dict(
    start_to_close_timeout=timedelta(seconds=30),
    retry_policy=RetryPolicy(maximum_attempts=1),
)

# Per-source statuses in the result dict.
OK, NEEDS_LOGIN, FAILED, REJECTED, PENDING = "ok", "needs_login", "failed", "rejected", "pending"
LOGIN_TITLE = "Finance sync - login needed"


def _cause(e: ActivityError):
    c = e.cause
    return (c.type, c.message) if isinstance(c, ApplicationError) else (None, str(c))


def _detail(e: ActivityError, limit=600) -> str:
    """The activity's message plus its details (command output tail), trimmed."""
    c = e.cause
    extra = "\n".join(str(d) for d in getattr(c, "details", ()) or ())
    return (f"{_cause(e)[1]}\n{extra}".strip())[-limit:]


class _FinanceSync:
    """The sync's state and flow, shared by FinanceSyncWorkflow and the AMEX-only wrapper."""

    def __init__(self) -> None:
        self._phase = "starting"
        self._results: dict = {}
        self._resumed = False
        self._all = False  # a signal without names re-checks every dead source
        self._named: set = set()

    def refreshed(self, names=None) -> None:
        self._resumed = True
        if not names:
            self._all = True
        for n in names or ():
            try:
                self._named |= sources.resolve([n])
            except ValueError:
                pass  # a mistyped name must not wedge the workflow task

    def status(self) -> dict:
        return {"phase": self._phase, "sources": {k: dict(v) for k, v in self._results.items()}}

    def _set(self, source: str, status: str, detail: str = "") -> None:
        self._results[source] = {"status": status, "detail": detail}

    async def _say(self, title: str, message: str) -> None:
        await workflow.execute_activity("notify", args=[title, message], **NOTIFY)

    async def _probe(self, source: str) -> str:
        """ensure_chrome + check_session -> "live" | "dead" | "unknown" | "failed".
        A check that cannot run is unknown, never dead: only a positive logged-out signal pages the human."""
        try:
            await workflow.execute_activity("ensure_chrome", source, **QUICK)
        except ActivityError as e:
            self._set(source, FAILED, f"Chrome unavailable: {_detail(e)}")
            return "failed"
        try:
            return await workflow.execute_activity("check_session", source, **QUICK)
        except ActivityError:
            return "unknown"

    def _login_message(self, dead: list) -> str:
        groups = sources.login_groups(dead)
        lines = []
        for group, members in groups.items():
            profile = sources.get(members[0]).profile
            lines.append(f"{group} ({', '.join(members)}; profile {profile})" if len(members) > 1
                         else f"{group} (profile {profile})")
        return ("Log in in these Chrome windows: " + "; ".join(lines)
                + ". Then run `python3 sync/resume.py`.")

    def _was_named(self, source: str) -> bool:
        return self._all or source in self._named

    async def _scrape_one(self, source: str, unverified: bool) -> str:
        """scrape + validate. Returns "ok" | "needs_login" | "failed" | "rejected"."""
        self._set(source, "scraping")
        try:
            await workflow.execute_activity("scrape", source, **SCRAPE)
        except ActivityError as e:
            kind, _ = _cause(e)
            if kind == "SessionExpired":
                self._set(source, NEEDS_LOGIN, "session expired during scrape")
                return NEEDS_LOGIN
            self._set(source, FAILED, _detail(e))
            return FAILED
        self._set(source, "validating")
        try:
            gate = await workflow.execute_activity("validate_dump", source, **VALIDATE)
        except ActivityError as e:
            self._set(source, REJECTED, _detail(e))
            return REJECTED
        note = "session unverified; " if unverified else ""
        self._set(source, OK, f"{note}scraped, validation {gate}")
        return OK

    async def run(self, requested=None) -> dict:
        try:
            order = sources.ordered(requested)
        except ValueError as e:
            raise ApplicationError(str(e), non_retryable=True)
        self._results = {s: {"status": PENDING, "detail": ""} for s in order}

        # 1. Preflight: every session, before anything is scraped.
        self._phase = "preflight"
        state = {s: await self._probe(s) for s in order}

        # 2. One grouped notification, one wait. The human logs in once per group.
        dead = [s for s in order if state[s] == "dead"]
        if dead:
            self._phase = "waiting_for_login"
            await self._say(LOGIN_TITLE, self._login_message(dead))
            try:
                await workflow.wait_condition(lambda: self._resumed, timeout=LOGIN_WAIT)
            except TimeoutError:
                pass
            if self._resumed:
                self._phase = "rechecking"
                for s in (d for d in dead if self._was_named(d)):
                    state[s] = await self._probe(s)
            for s in dead:
                if state[s] == "dead":
                    self._set(s, NEEDS_LOGIN, "still logged out" if self._resumed else "no login within 12h")

        # 3. Scrape in registry order (Discount: account -> mortgage -> business).
        self._phase = "scraping"
        expired_groups: dict = {}
        for s in order:
            if state[s] not in ("live", "unknown"):
                continue
            group = sources.get(s).group
            if group in expired_groups:
                self._set(s, NEEDS_LOGIN, f"login expired while scraping {expired_groups[group]}")
                continue
            if await self._scrape_one(s, unverified=state[s] == "unknown") == NEEDS_LOGIN:
                expired_groups[group] = s

        # 4. Digest and publish once. A rejected dump is already on disk and the digest
        #    reads it, so the numbers are not published until that source is sorted out.
        scraped = [s for s in order if self._results[s]["status"] == OK]
        rejected = [s for s in order if self._results[s]["status"] == REJECTED]
        finish = None
        if scraped:
            try:
                self._phase = "digesting"
                summary = await workflow.execute_activity("digest", **DIGEST)
                if rejected:
                    published = f"withheld (rejected: {', '.join(rejected)})"
                else:
                    self._phase = "publishing"
                    published = await workflow.execute_activity("publish_data", **PUBLISH)
            except ActivityError:
                self._phase = "failed"
                await self._say("Finance sync", "Digest/publish failed - see Temporal UI (localhost:8233)")
                raise
            finish = {"digest": summary, "published": published}

        self._phase = "done"
        await self._say("Finance sync", self._summary(order, finish))
        results = {s: dict(self._results[s]) for s in order}
        if finish:
            results["_finish"] = finish
        return results

    def _summary(self, order: list, finish) -> str:
        by = {}
        for s in order:
            by.setdefault(self._results[s]["status"], []).append(s)
        parts = [f"{status}: {', '.join(names)}" for status, names in by.items()]
        if finish:
            parts.append(f"published: {finish['published']}")
        n = ((finish or {}).get("digest") or {}).get("transactions")
        return "; ".join(parts) + (f" ({n} transactions)" if n else "")


@workflow.defn
class FinanceSyncWorkflow:
    def __init__(self) -> None:
        self._sync = _FinanceSync()

    @workflow.signal
    def session_refreshed(self, names: list[str] | None = None) -> None:
        """The human logged in again. Optionally name sources or login groups ("discount"
        covers all three Discount apps); without names every dead source is re-checked."""
        self._sync.refreshed(names)

    @workflow.query
    def status(self) -> dict:
        return self._sync.status()

    @workflow.run
    async def run(self, sources: list[str] | None = None) -> dict:
        return await self._sync.run(sources)


@workflow.defn
class AmexSyncWorkflow:
    """The original AMEX-only workflow, kept so existing schedules and runs still resolve.
    It is FinanceSyncWorkflow(["amex"]); the result is the same per-source dict."""

    def __init__(self) -> None:
        self._sync = _FinanceSync()

    @workflow.signal
    def session_refreshed(self, names: list[str] | None = None) -> None:
        self._sync.refreshed(names)

    @workflow.query
    def status(self) -> dict:
        return self._sync.status()

    @workflow.run
    async def run(self) -> dict:
        return await self._sync.run(["amex"])
