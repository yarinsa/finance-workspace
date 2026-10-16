import asyncio
import uuid
from datetime import timedelta

from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from workflows import AmexSyncWorkflow

QUEUE = "test-queue"


class Fake:
    """Records activity calls; `live` is a list consumed one per session check."""

    def __init__(self, live, scrape_error=None):
        self.live = list(live)
        self.scrape_error = scrape_error
        self.calls = []

    def activities(self):
        @activity.defn(name="ensure_chrome")
        async def ensure_chrome() -> str:
            self.calls.append("ensure_chrome")
            return "already_running"

        @activity.defn(name="check_amex_session")
        async def check_amex_session() -> bool:
            self.calls.append("check")
            return self.live.pop(0)

        @activity.defn(name="scrape_amex")
        async def scrape_amex() -> str:
            self.calls.append("scrape")
            if self.scrape_error:
                raise self.scrape_error
            return "ok"

        @activity.defn(name="digest")
        async def digest() -> dict:
            self.calls.append("digest")
            return {"transactions": 42}

        @activity.defn(name="publish_data")
        async def publish_data() -> str:
            self.calls.append("publish")
            return "published"

        @activity.defn(name="notify")
        async def notify(title: str, message: str) -> None:
            self.calls.append("notify:" + message)

        return [ensure_chrome, check_amex_session, scrape_amex, digest, publish_data, notify]


def run(fake, scenario):
    async def go():
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(env.client, task_queue=QUEUE, workflows=[AmexSyncWorkflow],
                              activities=fake.activities()):
                handle = await env.client.start_workflow(
                    AmexSyncWorkflow.run, id=f"wf-{uuid.uuid4()}", task_queue=QUEUE)
                return await scenario(env, handle)
    return asyncio.run(go())


def steps(fake):
    return [c for c in fake.calls if not c.startswith("notify")]


def test_live_path_scrapes_digests_publishes():
    fake = Fake([True])
    result = run(fake, lambda env, h: h.result())
    assert result["status"] == "ok"
    assert steps(fake) == ["ensure_chrome", "check", "scrape", "digest", "publish"]
    assert any("42 transactions" in c for c in fake.calls if c.startswith("notify"))


def test_dead_session_notifies_then_resumes_on_signal():
    fake = Fake([False, True])

    async def scenario(env, h):
        for _ in range(100):  # wait until it is parked on the login wait
            if await h.query(AmexSyncWorkflow.status) == "waiting_for_login":
                break
            await asyncio.sleep(0.05)
        assert "scrape" not in fake.calls
        await h.signal(AmexSyncWorkflow.session_refreshed)
        return await h.result()

    result = run(fake, scenario)
    assert result["status"] == "ok"
    assert any("python3 sync/resume.py" in c for c in fake.calls)
    assert steps(fake) == ["ensure_chrome", "check", "ensure_chrome", "check", "scrape", "digest", "publish"]


def test_dead_session_times_out_after_12h_without_scraping():
    fake = Fake([False])

    async def scenario(env, h):
        return await h.result()  # time-skipping fast-forwards the 12h timer

    result = run(fake, scenario)
    assert result == {"status": "needs_login"}
    assert not {"scrape", "digest", "publish"} & set(fake.calls)


def test_signal_but_still_dead_returns_needs_login():
    fake = Fake([False, False])

    async def scenario(env, h):
        await h.signal(AmexSyncWorkflow.session_refreshed)
        return await h.result()

    assert run(fake, scenario)["status"] == "needs_login"
    assert "scrape" not in fake.calls


def test_session_expired_in_scrape_is_not_retried():
    err = ApplicationError("expired", type="SessionExpired", non_retryable=True)
    fake = Fake([True], scrape_error=err)
    result = run(fake, lambda env, h: h.result())
    assert result["status"] == "needs_login"
    assert fake.calls.count("scrape") == 1
    assert "digest" not in fake.calls
