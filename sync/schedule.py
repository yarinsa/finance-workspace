"""Create-or-update the daily finance sync schedule (idempotent).

  python3 sync/schedule.py                          create/update, every source
  python3 sync/schedule.py --sources amex,cal       ...only these (registry order is kept)
  python3 sync/schedule.py --trigger                run once now
  python3 sync/schedule.py --pause / --unpause

The schedule id is `finance-sync`. It replaces the AMEX-only `amex-sync`, which is
deleted on the next create/update so the two never both fire.
"""
import argparse
import asyncio
import os
from datetime import timedelta

from temporalio.client import (
    Client, Schedule, ScheduleActionStartWorkflow, ScheduleOverlapPolicy,
    SchedulePolicy, ScheduleSpec, ScheduleUpdate,
)

import sources
from workflows import TASK_QUEUE, FinanceSyncWorkflow

SCHEDULE_ID = "finance-sync"
LEGACY_SCHEDULE_ID = "amex-sync"


def build_schedule(names: list[str] | None = None) -> Schedule:
    """`names` None = every source in sources.py."""
    return Schedule(
        action=ScheduleActionStartWorkflow(
            FinanceSyncWorkflow.run,
            args=[sources.ordered(names) if names else None],
            id="finance-sync-run",  # schedule suffixes the fire time
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
    p.add_argument("--sources", help="comma-separated source names (default: all)")
    args = p.parse_args()
    names = [n for n in (args.sources or "").split(",") if n] or None
    if names:
        sources.ordered(names)  # fail on a typo before touching the schedule

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

    schedule = build_schedule(names)
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
    # Retire the AMEX-only schedule: it would start a second, overlapping AMEX scrape.
    try:
        await client.get_schedule_handle(LEGACY_SCHEDULE_ID).delete()
        print(f"deleted legacy schedule {LEGACY_SCHEDULE_ID}")
    except Exception:
        pass  # not there


if __name__ == "__main__":
    asyncio.run(main())
