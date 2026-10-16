"""Tell waiting amex-sync workflow(s) that you have logged in again.

  python3 sync/resume.py
"""
import asyncio
import os

from temporalio.client import Client

SIGNAL = "session_refreshed"
QUERY = "WorkflowType = 'AmexSyncWorkflow' AND ExecutionStatus = 'Running'"


async def main() -> int:
    client = await Client.connect(
        os.environ.get("TEMPORAL_ADDRESS", "localhost:7233"),
        namespace=os.environ.get("TEMPORAL_NAMESPACE", "default"),
    )
    n = 0
    async for wf in client.list_workflows(QUERY):
        await client.get_workflow_handle(wf.id, run_id=wf.run_id).signal(SIGNAL)
        print(f"signalled {wf.id}")
        n += 1
    if not n:
        print("no running AmexSyncWorkflow; trigger one with: python3 sync/schedule.py --trigger")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
