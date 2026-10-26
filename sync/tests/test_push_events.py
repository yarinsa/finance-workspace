"""Web Push events raised by the sync workflow (the sending itself is tested in data/tests/test_push.py)."""
from fakes import Fake, expired, rejected, result_of


def test_dead_session_pushes_one_payload_per_login_group():
    fake = Fake(sessions={"leumi": ["dead", "dead"], "cal": ["dead", "dead"]})
    result_of(fake, args=(["leumi", "cal"],))
    import sources
    tags = {p["tag"] for p in fake.pushes}
    assert tags == {f"login-{g}" for g in sources.login_groups(["leumi", "cal"])} and len(tags) == 2
    assert all(p["url"] == "/syncs" for p in fake.pushes if p["tag"].startswith("login-"))


def test_rejected_dump_pushes_once_and_failed_scrape_pushes():
    fake = Fake(validate_errors={"cal": rejected()}, scrape_errors={"amex": RuntimeError("boom")})
    result_of(fake, args=(["cal", "amex"],))
    by_tag = {p["tag"]: p for p in fake.pushes}
    assert "sync-rejected-cal" in by_tag and "sync-failed-amex" in by_tag
    assert by_tag["sync-rejected-cal"]["title"] == "הנתונים נדחו"
    assert len([p for p in fake.pushes if p["tag"] == "sync-rejected-cal"]) == 1


def test_clean_run_pushes_actions_and_offers_summary_but_no_failure_push():
    fake = Fake()
    result_of(fake, args=(["amex"],))
    assert fake.action_pushes == 1
    assert len(fake.summary_calls) == 1
    assert fake.pushes == []


def test_nothing_scraped_pushes_no_digest_events():
    fake = Fake(sessions={"amex": "dead"})
    result_of(fake, args=(["amex"],))
    assert fake.action_pushes == 0 and fake.summary_calls == []
