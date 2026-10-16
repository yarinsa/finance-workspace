"""Talk to Temporal: ask the host worker to rebuild and publish the ledger after an edit.

The workflow lives in sync/ (a different deployment), so it is referred to by name only.
The API never fails because Temporal is down: an edit is already saved, and the next
signal or the daily sync publishes it.
"""
import asyncio
import logging

from temporalio.api.workflowservice.v1 import GetSystemInfoRequest
from temporalio.client import Client
from temporalio.common import WorkflowIDConflictPolicy

log = logging.getLogger("finance_api")

WORKFLOW = "LedgerRebuildWorkflow"
WORKFLOW_ID = "ledger-rebuild"
TASK_QUEUE = "finance-sync"
SIGNAL = "edited"
QUERY = "status"
TIMEOUT = 3.0

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

    def signal_edited(self):
        """Signal-with-start: starts the workflow if idle, else tells the running one. Never raises."""
        async def go(client):
            await client.start_workflow(
                WORKFLOW, id=WORKFLOW_ID, task_queue=TASK_QUEUE, start_signal=SIGNAL,
                id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING)
        try:
            self._run(go)
            return True
        except Exception:
            log.exception("could not signal %s; the edit is saved and will publish with the next rebuild", WORKFLOW)
            return False

    def status(self):
        """The workflow's `status` query, or idle if there is no workflow or Temporal is down."""
        async def go(client):
            return await client.get_workflow_handle(WORKFLOW_ID).query(QUERY)
        try:
            result = self._run(go)
            return {**IDLE, **{k: result.get(k) for k in IDLE if k in result}}
        except Exception:
            return dict(IDLE)

    def ping(self):
        """True if the Temporal frontend answers."""
        async def go(client):
            await client.workflow_service.get_system_info(GetSystemInfoRequest())
        try:
            self._run(go)
            return True
        except Exception:
            return False
