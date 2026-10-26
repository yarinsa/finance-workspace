"""Temporal worker for the finance sync. Run via launchd (sync/launchd/)."""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # finance.push (workflows, activities)

from temporalio.client import Client
from temporalio.worker import Worker

from activities import ALL_ACTIVITIES, seed_status_db
from workflows import TASK_QUEUE, AmexSyncWorkflow, FinanceSyncWorkflow, LedgerRebuildWorkflow


async def main() -> None:
    client = await Client.connect(
        os.environ.get("TEMPORAL_ADDRESS", "localhost:7233"),
        namespace=os.environ.get("TEMPORAL_NAMESPACE", "default"),
    )
    print(f"sync_status seeded with {seed_status_db()} source(s)", flush=True)
    worker = Worker(client, task_queue=TASK_QUEUE, workflows=[FinanceSyncWorkflow, AmexSyncWorkflow, LedgerRebuildWorkflow], activities=ALL_ACTIVITIES)
    print(f"worker up on task queue {TASK_QUEUE}", flush=True)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
