"""Temporal activities for the AMEX sync.

Each activity wraps an existing, human-run script (the amex-refresh skill's
scripts, the digest chain, infra/deploy.sh) in a subprocess. Nothing here ever
authenticates: no credentials, no OTPs, no Keychain. A dead session is reported,
never repaired.
"""
import asyncio
import collections
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

from temporalio import activity
from temporalio.exceptions import ApplicationError

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_SCRIPTS = REPO_ROOT / ".claude" / "skills" / "amex-refresh" / "scripts"

CDP_PORT = 9226
CDP_VERSION_URL = f"http://127.0.0.1:{CDP_PORT}/json/version"  # 127.0.0.1, never localhost (IPv6)
CHROME_BIN = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
CHROME_PROFILE = Path.home() / ".chrome-cdp-amex"
AMEX_URL = "https://www.americanexpress.co.il/"
PW_SESSION = "amex"

SESSION_EXPIRED = "SessionExpired"
SCRAPE_FAILED = "ScrapeFailed"

_VERDICT_RE = re.compile(r"^VERDICT:\s*(LIVE|LOGGED_OUT)\s*$", re.MULTILINE)


def parse_verdict(output: str):
    """Return True/False from the last `VERDICT: LIVE|LOGGED_OUT` line of
    check_session.sh output, or None when there is no verdict (e.g. playwright-cli
    could not attach). The exit code alone is not trusted: check_session.sh
    swallows playwright-cli failures, so "no verdict" must stay distinguishable
    from "logged out"."""
    matches = _VERDICT_RE.findall(output)
    if not matches:
        return None
    return matches[-1] == "LIVE"


def _heartbeat(detail=None):
    try:
        activity.heartbeat(detail)
    except RuntimeError:  # not inside an activity (unit tests)
        pass


async def run_cmd(args, *, env=None, heartbeat_every=10.0, tail_lines=40):
    """Run a command in the repo root, heartbeating while it runs.

    Returns (returncode, tail) where tail is the last `tail_lines` lines of
    merged stdout+stderr. The process is killed if the activity is cancelled.
    """
    proc = await asyncio.create_subprocess_exec(
        *args,
        cwd=str(REPO_ROOT),
        env={**os.environ, **(env or {})},
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    tail = collections.deque(maxlen=tail_lines)

    async def pump():
        async for line in proc.stdout:
            tail.append(line.decode("utf-8", "replace").rstrip())

    reader = asyncio.ensure_future(pump())
    try:
        while not reader.done():
            await asyncio.wait({reader}, timeout=heartbeat_every)
            _heartbeat(tail[-1] if tail else None)
        await proc.wait()
    except BaseException:
        if proc.returncode is None:
            proc.kill()
        reader.cancel()
        raise
    return proc.returncode, "\n".join(tail)


def _cdp_up() -> bool:
    try:
        with urllib.request.urlopen(CDP_VERSION_URL, timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


async def _wait_for_cdp(seconds: int) -> bool:
    for _ in range(seconds):
        if await asyncio.to_thread(_cdp_up):
            return True
        await asyncio.sleep(1)
    return False


def _launch_chrome():
    """Open the AMEX Chrome window exactly as the amex-refresh skill does. It is
    detached so it outlives the worker. We only open the window; the human logs in."""
    subprocess.Popen(
        [
            CHROME_BIN,
            f"--remote-debugging-port={CDP_PORT}",
            f"--user-data-dir={CHROME_PROFILE}",
            "--no-first-run",
            "--no-default-browser-check",
            "--new-window",
            AMEX_URL,
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


@activity.defn
async def ensure_chrome() -> str:
    """Make sure the AMEX Chrome (CDP 9226, persisted profile) is up and that a
    playwright-cli session is attached to it. Returns "already_running" or "launched"."""
    state = "already_running"
    if not await asyncio.to_thread(_cdp_up):
        state = "launched"
        # Launch gotcha (SKILL.md): the launcher can exit without the port
        # binding. Poll, and retry the launch once.
        for _ in range(2):
            await asyncio.to_thread(_launch_chrome)
            if await _wait_for_cdp(20):
                break
        else:
            raise ApplicationError(f"Chrome did not open CDP port {CDP_PORT}")
    # Attaching is not authenticating; it only binds playwright-cli to the window.
    rc, tail = await run_cmd(["playwright-cli", f"-s={PW_SESSION}", "attach", f"--cdp=http://127.0.0.1:{CDP_PORT}"])
    if rc != 0:
        raise ApplicationError(f"playwright-cli attach failed (rc={rc}):\n{tail}")
    await run_cmd(["playwright-cli", f"-s={PW_SESSION}", "tab-select", "0"])
    return state


@activity.defn
async def check_amex_session() -> bool:
    """True when check_session.sh prints VERDICT: LIVE. False for LOGGED_OUT.
    A missing verdict is an infrastructure problem and raises (retryable)."""
    rc, tail = await run_cmd([str(SKILL_SCRIPTS / "check_session.sh"), PW_SESSION])
    live = parse_verdict(tail)
    if live is None:
        raise ApplicationError(f"check_session.sh printed no VERDICT (rc={rc}):\n{tail}")
    return live


@activity.defn
async def scrape_amex() -> str:
    """Run dump.sh (which re-checks liveness and never overwrites a good dump
    with a stub). Every failure is non-retryable: retrying cannot fix a dead
    session or a moved endpoint, and the workflow must not hammer the bank."""
    rc, tail = await run_cmd([str(SKILL_SCRIPTS / "dump.sh"), PW_SESSION])
    if rc == 0:
        return tail
    if "session not live" in tail or "VERDICT: LOGGED_OUT" in tail:
        raise ApplicationError("AMEX session expired", tail, type=SESSION_EXPIRED, non_retryable=True)
    raise ApplicationError(f"dump.sh failed (rc={rc})", tail, type=SCRAPE_FAILED, non_retryable=True)


DIGEST_STEPS = ["digest.py", "forecast.py", "cashflow.py", "goals.py"]  # order matters (sync-data skill)


@activity.defn
async def digest() -> dict:
    """digest -> forecast -> cashflow -> goals. Stops at the first failure so a
    half-rebuilt set is never published."""
    for step in DIGEST_STEPS:
        rc, tail = await run_cmd([sys.executable, str(REPO_ROOT / "data" / step)])
        if rc != 0:
            raise ApplicationError(f"{step} failed (rc={rc}):\n{tail}")
    summary = {"steps": DIGEST_STEPS}
    try:
        tx = json.loads((REPO_ROOT / "data" / "digested" / "transactions.json").read_text())
        summary["transactions"] = len(tx["transactions"])
    except Exception:
        pass
    return summary


@activity.defn
async def publish_data() -> str:
    """infra/deploy.sh --data-only, only when SYNC_PUBLISH=1. Returns "published" or "skipped"."""
    if os.environ.get("SYNC_PUBLISH") != "1":
        return "skipped"
    rc, tail = await run_cmd([str(REPO_ROOT / "infra" / "deploy.sh"), "--data-only"])
    if rc != 0:
        raise ApplicationError(f"deploy.sh --data-only failed (rc={rc}):\n{tail}")
    return "published"


@activity.defn
async def notify(title: str, message: str) -> None:
    """macOS notification via osascript. Never raises."""
    try:
        # Values go in as argv, so quotes in the text cannot break the script.
        await run_cmd([
            "osascript",
            "-e", "on run argv",
            "-e", "display notification (item 2 of argv) with title (item 1 of argv)",
            "-e", "end run",
            title, message,
        ])
    except Exception:
        pass


ALL_ACTIVITIES = [ensure_chrome, check_amex_session, scrape_amex, digest, publish_data, notify]
