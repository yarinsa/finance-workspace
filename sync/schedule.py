"""Create-or-update the finance sync schedule, 06:20 and 22:00 daily (idempotent).

  python3 sync/schedule.py                          create/update, every source
  python3 sync/schedule.py --sources amex,cal       ...only these (registry order is kept)
  python3 sync/schedule.py --tenant ID              the same for another tenant (self-login sources
                                                    only, 06:50 and 22:30), schedule `finance-sync-<ID>`
  python3 sync/schedule.py --trigger                run once now
  python3 sync/schedule.py --pause / --unpause

The schedule id is `finance-sync`. It replaces the AMEX-only `amex-sync`, which is
deleted on the next create/update so the two never both fire.
"""
import argparse
import asyncio
import os
import uuid
from datetime import timedelta

from temporalio.client import (
    Client, Schedule, ScheduleActionStartWorkflow, ScheduleOverlapPolicy,
    SchedulePolicy, ScheduleSpec, ScheduleUpdate,
)

import sources
from workflows import TASK_QUEUE, FinanceSyncWorkflow

MASTER = "00000000-0000-4000-8000-000000000001"
SCHEDULE_ID = "finance-sync"
LEGACY_SCHEDULE_ID = "amex-sync"


def schedule_id(tenant_id: str | None = None) -> str:
    """The master tenant keeps `finance-sync`; every other tenant has its own schedule."""
    return SCHEDULE_ID if not tenant_id or tenant_id == MASTER else f"{SCHEDULE_ID}-{tenant_id}"


def build_schedule(names: list[str] | None = None, tenant_id: str | None = None) -> Schedule:
    """`names` None = every source in sources.py (every self-login source, for another tenant)."""
    other = bool(tenant_id) and tenant_id != MASTER
    return Schedule(
        action=ScheduleActionStartWorkflow(
            FinanceSyncWorkflow.run,
            args=[sources.ordered(names) if names else None, {"tenant_id": tenant_id} if other else None],
            id=f"finance-sync-run-{tenant_id}" if other else "finance-sync-run",  # schedule suffixes the fire time
            task_queue=TASK_QUEUE,
        ),
        # another tenant runs half an hour later: two households' headless logins never overlap
        spec=ScheduleSpec(cron_expressions=["50 6 * * *", "30 22 * * *"] if other else ["20 6 * * *", "0 22 * * *"],
                          time_zone_name="Asia/Jerusalem"),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP, catchup_window=timedelta(hours=1)),
    )


async def main() -> None:
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group()
    g.add_argument("--trigger", action="store_true")
    g.add_argument("--pause", action="store_true")
    g.add_argument("--unpause", action="store_true")
    p.add_argument("--sources", help="comma-separated source names (default: all)")
    p.add_argument("--tenant", help="tenant id (default: the master tenant)")
    args = p.parse_args()
    if args.tenant:
        uuid.UUID(args.tenant)   # fail on a typo before touching a schedule
        args.tenant = args.tenant.lower()
    sid = schedule_id(args.tenant)
    names = [n for n in (args.sources or "").split(",") if n] or None
    if names:
        sources.ordered(names)  # fail on a typo before touching the schedule

    client = await Client.connect(
        os.environ.get("TEMPORAL_ADDRESS", "localhost:7233"),
        namespace=os.environ.get("TEMPORAL_NAMESPACE", "default"),
    )
    if args.trigger or args.pause or args.unpause:
        handle = client.get_schedule_handle(sid)
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

    schedule = build_schedule(names, args.tenant)
    try:
        await client.create_schedule(sid, schedule)
        print(f"created schedule {sid}")
    except Exception as e:
        if "already" not in str(e).lower():
            raise
        # Keep the paused/unpaused state the user chose; replace the definition.
        async def updater(inp):
            schedule.state = inp.description.schedule.state
            return ScheduleUpdate(schedule=schedule)
        await client.get_schedule_handle(sid).update(updater)
        print(f"updated schedule {sid}")
    # Retire the AMEX-only schedule: it would start a second, overlapping AMEX scrape.
    if sid != SCHEDULE_ID:
        return
    try:
        await client.get_schedule_handle(LEGACY_SCHEDULE_ID).delete()
        print(f"deleted legacy schedule {LEGACY_SCHEDULE_ID}")
    except Exception:
        pass  # not there


if __name__ == "__main__":
    asyncio.run(main())
