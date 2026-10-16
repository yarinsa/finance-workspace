"""The registry, and the activities that read it (checks, scrape, validation gate)."""
import asyncio
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
        "discount": 9223, "discount-mortgage": 9223, "discount-business": 9223,
        "leumi": 9224, "cal": 9225, "amex": 9226, "harel": 9227, "more": 9228, "analyst": 9229,
    }
    assert "riseup" not in sources.SOURCES
    assert list(sources.SYNC_ORDER[:3]) == ["discount", "discount-mortgage", "discount-business"]


def test_ports_match_check_sessions_script():
    """Ports are copied from check_sessions.sh; this keeps the two from drifting."""
    text = (REFRESH_ALL / "check_sessions.sh").read_text()
    in_script = dict(re.findall(r'"(\w+)\|(\d+)\|', text))
    for name, port in in_script.items():
        if name in sources.SOURCES:
            assert sources.SOURCES[name].port == int(port), name


def test_discount_apps_share_one_chrome_and_one_login():
    d = [sources.get(n) for n in ("discount", "discount-mortgage", "discount-business")]
    assert {s.group for s in d} == {"discount"}
    assert {(s.port, s.profile, s.pw_session) for s in d} == {(9223, sources.get("discount").profile, "discount")}
    assert sources.get("discount").profile.name == ".chrome-cdp-discount"


def test_ordered_puts_business_last_whatever_the_caller_passed():
    assert sources.ordered(["discount-business", "amex", "discount", "discount-mortgage", "amex"]) == \
        ["discount", "discount-mortgage", "discount-business", "amex"]


def test_unknown_source_is_an_error():
    with pytest.raises(ValueError):
        sources.ordered(["riseup"])


def test_resolve_accepts_names_and_login_groups():
    assert sources.resolve(["discount"]) == {"discount", "discount-mortgage", "discount-business"}
    assert sources.resolve(["amex", "cal"]) == {"amex", "cal"}


def test_every_dump_script_exists():
    for s in sources.SOURCES.values():
        for dump in s.dumps:
            assert (activities.SKILLS / dump[0]).is_file(), dump[0]


def test_business_tab_is_matched_by_the_shared_table():
    biz = sources.get("discount-business")
    pages = [{"type": "page", "url": "https://start.telebank.co.il/apollo/retail3/#/HOME"},
             {"type": "page", "url": "https://start.telebank.co.il/apollo/business2/#/MY_ACCOUNT_HOMEPAGE"}]
    assert activities._tab_index(biz, pages, app_only=True) == 1
    assert activities._tab_index(sources.get("discount"), pages, app_only=True) == 0


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
    _fake_cmd(monkeypatch, "discount     9223   live\n", seen)
    assert run(activities.check_session("discount-mortgage")) == "live"  # mortgage reuses the discount signal
    args, kw = seen[0]
    assert args[0].endswith("refresh-all/scripts/check_sessions.sh") and args[1] == "discount"
    assert kw["timeout"] == activities.SESSIONS_TIMEOUT


def test_unknown_stays_unknown_without_a_login_page(monkeypatch):
    _fake_cmd(monkeypatch, "cal          9225   unknown (no tab on this app)\n")
    monkeypatch.setattr(activities, "_cdp_pages", lambda src: [{"type": "page", "url": "https://example.com/"}])
    assert run(activities.check_session("cal")) == "unknown"


def test_unknown_with_login_page_open_is_dead(monkeypatch):
    _fake_cmd(monkeypatch, "cal          9225   unknown (no tab on this app)\n")
    monkeypatch.setattr(activities, "_cdp_pages",
                        lambda src: [{"type": "page", "url": "https://digital-web.cal-online.co.il/login"}])
    assert run(activities.check_session("cal")) == "dead"


def test_unreadable_tabs_are_unknown_not_dead(monkeypatch):
    _fake_cmd(monkeypatch, "cal          9225   unknown (no tab on this app)\n")

    def boom(src):
        raise OSError("connection refused")

    monkeypatch.setattr(activities, "_cdp_pages", boom)
    assert run(activities.check_session("cal")) == "unknown"


def test_missing_row_is_an_infrastructure_error(monkeypatch):
    _fake_cmd(monkeypatch, "playwright-cli: command not found\n")
    with pytest.raises(ApplicationError):
        run(activities.check_session("cal"))


def test_business_check_is_tabs_only(monkeypatch):
    async def never(*a, **k):
        pytest.fail("business has no check_sessions.sh signal; it must not shell out")

    monkeypatch.setattr(activities, "run_cmd", never)
    monkeypatch.setattr(activities, "_cdp_pages",
                        lambda src: [{"type": "page", "url": "https://start.telebank.co.il/apollo/business2/#/HOME"}])
    assert run(activities.check_session("discount-business")) == "live"
    monkeypatch.setattr(activities, "_cdp_pages",
                        lambda src: [{"type": "page", "url": "https://start.telebank.co.il/apollo/retail3/#/HOME"}])
    assert run(activities.check_session("discount-business")) == "unknown"  # no business tab yet: not a dead login


def test_amex_keeps_the_verdict_path(monkeypatch):
    seen = []

    async def fake(args, **kw):
        seen.append(args)
        return 1, "VERDICT: LOGGED_OUT"

    monkeypatch.setattr(activities, "run_cmd", fake)
    assert run(activities.check_session("amex")) == "dead"
    assert seen[0][0].endswith("amex-refresh/scripts/check_session.sh")


def test_amex_without_verdict_raises_instead_of_calling_it_dead(monkeypatch):
    async def fake(args, **kw):
        return 1, "Error: session 'amex' not found"

    monkeypatch.setattr(activities, "run_cmd", fake)
    with pytest.raises(ApplicationError):
        run(activities.check_session("amex"))


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
    run(activities.scrape("discount-mortgage"))
    run(activities.scrape("more"))
    runs = [c for c in cmds if c[0] == "run"]
    assert runs == [("run", "discount-mortgage-refresh", ["discount"]), ("run", "more-refresh", ["9228"])]
    assert not [c for c in cmds if c[:2] == ("bind", "more")]  # raw-CDP source: no playwright


def test_leumi_runs_dump_then_loans_and_stops_on_first_failure(scrape_env):
    cmds, results = scrape_env
    run(activities.scrape("leumi"))
    assert [c[1] for c in cmds if c[0] == "run"] == ["leumi-account-refresh"] * 2
    cmds.clear()
    results.append((2, "something moved"))
    with pytest.raises(ApplicationError) as e:
        run(activities.scrape("leumi"))
    assert e.value.type == "ScrapeFailed" and e.value.non_retryable
    assert len([c for c in cmds if c[0] == "run"]) == 1  # dump-loans.sh never ran


@pytest.mark.parametrize("output", [
    "ABORT: session not live. Nothing written - existing dump preserved.",
    "  --        350B  mortgage_details.json  <-- LOGIN-SHELL HTML, NOT WRITTEN (previous file kept)",
    "accountData missing/invalid at https://my-account.more.co.il/ - session likely dead (log in again).",
    "No logged-in more.co.il personalarea tab on port 9228",
    '{"error":"actionRequired","actionRequired":"stepup"}',
    "SME - קלט לא תקין",
])
def test_expired_signatures_are_session_expired(scrape_env, output):
    _, results = scrape_env
    results.append((2, output))
    with pytest.raises(ApplicationError) as e:
        run(activities.scrape("discount"))
    assert e.value.type == "SessionExpired" and e.value.non_retryable


def test_business_scrape_opens_the_app_when_no_business_tab_exists(scrape_env, monkeypatch):
    cmds, _ = scrape_env
    monkeypatch.setattr(activities, "_cdp_pages",
                        lambda src: [{"type": "page", "url": "https://start.telebank.co.il/apollo/retail3/"}])
    run(activities.scrape("discount-business"))
    assert ("tab", "discount-business", "https://start.telebank.co.il/apollo/business2/") in cmds
    cmds.clear()
    run(activities.scrape("discount"))
    assert ("tab", "discount", None) in cmds  # the retail apps never open a page here


# --- validation gate --------------------------------------------------------

def test_validate_passes_when_validator_does_not_exist_yet(monkeypatch, tmp_path):
    monkeypatch.setattr(activities, "VALIDATOR", tmp_path / "validate.py")
    assert run(activities.validate_dump("cal")) == "skipped"


def test_validate_runs_the_validator_with_dump_and_source(monkeypatch, tmp_path):
    v = tmp_path / "validate.py"
    v.write_text("import sys; print(sys.argv[1:]); sys.exit(0)")
    monkeypatch.setattr(activities, "VALIDATOR", v)
    assert run(activities.validate_dump("cal")) == "ok"


def test_validate_rejection_carries_the_validators_output(monkeypatch, tmp_path):
    v = tmp_path / "validate.py"
    v.write_text("import sys; print('cal: 0 transactions, expected >= 100'); sys.exit(1)")
    monkeypatch.setattr(activities, "VALIDATOR", v)
    with pytest.raises(ApplicationError) as e:
        run(activities.validate_dump("cal"))
    assert "0 transactions, expected >= 100" in str(e.value)
    assert e.value.type == "ValidationFailed" and e.value.non_retryable
