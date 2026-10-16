"""Regression tests for the 2026-10-16 incident: the AMEX Chrome (9226) had run
for 7 days holding only More/Harel tabs (plus browser_ui/omnibox and extension
targets), and `playwright-cli attach` / `run-code` hung forever."""
import asyncio
import sys
import time

import pytest
from temporalio.exceptions import ApplicationError

import activities

INCIDENT_TARGETS = [
    {"type": "page", "url": "chrome://omnibox-popup.top-chrome/"},
    {"type": "page", "url": "chrome://browser-ui/"},
    {"type": "page", "url": "https://www.more.co.il/personal-area"},
    {"type": "page", "url": "https://www.harel-group.co.il/client-view"},
    {"type": "background_page", "url": "chrome-extension://abc/_generated_background_page.html"},
    {"type": "service_worker", "url": "chrome-extension://abc/sw.js"},
]


def _run(coro):
    return asyncio.run(coro)


def test_no_amex_tab_in_incident_profile():
    assert activities._amex_tab_index(INCIDENT_TARGETS) is None


def test_amex_tab_index_skips_internal_targets():
    pages = INCIDENT_TARGETS + [{"type": "page", "url": "https://web.americanexpress.co.il/login"}]
    pages = [p for p in pages if p["type"] == "page"]
    assert activities._amex_tab_index(pages) == 2  # after More and Harel, not browser_ui/omnibox


def test_ensure_chrome_opens_amex_tab_and_selects_it(monkeypatch):
    listings = [
        [t for t in INCIDENT_TARGETS if t["type"] == "page"],
        [t for t in INCIDENT_TARGETS if t["type"] == "page"] + [{"type": "page", "url": "https://web.americanexpress.co.il/"}],
    ]
    opened, calls = [], []

    async def no_sleep(_):
        pass

    async def fake_run_cmd(args, **kw):
        calls.append((args, kw))
        return 0, ""

    monkeypatch.setattr(activities, "_cdp_up", lambda: True)
    monkeypatch.setattr(activities, "_cdp_pages", lambda: listings.pop(0))
    monkeypatch.setattr(activities, "_open_amex_tab", lambda: opened.append(1))
    monkeypatch.setattr(activities, "run_cmd", fake_run_cmd)
    monkeypatch.setattr(activities.asyncio, "sleep", no_sleep)

    assert _run(activities.ensure_chrome()) == "already_running"
    assert opened == [1]
    attach, select = calls
    assert "attach" in attach[0] and attach[1]["timeout"] == activities.PW_TIMEOUT
    assert select[0][-2:] == ["tab-select", "2"] and select[1]["timeout"] == activities.PW_TIMEOUT


def test_existing_amex_tab_is_not_reopened(monkeypatch):
    pages = [{"type": "page", "url": "https://web.americanexpress.co.il/x"}]
    monkeypatch.setattr(activities, "_cdp_pages", lambda: pages)
    monkeypatch.setattr(activities, "_open_amex_tab", lambda: pytest.fail("must not open a second tab"))
    assert _run(activities._ensure_amex_tab()) == 0


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


def test_check_session_hang_is_bounded(monkeypatch):
    seen = {}

    async def fake_run_cmd(args, **kw):
        seen.update(kw)
        return 0, "VERDICT: LIVE"

    monkeypatch.setattr(activities, "run_cmd", fake_run_cmd)
    assert _run(activities.check_amex_session()) is True
    assert seen["timeout"] == activities.PW_TIMEOUT
