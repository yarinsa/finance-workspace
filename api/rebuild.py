"""Talk to Temporal: ask the host worker to rebuild and publish the ledger after an edit.

The workflow lives in sync/ (a different deployment), so it is referred to by name only.
The API never fails because Temporal is down: an edit is already saved, and the next
signal or the daily sync publishes it.
"""
import asyncio
import logging
import uuid
from datetime import timedelta

from temporalio.api.workflowservice.v1 import GetSystemInfoRequest
from temporalio.client import Client
from temporalio.common import WorkflowIDConflictPolicy

from finance.tenancy import DEFAULT_TENANT_ID

log = logging.getLogger("finance_api")

WORKFLOW = "LedgerRebuildWorkflow"
WORKFLOW_ID = "ledger-rebuild"
ACCESS_WORKFLOW = "TenantAccessWorkflow"
ACCESS_WAIT = 40   # seconds the app waits for a Cognito group change
TASK_QUEUE = "finance-sync"
SIGNAL = "edited"
QUERY = "status"
TIMEOUT = 3.0

# Logging in from the app: a one-source FinanceSyncWorkflow whose dump asks for an SMS and waits
# for the code the human types (signal `submit_otp`). Only these sources have an app login.
SYNC_WORKFLOW = "FinanceSyncWorkflow"
OTP_SOURCES = frozenset({"harel"})
OTP_SIGNAL = "submit_otp"


def rebuild_workflow_id(tenant_id=None):
    """One debounced rebuild per tenant; the master tenant keeps the original id."""
    tid = str(tenant_id or DEFAULT_TENANT_ID)
    return WORKFLOW_ID if tid == str(DEFAULT_TENANT_ID) else f"{WORKFLOW_ID}-{tid}"


def login_workflow_id(source):
    return f"finance-sync-login-{source}"


def retry_workflow_id(source):
    # An OTP source's retry may have to log in again, and submit_otp signals the login id.
    return login_workflow_id(source) if source in OTP_SOURCES else f"finance-sync-retry-{source}"


RETRYABLE = frozenset({"failed", "rejected"})
DIGEST_STEP = 4  # sync/workflows.py STEPS: digesting = 4, publishing = 5


def resume_point(entry):
    """Where a retry continues for this sync_status entry: "digest" when the source stopped in
    digest/publish (its dump is on disk and validated), "scrape" for anything earlier, None when
    the last run did not fail. A failed entry keeps the step it reached."""
    if not entry or entry.get("status") not in RETRYABLE:
        return None
    if entry["status"] == "failed" and (entry.get("step") or 0) >= DIGEST_STEP:
        return "digest"
    return "scrape"


IDLE = {"state": "idle", "last_published_at": None, "last_error": None}


class Rebuilder:
    """Sync facade (the routes are sync handlers). Each call opens a short-lived client."""

    def __init__(self, address):
        self.address = address

    def _run(self, coro_fn):
        async def go():
            client = await asyncio.wait_for(Client.connect(self.address), TIMEOUT)
            return await asyncio.wait_for(coro_fn(client), TIMEOUT)
        return asyncio.run(go())

    def signal_edited(self, tenant_id=None):
        """Signal-with-start this tenant's rebuild: starts it if idle, else tells the running one.
        Never raises."""
        tid = str(tenant_id or DEFAULT_TENANT_ID)
        opts = None if tid == str(DEFAULT_TENANT_ID) else {"tenant_id": tid}

        async def go(client):
            await client.start_workflow(
                WORKFLOW, arg=opts, id=rebuild_workflow_id(tid), task_queue=TASK_QUEUE, start_signal=SIGNAL,
                id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING)
        try:
            self._run(go)
            return True
        except Exception:
            log.exception("could not signal %s; the edit is saved and will publish with the next rebuild", WORKFLOW)
            return False

    def status(self, tenant_id=None):
        """This tenant's rebuild `status` query, or idle if there is no workflow or Temporal is down."""
        async def go(client):
            return await client.get_workflow_handle(rebuild_workflow_id(tenant_id)).query(QUERY)
        try:
            result = self._run(go)
            return {**IDLE, **{k: result.get(k) for k in IDLE if k in result}}
        except Exception:
            return dict(IDLE)

    def start_login(self, source):
        """Start (or join the running) one-source sync that logs in with an app-typed code. True on success."""
        async def go(client):
            await client.start_workflow(
                SYNC_WORKFLOW, [source], id=login_workflow_id(source), task_queue=TASK_QUEUE,
                id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING)
        try:
            self._run(go)
            return True
        except Exception:
            log.exception("could not start the %s login", source)
            return False

    def retry(self, source, resume):
        """Start (or join the running) one-source sync continuing at `resume`. True on success."""
        args = [[source], {"resume": resume}] if resume == "digest" else [[source]]
        async def go(client):
            await client.start_workflow(
                SYNC_WORKFLOW, args=args, id=retry_workflow_id(source), task_queue=TASK_QUEUE,
                id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING)
        try:
            self._run(go)
            return True
        except Exception:
            log.exception("could not start the %s retry", source)
            return False

    def submit_otp(self, source, code):
        """Relay the human's code to that login's sync (ignored there unless it is waiting). True on success."""
        async def go(client):
            await client.get_workflow_handle(login_workflow_id(source)).signal(OTP_SIGNAL, args=[source, code])
        try:
            self._run(go)
            return True
        except Exception:
            log.warning("could not deliver the %s code (no login waiting?)", source)  # never log the code
            return False

    def sync_tenant_access(self, tenant_id, email):
        """Run `TenantAccessWorkflow` on the Mac and wait for it: (True, "added"|"removed") or
        (False, reason). The worker decides the action from the database, not from this call."""
        async def go(client):
            return await client.execute_workflow(
                ACCESS_WORKFLOW, args=[tenant_id, email], id=f"tenant-access-{uuid.uuid4()}",
                task_queue=TASK_QUEUE, execution_timeout=timedelta(seconds=ACCESS_WAIT))
        try:
            async def run():
                client = await asyncio.wait_for(Client.connect(self.address), TIMEOUT)
                return await asyncio.wait_for(go(client), ACCESS_WAIT + 5)
            return True, asyncio.run(run())
        except Exception as e:
            cause = getattr(e, "cause", None)
            while getattr(cause, "cause", None) is not None:
                cause = cause.cause   # the activity's own error carries the script's output
            log.warning("tenant access sync failed: %s", type(e).__name__)
            return False, str(getattr(cause, "message", None) or "the sync worker did not answer in time")

    def ping(self):
        """True if the Temporal frontend answers."""
        async def go(client):
            await client.workflow_service.get_system_info(GetSystemInfoRequest())
        try:
            self._run(go)
            return True
        except Exception:
            return False
