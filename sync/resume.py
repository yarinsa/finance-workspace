"""Tell waiting sync workflow(s) that you have logged in again.

  python3 sync/resume.py                    # every dead source: re-check
  python3 sync/resume.py discount amex      # only these (a source name, or a login group)
"""
import asyncio
import os
import sys

from temporalio.client import Client

import sources

SIGNAL = "session_refreshed"
QUERY = ("WorkflowType IN ('FinanceSyncWorkflow', 'AmexSyncWorkflow') "
         "AND ExecutionStatus = 'Running'")


async def main(names: list) -> int:
    sources.resolve(names)  # fail fast on a typo, before signalling anything
    client = await Client.connect(
        os.environ.get("TEMPORAL_ADDRESS", "localhost:7233"),
        namespace=os.environ.get("TEMPORAL_NAMESPACE", "default"),
    )
    n = 0
    async for wf in client.list_workflows(QUERY):
        handle = client.get_workflow_handle(wf.id, run_id=wf.run_id)
        await (handle.signal(SIGNAL, names) if names else handle.signal(SIGNAL))
        print(f"signalled {wf.id}")
        n += 1
    if not n:
        print("no running sync workflow; trigger one with: python3 sync/schedule.py --trigger")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main(sys.argv[1:])))
    except ValueError as e:
        raise SystemExit(str(e))
