"""Create-or-update the daily AMEX sync schedule (idempotent).

  python3 sync/schedule.py              create/update
  python3 sync/schedule.py --trigger    run once now
  python3 sync/schedule.py --pause / --unpause
"""
import argparse
import asyncio
import os
from datetime import timedelta

from temporalio.client import (
    Client, Schedule, ScheduleActionStartWorkflow, ScheduleOverlapPolicy,
    SchedulePolicy, ScheduleSpec, ScheduleUpdate,
)

from workflows import TASK_QUEUE, AmexSyncWorkflow

SCHEDULE_ID = "amex-sync"


def build_schedule() -> Schedule:
    return Schedule(
        action=ScheduleActionStartWorkflow(
            AmexSyncWorkflow.run,
            id="amex-sync-run",  # schedule suffixes the fire time
            task_queue=TASK_QUEUE,
        ),
        spec=ScheduleSpec(cron_expressions=["30 7 * * *"], time_zone_name="Asia/Jerusalem"),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP, catchup_window=timedelta(hours=1)),
    )


async def main() -> None:
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group()
    g.add_argument("--trigger", action="store_true")
    g.add_argument("--pause", action="store_true")
    g.add_argument("--unpause", action="store_true")
    args = p.parse_args()

    client = await Client.connect(
        os.environ.get("TEMPORAL_ADDRESS", "localhost:7233"),
        namespace=os.environ.get("TEMPORAL_NAMESPACE", "default"),
    )
    if args.trigger or args.pause or args.unpause:
        handle = client.get_schedule_handle(SCHEDULE_ID)
        if args.trigger:
            await handle.trigger()
            print("triggered")
        elif args.pause:
            await handle.pause(note="paused via schedule.py")
            print("paused")
        else:
            await handle.unpause(note="unpaused via schedule.py")
            print("unpaused")
        return

    schedule = build_schedule()
    try:
        await client.create_schedule(SCHEDULE_ID, schedule)
        print(f"created schedule {SCHEDULE_ID}")
    except Exception as e:
        if "already" not in str(e).lower():
            raise
        # Keep the paused/unpaused state the user chose; replace the definition.
        async def updater(inp):
            schedule.state = inp.description.schedule.state
            return ScheduleUpdate(schedule=schedule)
        await client.get_schedule_handle(SCHEDULE_ID).update(updater)
        print(f"updated schedule {SCHEDULE_ID}")


if __name__ == "__main__":
    asyncio.run(main())
