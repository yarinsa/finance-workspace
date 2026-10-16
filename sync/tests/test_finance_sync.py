"""FinanceSyncWorkflow: preflight, grouped login, scrape order, isolation, validation gate."""
import pytest
from temporalio.exceptions import ApplicationError

from fakes import Fake, expired, moved, rejected, result_of, run, until_phase
from workflows import FinanceSyncWorkflow

ALL = ["discount-mortgage", "discount-business", "discount", "leumi", "cal", "amex", "max", "harel", "more", "analyst"]


def test_all_sources_live_scrapes_in_registry_order_then_digests_and_publishes_once():
    fake = Fake()
    result = result_of(fake)
    assert fake.of("scrape") == ALL
    assert fake.of("validate") == ALL
    assert fake.calls.count(("digest",)) == 1 and fake.calls.count(("publish",)) == 1
    assert all(result[s]["status"] == "ok" for s in ALL)
    assert result["_finish"] == {"digest": {"transactions": 42}, "published": "published"}


def test_every_session_is_checked_before_any_scrape():
    fake = Fake()
    result_of(fake)
    kinds = [c[0] for c in fake.calls]
    assert max(i for i, k in enumerate(kinds) if k == "check") < kinds.index("scrape")


def test_result_dict_is_per_source_with_status_and_detail():
    fake = Fake(sessions={"cal": "dead"}, scrape_errors={"harel": moved()}, validate_errors={"more": rejected()})
    result = result_of(fake)
    assert set(result) == set(ALL) | {"_finish"}
    assert {k: v["status"] for k, v in result.items() if k != "_finish"} == {
        "discount": "ok", "discount-mortgage": "ok", "discount-business": "ok", "leumi": "ok", "amex": "ok",
        "max": "ok", "analyst": "ok", "cal": "needs_login", "harel": "failed", "more": "rejected",
    }
    assert "endpoint moved" in result["harel"]["detail"]
    assert "0 transactions" in result["more"]["detail"]
    assert all(set(v) == {"status", "detail"} for k, v in result.items() if k != "_finish")


# --- preflight / grouped login ------------------------------------------------

def test_dead_sessions_produce_exactly_one_grouped_notification():
    fake = Fake(sessions={"discount-mortgage": "dead", "discount-business": "dead",
                          "amex": "dead", "harel": "dead"})
    result = result_of(fake)  # nobody signals: time-skipping fast-forwards the 12h wait
    notes = fake.login_notes()
    assert len(notes) == 1
    msg = notes[0]
    assert "discount (discount-mortgage, discount-business;" in msg  # one entry for the shared Chrome login
    assert msg.count(".chrome-cdp-discount") == 1
    assert "amex" in msg and "harel" in msg and "cal" not in msg
    assert "sync/resume.py" in msg
    assert all(result[s]["status"] == "needs_login" for s in ["discount-mortgage", "discount-business", "amex", "harel"])
    assert result["discount"]["status"] == "ok"  # self-login checking needs no Chrome login
    assert "12h" in result["amex"]["detail"]
    # The live ones were still scraped.
    assert fake.of("scrape") == ["discount", "leumi", "cal", "max", "more", "analyst"]


def test_signal_rechecks_and_scrapes_only_what_came_back():
    fake = Fake(sessions={"amex": ["dead", "live"], "cal": ["dead", "dead"]})

    async def scenario(env, h):
        await until_phase(h, FinanceSyncWorkflow, "waiting_for_login")
        assert "amex" not in fake.of("scrape")
        await h.signal(FinanceSyncWorkflow.session_refreshed)
        return await h.result()

    result = run(fake, scenario)
    assert len(fake.login_notes()) == 1
    assert result["amex"]["status"] == "ok"
    assert result["cal"] == {"status": "needs_login", "detail": "still logged out"}  # skipped, not fatal
    assert "cal" not in fake.of("scrape") and "amex" in fake.of("scrape")


def test_signal_naming_a_login_group_rechecks_the_whole_group():
    fake = Fake(sessions={"discount-mortgage": ["dead", "live"],
                          "discount-business": ["dead", "live"], "amex": ["dead", "live"]})

    async def scenario(env, h):
        await until_phase(h, FinanceSyncWorkflow, "waiting_for_login")
        await h.signal(FinanceSyncWorkflow.session_refreshed, ["discount"])
        return await h.result()

    result = run(fake, scenario)
    assert [result[s]["status"] for s in ["discount-mortgage", "discount-business"]] == ["ok"] * 2
    assert result["amex"]["status"] == "needs_login"  # not named, so not re-checked
    assert fake.of("scrape").index("discount-mortgage") < fake.of("scrape").index("discount-business")


def test_unknown_is_not_dead():
    fake = Fake(sessions={s: "unknown" for s in ALL})
    result = result_of(fake)
    assert fake.login_notes() == []  # nobody is asked to log in
    assert fake.of("scrape") == ALL  # and everything is attempted
    assert all(result[s]["status"] == "ok" and "unverified" in result[s]["detail"] for s in ALL)


def test_check_that_cannot_run_is_unknown_not_dead():
    fake = Fake(check_errors=["cal"])
    result = result_of(fake)
    assert fake.login_notes() == []
    assert "cal" in fake.of("scrape") and result["cal"]["status"] == "ok"


def test_chrome_that_will_not_open_fails_that_source_only():
    fake = Fake(chrome_errors=["leumi"])
    result = result_of(fake, args=[["leumi", "cal"]])
    assert result["leumi"]["status"] == "failed" and "Chrome unavailable" in result["leumi"]["detail"]
    assert result["cal"]["status"] == "ok" and fake.of("scrape") == ["cal"]


# --- scrape order / isolation -------------------------------------------------

def test_discount_order_has_business_last_whatever_order_was_requested():
    fake = Fake()
    result_of(fake, args=[["discount-business", "amex", "discount-mortgage", "discount"]])
    assert fake.of("scrape") == ["discount-mortgage", "discount-business", "discount", "amex"]


def test_requested_subset_only_touches_those_sources():
    fake = Fake()
    result = result_of(fake, args=[["cal", "analyst"]])
    assert fake.of("ensure_chrome") == ["cal", "analyst"]
    assert fake.of("scrape") == ["cal", "analyst"]
    assert set(result) == {"cal", "analyst", "_finish"}


def test_one_failing_source_does_not_abort_the_others():
    fake = Fake(scrape_errors={"leumi": moved(), "discount-mortgage": moved()})
    result = result_of(fake)
    assert result["leumi"]["status"] == "failed" and result["discount-mortgage"]["status"] == "failed"
    assert fake.of("scrape") == ALL  # every source was still tried, in order
    assert "leumi" not in fake.of("validate")  # a failed scrape has nothing to validate
    assert {result[s]["status"] for s in ALL if s not in ("leumi", "discount-mortgage")} == {"ok"}
    assert fake.calls.count(("digest",)) == 1 and fake.calls.count(("publish",)) == 1


def test_session_expiring_mid_scrape_skips_the_rest_of_the_chrome_login_group():
    fake = Fake(scrape_errors={"discount-mortgage": expired()})
    result = result_of(fake)
    assert result["discount-mortgage"]["status"] == "needs_login"
    assert result["discount-business"]["status"] == "needs_login" and "discount-mortgage" in result["discount-business"]["detail"]
    assert "discount-business" not in fake.of("scrape")  # the bank is not hammered with a dead login
    assert result["leumi"]["status"] == "ok"


def test_chrome_group_expiry_does_not_skip_self_login_checking():
    fake = Fake(scrape_errors={"discount-mortgage": expired()})
    result = result_of(fake)
    assert result["discount"]["status"] == "ok" and "discount" in fake.of("scrape")


def test_self_login_expiry_skips_nothing_else():
    fake = Fake(scrape_errors={"discount": expired()})
    result = result_of(fake)
    assert result["discount"]["status"] == "needs_login"
    assert fake.of("scrape") == ALL  # checking runs after the Chrome apps, which were already done
    assert all(result[s]["status"] == "ok" for s in ALL if s != "discount")


def test_nothing_scraped_means_no_digest_and_no_publish():
    fake = Fake(scrape_errors={"cal": moved(), "amex": expired()})
    result = result_of(fake, args=[["cal", "amex"]])
    assert "digest" not in [c[0] for c in fake.calls] and "publish" not in [c[0] for c in fake.calls]
    assert "_finish" not in result


# --- validation gate ----------------------------------------------------------

def test_rejected_dump_does_not_count_and_withholds_publish():
    fake = Fake(validate_errors={"cal": rejected()})
    result = result_of(fake)
    assert result["cal"]["status"] == "rejected"
    assert "cal: 0 transactions" in result["cal"]["detail"]  # the validator's output reaches the result
    assert result["amex"]["status"] == "ok"
    assert fake.calls.count(("digest",)) == 1  # the others still digest...
    assert ("publish",) not in fake.calls  # ...but the numbers are not pushed while a bad dump is on disk
    assert result["_finish"]["published"] == "withheld (rejected: cal)"


def test_only_source_rejected_means_nothing_to_digest():
    fake = Fake(validate_errors={"cal": rejected()})
    result = result_of(fake, args=[["cal"]])
    assert result["cal"]["status"] == "rejected"
    assert ("digest",) not in fake.calls and ("publish",) not in fake.calls


def test_validate_runs_after_its_scrape_and_before_the_next_source():
    fake = Fake()
    result_of(fake, args=[["cal", "amex"]])
    steps = [c for c in fake.calls if c[0] in ("scrape", "validate")]
    assert steps == [("scrape", "cal"), ("validate", "cal"), ("scrape", "amex"), ("validate", "amex")]


# --- misc ---------------------------------------------------------------------

def test_status_query_reports_per_source_state_while_waiting():
    fake = Fake(sessions={"amex": "dead"})

    async def scenario(env, h):
        await until_phase(h, FinanceSyncWorkflow, "waiting_for_login")
        st = await h.query(FinanceSyncWorkflow.status)
        assert st["sources"]["amex"]["status"] == "pending"
        assert set(st["sources"]) == set(ALL)
        return await h.result()

    run(fake, scenario)


def test_final_notification_summarises_by_status():
    fake = Fake(scrape_errors={"cal": moved()})
    result_of(fake, args=[["cal", "amex"]])
    title, msg = fake.notes()[-1]
    assert title == "Finance sync" and "failed: cal" in msg and "ok: amex" in msg


# --- live status: one entry per source -----------------------------------------

def test_two_source_run_publishes_a_separate_entry_per_source():
    fake = Fake()
    result_of(fake, args=[["cal", "amex"]])
    steps = ["checking_session", "scraping", "validating", "digesting", "publishing", "done"]
    assert fake.published("cal") == steps and fake.published("amex") == steps
    assert {s for s, _ in fake.statuses} == {"cal", "amex"}
    entries = {s: e for s, e in fake.statuses if e["status"] == "done"}
    assert "כאל" in entries["cal"]["message"] and "אמריקן אקספרס" in entries["amex"]["message"]
    assert entries["cal"]["workflow_id"] == entries["amex"]["workflow_id"]  # one run, two entries
    # Each source moves through its own steps in turn.
    scraping = [s for s, e in fake.statuses if e["status"] == "scraping"]
    assert scraping == ["cal", "amex"]


def test_digest_and_publish_are_reported_on_every_source_that_scraped():
    fake = Fake(scrape_errors={"leumi": moved()})
    result_of(fake, args=[["leumi", "cal", "amex"]])
    for s in ("cal", "amex"):
        assert fake.published(s)[-3:] == ["digesting", "publishing", "done"]
    assert fake.published("leumi") == ["checking_session", "scraping", "failed"]  # never digested


def test_rejected_dump_publishes_rejected_with_the_reason():
    fake = Fake(validate_errors={"cal": rejected()})
    result_of(fake, args=[["cal", "amex"]])
    assert fake.published("cal") == ["checking_session", "scraping", "validating", "rejected"]
    last = [e for s, e in fake.statuses if s == "cal"][-1]
    assert last["step"] == 3 and "0 transactions" in last["error"]
    # amex scraped fine; its publish is withheld and it says so.
    assert fake.published("amex")[-1] == "done" and "publishing" not in fake.published("amex")
    assert "הוחזק" in [e for s, e in fake.statuses if s == "amex"][-1]["message"]


def test_dead_source_is_published_waiting_then_needs_login_while_live_ones_are_queued():
    fake = Fake(sessions={"amex": "dead"})
    result_of(fake, args=[["amex", "cal"]])
    assert fake.published("amex") == ["checking_session", "waiting_for_login", "needs_login"]
    cal = [e for s, e in fake.statuses if s == "cal"]
    assert "בתור" in cal[1]["message"]  # connected, but queued behind the login wait
    assert fake.published("cal")[-1] == "done"


def test_login_group_expiring_publishes_needs_login_for_the_skipped_apps():
    fake = Fake(scrape_errors={"discount-mortgage": expired()})
    result_of(fake, args=[["discount-mortgage", "discount-business"]])
    assert fake.published("discount-mortgage")[-1] == "needs_login"
    assert fake.published("discount-business") == ["checking_session", "needs_login"]


def test_digest_failure_marks_every_scraped_source_failed():
    fake = Fake(digest_error=ApplicationError("digest.py failed (rc=1)", non_retryable=True))

    async def scenario(env, h):
        try:
            await h.result()
        except Exception:
            return None

    run(fake, scenario, args=[["cal", "amex"]])
    for s in ("cal", "amex"):
        assert fake.published(s)[-2:] == ["digesting", "failed"]


def test_status_publishing_failure_never_fails_a_multi_source_sync():
    fake = Fake(status_error=True)
    result = result_of(fake, args=[["cal", "amex"]])
    assert result["cal"]["status"] == result["amex"]["status"] == "ok"
    assert fake.calls.count(("publish",)) == 1


def test_merge_status_advances_last_success_only_on_done():
    import activities
    doc = None
    for source, status, at in [("cal", "done", "t1"), ("amex", "rejected", "t2"), ("cal", "scraping", "t3"),
                               ("cal", "rejected", "t4")]:
        doc = activities.merge_status(doc, source, {"status": status, "updated_at": at})
    assert doc["sources"]["cal"]["last_success_at"] == "t1"
    assert doc["sources"]["amex"]["last_success_at"] is None
