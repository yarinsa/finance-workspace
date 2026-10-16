"""AmexSyncWorkflow: scrape AMEX -> digest -> publish, without ever logging in.

If the session is dead the workflow notifies the human and waits (up to 12h) for
the `session_refreshed` signal (sent by sync/resume.py after they log in).

Every status change is also published (publish_status) to sync-status.json, which
the dashboard polls to show what the sync is doing right now.
"""
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError

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

SOURCE = "amex"
TOTAL_STEPS = 4
# status -> (step, short text shown on the dashboard)
STEPS = {
    "checking_session": (1, "בודק חיבור לאמריקן אקספרס"),
    "waiting_for_login": (1, "ממתין שתתחבר לאמריקן אקספרס ב-Chrome במק"),
    "scraping": (2, "מוריד עסקאות מאמריקן אקספרס"),
    "digesting": (3, "בונה מחדש את הנתונים"),
    "publishing": (4, "מפרסם לדשבורד"),
    "done": (4, "הסנכרון הושלם"),
    "needs_login": (1, "לא בוצע סנכרון — נדרשת התחברות"),
    "failed": (None, "הסנכרון נכשל"),
}
TERMINAL = {"done", "needs_login", "failed"}

RESUME_HINT = ("AMEX session expired - log in in the AMEX Chrome window, "
               "then run `python3 sync/resume.py`")


@workflow.defn
class AmexSyncWorkflow:
    def __init__(self) -> None:
        self._resumed = False
        self._status = "starting"
        self._step = None

    @workflow.signal
    def session_refreshed(self) -> None:
        self._resumed = True

    @workflow.query
    def status(self) -> str:
        return self._status

    async def _set(self, status: str, message: str | None = None, error: str | None = None) -> None:
        """Change status and publish it. Publishing never fails the workflow."""
        self._status = status
        step, text = STEPS[status]
        if step is not None:
            self._step = step
        info = workflow.info()
        entry = {
            "status": status,
            "message": message or text,
            "step": self._step,
            "total_steps": TOTAL_STEPS,
            "workflow_id": info.workflow_id,
            "run_id": info.run_id,
            "started_at": info.start_time.isoformat(),
            "updated_at": workflow.now().isoformat(),
            "error": error,
        }
        try:
            await workflow.execute_activity("publish_status", args=[SOURCE, entry], **STATUS)
        except ActivityError:
            pass

    async def _live(self) -> bool:
        await self._set("checking_session")
        await workflow.execute_activity("ensure_chrome", **QUICK)
        return await workflow.execute_activity("check_amex_session", **QUICK)

    async def _say(self, title: str, message: str) -> None:
        await workflow.execute_activity("notify", args=[title, message], **NOTIFY)

    @workflow.run
    async def run(self) -> dict:
        try:
            return await self._run()
        except Exception as e:
            # Anything not already reported (digest/publish failures, Chrome
            # never coming up) still reaches the dashboard as `failed`.
            if self._status not in TERMINAL:
                await self._set("failed", error=_reason(e))
            raise

    async def _run(self) -> dict:
        if not await self._live():
            await self._set("waiting_for_login")
            await self._say("Finance sync", RESUME_HINT)
            try:
                await workflow.wait_condition(lambda: self._resumed, timeout=LOGIN_WAIT)
            except TimeoutError:
                pass
            if not self._resumed or not await self._live():
                await self._set("needs_login")
                await self._say("Finance sync", "AMEX still logged out - sync skipped")
                return {"status": "needs_login"}

        try:
            await self._set("scraping")
            await workflow.execute_activity("scrape_amex", **SCRAPE)
        except ActivityError as e:
            cause = e.cause
            if isinstance(cause, ApplicationError) and cause.type == "SessionExpired":
                await self._set("needs_login", "החיבור לאמריקן אקספרס פג באמצע ההורדה — התחבר והפעל שוב")
                await self._say("Finance sync", "AMEX session died mid-scrape - log in and re-trigger")
                return {"status": "needs_login", "reason": "session expired during scrape"}
            await self._set("failed", "ההורדה מאמריקן אקספרס נכשלה", error=_reason(e))
            await self._say("Finance sync", "AMEX scrape failed - see Temporal UI (localhost:8233)")
            raise

        await self._set("digesting")
        summary = await workflow.execute_activity("digest", **DIGEST)
        await self._set("publishing")
        published = await workflow.execute_activity("publish_data", **PUBLISH)
        n = (summary or {}).get("transactions")
        await self._set("done", f"הסנכרון הושלם · {n:,} עסקאות" if n else None)
        await self._say("Finance sync", f"AMEX synced ({published})" + (f", {n} transactions" if n else ""))
        return {"status": "ok", "published": published, "digest": summary}


def _reason(e: BaseException) -> str:
    """One short line for the dashboard: the root cause's message, no tracebacks."""
    while isinstance(e, ActivityError) and e.cause is not None:
        e = e.cause
    return (str(e).splitlines() or [type(e).__name__])[0][:200]
