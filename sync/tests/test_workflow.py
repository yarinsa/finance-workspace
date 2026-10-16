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

    def __init__(self, live, scrape_error=None, digest_error=None, status_error=False):
        self.live = list(live)
        self.scrape_error = scrape_error
        self.digest_error = digest_error
        self.status_error = status_error
        self.calls = []
        self.statuses = []  # every publish_status entry, in order

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
            if self.digest_error:
                raise self.digest_error
            return {"transactions": 42}

        @activity.defn(name="publish_data")
        async def publish_data() -> str:
            self.calls.append("publish")
            return "published"

        @activity.defn(name="notify")
        async def notify(title: str, message: str) -> None:
            self.calls.append("notify:" + message)

        @activity.defn(name="publish_status")
        async def publish_status(source: str, entry: dict) -> str:
            self.statuses.append((source, entry))
            if self.status_error:
                raise RuntimeError("bucket unreachable")
            return "local"

        return [ensure_chrome, check_amex_session, scrape_amex, digest, publish_data, notify, publish_status]


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


def published(fake):
    return [e["status"] for _, e in fake.statuses]


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


# --- live status (sync-status.json) -------------------------------------------

def test_happy_path_publishes_every_step_in_order():
    fake = Fake([True])
    run(fake, lambda env, h: h.result())
    assert published(fake) == ["checking_session", "scraping", "digesting", "publishing", "done"]
    assert {s for s, _ in fake.statuses} == {"amex"}
    done = fake.statuses[-1][1]
    assert done["step"] == done["total_steps"] == 4
    assert "42" in done["message"]
    assert done["workflow_id"] and done["run_id"] and done["started_at"] and done["updated_at"]


def test_login_wait_is_published_before_parking():
    fake = Fake([False, True])

    async def scenario(env, h):
        for _ in range(100):
            if await h.query(AmexSyncWorkflow.status) == "waiting_for_login":
                break
            await asyncio.sleep(0.05)
        assert published(fake)[-1] == "waiting_for_login"
        await h.signal(AmexSyncWorkflow.session_refreshed)
        return await h.result()

    run(fake, scenario)
    assert published(fake) == ["checking_session", "waiting_for_login", "checking_session",
                               "scraping", "digesting", "publishing", "done"]


def test_timeout_publishes_needs_login():
    fake = Fake([False])
    run(fake, lambda env, h: h.result())
    assert published(fake)[-1] == "needs_login"


def test_session_expired_mid_scrape_publishes_needs_login():
    err = ApplicationError("expired", type="SessionExpired", non_retryable=True)
    fake = Fake([True], scrape_error=err)
    run(fake, lambda env, h: h.result())
    assert published(fake)[-1] == "needs_login"


def test_scrape_failure_publishes_failed_with_reason():
    err = ApplicationError("dump.sh failed (rc=3)", type="ScrapeFailed", non_retryable=True)
    fake = Fake([True], scrape_error=err)

    async def scenario(env, h):
        try:
            await h.result()
        except Exception:
            return None

    run(fake, scenario)
    assert published(fake)[-1] == "failed"
    assert published(fake).count("failed") == 1
    assert "dump.sh failed" in fake.statuses[-1][1]["error"]


def test_digest_failure_still_publishes_failed():
    err = ApplicationError("digest.py failed (rc=1)", non_retryable=True)
    fake = Fake([True], digest_error=err)

    async def scenario(env, h):
        try:
            await h.result()
        except Exception:
            return None

    run(fake, scenario)
    assert published(fake)[-2:] == ["digesting", "failed"]
    assert fake.statuses[-1][1]["step"] == 3  # failed keeps the step it died on
    assert "digest.py failed" in fake.statuses[-1][1]["error"]


def test_status_publish_failure_never_fails_the_sync():
    fake = Fake([True], status_error=True)
    result = run(fake, lambda env, h: h.result())
    assert result["status"] == "ok"
    assert steps(fake) == ["ensure_chrome", "check", "scrape", "digest", "publish"]
