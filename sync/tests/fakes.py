"""Mocked activities + a time-skipping runner shared by the workflow tests."""
import asyncio
import uuid

from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from workflows import AmexSyncWorkflow, FinanceSyncWorkflow, LedgerRebuildWorkflow

QUEUE = "test-queue"


def expired(msg="expired"):
    return ApplicationError(msg, type="SessionExpired", non_retryable=True)


def moved(msg="endpoint moved"):
    return ApplicationError(msg, "tail of dump output", type="ScrapeFailed", non_retryable=True)


def rejected(msg="validate.py rejected the dump:\ncal: 0 transactions"):
    return ApplicationError(msg, type="ValidationFailed", non_retryable=True)


class Fake:
    """Records activity calls as tuples.

    sessions        {source: "live"|"dead"|"unknown" | [consumed one per check, last repeats]}; default live
    scrape_errors   {source: exception}
    validate_errors {source: exception}
    check_errors    sources whose check_session activity itself blows up
    chrome_errors   sources whose ensure_chrome fails
    digest_error    exception raised by the digest activity
    status_error    make every publish_status call blow up (it must never fail the sync)
    """

    def __init__(self, sessions=None, scrape_errors=None, validate_errors=None, check_errors=(), chrome_errors=(),
                 digest_error=None, status_error=False, digest_delay=0.0):
        self.sessions = {k: list(v) if isinstance(v, list) else [v] for k, v in (sessions or {}).items()}
        self.scrape_errors = scrape_errors or {}
        self.validate_errors = validate_errors or {}
        self.check_errors = set(check_errors)
        self.chrome_errors = set(chrome_errors)
        self.digest_error = digest_error
        self.digest_delay = digest_delay  # real seconds the digest activity takes
        self.digest_args = []  # the `normalize` flag of each digest call
        self.status_error = status_error
        self.calls = []
        self.statuses = []  # every publish_status (source, entry), in order

    # --- helpers for assertions
    def of(self, kind):
        return [c[1] for c in self.calls if c[0] == kind and len(c) > 1]

    def published(self, source):
        """The statuses published for one source, in order."""
        return [e["status"] for s, e in self.statuses if s == source]

    def notes(self):
        return [(c[1], c[2]) for c in self.calls if c[0] == "notify"]

    def login_notes(self):
        return [m for t, m in self.notes() if "login needed" in t]

    def activities(self):
        @activity.defn(name="ensure_chrome")
        async def ensure_chrome(source: str) -> str:
            self.calls.append(("ensure_chrome", source))
            if source in self.chrome_errors:
                raise ApplicationError("Chrome did not open CDP port", non_retryable=True)
            return "already_running"

        @activity.defn(name="check_session")
        async def check_session(source: str) -> str:
            self.calls.append(("check", source))
            if source in self.check_errors:
                raise ApplicationError("check_sessions.sh printed no row", non_retryable=True)
            seq = self.sessions.get(source, ["live"])
            return seq.pop(0) if len(seq) > 1 else seq[0]

        @activity.defn(name="scrape")
        async def scrape(source: str) -> str:
            self.calls.append(("scrape", source))
            if source in self.scrape_errors:
                raise self.scrape_errors[source]
            return "ok"

        @activity.defn(name="validate_dump")
        async def validate_dump(source: str) -> str:
            self.calls.append(("validate", source))
            if source in self.validate_errors:
                raise self.validate_errors[source]
            return "ok"

        @activity.defn(name="digest")
        async def digest(normalize: bool = True) -> dict:
            self.calls.append(("digest",))
            self.digest_args.append(normalize)
            if self.digest_delay:
                await asyncio.sleep(self.digest_delay)
            if self.digest_error:
                raise self.digest_error
            return {"transactions": 42}

        @activity.defn(name="publish_data")
        async def publish_data() -> str:
            self.calls.append(("publish",))
            return "published"

        @activity.defn(name="notify")
        async def notify(title: str, message: str) -> None:
            self.calls.append(("notify", title, message))

        @activity.defn(name="publish_status")
        async def publish_status(source: str, entry: dict) -> str:
            self.statuses.append((source, entry))
            if self.status_error:
                raise RuntimeError("bucket unreachable")
            return "local"

        return [ensure_chrome, check_session, scrape, validate_dump, digest, publish_data, notify, publish_status]


def run(fake, scenario, workflow=FinanceSyncWorkflow, args=()):
    async def go():
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(env.client, task_queue=QUEUE, workflows=[FinanceSyncWorkflow, AmexSyncWorkflow, LedgerRebuildWorkflow],
                              activities=fake.activities()):
                handle = await env.client.start_workflow(
                    workflow.run, args=list(args), id=f"wf-{uuid.uuid4()}", task_queue=QUEUE)
                return await scenario(env, handle)
    return asyncio.run(go())


def result_of(fake, args=(), workflow=FinanceSyncWorkflow):
    return run(fake, lambda env, h: h.result(), workflow=workflow, args=args)


async def until_phase(handle, workflow_cls, phase, tries=200):
    for _ in range(tries):
        if (await handle.query(workflow_cls.status))["phase"] == phase:
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"never reached phase {phase}")
