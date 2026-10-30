"""Temporal activities for the multi-source finance sync.

Each activity wraps an existing, human-run script (the per-source refresh skills'
dump.sh, refresh-all's session checks, the digest chain, infra/deploy.sh) in a
subprocess. Which port, profile and dump to use comes from sources.py.
Nothing here authenticates a Chrome session: no OTPs, no Keychain. A dead session
is reported, never repaired. The one exception is a source whose own dump logs in
headless from .env (check=SELF, Discount mortgage and checking); its refused login is reported
as needs_login like a dead session.
"""
import asyncio
import collections
import contextlib
import fcntl
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
import urllib.request
from pathlib import Path

from temporalio import activity
from temporalio.exceptions import ApplicationError

import sources

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from finance import tenancy  # noqa: E402
from finance.paths import data_root  # noqa: E402
from finance.tenancy import DEFAULT_TENANT_ID  # noqa: E402


def _tid(tenant_id=None):
    """The tenant an activity works for. Activities receive it explicitly from the workflow;
    none means the master tenant, the single household this ran for before tenants."""
    return uuid.UUID(str(tenant_id)) if tenant_id else DEFAULT_TENANT_ID


def _tenant_env(tenant_id=None):
    """Environment that makes a child process (scraper, digest step, deploy) work for one tenant."""
    return {"FINANCE_TENANT_ID": str(_tid(tenant_id))}
SKILLS = REPO_ROOT / ".claude" / "skills"
REFRESH_ALL = SKILLS / "refresh-all" / "scripts"
AMEX_CHECK = SKILLS / "amex-refresh" / "scripts" / "check_session.sh"
VALIDATOR = REPO_ROOT / "data" / "validate.py"  # built separately; absent means no gate yet

CHROME_BIN = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PW_TIMEOUT = 30.0  # playwright-cli / check_session.sh can hang forever on a wedged Chrome
SESSIONS_TIMEOUT = 90.0  # check_sessions.sh makes several playwright-cli calls for one source
VALIDATE_TIMEOUT = 120.0

SESSION_EXPIRED = "SessionExpired"
SCRAPE_FAILED = "ScrapeFailed"
VALIDATION_FAILED = "ValidationFailed"

# What the dump scripts print when the session, not the endpoint, is the problem:
# amex's liveness gate, the Discount/Leumi/CAL/Harel stub guards (login-shell HTML,
# SME rebind) and the raw-CDP scripts (more, analyst) that find no logged-in tab.
EXPIRED_MARKERS = (
    "session not live", "VERDICT: LOGGED_OUT", "LOGIN-SHELL HTML", "actionRequired", "stepup",
    "קלט לא תקין", "session likely", "probably logged out", "No logged-in", "No amitim",
    # self-login scrapers (scrapers/*): the bank refused the .env credentials or wants a human step
    "LOGIN FAILED: INVALID_PASSWORD", "LOGIN FAILED: CHANGE_PASSWORD",
    "LOGIN FAILED: OTP_REQUIRED", "LOGIN FAILED: ACCOUNT_BLOCKED", "LOGIN FAILED: SESSION_EXPIRED",
    "LOGIN FAILED: OTP_TIMEOUT", "LOGIN FAILED: OTP_REJECTED", "LOGIN FAILED: LOGIN_ERROR",
    "LOGIN FAILED: BOT_BLOCKED",  # the site's bot protection refused the login call (HTTP 403/429)
)


def looks_expired(output: str) -> bool:
    """True when dump output says the login lapsed (log in again) rather than that an
    endpoint moved (triage the skill). Only known signatures count."""
    return any(m in output for m in EXPIRED_MARKERS)


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


def log_failure(kind: str, source: str, rc: int, tail: str) -> None:
    """Put a failed dump's output tail in the worker log. It otherwise lives only in the
    activity's failure details, i.e. in Temporal history, which is pruned after its retention."""
    activity.logger.error("%s failed for %s (rc=%s). Output tail:\n%s", kind, source, rc, tail or "(no output)")


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


def _load_app_tabs():
    """refresh-all's app_tab_index.py is the single tab-matching table; load it from
    its file (it is a script, not a package) instead of copying the table."""
    spec = importlib.util.spec_from_file_location("app_tab_index", REFRESH_ALL / "app_tab_index.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


app_tabs = _load_app_tabs()
INTERNAL_URLS = ("chrome://", "chrome-untrusted://", "devtools://", "chrome-extension://")


def _cdp(src, path: str) -> str:
    return f"http://127.0.0.1:{src.port}{path}"  # 127.0.0.1, never localhost (IPv6)


def _cdp_up(src) -> bool:
    try:
        with urllib.request.urlopen(_cdp(src, "/json/version"), timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


async def _wait_for_cdp(src, seconds: int) -> bool:
    for _ in range(seconds):
        if await asyncio.to_thread(_cdp_up, src):
            return True
        await asyncio.sleep(1)
    return False


def _launch_chrome(src):
    """Open the source's Chrome window exactly as the refresh skills do. It is
    detached so it outlives the worker. We only open the window; the human logs in."""
    subprocess.Popen(
        [
            CHROME_BIN,
            f"--remote-debugging-port={src.port}",
            f"--user-data-dir={src.profile}",
            "--no-first-run",
            "--no-default-browser-check",
            "--new-window",
            src.login_url,
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _cdp_pages(src) -> list:
    """Page targets from CDP /json/list (no playwright attach needed)."""
    with urllib.request.urlopen(_cdp(src, "/json/list"), timeout=3) as r:
        targets = json.loads(r.read())
    return [t for t in targets if t.get("type") == "page"]


def _open_tab(src, url: str):
    # /json/new needs PUT on modern Chrome; GET is rejected with 405.
    req = urllib.request.Request(_cdp(src, f"/json/new?{url}"), method="PUT")
    with urllib.request.urlopen(req, timeout=5) as r:
        r.read()


def _user_tabs(pages) -> list:
    """The tabs playwright-cli lists, in its order: chrome:// internals (browser_ui,
    omnibox popup) and extension targets are not tabs to it."""
    return [p for p in pages if not p.get("url", "").startswith(INTERNAL_URLS)]


def _tab_index(src, pages, *, app_only=False) -> int | None:
    """playwright tab index of the tab on src's app; else (unless app_only) the first
    tab anywhere on the bank's host, e.g. its login page, so the human finds the window."""
    tabs = _user_tabs(pages)
    idx = app_tabs.app_tab_index(tabs, src.app_tab_key)
    if idx is None and not app_only:
        idx = next((i for i, t in enumerate(tabs) if src.app_host in t.get("url", "")), None)
    return idx


def classify_tabs(src, pages) -> str:
    """Judge a session from open tabs alone: "live" on the app, "dead" when the bank's
    host shows a login page and nothing is on the app, else "unknown". No tab at all is
    unknown: a closed tab is not an expired session (check_sessions.sh's rule)."""
    tabs = _user_tabs(pages)
    if app_tabs.app_tab_index(tabs, src.app_tab_key) is not None:
        return "live"
    for t in tabs:
        url = t.get("url", "")
        if src.app_host in url and any(h in url.lower() for h in app_tabs.LOGIN_HINTS):
            return "dead"
    return "unknown"


async def _ensure_tab(src, *, open_url=None) -> int:
    """Return the index of src's tab, opening a page first when the profile has no tab on
    the bank (src's login page) or when `open_url` is given. Opening a login page is not
    authenticating."""
    idx = _tab_index(src, await asyncio.to_thread(_cdp_pages, src))
    if idx is None or open_url:
        await asyncio.to_thread(_open_tab, src, open_url or src.open_url)
        await asyncio.sleep(1)
        idx = _tab_index(src, await asyncio.to_thread(_cdp_pages, src))
    if idx is None:
        raise ApplicationError(f"no {src.name} tab in Chrome after opening one")
    return idx


async def _bind_playwright(src, tab: int):
    # Attaching is not authenticating; it only binds playwright-cli to the window.
    rc, tail = await run_cmd(
        ["playwright-cli", f"-s={src.pw_session}", "attach", f"--cdp=http://127.0.0.1:{src.port}"], timeout=PW_TIMEOUT
    )
    if rc != 0:
        raise ApplicationError(f"playwright-cli attach failed (rc={rc}):\n{tail}")
    await run_cmd(["playwright-cli", f"-s={src.pw_session}", "tab-select", str(tab)], timeout=PW_TIMEOUT)


@activity.defn
async def ensure_chrome(source: str) -> str:
    """Make sure the source's Chrome (its CDP port, persisted profile) is up, has a tab
    on the bank, and, for playwright sources, has a playwright-cli session attached to
    that tab. Returns "already_running" or "launched"."""
    src = sources.get(source)
    if src.check in (sources.SELF, sources.HEADLESS):
        return "already_running"  # no Chrome: the dump runs its own headless browser
    return await _open_chrome(src)


async def _open_chrome(src) -> str:
    state = "already_running"
    if not await asyncio.to_thread(_cdp_up, src):
        state = "launched"
        # Launch gotcha (SKILL.md): the launcher can exit without the port
        # binding. Poll, and retry the launch once.
        for _ in range(2):
            await asyncio.to_thread(_launch_chrome, src)
            if await _wait_for_cdp(src, 20):
                break
        else:
            raise ApplicationError(f"Chrome did not open CDP port {src.port}")
    # Without a tab on the bank attach/run-code hang (2026-10-16), so create one first.
    tab = await _ensure_tab(src)
    if src.playwright:
        await _bind_playwright(src, tab)
    return state


def parse_sessions_row(output: str, name: str) -> str | None:
    """Map check_sessions.sh's table row for `name` to live / dead / unknown. A closed
    Chrome is unknown, not dead. None when the row is missing (the script did not run)."""
    m = re.search(rf"^{re.escape(name)}\s+\d+\s+(.+?)\s*$", output, re.MULTILINE)
    if not m:
        return None
    status = m.group(1).lower()
    if status == "live":
        return "live"
    if status.startswith("needs login"):
        return "dead"
    return "unknown"


@activity.defn
async def check_session(source: str) -> str:
    """"live" | "dead" | "unknown". Read-only: never navigates, never logs in.
    "unknown" means the check could not tell (no tab on the app, page unreadable); the
    workflow scrapes it anyway and the dump script's stub guard is the backstop.
    Infrastructure failures raise (retryable); the workflow reads a persistent one as unknown."""
    src = sources.get(source)
    if src.check == sources.SELF:
        return "live"  # the dump authenticates itself; a bad login surfaces from scrape()
    if src.check == sources.HEADLESS:
        rc, tail = await run_cmd([src.dumps[0][0], "--check"], timeout=SESSIONS_TIMEOUT)
        live = parse_verdict(tail)
        if live is None:
            raise ApplicationError(f"{Path(src.dumps[0][0]).name} --check printed no VERDICT (rc={rc}):\n{tail}")
        if not live:
            await _open_chrome(src)  # the window the human logs in to; the recheck reuses it over CDP
        return "live" if live else "dead"
    if src.check == sources.VERDICT:
        # AMEX's own check_session.sh: auth cookies + /IsLoggedIn, the strongest signal we have.
        rc, tail = await run_cmd([str(AMEX_CHECK), src.pw_session], timeout=PW_TIMEOUT)
        live = parse_verdict(tail)
        if live is None:
            raise ApplicationError(f"check_session.sh printed no VERDICT (rc={rc}):\n{tail}")
        return "live" if live else "dead"

    if src.check == sources.SESSIONS:
        rc, tail = await run_cmd([str(REFRESH_ALL / "check_sessions.sh"), src.check_key], timeout=SESSIONS_TIMEOUT)
        verdict = parse_sessions_row(tail, src.check_key)
        if verdict is None:
            raise ApplicationError(f"check_sessions.sh printed no row for {src.check_key} (rc={rc}):\n{tail}")
        if verdict != "unknown":
            return verdict

    # Open tabs are all that is left to go on. For TABS sources that is the whole check; for
    # SESSIONS sources it can only upgrade "unknown" to "dead", when the bank's login page
    # is sitting in the window (check_sessions.sh itself only ever says live or unknown).
    try:
        verdict = classify_tabs(src, await asyncio.to_thread(_cdp_pages, src))
    except Exception:
        return "unknown"
    if src.check == sources.TABS:
        return verdict
    return "dead" if verdict == "dead" else "unknown"


@activity.defn
async def scrape(source: str, tenant_id: str | None = None) -> str:
    """Run the source's dump script(s) in order (each one re-guards against stubs and
    keeps the previous dump on failure). Every failure is non-retryable: retrying cannot
    fix a dead session or a moved endpoint, and the workflow must not hammer the bank."""
    src = sources.get(source)
    if src.playwright:
        # Re-select the right tab: the previous source on this Chrome (the Discount apps
        # share one) may have moved it. The only page ever opened here is the business app,
        # which runs LAST in the Discount chain, so rebinding the shared login is expected.
        pages = await asyncio.to_thread(_cdp_pages, src)
        missing = bool(src.app_url) and _tab_index(src, pages, app_only=True) is None
        await _bind_playwright(src, await _ensure_tab(src, open_url=src.app_url if missing else None))
    tail = ""
    for dump in src.dumps:
        argv = [str(SKILLS / dump[0])] + [a.format(session=src.pw_session, port=src.port) for a in dump[1:]]
        rc, tail = await run_cmd(argv, env=_tenant_env(tenant_id))
        if rc != 0:
            log_failure(Path(argv[0]).name, source, rc, tail)
            if looks_expired(tail):
                raise ApplicationError(f"{source} session expired", tail, type=SESSION_EXPIRED, non_retryable=True)
            raise ApplicationError(f"{Path(argv[0]).name} failed for {source} (rc={rc})", tail,
                                   type=SCRAPE_FAILED, non_retryable=True)
    return tail


@activity.defn
async def scrape_login(source: str) -> str:
    """Like `scrape`, but the dump may log in (`--login`) with a code the human types in the app,
    which `deliver_otp` drops into the source's OTP file. Never retried: a retry is another SMS."""
    src = sources.get(source)
    if not src.otp:
        raise ApplicationError(f"{source} has no app login", type=SCRAPE_FAILED, non_retryable=True)
    otp_file = otp_path(source)
    otp_file.unlink(missing_ok=True)  # a code left from an earlier run is stale
    argv = [src.dumps[0][0], "--login", "--otp-file", str(otp_file)]
    try:
        rc, tail = await run_cmd(argv)
    finally:
        otp_file.unlink(missing_ok=True)
    if rc != 0:
        log_failure(f"{Path(argv[0]).name} --login", source, rc, tail)
        if looks_expired(tail):
            raise ApplicationError(f"{source} login failed", tail, type=SESSION_EXPIRED, non_retryable=True)
        raise ApplicationError(f"{Path(argv[0]).name} --login failed for {source} (rc={rc})", tail,
                               type=SCRAPE_FAILED, non_retryable=True)
    return tail


def otp_path(source: str) -> Path:
    return sources.OTP_DIR / f"{sources.get(source).name}.code"


@activity.defn
async def deliver_otp(source: str, code: str) -> None:
    """Hand the human's code to the waiting `scrape_login` dump: an 0600 file it reads once and deletes."""
    if not sources.get(source).otp or not re.fullmatch(r"\d{4,8}", code or ""):
        raise ApplicationError("not a code", non_retryable=True)
    sources.OTP_DIR.mkdir(mode=0o700, exist_ok=True)
    target = otp_path(source)
    tmp = target.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(code)
    os.replace(tmp, target)


@activity.defn
async def validate_dump(source: str, tenant_id: str | None = None) -> dict:
    """Gate a fresh dump: `python3 data/validate.py dump <source> --json` (exit 0 = good).
    Returns {"gate": "ok" | "skipped", "records", "records_before", "latest_txn"} (the counts
    are None when the validator printed none, or does not exist yet). A rejection raises
    non-retryable with the validator's output, so the workflow does not count the scrape."""
    sources.get(source)
    if not VALIDATOR.exists():
        return {"gate": "skipped", "records": None, "records_before": None, "latest_txn": None}
    rc, tail = await run_cmd([sys.executable, str(VALIDATOR), "dump", source, "--json"], timeout=VALIDATE_TIMEOUT,
                          env=_tenant_env(tenant_id))
    if rc != 0:
        human = "\n".join(l for l in tail.splitlines() if not l.startswith("DUMP_JSON "))
        log_failure("validate.py", source, rc, human)
        raise ApplicationError(f"validate.py rejected the {source} dump (rc={rc}):\n{human}",
                               type=VALIDATION_FAILED, non_retryable=True)
    return {"gate": "ok", **parse_dump_json(tail)}


def parse_dump_json(output: str) -> dict:
    """Record counts from validate.py's `DUMP_JSON {...}` line; Nones when it is missing."""
    info = {"records": None, "records_before": None, "latest_txn": None}
    for line in reversed(output.splitlines()):
        if line.startswith("DUMP_JSON "):
            try:
                body = json.loads(line[len("DUMP_JSON "):])
            except ValueError:
                break
            return {k: body.get(k) for k in info}
    return info


DIGEST_STEPS = ["digest.py", "validate.py", "forecast.py", "cashflow.py", "goals.py"]  # order matters (sync-data skill)


DIGEST_LOCK = REPO_ROOT / "data" / "digested" / ".lock"


@contextlib.asynccontextmanager
async def digest_lock(path: Path = DIGEST_LOCK, poll: float = 0.2):
    """Exclusive `flock` on `path`, so two digest chains (FinanceSyncWorkflow and
    LedgerRebuildWorkflow) never write data/digested/ at once.

    Polls with LOCK_NB instead of blocking, so the event loop stays free and the activity
    keeps heartbeating while it waits behind a long digest. The kernel drops the lock if the
    worker dies, so a crash never leaves it stuck.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as fh:
        while True:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                _heartbeat("waiting for digest lock")
                await asyncio.sleep(poll)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


@activity.defn
async def digest(normalize: bool = True, tenant_id: str | None = None) -> dict:
    """digest -> validate -> forecast -> cashflow -> goals, under the digest file lock. Stops at
    the first failure so a half-rebuilt set is never published. `normalize=False` passes
    `--no-normalize` to digest.py (override-only edits don't need a re-normalize)."""
    tid = _tid(tenant_id)
    async with digest_lock(data_root(tid) / "digested" / ".lock"):
        for step in DIGEST_STEPS:
            cmd = [sys.executable, str(REPO_ROOT / "data" / step)]
            if step == "digest.py" and not normalize:
                cmd.append("--no-normalize")
            rc, tail = await run_cmd(cmd, env=_tenant_env(tid))
            if rc != 0:
                raise ApplicationError(f"{step} failed (rc={rc}):\n{tail}")
        summary = {"steps": DIGEST_STEPS}
        try:
            tx = json.loads((data_root(tid) / "digested" / "transactions.json").read_text())
            summary["transactions"] = len(tx["transactions"])
        except Exception:
            pass
        return summary


@activity.defn
async def publish_data(tenant_id: str | None = None) -> str:
    """infra/deploy.sh --data-only, only when SYNC_PUBLISH=1. Returns "published" or "skipped"."""
    if os.environ.get("SYNC_PUBLISH") != "1":
        return "skipped"
    tid = _tid(tenant_id)
    argv = [str(REPO_ROOT / "infra" / "deploy.sh"), "--data-only", "--tenant", str(tid)]
    rc, tail = await run_cmd(argv, env=_tenant_env(tid))
    if rc != 0:
        raise ApplicationError(f"deploy.sh --data-only failed (rc={rc}):\n{tail}")
    return "published"


@activity.defn
async def notify(title: str, message: str, pushes: list | None = None) -> None:
    """macOS notification via osascript, plus Web Push for each payload in `pushes`
    ({title, body, url, tag}). Never raises."""
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
    if pushes:
        await _push(pushes)


PUSH_TIMEOUT = 20.0  # inside NOTIFY's 30s start_to_close; a slow push service must not stall a sync


def _push_module():
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from finance import push
    return push


async def _push(payloads, tenant_id=None) -> dict | None:
    """Send Web Push payloads from a thread (psycopg/pywebpush block). Never raises."""
    try:
        tenancy.set_context(tenancy.TenantContext(None, _tid(tenant_id)))   # copied into the thread
        return await asyncio.wait_for(asyncio.to_thread(_push_module().send, payloads), timeout=PUSH_TIMEOUT)
    except BaseException as e:
        if isinstance(e, asyncio.CancelledError):
            raise
        return None


@activity.defn
async def push_event(payload: dict, tenant_id: str | None = None) -> str:
    """Web Push one {title, body, url, tag}: a source failed or its dump was rejected. Never raises."""
    res = await _push(payload, tenant_id)
    return f"{res['sent']} delivered" if res else "push unavailable"


@activity.defn
async def push_new_actions(tenant_id: str | None = None) -> str:
    """Push the PROBLEM / WARNING inbox items not pushed before (notifications.pushed_at). Never raises."""
    try:
        tenancy.set_context(tenancy.TenantContext(None, _tid(tenant_id)))
        return await asyncio.wait_for(asyncio.to_thread(_push_module().push_new_actions), timeout=PUSH_TIMEOUT)
    except Exception as e:
        return f"error: {e}"[:200]


@activity.defn
async def push_daily_summary(started_at: str, tenant_id: str | None = None) -> str:
    """After the evening run only (decided here from the workflow's start time, not in workflow
    code): balance, spent today and safe-to-spend. Never raises."""
    try:
        tenancy.set_context(tenancy.TenantContext(None, _tid(tenant_id)))
        push = _push_module()
        if not push.is_evening_run(started_at):
            return "skipped (not the evening run)"
        return await asyncio.wait_for(asyncio.to_thread(push.push_daily_summary), timeout=PUSH_TIMEOUT)
    except Exception as e:
        return f"error: {e}"[:200]


STATUS_FILE = REPO_ROOT / "data" / "digested" / "sync-status.json"
STATUS_KEY = "data/sync-status.json"
STATUS_UPLOAD_TIMEOUT = 15.0
_bucket_cache: str | None = None


BAD_TERMINAL = {"failed", "rejected", "needs_login"}


def _failure_streak(prev: dict, entry: dict) -> dict:
    """`failure_streak`: runs in a row that ended failed / rejected / needs_login for this source,
    0 after a `done`. A run republishes its status many times, so a run is counted once, by
    `streak_run_id`; in-flight statuses (scraping, validating...) just carry the count over."""
    streak, run = prev.get("failure_streak") or 0, prev.get("streak_run_id")
    status, run_id = entry.get("status"), entry.get("run_id")
    if status == "done":
        streak, run = 0, run_id
    elif status in BAD_TERMINAL and run_id != run:
        streak, run = streak + 1, run_id
    return {"failure_streak": streak, "streak_run_id": run}


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
    merged.update(_failure_streak(prev, entry))
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


def _database_url() -> str | None:
    """Owner DATABASE_URL from the environment, else from the repo .env."""
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    try:
        for line in (REPO_ROOT / ".env").read_text().splitlines():
            if line.startswith("DATABASE_URL="):
                return line.split("=", 1)[1].strip().strip("'\"") or None
    except OSError:
        pass
    return None


def _db_upsert_status(url: str, source: str, entry: dict) -> None:
    """Upsert one source's merged entry into sync_status; its trigger NOTIFYs the API."""
    import psycopg
    from psycopg.types.json import Jsonb

    with psycopg.connect(url, connect_timeout=3) as conn:
        conn.execute(
            "INSERT INTO sync_status (source, entry) VALUES (%s, %s) "
            "ON CONFLICT (source) DO UPDATE SET entry = EXCLUDED.entry, updated_at = now()",
            (source, Jsonb(entry)),
        )


def seed_status_db() -> int:
    """Copy sync-status.json into an empty-for-that-source sync_status, so the first SSE
    snapshot after a deploy isn't blank. Existing rows win. Best-effort; returns rows added."""
    url = _database_url()
    if not url or not STATUS_FILE.exists():
        return 0
    try:
        import psycopg
        from psycopg.types.json import Jsonb

        sources = json.loads(STATUS_FILE.read_text()).get("sources") or {}
        with psycopg.connect(url, connect_timeout=3) as conn:
            added = 0
            for source, entry in sources.items():
                cur = conn.execute(
                    "INSERT INTO sync_status (source, entry) VALUES (%s, %s) ON CONFLICT (source) DO NOTHING",
                    (source, Jsonb(entry)),
                )
                added += cur.rowcount
            return added
    except Exception as e:  # noqa: BLE001 - status is best-effort by design
        print(f"sync_status seed skipped: {e}", flush=True)
        return 0


async def _push_status_db(source: str, entry: dict) -> None:
    """Best-effort DB push: no DATABASE_URL skips silently, any error only warns."""
    url = _database_url()
    if not url:
        return
    try:
        await asyncio.to_thread(_db_upsert_status, url, source, entry)
    except Exception as e:  # noqa: BLE001 - status is best-effort by design
        activity.logger.warning("sync_status DB upsert failed for %s: %s", source, e)


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
async def publish_status(source: str, entry: dict, tenant_id: str | None = None) -> str:
    """Write the live status of one source to data/digested/sync-status.json, upsert
    it into Postgres `sync_status` (NOTIFY -> API SSE) when DATABASE_URL is set and,
    with SYNC_PUBLISH=1, copy it to s3://<bucket>/data/sync-status.json.

    Status only: no secrets, cookies or account data. Never raises, so a missing
    bucket or a network blip can never fail the sync. Returns "published",
    "local" or "error: ...".
    """
    if _tid(tenant_id) != DEFAULT_TENANT_ID:
        return "skipped (status is the master tenant's; follow other tenants in the Temporal UI)"
    try:
        doc = _write_status(source, entry)
        await _push_status_db(source, doc["sources"][source])
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


@activity.defn
async def failure_streak(source: str, tenant_id: str | None = None) -> int:
    """Failed runs in a row for `source`, as publish_status recorded them (0 when unknown)."""
    if _tid(tenant_id) != DEFAULT_TENANT_ID:
        return 0
    try:
        return int(json.loads(STATUS_FILE.read_text())["sources"][source].get("failure_streak") or 0)
    except (OSError, ValueError, KeyError, TypeError):
        return 0


ALL_ACTIVITIES = [ensure_chrome, check_session, scrape, scrape_login, deliver_otp, validate_dump, digest, publish_data, notify, publish_status, failure_streak,
                  push_event, push_new_actions, push_daily_summary]
