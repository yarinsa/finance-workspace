"""AmexSyncWorkflow, now a thin wrapper over FinanceSyncWorkflow(["amex"])."""
from temporalio.exceptions import ApplicationError

from fakes import Fake, expired, result_of, run, until_phase
from workflows import AmexSyncWorkflow


def test_live_path_scrapes_digests_publishes():
    fake = Fake()
    result = result_of(fake, workflow=AmexSyncWorkflow)
    assert result["amex"]["status"] == "ok"
    assert [c[0] for c in fake.calls if c[0] != "notify"] == [
        "ensure_chrome", "check", "scrape", "validate", "digest", "publish"]
    assert fake.of("scrape") == ["amex"]  # only amex, never the other eight
    assert any("42 transactions" in m for _, m in fake.notes())


def test_dead_session_notifies_then_resumes_on_signal():
    fake = Fake(sessions={"amex": ["dead", "live"]})

    async def scenario(env, h):
        await until_phase(h, AmexSyncWorkflow, "waiting_for_login")
        assert ("scrape", "amex") not in fake.calls
        await h.signal(AmexSyncWorkflow.session_refreshed)
        return await h.result()

    result = run(fake, scenario, workflow=AmexSyncWorkflow)
    assert result["amex"]["status"] == "ok"
    assert any("python3 sync/resume.py" in m for m in fake.login_notes())
    assert [c[0] for c in fake.calls if c[0] not in ("notify", "validate")] == [
        "ensure_chrome", "check", "ensure_chrome", "check", "scrape", "digest", "publish"]


def test_dead_session_times_out_after_15m_without_scraping():
    fake = Fake(sessions={"amex": "dead"})
    result = result_of(fake, workflow=AmexSyncWorkflow)  # time-skipping fast-forwards the 15m timer
    assert result == {"amex": {"status": "needs_login", "detail": "no login within 15m"}}
    assert not {"scrape", "digest", "publish"} & {c[0] for c in fake.calls}


def test_signal_but_still_dead_returns_needs_login():
    fake = Fake(sessions={"amex": ["dead", "dead"]})

    async def scenario(env, h):
        await h.signal(AmexSyncWorkflow.session_refreshed)
        return await h.result()

    assert run(fake, scenario, workflow=AmexSyncWorkflow)["amex"]["status"] == "needs_login"
    assert ("scrape", "amex") not in fake.calls


def test_session_expired_in_scrape_is_not_retried():
    fake = Fake(scrape_errors={"amex": expired()})
    result = result_of(fake, workflow=AmexSyncWorkflow)
    assert result["amex"]["status"] == "needs_login"
    assert fake.calls.count(("scrape", "amex")) == 1
    assert ("digest",) not in fake.calls


# --- live status (sync-status.json), adapted from the AMEX-only workflow -------

def test_happy_path_publishes_every_step_in_order():
    fake = Fake()
    result_of(fake, workflow=AmexSyncWorkflow)
    assert fake.published("amex") == ["checking_session", "scraping", "validating", "digesting", "publishing", "done"]
    assert {s for s, _ in fake.statuses} == {"amex"}
    done = fake.statuses[-1][1]
    assert done["step"] == done["total_steps"] == 5
    assert "42" in done["message"]
    assert done["workflow_id"] and done["run_id"] and done["started_at"] and done["updated_at"]


def test_login_wait_is_published_before_parking():
    fake = Fake(sessions={"amex": ["dead", "live"]})

    async def scenario(env, h):
        await until_phase(h, AmexSyncWorkflow, "waiting_for_login")
        assert fake.published("amex")[-1] == "waiting_for_login"
        await h.signal(AmexSyncWorkflow.session_refreshed)
        return await h.result()

    run(fake, scenario, workflow=AmexSyncWorkflow)
    assert fake.published("amex") == ["checking_session", "waiting_for_login", "checking_session",
                                      "scraping", "validating", "digesting", "publishing", "done"]


def test_timeout_publishes_needs_login():
    fake = Fake(sessions={"amex": "dead"})
    result_of(fake, workflow=AmexSyncWorkflow)
    assert fake.published("amex")[-1] == "needs_login"


def test_session_expired_mid_scrape_publishes_needs_login():
    fake = Fake(scrape_errors={"amex": expired()})
    result_of(fake, workflow=AmexSyncWorkflow)
    assert fake.published("amex")[-1] == "needs_login"


def test_scrape_failure_publishes_failed_with_reason():
    fake = Fake(scrape_errors={"amex": ApplicationError("dump.sh failed (rc=3)", type="ScrapeFailed", non_retryable=True)})
    result_of(fake, workflow=AmexSyncWorkflow)
    assert fake.published("amex")[-1] == "failed" and fake.published("amex").count("failed") == 1
    assert "dump.sh failed" in fake.statuses[-1][1]["error"]


def test_digest_failure_still_publishes_failed():
    fake = Fake(digest_error=ApplicationError("digest.py failed (rc=1)", non_retryable=True))

    async def scenario(env, h):
        try:
            await h.result()
        except Exception:
            return None

    run(fake, scenario, workflow=AmexSyncWorkflow)
    assert fake.published("amex")[-2:] == ["digesting", "failed"]
    assert fake.statuses[-1][1]["step"] == 4  # failed keeps the step it died on
    assert "digest.py failed" in fake.statuses[-1][1]["error"]


def test_status_publish_failure_never_fails_the_sync():
    fake = Fake(status_error=True)
    result = result_of(fake, workflow=AmexSyncWorkflow)
    assert result["amex"]["status"] == "ok"
    assert fake.of("scrape") == ["amex"]
