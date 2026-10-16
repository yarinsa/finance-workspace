"""FinanceSyncWorkflow: preflight, grouped login, scrape order, isolation, validation gate."""
from fakes import Fake, expired, moved, rejected, result_of, run, until_phase
from workflows import FinanceSyncWorkflow

ALL = ["discount", "discount-mortgage", "discount-business", "leumi", "cal", "amex", "harel", "more", "analyst"]


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
        "analyst": "ok", "cal": "needs_login", "harel": "failed", "more": "rejected",
    }
    assert "endpoint moved" in result["harel"]["detail"]
    assert "0 transactions" in result["more"]["detail"]
    assert all(set(v) == {"status", "detail"} for k, v in result.items() if k != "_finish")


# --- preflight / grouped login ------------------------------------------------

def test_dead_sessions_produce_exactly_one_grouped_notification():
    fake = Fake(sessions={"discount": "dead", "discount-mortgage": "dead", "discount-business": "dead",
                          "amex": "dead", "harel": "dead"})
    result = result_of(fake)  # nobody signals: time-skipping fast-forwards the 12h wait
    notes = fake.login_notes()
    assert len(notes) == 1
    msg = notes[0]
    assert "discount (discount, discount-mortgage, discount-business" in msg  # one entry for the shared login
    assert msg.count(".chrome-cdp-discount") == 1
    assert "amex" in msg and "harel" in msg and "cal" not in msg
    assert "sync/resume.py" in msg
    assert all(result[s]["status"] == "needs_login" for s in ["discount", "discount-mortgage", "discount-business", "amex", "harel"])
    assert "12h" in result["amex"]["detail"]
    # The live ones were still scraped.
    assert fake.of("scrape") == ["leumi", "cal", "more", "analyst"]


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
    fake = Fake(sessions={"discount": ["dead", "live"], "discount-mortgage": ["dead", "live"],
                          "discount-business": ["dead", "live"], "amex": ["dead", "live"]})

    async def scenario(env, h):
        await until_phase(h, FinanceSyncWorkflow, "waiting_for_login")
        await h.signal(FinanceSyncWorkflow.session_refreshed, ["discount"])
        return await h.result()

    result = run(fake, scenario)
    assert [result[s]["status"] for s in ["discount", "discount-mortgage", "discount-business"]] == ["ok"] * 3
    assert result["amex"]["status"] == "needs_login"  # not named, so not re-checked
    assert fake.of("scrape").index("discount") < fake.of("scrape").index("discount-business")


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
    assert fake.of("scrape") == ["discount", "discount-mortgage", "discount-business", "amex"]


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


def test_session_expiring_mid_scrape_skips_the_rest_of_that_login_group_only():
    fake = Fake(scrape_errors={"discount": expired()})
    result = result_of(fake)
    assert result["discount"]["status"] == "needs_login"
    for s in ("discount-mortgage", "discount-business"):
        assert result[s]["status"] == "needs_login" and "discount" in result[s]["detail"]
        assert s not in fake.of("scrape")  # the bank is not hammered with a dead login
    assert fake.of("scrape") == ["discount", "leumi", "cal", "amex", "harel", "more", "analyst"]
    assert result["leumi"]["status"] == "ok"


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
