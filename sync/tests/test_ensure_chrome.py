"""Regression tests for the 2026-10-16 incident: the AMEX Chrome (9226) had run
for 7 days holding only More/Harel tabs (plus browser_ui/omnibox and extension
targets), and `playwright-cli attach` / `run-code` hung forever. AMEX now logs in headless,
and Harel scrapes headless too, so a Chrome-style Harel (the chrome_harel fixture) carries the
same scenario: its Chrome holding only other banks' tabs."""
import asyncio
import sys
import time

import pytest
from temporalio.exceptions import ApplicationError

import activities
import sources

HAREL = sources.get("harel")

INCIDENT_TARGETS = [
    {"type": "page", "url": "chrome://omnibox-popup.top-chrome/"},
    {"type": "page", "url": "chrome://browser-ui/"},
    {"type": "page", "url": "https://www.more.co.il/personal-area"},
    {"type": "page", "url": "https://web.americanexpress.co.il/transactions"},
    {"type": "background_page", "url": "chrome-extension://abc/_generated_background_page.html"},
    {"type": "service_worker", "url": "chrome-extension://abc/sw.js"},
]


def _run(coro):
    return asyncio.run(coro)


def test_no_harel_tab_in_incident_profile():
    assert activities._tab_index(HAREL, INCIDENT_TARGETS) is None


def test_harel_tab_index_skips_internal_targets():
    pages = INCIDENT_TARGETS + [{"type": "page", "url": "https://www.harel-group.co.il/client-view"}]
    pages = [p for p in pages if p["type"] == "page"]
    assert activities._tab_index(HAREL, pages) == 2  # after More and AMEX, not browser_ui/omnibox


def test_ensure_chrome_opens_harel_tab_and_selects_it(monkeypatch, chrome_harel):
    pages = [t for t in INCIDENT_TARGETS if t["type"] == "page"]
    listings = [pages, pages + [{"type": "page", "url": chrome_harel.open_url}]]
    opened, calls = [], []

    async def no_sleep(_):
        pass

    async def fake_run_cmd(args, **kw):
        calls.append((args, kw))
        return 0, ""

    monkeypatch.setattr(activities, "_cdp_up", lambda src: True)
    monkeypatch.setattr(activities, "_cdp_pages", lambda src: listings.pop(0))
    monkeypatch.setattr(activities, "_open_tab", lambda src, url: opened.append(url))
    monkeypatch.setattr(activities, "run_cmd", fake_run_cmd)
    monkeypatch.setattr(activities.asyncio, "sleep", no_sleep)

    assert _run(activities.ensure_chrome("chrome-harel")) == "already_running"
    assert opened == [chrome_harel.open_url]
    attach, select = calls
    assert "attach" in attach[0] and attach[1]["timeout"] == activities.PW_TIMEOUT
    assert "--cdp=http://127.0.0.1:9227" in attach[0]
    assert select[0][-2:] == ["tab-select", "2"] and select[1]["timeout"] == activities.PW_TIMEOUT


def test_existing_harel_tab_is_not_reopened(monkeypatch):
    pages = [{"type": "page", "url": "https://www.harel-group.co.il/x"}]
    monkeypatch.setattr(activities, "_cdp_pages", lambda src: pages)
    monkeypatch.setattr(activities, "_open_tab", lambda src, url: pytest.fail("must not open a second tab"))
    assert _run(activities._ensure_tab(HAREL)) == 0


def test_raw_cdp_sources_get_a_tab_but_no_playwright_session(monkeypatch):
    calls = []

    async def fake_run_cmd(args, **kw):
        calls.append(args)
        return 0, ""

    pages = [{"type": "page", "url": "https://my-account.more.co.il/personalarea/dashboard"}]
    monkeypatch.setattr(activities, "_cdp_up", lambda src: True)
    monkeypatch.setattr(activities, "_cdp_pages", lambda src: pages)
    monkeypatch.setattr(activities, "run_cmd", fake_run_cmd)
    assert _run(activities.ensure_chrome("more")) == "already_running"
    assert calls == []  # more/analyst dump over raw CDP; attaching playwright has hung on shared Chrome


def test_ensure_chrome_launches_with_the_sources_own_port_and_profile(monkeypatch, chrome_harel):
    launched, up = [], []

    async def no_sleep(_):
        pass

    def fake_launch(src):
        launched.append(src.name)
        up.append(True)

    async def fake_run_cmd(args, **kw):
        return 0, ""

    monkeypatch.setattr(activities, "_cdp_up", lambda src: bool(up))
    monkeypatch.setattr(activities, "_launch_chrome", fake_launch)
    monkeypatch.setattr(activities, "_cdp_pages", lambda src: [{"type": "page", "url": "https://www.harel-group.co.il/x"}])
    monkeypatch.setattr(activities, "run_cmd", fake_run_cmd)
    monkeypatch.setattr(activities.asyncio, "sleep", no_sleep)
    assert _run(activities.ensure_chrome("chrome-harel")) == "launched"
    assert launched == ["chrome-harel"]
    assert sources.get("harel").port == 9227 and sources.get("harel").profile.name == ".chrome-cdp-harel"


def test_run_cmd_kills_hung_command_and_raises():
    start = time.monotonic()
    with pytest.raises(ApplicationError) as e:
        _run(activities.run_cmd([sys.executable, "-c", "import time; print('attaching', flush=True); time.sleep(60)"],
                                timeout=0.5, heartbeat_every=0.1))
    assert time.monotonic() - start < 5
    assert "timed out" in str(e.value) and "attaching" in str(e.value)
    assert not e.value.non_retryable  # retryable: Temporal retries after Chrome recovers


def test_run_cmd_without_timeout_unchanged():
    rc, tail = _run(activities.run_cmd([sys.executable, "-c", "print('ok')"]))
    assert (rc, tail) == (0, "ok")


def test_check_session_hang_is_bounded(monkeypatch, chrome_harel):
    seen = {}

    async def fake_run_cmd(args, **kw):
        seen.update(kw)
        return 0, "harel        9227   live\n"

    monkeypatch.setattr(activities, "run_cmd", fake_run_cmd)
    assert _run(activities.check_session("chrome-harel")) == "live"
    assert seen["timeout"] == activities.SESSIONS_TIMEOUT


# --- Harel headless: `scrape.mjs --check` is the session check, no Chrome until a human must log in ---

def test_harel_is_headless_and_needs_no_chrome(monkeypatch):
    assert HAREL.check == sources.HEADLESS and not HAREL.playwright
    monkeypatch.setattr(activities, "_cdp_up", lambda src: pytest.fail("must not touch Chrome"))
    assert _run(activities.ensure_chrome("harel")) == "already_running"


def _harel_check(monkeypatch, rc, out):
    seen, opened = [], []

    async def fake_run_cmd(args, **kw):
        seen.append((args, kw))
        return rc, out

    async def fake_open(src):
        opened.append(src.name)
        return "launched"

    monkeypatch.setattr(activities, "run_cmd", fake_run_cmd)
    monkeypatch.setattr(activities, "_open_chrome", fake_open)
    return seen, opened


def test_harel_live_session_opens_no_window(monkeypatch):
    seen, opened = _harel_check(monkeypatch, 0, "VERDICT: LIVE\n")
    assert _run(activities.check_session("harel")) == "live"
    (args, kw), = seen
    assert args[0].endswith("scrapers/harel/scrape.mjs") and args[1:] == ["--check"]
    assert kw["timeout"] == activities.SESSIONS_TIMEOUT
    assert opened == []


def test_harel_dead_session_opens_the_login_window(monkeypatch):
    _, opened = _harel_check(monkeypatch, 3, "LOGIN FAILED: SESSION_EXPIRED\nVERDICT: LOGGED_OUT\n")
    assert _run(activities.check_session("harel")) == "dead"
    assert opened == ["harel"]  # the human logs in there; the recheck reuses it over CDP


def test_harel_check_without_verdict_is_an_infrastructure_error(monkeypatch):
    _, opened = _harel_check(monkeypatch, 1, "Error: Failed to launch the browser process\n")
    with pytest.raises(ApplicationError):
        _run(activities.check_session("harel"))
    assert opened == []


def test_harel_session_expiring_mid_scrape_is_needs_login():
    assert activities.looks_expired("LOGIN FAILED: SESSION_EXPIRED\n")
