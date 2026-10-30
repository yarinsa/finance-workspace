"""Temporal worker for the finance sync. Run via launchd (sync/launchd/)."""
import asyncio
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # finance.push (workflows, activities)

from google.protobuf.duration_pb2 import Duration
from temporalio.api.workflowservice.v1 import DescribeNamespaceRequest, UpdateNamespaceRequest
from temporalio.client import Client
from temporalio.worker import Worker

from activities import ALL_ACTIVITIES, seed_status_db
from workflows import TASK_QUEUE, AmexSyncWorkflow, FinanceSyncWorkflow, LedgerRebuildWorkflow


# The dev server keeps a finished run's history for 24h by default, which is too short to look back
# at last week's failures. Run history is small; keep a month.
RETENTION_DAYS = int(os.environ.get("TEMPORAL_RETENTION_DAYS", "30"))


async def ensure_retention(client: Client, days: int = RETENTION_DAYS) -> str:
    """Raise the namespace's workflow retention to `days` (never lowers it). Best-effort: a failure
    only warns, the sync does not depend on it. Returns a one-line note for the log."""
    try:
        svc, ns = client.workflow_service, client.namespace
        info = await svc.describe_namespace(DescribeNamespaceRequest(namespace=ns))
        current = info.config.workflow_execution_retention_ttl.ToTimedelta().days
        if current >= days:
            return f"namespace {ns}: retention {current}d"
        request = UpdateNamespaceRequest(namespace=ns)
        request.config.workflow_execution_retention_ttl.CopyFrom(Duration(seconds=days * 86400))
        await svc.update_namespace(request)
        return f"namespace {ns}: retention {current}d -> {days}d"
    except Exception as e:  # noqa: BLE001
        return f"namespace retention not updated: {e}"


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    client = await Client.connect(
        os.environ.get("TEMPORAL_ADDRESS", "localhost:7233"),
        namespace=os.environ.get("TEMPORAL_NAMESPACE", "default"),
    )
    print(await ensure_retention(client), flush=True)
    print(f"sync_status seeded with {seed_status_db()} source(s)", flush=True)
    worker = Worker(client, task_queue=TASK_QUEUE, workflows=[FinanceSyncWorkflow, AmexSyncWorkflow, LedgerRebuildWorkflow], activities=ALL_ACTIVITIES)
    print(f"worker up on task queue {TASK_QUEUE}", flush=True)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
