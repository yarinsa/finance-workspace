"""AmexSyncWorkflow: scrape AMEX -> digest -> publish, without ever logging in.

If the session is dead the workflow notifies the human and waits (up to 12h) for
the `session_refreshed` signal (sent by sync/resume.py after they log in).
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

RESUME_HINT = ("AMEX session expired - log in in the AMEX Chrome window, "
               "then run `python3 sync/resume.py`")


@workflow.defn
class AmexSyncWorkflow:
    def __init__(self) -> None:
        self._resumed = False
        self._status = "starting"

    @workflow.signal
    def session_refreshed(self) -> None:
        self._resumed = True

    @workflow.query
    def status(self) -> str:
        return self._status

    async def _live(self) -> bool:
        self._status = "checking_session"
        await workflow.execute_activity("ensure_chrome", **QUICK)
        return await workflow.execute_activity("check_amex_session", **QUICK)

    async def _say(self, title: str, message: str) -> None:
        await workflow.execute_activity("notify", args=[title, message], **NOTIFY)

    @workflow.run
    async def run(self) -> dict:
        if not await self._live():
            self._status = "waiting_for_login"
            await self._say("Finance sync", RESUME_HINT)
            try:
                await workflow.wait_condition(lambda: self._resumed, timeout=LOGIN_WAIT)
            except TimeoutError:
                pass
            if not self._resumed or not await self._live():
                self._status = "needs_login"
                await self._say("Finance sync", "AMEX still logged out - sync skipped")
                return {"status": "needs_login"}

        try:
            self._status = "scraping"
            await workflow.execute_activity("scrape_amex", **SCRAPE)
        except ActivityError as e:
            self._status = "failed"
            cause = e.cause
            if isinstance(cause, ApplicationError) and cause.type == "SessionExpired":
                await self._say("Finance sync", "AMEX session died mid-scrape - log in and re-trigger")
                return {"status": "needs_login", "reason": "session expired during scrape"}
            await self._say("Finance sync", "AMEX scrape failed - see Temporal UI (localhost:8233)")
            raise

        self._status = "digesting"
        summary = await workflow.execute_activity("digest", **DIGEST)
        self._status = "publishing"
        published = await workflow.execute_activity("publish_data", **PUBLISH)
        self._status = "done"
        n = (summary or {}).get("transactions")
        await self._say("Finance sync", f"AMEX synced ({published})" + (f", {n} transactions" if n else ""))
        return {"status": "ok", "published": published, "digest": summary}
