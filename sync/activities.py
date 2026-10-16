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
import tempfile
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
AMEX_TAB_URL = "https://web.americanexpress.co.il/"  # opened when the profile has no AMEX tab
AMEX_HOST = "americanexpress.co.il"
CDP_LIST_URL = f"http://127.0.0.1:{CDP_PORT}/json/list"
CDP_NEW_URL = f"http://127.0.0.1:{CDP_PORT}/json/new?{AMEX_TAB_URL}"
PW_SESSION = "amex"
PW_TIMEOUT = 30.0  # playwright-cli / check_session.sh can hang forever on a wedged Chrome

SESSION_EXPIRED = "SessionExpired"
SCRAPE_FAILED = "ScrapeFailed"

# Starts a line, or follows a literal "\n" / opening quote: playwright-cli --raw
# JSON-quotes the returned string, so its newlines arrive escaped.
_VERDICT_RE = re.compile(r'(?:^|\\n|")VERDICT:\s*(LIVE|LOGGED_OUT)\b', re.MULTILINE)


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


async def run_cmd(args, *, env=None, heartbeat_every=10.0, tail_lines=40, timeout=None):
    """Run a command in the repo root, heartbeating while it runs.

    Returns (returncode, tail) where tail is the last `tail_lines` lines of
    merged stdout+stderr. The process is killed if the activity is cancelled.
    With `timeout` (seconds) a command that overruns is killed and a retryable
    ApplicationError is raised, so a hung playwright-cli fails fast.
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
    loop = asyncio.get_running_loop()
    deadline = None if timeout is None else loop.time() + timeout
    try:
        while not reader.done():
            wait = heartbeat_every
            if deadline is not None:
                wait = min(wait, max(deadline - loop.time(), 0))
            await asyncio.wait({reader}, timeout=wait)
            _heartbeat(tail[-1] if tail else None)
            if deadline is not None and not reader.done() and loop.time() >= deadline:
                raise ApplicationError(
                    f"{' '.join(str(a) for a in args[:3])} timed out after {timeout:g}s:\n" + "\n".join(tail)
                )
        await proc.wait()
    except BaseException:
        if proc.returncode is None:
            proc.kill()
            await asyncio.shield(proc.wait())
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


def _cdp_pages() -> list:
    """Page targets from CDP /json/list (no playwright attach needed)."""
    with urllib.request.urlopen(CDP_LIST_URL, timeout=3) as r:
        targets = json.loads(r.read())
    return [t for t in targets if t.get("type") == "page"]


def _open_amex_tab():
    # /json/new needs PUT on modern Chrome; GET is rejected with 405.
    req = urllib.request.Request(CDP_NEW_URL, method="PUT")
    with urllib.request.urlopen(req, timeout=5) as r:
        r.read()


def _amex_tab_index(pages) -> int | None:
    """Index of the first AMEX page among the user-facing tabs, or None.
    chrome:// internals (browser_ui, omnibox popup) are not tabs playwright lists."""
    tabs = [p for p in pages if not p.get("url", "").startswith(("chrome://", "chrome-untrusted://", "devtools://", "chrome-extension://"))]
    for i, p in enumerate(tabs):
        if AMEX_HOST in p.get("url", ""):
            return i
    return None


async def _ensure_amex_tab() -> int:
    """Make sure an AMEX tab exists (open one if not) and return its tab index.
    Opening the login page is not authenticating."""
    pages = await asyncio.to_thread(_cdp_pages)
    idx = _amex_tab_index(pages)
    if idx is None:
        await asyncio.to_thread(_open_amex_tab)
        await asyncio.sleep(1)
        idx = _amex_tab_index(await asyncio.to_thread(_cdp_pages))
    if idx is None:
        raise ApplicationError("no AMEX tab in Chrome after opening one")
    return idx


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
    # Without an AMEX tab attach/run-code hang (2026-10-16), so create one first.
    tab = await _ensure_amex_tab()
    # Attaching is not authenticating; it only binds playwright-cli to the window.
    rc, tail = await run_cmd(
        ["playwright-cli", f"-s={PW_SESSION}", "attach", f"--cdp=http://127.0.0.1:{CDP_PORT}"], timeout=PW_TIMEOUT
    )
    if rc != 0:
        raise ApplicationError(f"playwright-cli attach failed (rc={rc}):\n{tail}")
    await run_cmd(["playwright-cli", f"-s={PW_SESSION}", "tab-select", str(tab)], timeout=PW_TIMEOUT)
    return state


@activity.defn
async def check_amex_session() -> bool:
    """True when check_session.sh prints VERDICT: LIVE. False for LOGGED_OUT.
    A missing verdict is an infrastructure problem and raises (retryable)."""
    rc, tail = await run_cmd([str(SKILL_SCRIPTS / "check_session.sh"), PW_SESSION], timeout=PW_TIMEOUT)
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


STATUS_FILE = REPO_ROOT / "data" / "digested" / "sync-status.json"
STATUS_KEY = "data/sync-status.json"
STATUS_UPLOAD_TIMEOUT = 15.0
_bucket_cache: str | None = None


def merge_status(doc: dict | None, source: str, entry: dict) -> dict:
    """Fold one source's status `entry` into the sync-status document.

    Other sources are kept as-is. `last_success_at` survives across runs and is
    moved forward only when this entry reports `done`. Pure, so it is unit-tested.
    """
    doc = dict(doc or {})
    sources = dict(doc.get("sources") or {})
    prev = sources.get(source) or {}
    merged = {**entry}
    merged["last_success_at"] = entry["updated_at"] if entry.get("status") == "done" else prev.get("last_success_at")
    sources[source] = merged
    doc["sources"] = sources
    doc["updated_at"] = entry["updated_at"]
    return doc


def _write_status(source: str, entry: dict) -> dict:
    try:
        doc = json.loads(STATUS_FILE.read_text())
    except (OSError, ValueError):
        doc = None
    doc = merge_status(doc, source, entry)
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Atomic replace: the dev server or an upload must never read half a file.
    with tempfile.NamedTemporaryFile("w", dir=STATUS_FILE.parent, delete=False, suffix=".tmp") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    os.replace(f.name, STATUS_FILE)
    return doc


async def _bucket() -> str | None:
    """BUCKET env, else `terraform output -raw bucket` (cached for the worker's life)."""
    global _bucket_cache
    if _bucket_cache is None:
        _bucket_cache = os.environ.get("BUCKET") or ""
        if not _bucket_cache:
            proc = await asyncio.create_subprocess_exec(
                "terraform", "output", "-raw", "bucket", cwd=str(REPO_ROOT / "infra"),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            )
            out, _ = await asyncio.wait_for(proc.communicate(), STATUS_UPLOAD_TIMEOUT)
            _bucket_cache = out.decode().strip() if proc.returncode == 0 else ""
    return _bucket_cache or None


@activity.defn
async def publish_status(source: str, entry: dict) -> str:
    """Write the live status of one source to data/digested/sync-status.json and,
    with SYNC_PUBLISH=1, copy it to s3://<bucket>/data/sync-status.json.

    Status only: no secrets, cookies or account data. Never raises, so a missing
    bucket or a network blip can never fail the sync. Returns "published",
    "local" or "error: ...".
    """
    try:
        _write_status(source, entry)
        if os.environ.get("SYNC_PUBLISH") != "1":
            return "local"
        bucket = await _bucket()
        if not bucket:
            return "error: bucket unknown"
        rc, tail = await run_cmd([
            "aws", "s3", "cp", str(STATUS_FILE), f"s3://{bucket}/{STATUS_KEY}",
            "--cache-control", "no-cache,no-store,must-revalidate",
            "--content-type", "application/json; charset=utf-8",
        ], timeout=STATUS_UPLOAD_TIMEOUT)
        return "published" if rc == 0 else f"error: aws rc={rc}: {tail[-200:]}"
    except Exception as e:  # noqa: BLE001 - status is best-effort by design
        return f"error: {e}"


ALL_ACTIVITIES = [ensure_chrome, check_amex_session, scrape_amex, digest, publish_data, notify, publish_status]
