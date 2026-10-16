"""Temporal worker for the finance sync. Run via launchd (sync/launchd/)."""
import asyncio
import os

from temporalio.client import Client
from temporalio.worker import Worker

from activities import ALL_ACTIVITIES
from workflows import TASK_QUEUE, AmexSyncWorkflow, FinanceSyncWorkflow


async def main() -> None:
    client = await Client.connect(
        os.environ.get("TEMPORAL_ADDRESS", "localhost:7233"),
        namespace=os.environ.get("TEMPORAL_NAMESPACE", "default"),
    )
    worker = Worker(client, task_queue=TASK_QUEUE, workflows=[FinanceSyncWorkflow, AmexSyncWorkflow], activities=ALL_ACTIVITIES)
    print(f"worker up on task queue {TASK_QUEUE}", flush=True)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
