"""AmexSyncWorkflow, now a thin wrapper over FinanceSyncWorkflow(["amex"])."""
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


def test_dead_session_times_out_after_12h_without_scraping():
    fake = Fake(sessions={"amex": "dead"})
    result = result_of(fake, workflow=AmexSyncWorkflow)  # time-skipping fast-forwards the 12h timer
    assert result == {"amex": {"status": "needs_login", "detail": "no login within 12h"}}
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
