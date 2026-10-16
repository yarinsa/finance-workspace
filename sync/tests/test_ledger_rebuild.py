"""LedgerRebuildWorkflow: debounced digest (--no-normalize) + publish after ledger edits,
plus the digest file lock shared with FinanceSyncWorkflow."""
import asyncio
import time

from temporalio.exceptions import ApplicationError

import activities
from fakes import Fake, run
from workflows import LedgerRebuildWorkflow as W


async def until(env, cond, tries=200):
    """Poll `cond` (async), advancing the test env's clock so the debounce timer can fire."""
    for _ in range(tries):
        if await cond():
            return
        await env.sleep(1)
    raise AssertionError("condition never became true")


async def settle(env, handle, state):
    async def reached():
        return (await handle.query(W.status))["state"] == state
    await until(env, reached)


def test_burst_of_signals_runs_one_digest_and_one_publish():
    fake = Fake()

    async def scenario(env, h):
        for _ in range(3):
            await h.signal(W.edited)
        return await h.result()

    result = run(fake, scenario, workflow=W)
    assert [c[0] for c in fake.calls] == ["digest", "publish"]
    assert fake.digest_args == [False]  # edits only change overrides: no re-normalize
    assert result["passes"] == 1 and result["state"] == "idle"
    assert result["last_published_at"] and result["last_error"] is None


def test_signal_during_a_run_queues_one_more_pass():
    fake = Fake(digest_delay=0.4)

    async def scenario(env, h):
        await h.signal(W.edited)
        await settle(env, h, "running")
        await h.signal(W.edited)
        await h.signal(W.edited)  # two mid-run signals still mean a single extra pass
        assert (await h.query(W.status))["state"] == "running"
        return await h.result()

    result = run(fake, scenario, workflow=W)
    assert [c[0] for c in fake.calls] == ["digest", "publish", "digest", "publish"]
    assert result["passes"] == 2


def test_status_goes_pending_running_pending_idle():
    fake = Fake(digest_delay=0.4)
    seen = []

    async def scenario(env, h):
        assert (await h.query(W.status)) == {"state": "idle", "last_published_at": None, "last_error": None}
        await h.signal(W.edited)
        seen.append((await h.query(W.status))["state"])
        await settle(env, h, "running")
        seen.append("running")
        await h.signal(W.edited)
        seen.append((await h.query(W.status))["state"])  # still running until the pass ends
        await settle(env, h, "pending")
        seen.append("pending")
        return await h.result()

    result = run(fake, scenario, workflow=W)
    assert seen == ["pending", "running", "running", "pending"]
    assert result["state"] == "idle"


def test_activity_failure_sets_last_error_and_goes_idle():
    fake = Fake(digest_error=ApplicationError("forecast.py failed (rc=1)", non_retryable=True))

    async def scenario(env, h):
        await h.signal(W.edited)
        await settle(env, h, "pending")
        await settle(env, h, "idle")  # idle again, not crashed
        status = await h.query(W.status)
        return status, await h.result()

    status, result = run(fake, scenario, workflow=W)
    assert "forecast.py failed" in status["last_error"]
    assert status["last_published_at"] is None
    assert ("publish",) not in fake.calls
    assert result["state"] == "idle"  # the workflow itself completed normally


def test_next_edit_after_a_failure_recovers():
    fake = Fake(digest_error=ApplicationError("boom", non_retryable=True))

    async def scenario(env, h):
        await h.signal(W.edited)
        await h.signal(W.edited)
        # wait for the failed pass to finish, then fix the cause and edit again
        async def failed():
            return bool((await h.query(W.status))["last_error"])
        await until(env, failed)
        fake.digest_error = None
        await h.signal(W.edited)
        return await h.result()

    result = run(fake, scenario, workflow=W)
    assert result["last_error"] is None and result["last_published_at"]


def test_idle_timeout_completes_the_workflow():
    fake = Fake()
    result = run(fake, lambda env, h: h.result(), workflow=W)  # no signal: 10 min idle, time-skipped
    assert result == {"passes": 0, "state": "idle", "last_published_at": None, "last_error": None}
    assert fake.calls == []


def test_debounce_restarts_on_every_signal():
    fake = Fake()

    async def scenario(env, h):
        await h.signal(W.edited)
        await env.sleep(15)  # inside the 20 s window
        await h.signal(W.edited)
        await env.sleep(15)  # 30 s after the first signal, 15 after the second
        assert fake.calls == []
        return await h.result()

    run(fake, scenario, workflow=W)
    assert [c[0] for c in fake.calls] == ["digest", "publish"]


def test_continues_as_new_after_max_passes_and_keeps_status():
    fake = Fake()

    async def scenario(env, h):
        for i in range(1, 4):
            await h.signal(W.edited)

            async def pass_done():
                return len(fake.calls) >= 2 * i
            await until(env, pass_done)
        return await h.result()

    result = run(fake, scenario, workflow=W, args=[{"max_passes": 2}])
    assert fake.calls.count(("digest",)) == 3
    assert result["last_published_at"]  # carried across the continue-as-new


# --- digest file lock --------------------------------------------------------------------

def test_lock_serializes_concurrent_holders(tmp_path):
    lock = tmp_path / "digested" / ".lock"
    inside, peak, order = 0, 0, []

    async def holder(name):
        nonlocal inside, peak
        async with activities.digest_lock(lock, poll=0.01):
            inside += 1
            peak = max(peak, inside)
            order.append(f"{name}+")
            await asyncio.sleep(0.15)
            order.append(f"{name}-")
            inside -= 1

    async def both():
        t = time.monotonic()
        await asyncio.gather(holder("a"), holder("b"))
        return time.monotonic() - t

    elapsed = asyncio.run(both())
    assert peak == 1
    first = order[0][0]
    assert order[1] == f"{first}-"  # the first holder leaves before the second enters
    assert elapsed >= 0.3


def test_lock_is_released_when_the_holder_raises(tmp_path):
    lock = tmp_path / ".lock"

    async def go():
        try:
            async with activities.digest_lock(lock, poll=0.01):
                raise RuntimeError("digest failed")
        except RuntimeError:
            pass
        async with activities.digest_lock(lock, poll=0.01):
            return "reacquired"

    assert asyncio.run(asyncio.wait_for(go(), 2)) == "reacquired"
