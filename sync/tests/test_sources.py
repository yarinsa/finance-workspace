"""The registry, and the activities that read it (checks, scrape, validation gate)."""
import asyncio
import os
import re
from pathlib import Path

import pytest
from temporalio.exceptions import ApplicationError

import activities
import sources

REFRESH_ALL = Path(__file__).resolve().parents[2] / ".claude" / "skills" / "refresh-all" / "scripts"


def run(coro):
    return asyncio.run(coro)


# --- registry ---------------------------------------------------------------

def test_registry_ports_and_scrape_order():
    assert {n: s.port for n, s in sources.SOURCES.items()} == {
        "discount-business": 0, "discount-mortgage": 0, "discount": 0,  # all of Discount logs in by itself: no Chrome
        "leumi": 0, "cal": 0, "amex": 0, "max": 0, "harel": 9227, "more": 9228, "analyst": 9229,
    }
    assert "riseup" not in sources.SOURCES
    # Discount stays business -> mortgage -> checking; each is its own headless session.
    assert list(sources.SYNC_ORDER[:3]) == ["discount-business", "discount-mortgage", "discount"]


def test_ports_match_check_sessions_script():
    """Ports are copied from check_sessions.sh; this keeps the two from drifting."""
    text = (REFRESH_ALL / "check_sessions.sh").read_text()
    in_script = dict(re.findall(r'"(\w+)\|(\d+)\|', text))
    for name, port in in_script.items():
        if name in sources.SOURCES and sources.SOURCES[name].check != sources.SELF:  # self-login: no Chrome port
            assert sources.SOURCES[name].port == int(port), name


DISCOUNT_SCRIPTS = [("discount", "scrape.mjs"), ("discount-mortgage", "scrape-mortgage.mjs"),
                    ("discount-business", "scrape-business.mjs")]


def test_no_source_uses_the_discount_chrome_any_more():
    assert [n for n, s in sources.SOURCES.items() if s.port == 9223] == []


@pytest.mark.parametrize("name, script", DISCOUNT_SCRIPTS)
def test_discount_self_login_sources_need_no_chrome(name, script):
    s = sources.get(name)
    assert s.check == sources.SELF and s.port == 0 and not s.playwright and not s.login_group
    assert s.dumps == ((str(Path(__file__).resolve().parents[2] / "scrapers" / "discount" / script),),)


def test_max_logs_in_by_itself():
    s = sources.get("max")
    assert s.check == sources.SELF and s.port == 0 and not s.playwright
    assert s.dumps == ((str(Path(__file__).resolve().parents[2] / "scrapers" / "max" / "scrape.mjs"),),)
    assert Path(s.dumps[0][0]).is_file()
    assert s.group != sources.get("discount").group  # a refused Max login never skips Discount


def test_max_refused_login_is_session_expired(scrape_env):
    _, results = scrape_env
    results.append((3, "LOGIN FAILED: INVALID_PASSWORD\n"))
    with pytest.raises(ApplicationError) as e:
        run(activities.scrape("max"))
    assert e.value.type == "SessionExpired" and e.value.non_retryable


def test_self_login_sources_share_one_group_so_a_refused_login_is_not_retried():
    # Business logs in through the SME page but with the same .env credentials.
    assert sources.get("discount").group == sources.get("discount-mortgage").group == \
        sources.get("discount-business").group == "telebank.co.il-self"


def test_ordered_puts_business_first_then_mortgage_then_checking():
    assert sources.ordered(["discount", "amex", "discount-business", "discount-mortgage", "amex"]) == \
        ["discount-business", "discount-mortgage", "discount", "amex"]


def test_unknown_source_is_an_error():
    with pytest.raises(ValueError):
        sources.ordered(["riseup"])


def test_resolve_accepts_names_and_login_groups():
    assert sources.resolve(["discount"]) == {"discount"}
    assert sources.resolve(["telebank.co.il-self"]) == {"discount", "discount-mortgage", "discount-business"}
    assert sources.resolve(["discount-mortgage"]) == {"discount-mortgage"}
    assert sources.resolve(["amex", "cal"]) == {"amex", "cal"}


def test_every_dump_script_exists():
    for s in sources.SOURCES.values():
        for dump in s.dumps:
            script = activities.SKILLS / dump[0]
            assert script.is_file(), dump[0]
            assert os.access(script, os.X_OK), f"{dump[0]} is not executable (chmod +x)"  # run directly by the worker


# --- tab-based session judgement ---------------------------------------------

def test_classify_tabs():
    more = sources.get("more")
    on_app = [{"type": "page", "url": "https://my-account.more.co.il/personalarea/dashboard"}]
    login = [{"type": "page", "url": "https://my-account.more.co.il/login"}]
    other = [{"type": "page", "url": "https://example.com/"}]
    assert activities.classify_tabs(more, on_app) == "live"
    assert activities.classify_tabs(more, login) == "dead"
    assert activities.classify_tabs(more, other) == "unknown"  # a parked tab proves nothing
    assert activities.classify_tabs(more, []) == "unknown"


def test_parse_sessions_row():
    out = """SOURCE       PORT   STATUS
----------------------------------------------------
discount     9223   live
leumi        9224   chrome not running
cal          9225   unknown (no tab on this app)
harel        9227   NEEDS LOGIN
"""
    assert activities.parse_sessions_row(out, "discount") == "live"
    assert activities.parse_sessions_row(out, "leumi") == "unknown"  # a closed browser is not a lapsed login
    assert activities.parse_sessions_row(out, "cal") == "unknown"
    assert activities.parse_sessions_row(out, "harel") == "dead"
    assert activities.parse_sessions_row(out, "more") is None


def _fake_cmd(monkeypatch, output, seen=None):
    async def fake(args, **kw):
        if seen is not None:
            seen.append((args, kw))
        return 1, output  # check_sessions.sh exits 1 unless everything is live; rc is ignored

    monkeypatch.setattr(activities, "run_cmd", fake)


def test_check_uses_single_source_mode_and_timeout(monkeypatch):
    seen = []
    _fake_cmd(monkeypatch, "harel        9227   live\n", seen)
    assert run(activities.check_session("harel")) == "live"
    args, kw = seen[0]
    assert args[0].endswith("refresh-all/scripts/check_sessions.sh") and args[1] == "harel"
    assert kw["timeout"] == activities.SESSIONS_TIMEOUT


def test_unknown_stays_unknown_without_a_login_page(monkeypatch):
    _fake_cmd(monkeypatch, "harel        9227   unknown (no tab on this app)\n")
    monkeypatch.setattr(activities, "_cdp_pages", lambda src: [{"type": "page", "url": "https://example.com/"}])
    assert run(activities.check_session("harel")) == "unknown"


def test_unknown_with_login_page_open_is_dead(monkeypatch):
    _fake_cmd(monkeypatch, "harel        9227   unknown (no tab on this app)\n")
    monkeypatch.setattr(activities, "_cdp_pages",
                        lambda src: [{"type": "page", "url": "https://digital-web.harel-group.co.il/login"}])
    assert run(activities.check_session("harel")) == "dead"


def test_unreadable_tabs_are_unknown_not_dead(monkeypatch):
    _fake_cmd(monkeypatch, "harel        9227   unknown (no tab on this app)\n")

    def boom(src):
        raise OSError("connection refused")

    monkeypatch.setattr(activities, "_cdp_pages", boom)
    assert run(activities.check_session("harel")) == "unknown"


def test_missing_row_is_an_infrastructure_error(monkeypatch):
    _fake_cmd(monkeypatch, "playwright-cli: command not found\n")
    with pytest.raises(ApplicationError):
        run(activities.check_session("harel"))


def test_amex_logs_in_by_itself(monkeypatch):
    s = sources.get("amex")
    assert s.check == sources.SELF and s.port == 0 and not s.playwright
    assert s.group == "americanexpress.co.il-self" != sources.get("discount").group
    seen = []

    async def fake_run(args, **kw):
        seen.append(list(args))
        return 3, "LOGIN FAILED: INVALID_PASSWORD\n"

    monkeypatch.setattr(activities, "run_cmd", fake_run)
    assert run(activities.check_session("amex")) == "live"  # no Chrome to check
    with pytest.raises(ApplicationError) as e:
        run(activities.scrape("amex"))
    assert e.value.type == "SessionExpired" and e.value.non_retryable
    script = Path(__file__).resolve().parents[2] / "scrapers" / "amex" / "scrape.mjs"
    assert seen == [[str(script)]] and script.is_file()


# --- scrape -----------------------------------------------------------------

@pytest.fixture
def scrape_env(monkeypatch):
    """No Chrome: tab binding is stubbed, dump commands are recorded."""
    cmds, results = [], []
    monkeypatch.setattr(activities, "_cdp_pages", lambda src: [])

    async def fake_ensure(src, open_url=None):
        cmds.append(("tab", src.name, open_url))
        return 0

    async def fake_bind(src, tab):
        cmds.append(("bind", src.name))

    async def fake_run(args, **kw):
        cmds.append(("run", Path(args[0]).parent.parent.name, args[1:]))
        return results.pop(0) if results else (0, "done")

    monkeypatch.setattr(activities, "_ensure_tab", fake_ensure)
    monkeypatch.setattr(activities, "_bind_playwright", fake_bind)
    monkeypatch.setattr(activities, "run_cmd", fake_run)
    return cmds, results


def test_scrape_passes_session_or_port_per_script(scrape_env):
    cmds, _ = scrape_env
    run(activities.scrape("harel"))
    run(activities.scrape("more"))
    runs = [c for c in cmds if c[0] == "run"]
    assert runs == [("run", "harel-refresh", ["harel"]), ("run", "more-refresh", ["9228"])]
    assert not [c for c in cmds if c[:2] == ("bind", "more")]  # raw-CDP source: no playwright


def test_leumi_logs_in_by_itself_in_one_script(scrape_env):
    """dump.sh + dump-loans.sh are one headless run now: no Chrome tab, no playwright."""
    cmds, _ = scrape_env
    leumi = sources.get("leumi")
    assert leumi.check == sources.SELF and leumi.group == "bankleumi.co.il-self"
    run(activities.scrape("leumi"))
    assert [c for c in cmds if c[0] == "run"] == [("run", "scrapers", [])]
    assert not [c for c in cmds if c[0] in ("tab", "bind")]


@pytest.mark.parametrize("output", [
    "ABORT: session not live. Nothing written - existing dump preserved.",
    "  --        350B  mortgage_details.json  <-- LOGIN-SHELL HTML, NOT WRITTEN (previous file kept)",
    "accountData missing/invalid at https://my-account.more.co.il/ - session likely dead (log in again).",
    "No logged-in more.co.il personalarea tab on port 9228",
    '{"error":"actionRequired","actionRequired":"stepup"}',
    "SME - קלט לא תקין",
    "LOGIN FAILED: INVALID_PASSWORD",
    "LOGIN FAILED: CHANGE_PASSWORD",
    "LOGIN FAILED: OTP_REQUIRED",
    "LOGIN FAILED: ACCOUNT_BLOCKED",
])
def test_expired_signatures_are_session_expired(scrape_env, output):
    _, results = scrape_env
    results.append((2, output))
    with pytest.raises(ApplicationError) as e:
        run(activities.scrape("discount-business"))
    assert e.value.type == "SessionExpired" and e.value.non_retryable


def test_self_login_refused_is_session_expired(scrape_env):
    _, results = scrape_env
    results.append((1, "navigating...\nLOGIN FAILED: INVALID_PASSWORD\n"))
    with pytest.raises(ApplicationError) as e:
        run(activities.scrape("discount"))
    assert e.value.type == "SessionExpired" and e.value.non_retryable


@pytest.mark.parametrize("name, script", DISCOUNT_SCRIPTS)
def test_discount_dump_argv_is_the_absolute_script(monkeypatch, name, script):
    seen = []

    async def fake_run(args, **kw):
        seen.append(list(args))
        return 0, "done"

    monkeypatch.setattr(activities, "run_cmd", fake_run)
    run(activities.scrape(name))
    expected = Path(__file__).resolve().parents[2] / "scrapers" / "discount" / script
    assert seen == [[str(expected)]] and Path(seen[0][0]).is_absolute()
    assert expected.is_file()


@pytest.mark.parametrize("name", ["discount", "discount-mortgage", "discount-business", "max"])
def test_self_check_is_live_without_running_anything(monkeypatch, name):
    async def never(*a, **k):
        pytest.fail("a self-login source must not shell out or read tabs")

    monkeypatch.setattr(activities, "run_cmd", never)
    monkeypatch.setattr(activities, "_cdp_pages", lambda src: pytest.fail("must not read tabs"))
    assert run(activities.check_session(name)) == "live"


def test_discount_scrapes_touch_no_chrome(scrape_env):
    cmds, _ = scrape_env
    for name in ("discount-business", "discount-mortgage", "discount"):
        cmds.clear()
        run(activities.scrape(name))
        assert not [c for c in cmds if c[0] in ("tab", "bind")]  # self-login sources touch no Chrome


# --- validation gate --------------------------------------------------------

def test_validate_passes_when_validator_does_not_exist_yet(monkeypatch, tmp_path):
    monkeypatch.setattr(activities, "VALIDATOR", tmp_path / "validate.py")
    assert run(activities.validate_dump("cal"))["gate"] == "skipped"


def test_validate_runs_the_validator_with_dump_and_source(monkeypatch, tmp_path):
    v = tmp_path / "validate.py"
    v.write_text("import sys; print(sys.argv[1:]); sys.exit(0)")
    monkeypatch.setattr(activities, "VALIDATOR", v)
    assert run(activities.validate_dump("cal"))["gate"] == "ok"


def test_validate_returns_the_dumps_record_counts(monkeypatch, tmp_path):
    """What the Syncs page shows as "came in": AMEX 2026-10-25, 322 -> 360 transactions."""
    v = tmp_path / "validate.py"
    v.write_text("import sys\n"
                 "assert sys.argv[1:] == ['dump', 'amex', '--json']\n"
                 "print('OK     amex: ok')\n"
                 "print('DUMP_JSON {\"status\": \"pass\", \"records\": {\"transactions\": 360}, '\n"
                 "      '\"records_before\": {\"transactions\": 322}, \"latest_txn\": \"2026-10-22\"}')\n")
    monkeypatch.setattr(activities, "VALIDATOR", v)
    assert run(activities.validate_dump("amex")) == {
        "gate": "ok", "records": {"transactions": 360}, "records_before": {"transactions": 322},
        "latest_txn": "2026-10-22"}


def test_rejection_message_leaves_out_the_json_line(monkeypatch, tmp_path):
    v = tmp_path / "validate.py"
    v.write_text("print('REJECT cal: latest transaction 2026-10-08 is 17 days old')\n"
                 "print('DUMP_JSON {}')\nimport sys; sys.exit(1)\n")
    monkeypatch.setattr(activities, "VALIDATOR", v)
    with pytest.raises(ApplicationError) as e:
        run(activities.validate_dump("cal"))
    assert "17 days old" in str(e.value) and "DUMP_JSON" not in str(e.value)


def test_validate_rejection_carries_the_validators_output(monkeypatch, tmp_path):
    v = tmp_path / "validate.py"
    v.write_text("import sys; print('cal: 0 transactions, expected >= 100'); sys.exit(1)")
    monkeypatch.setattr(activities, "VALIDATOR", v)
    with pytest.raises(ApplicationError) as e:
        run(activities.validate_dump("cal"))
    assert "0 transactions, expected >= 100" in str(e.value)
    assert e.value.type == "ValidationFailed" and e.value.non_retryable


def test_ensure_chrome_is_a_no_op_for_self_login_sources(monkeypatch):
    monkeypatch.setattr(activities, "_cdp_up", lambda src: pytest.fail("no Chrome for a self-login source"))
    monkeypatch.setattr(activities, "_launch_chrome", lambda src: pytest.fail("no Chrome for a self-login source"))
    run(activities.ensure_chrome("discount"))
    run(activities.ensure_chrome("discount-mortgage"))
    run(activities.ensure_chrome("discount-business"))


def test_cal_logs_in_by_itself(monkeypatch):
    s = sources.get("cal")
    assert s.check == sources.SELF and s.port == 0 and not s.playwright and not s.login_group
    assert s.group == "cal-online.co.il-self" != sources.get("discount").group
    seen = []

    async def fake_run(args, **kw):
        seen.append(list(args))
        return 1, "LOGIN FAILED: INVALID_PASSWORD\n"

    monkeypatch.setattr(activities, "run_cmd", fake_run)
    with pytest.raises(ApplicationError) as e:
        run(activities.scrape("cal"))
    assert e.value.type == "SessionExpired" and e.value.non_retryable
    script = Path(__file__).resolve().parents[2] / "scrapers" / "cal" / "scrape.mjs"
    assert seen == [[str(script)]] and script.is_file()
