"""FinanceSyncWorkflow: refresh every requested source -> digest -> publish, without
ever logging in.

  preflight   check every requested session first
  login       if any are dead, ONE notification listing them (grouped by login), then wait
              up to 15m for the `session_refreshed` signal (sync/resume.py)
  scrape      live (and unknown) sources in registry order; one failing never stops the rest.
              A dead `otp` source (Harel) the human started by name from the app logs in
              instead: its dump asks for an SMS and the code typed in the app arrives as the
              `submit_otp` signal (status waiting_for_otp). Scheduled runs never send a code.
  gate        validate_dump after each scrape; a rejected dump does not count
  finish      digest once, publish once, if at least one source scraped

A retry from the app (api POST /api/sync/{source}/retry) is a one-source run that continues
where that source stopped: a failed or rejected scrape runs the whole flow again (a live
session is not asked to log in again), a failure in digest/publish skips straight to
`finish` (opts {"resume": "digest"}), since the dump is already on disk and validated.

Every source's progress is also published (publish_status) as its own entry in
sync-status.json, which the dashboard polls: checking_session -> waiting_for_login ->
scraping -> validating -> digesting -> publishing -> done, or needs_login / failed /
rejected. Publishing is best-effort and never fails the sync.
"""
import re
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError

with workflow.unsafe.imports_passed_through():
    import sources
    from finance import push  # repo root is on sys.path (worker.py, tests/conftest.py)

TASK_QUEUE = "finance-sync"
# Short: an OTP expires within minutes anyway, and a login missed now is retried by the
# next scheduled run (06:20 / 22:00) instead of a waiting run swallowing it (overlap SKIP).
LOGIN_WAIT = timedelta(minutes=15)

QUICK = dict(
    start_to_close_timeout=timedelta(minutes=3),
    retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=10)),
)
# Retrying cannot fix a dead session or a moved endpoint, so those never retry.
# An OTP login: the dump waits up to 8 minutes for the code. One attempt: a retry is another SMS.
LOGIN = dict(
    start_to_close_timeout=timedelta(minutes=10),
    heartbeat_timeout=timedelta(seconds=60),
    retry_policy=RetryPolicy(maximum_attempts=1),
)

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
# Best-effort: one attempt, and _set() swallows any failure.
STATUS = dict(
    start_to_close_timeout=timedelta(seconds=30),
    retry_policy=RetryPolicy(maximum_attempts=1),
)

# Per-source statuses in the result dict.
OK, NEEDS_LOGIN, FAILED, REJECTED, PENDING = "ok", "needs_login", "failed", "rejected", "pending"
LOGIN_TITLE = "Finance sync - login needed"

TOTAL_STEPS = 5
# status -> (step, short Hebrew text shown on the dashboard; {name} is the source's label)
STEPS = {
    "checking_session": (1, "{name}: בודק חיבור"),
    "waiting_for_login": (1, "{name}: ממתין שתתחבר ב-Chrome במק"),
    "waiting_for_otp": (1, "{name}: נשלח קוד ב-SMS — הזן אותו כאן"),
    "scraping": (2, "{name}: מוריד נתונים"),
    "validating": (3, "{name}: בודק את הנתונים"),
    "digesting": (4, "{name}: בונה מחדש את הנתונים"),
    "publishing": (5, "{name}: מפרסם לדשבורד"),
    "done": (5, "{name}: הסנכרון הושלם"),
    "needs_login": (1, "{name}: לא בוצע סנכרון — נדרשת התחברות"),
    "rejected": (3, "{name}: הנתונים נדחו בבדיקה"),
    "failed": (None, "{name}: הסנכרון נכשל"),
}
TERMINAL = {"done", "needs_login", "rejected", "failed"}


def _cause(e: ActivityError):
    c = e.cause
    return (c.type, c.message) if isinstance(c, ApplicationError) else (None, str(c))


def _detail(e: ActivityError, limit=600) -> str:
    """The activity's message plus its details (command output tail), trimmed."""
    c = e.cause
    extra = "\n".join(str(d) for d in getattr(c, "details", ()) or ())
    return (f"{_cause(e)[1]}\n{extra}".strip())[-limit:]


_ERROR_LINE = re.compile(r"LOGIN FAILED|Error:|failed|NOT WRITTEN|rejected|refused|timed out|Missing env", re.I)


def _reason(e: BaseException, lines: int = 1) -> str:
    """Short text for the dashboard: the root cause's message (first `lines` lines), followed by
    the dump script's own error lines when the activity attached its output (no tracebacks)."""
    while isinstance(e, ActivityError) and e.cause is not None:
        e = e.cause
    head = " · ".join((str(e).splitlines() or [type(e).__name__])[:lines])[:200]
    details = getattr(e, "details", None) or ()
    output = details[0] if details and isinstance(details[0], str) else ""
    hits = [l.strip() for l in output.splitlines()
            if _ERROR_LINE.search(l) and not l.lstrip().startswith("at ")]
    hits = list(dict.fromkeys(hits))[-3:]  # last few distinct ones: the script stops at its first fatal error
    return "\n".join([head, *(h[:240] for h in hits)])


class _FinanceSync:
    """The sync's state and flow, shared by FinanceSyncWorkflow and the AMEX-only wrapper."""

    def __init__(self) -> None:
        self._phase = "starting"
        self._results: dict = {}
        self._published: dict = {}  # source -> last status sent to the dashboard
        self._steps: dict = {}
        self._counts: dict = {}  # source -> {"records", "records_before", "latest_txn"} from the dump gate
        self._log: dict = {}  # source -> [{"status", "at"}] for this run, the dashboard's timeline
        self._resumed = False
        self._all = False  # a signal without names re-checks every dead source
        self._named: set = set()
        self._pushed_failures: set = set()  # (source, status) already pushed, one push each per run
        self._requested: set = set()  # sources named when the run was started (empty: scheduled run)
        self._otp_waiting: str | None = None  # the source whose dump is waiting for a code

    async def submit_otp(self, source: str, code: str) -> None:
        """The human typed a code in the app. Ignored unless that source's login is waiting for one."""
        if source != self._otp_waiting or not (code or "").isdigit() or not 4 <= len(code) <= 8:
            return
        self._otp_waiting = None  # one code per login: a second submit is not relayed
        await workflow.execute_activity("deliver_otp", args=[source, code], **QUICK)
        await self._set(source, "scraping", f"{sources.LABEL_HE[source]}: הקוד התקבל — מתחבר")

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

    def _res(self, source: str, status: str, detail: str = "") -> None:
        self._results[source] = {"status": status, "detail": detail}

    async def _set(self, source: str, status: str, message: str | None = None, error: str | None = None) -> None:
        """Publish one source's status to the dashboard. Never fails the workflow."""
        self._published[source] = status
        step, text = STEPS[status]
        if step is not None:
            self._steps[source] = step
        info = workflow.info()
        now = workflow.now().isoformat()
        log = self._log.setdefault(source, [])
        if not log or log[-1]["status"] != status:
            log.append({"status": status, "at": now})
        counts = self._counts.get(source) or {}
        entry = {
            "status": status,
            "message": message or text.format(name=sources.LABEL_HE[source]),
            "step": self._steps.get(source),
            "total_steps": TOTAL_STEPS,
            "workflow_id": info.workflow_id,
            "run_id": info.run_id,
            "started_at": info.start_time.isoformat(),
            "updated_at": now,
            "error": error,
            "records": counts.get("records"),
            "records_before": counts.get("records_before"),
            "latest_txn": counts.get("latest_txn"),
            "log": list(log),
        }
        try:
            await workflow.execute_activity("publish_status", args=[source, entry], **STATUS)
        except ActivityError:
            pass
        if status in (FAILED, REJECTED) and (source, status) not in self._pushed_failures:
            self._pushed_failures.add((source, status))
            await self._push("push_event", push.failure_payload(source, sources.LABEL_HE[source], status, error))

    async def _say(self, title: str, message: str, pushes: list | None = None) -> None:
        """macOS banner, plus Web Push for each payload in `pushes`."""
        await workflow.execute_activity("notify", args=[title, message, pushes or []], **NOTIFY)

    async def _push(self, activity_name: str, *args) -> None:
        """A best-effort Web Push activity: one attempt, any failure is swallowed."""
        try:
            await workflow.execute_activity(activity_name, args=list(args), **NOTIFY)
        except ActivityError:
            pass

    async def _probe(self, source: str) -> str:
        """ensure_chrome + check_session -> "live" | "dead" | "unknown" | "failed".
        A check that cannot run is unknown, never dead: only a positive logged-out signal pages the human."""
        try:
            await workflow.execute_activity("ensure_chrome", source, **QUICK)
        except ActivityError as e:
            self._res(source, FAILED, f"Chrome unavailable: {_detail(e)}")
            await self._set(source, "failed", error=f"Chrome unavailable: {_reason(e)}")
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

    async def _scrape_one(self, source: str, unverified: bool, login: bool = False) -> str:
        """scrape (or, with `login`, log in with the app's code and scrape) + validate.
        Returns "ok" | "needs_login" | "failed" | "rejected"."""
        name = sources.LABEL_HE[source]
        self._res(source, "scraping")
        try:
            if login:
                self._otp_waiting = source
                await self._set(source, "waiting_for_otp")
                await self._say(LOGIN_TITLE, f"{source}: enter the SMS code in the app (/syncs)", [
                    {"title": "נדרש קוד SMS", "body": f"{name}: הזן את הקוד באפליקציה",
                     "url": "/syncs", "tag": f"login-{source}"}])
                try:
                    await workflow.execute_activity("scrape_login", source, **LOGIN)
                finally:
                    self._otp_waiting = None
            else:
                await self._set(source, "scraping")
                await workflow.execute_activity("scrape", source, **SCRAPE)
        except ActivityError as e:
            kind, _ = _cause(e)
            if kind == "SessionExpired":
                if login:
                    self._res(source, NEEDS_LOGIN, _detail(e))
                    await self._set(source, "needs_login", f"{name}: ההתחברות לא הושלמה — נסה שוב", error=_reason(e))
                    return NEEDS_LOGIN
                self._res(source, NEEDS_LOGIN, "session expired during scrape")
                await self._set(source, "needs_login", f"{name}: החיבור פג באמצע ההורדה — התחבר והפעל שוב")
                return NEEDS_LOGIN
            self._res(source, FAILED, _detail(e))
            await self._set(source, "failed", f"{name}: ההורדה נכשלה", error=_reason(e))
            return FAILED
        self._res(source, "validating")
        await self._set(source, "validating")
        try:
            gate = await workflow.execute_activity("validate_dump", source, **VALIDATE)
            if isinstance(gate, dict):  # older workers returned a bare "ok"
                self._counts[source] = gate
                gate = gate.get("gate", "ok")
        except ActivityError as e:
            self._res(source, REJECTED, _detail(e))
            await self._set(source, "rejected", error=_reason(e, lines=3))
            return REJECTED
        note = "session unverified; " if unverified else ""
        self._res(source, OK, f"{note}scraped, validation {gate}")
        return OK

    async def run(self, requested=None, opts=None) -> dict:
        try:
            return await self._run(requested, opts or {})
        except Exception as e:
            # Anything not already reported (digest/publish failures) still reaches
            # the dashboard as `failed` for every source that was mid-run.
            for s, status in list(self._published.items()):
                if status not in TERMINAL:
                    await self._set(s, "failed", error=_reason(e))
            raise

    async def _run(self, requested=None, opts=None) -> dict:
        try:
            order = sources.ordered(requested)
        except ValueError as e:
            raise ApplicationError(str(e), non_retryable=True)
        self._results = {s: {"status": PENDING, "detail": ""} for s in order}
        self._requested = set(order) if requested else set()
        if (opts or {}).get("resume") == "digest":
            if not requested:
                raise ApplicationError("resume needs named sources", non_retryable=True)
            for s in order:  # scraped and validated by the run that failed later
                self._res(s, OK, "resumed at digest")
            return await self._finish(order)

        # 1. Preflight: every session, before anything is scraped.
        self._phase = "preflight"
        state = {}
        for s in order:
            await self._set(s, "checking_session")
            state[s] = await self._probe(s)
            if state[s] == "dead" and sources.get(s).otp and s in self._requested:
                state[s] = "otp"  # started from the app: log in with a code there, no Chrome wait

        # 2. One grouped notification, one wait. The human logs in once per group.
        dead = [s for s in order if state[s] == "dead"]
        if dead:
            self._phase = "waiting_for_login"
            for s in order:
                if state[s] == "dead":
                    await self._set(s, "waiting_for_login")
                elif state[s] in ("live", "unknown"):  # connected, but queued behind the wait
                    await self._set(s, "checking_session", f"{sources.LABEL_HE[s]}: החיבור תקין — בתור לסנכרון")
            await self._say(LOGIN_TITLE, self._login_message(dead),
                            push.login_payloads(sources.login_groups(dead), sources.LABEL_HE))
            try:
                await workflow.wait_condition(lambda: self._resumed, timeout=LOGIN_WAIT)
            except TimeoutError:
                pass
            if self._resumed:
                self._phase = "rechecking"
                for s in (d for d in dead if self._was_named(d)):
                    await self._set(s, "checking_session")
                    state[s] = await self._probe(s)
            for s in dead:
                if state[s] == "dead":
                    self._res(s, NEEDS_LOGIN, "still logged out" if self._resumed else "no login within 15m")
                    await self._set(s, "needs_login")

        # 3. Scrape in registry order (Discount: business -> mortgage -> checking).
        self._phase = "scraping"
        expired_groups: dict = {}
        for s in order:
            if state[s] not in ("live", "unknown", "otp"):
                continue
            group = sources.get(s).group
            if group in expired_groups:
                self._res(s, NEEDS_LOGIN, f"login expired while scraping {expired_groups[group]}")
                await self._set(s, "needs_login")
                continue
            if await self._scrape_one(s, unverified=state[s] == "unknown", login=state[s] == "otp") == NEEDS_LOGIN:
                expired_groups[group] = s

        return await self._finish(order)

    async def _finish(self, order: list) -> dict:
        # 4. Digest and publish once. A rejected dump is already on disk and the digest
        #    reads it, so the numbers are not published until that source is sorted out.
        scraped = [s for s in order if self._results[s]["status"] == OK]
        rejected = [s for s in order if self._results[s]["status"] == REJECTED]
        finish = None
        if scraped:
            try:
                self._phase = "digesting"
                for s in scraped:
                    await self._set(s, "digesting")
                summary = await workflow.execute_activity("digest", **DIGEST)
                if rejected:
                    published = f"withheld (rejected: {', '.join(rejected)})"
                else:
                    self._phase = "publishing"
                    for s in scraped:
                        await self._set(s, "publishing")
                    published = await workflow.execute_activity("publish_data", **PUBLISH)
            except ActivityError:
                self._phase = "failed"
                await self._say("Finance sync", "Digest/publish failed - see Temporal UI (localhost:8233)")
                raise
            finish = {"digest": summary, "published": published}
            n = (summary or {}).get("transactions")
            for s in scraped:
                msg = f"{sources.LABEL_HE[s]}: הסנכרון הושלם" + (f" · {n:,} עסקאות" if n else "")
                if rejected:  # scraped fine, but the numbers are not pushed while a bad dump is on disk
                    msg += " · הפרסום לדשבורד הוחזק (נתונים שנדחו)"
                await self._set(s, "done", msg)

        if finish:  # new לטיפול items, and the evening summary (the activity decides from the start time)
            await self._push("push_new_actions")
            await self._push("push_daily_summary", workflow.info().start_time.isoformat())

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

    @workflow.signal
    async def submit_otp(self, source: str, code: str) -> None:
        """A login code the human typed in the app (api POST /api/sync/{source}/otp)."""
        await self._sync.submit_otp(source, code)

    @workflow.query
    def status(self) -> dict:
        return self._sync.status()

    @workflow.run
    async def run(self, sources: list[str] | None = None, opts: dict | None = None) -> dict:
        return await self._sync.run(sources, opts)


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


# --- LedgerRebuildWorkflow ----------------------------------------------------------------
# Defaults; tests (and anyone who needs to) override them through the optional `opts` arg of
# run(), because the workflow sandbox re-imports this module and ignores monkeypatching.
REBUILD_ID = "ledger-rebuild"
REBUILD_DEBOUNCE = timedelta(seconds=20)
REBUILD_IDLE = timedelta(minutes=10)
REBUILD_MAX_PASSES = 5  # continue-as-new after this many passes so history stays small


@workflow.defn(name="LedgerRebuildWorkflow")
class LedgerRebuildWorkflow:
    """Debounced rebuild after ledger edits (docs/ledger-api.md, "Rebuild workflow").

    The API signal-with-starts this under id `ledger-rebuild` on every edit. It waits until
    REBUILD_DEBOUNCE passes with no new `edited` signal, then runs `digest` (no re-normalize:
    an edit only changes overrides) and `publish_data`. Signals that arrive during a run queue
    exactly one more pass. After REBUILD_IDLE with no signals it returns, so the next
    signal-with-start begins a fresh run. A failed pass records `last_error` and goes idle; it
    never crashes the workflow, and the activities' RetryPolicies are bounded.

    `status` query -> {"state": "idle"|"pending"|"running", "last_published_at": iso|null,
    "last_error": str|null}.
    """

    def __init__(self) -> None:
        self._signals = 0  # total `edited` signals seen this run
        self._handled = 0  # signals covered by a pass that has started
        self._state = "idle"
        self._last_published_at: str | None = None
        self._last_error: str | None = None

    @workflow.signal
    def edited(self) -> None:
        self._signals += 1
        if self._state == "idle":
            self._state = "pending"

    @workflow.query
    def status(self) -> dict:
        return {
            "state": self._state,
            "last_published_at": self._last_published_at,
            "last_error": self._last_error,
        }

    async def _debounce(self, quiet: timedelta) -> None:
        """Return once `quiet` passes with no new signal."""
        while True:
            seen = self._signals
            try:
                await workflow.wait_condition(lambda: self._signals != seen, timeout=quiet)
            except TimeoutError:
                return

    async def _pass(self) -> None:
        self._state = "running"
        self._handled = self._signals
        try:
            await workflow.execute_activity("digest", args=[False], **DIGEST)
            await workflow.execute_activity("publish_data", **PUBLISH)
            self._last_published_at = workflow.now().isoformat()
            self._last_error = None
        except ActivityError as e:
            cause = e.cause
            self._last_error = str(getattr(cause, "message", None) or cause or e)
        finally:
            # A signal that landed mid-run stays "pending"; otherwise we are idle.
            self._state = "pending" if self._signals > self._handled else "idle"

    @workflow.run
    async def run(self, opts: dict | None = None) -> dict:
        """`opts` is optional (the API sends none): debounce_seconds, idle_seconds,
        max_passes override the constants; last_published_at / last_error are carried
        across continue-as-new."""
        opts = dict(opts or {})
        quiet = timedelta(seconds=opts.get("debounce_seconds", REBUILD_DEBOUNCE.total_seconds()))
        idle = timedelta(seconds=opts.get("idle_seconds", REBUILD_IDLE.total_seconds()))
        max_passes = opts.get("max_passes", REBUILD_MAX_PASSES)
        self._last_published_at = opts.get("last_published_at")
        self._last_error = opts.get("last_error")
        passes = 0

        while True:
            try:
                await workflow.wait_condition(lambda: self._signals > self._handled, timeout=idle)
            except TimeoutError:
                return {"passes": passes, **self.status()}
            self._state = "pending"
            await self._debounce(quiet)
            await self._pass()
            passes += 1
            if passes >= max_passes and self._signals == self._handled:
                workflow.continue_as_new(opts | {
                    "last_published_at": self._last_published_at,
                    "last_error": self._last_error,
                })
