"""Hand assignments of savings holdings to a horizon and a goal (`holding_assignments`).

Used by data/digest.py (it attaches them to the snapshot's savings) and the ledger API. Every
function takes an open psycopg connection scoped to a tenant (`ledger.connect`) and commits.

    .venv/bin/python db/holding_store.py list
"""
import sys

from sqlmodel import select

from finance.tables import Goal, HoldingAssignment, Horizon
from ledger import orm_session

UNSET = object()


def all_assignments(conn):
    """`{holding_id: {"horizon": key | None, "goal_id": int | None}}`, this tenant's only."""
    with orm_session(conn) as s:
        keys = {h.id: h.key for h in s.exec(select(Horizon)).all()}
        return {r.holding_id: {"horizon": keys.get(r.horizon_id), "goal_id": r.goal_id}
                for r in s.exec(select(HoldingAssignment)).all()}


def assign(conn, holding_id, horizon=UNSET, goal_id=UNSET):
    """Set a holding's `horizon` (key) and/or `goal_id`; None clears that field, an omitted one is
    untouched. A row left with neither is deleted. Returns the holding's assignment, or None.

    Raises ValueError for an unknown horizon key or goal id, before writing anything."""
    if not holding_id or not holding_id.strip():
        raise ValueError("holding_id is required")
    with orm_session(conn) as s:
        row = s.exec(select(HoldingAssignment).where(HoldingAssignment.holding_id == holding_id)).first()
        if row is None:
            row = HoldingAssignment(holding_id=holding_id)
        if horizon is not UNSET:
            if horizon is None:
                row.horizon_id = None
            else:
                h = s.exec(select(Horizon).where(Horizon.key == horizon)).first()
                if not h:
                    raise ValueError(f"no horizon {horizon!r}")
                row.horizon_id = h.id
        if goal_id is not UNSET:
            if goal_id is not None and s.get(Goal, goal_id) is None:
                raise ValueError(f"no goal {goal_id!r}")
            row.goal_id = goal_id
        if row.horizon_id is None and row.goal_id is None:
            if row in s:
                s.delete(row)
        else:
            s.add(row)
        s.commit()
    return all_assignments(conn).get(holding_id)


def main(argv):
    from finance.tenancy import use_cli_tenant
    from ledger import connect
    use_cli_tenant()
    with connect() as conn:
        if argv == ["list"]:
            for k, v in sorted(all_assignments(conn).items()):
                print(f"{k}: horizon={v['horizon']} goal={v['goal_id']}")
            return 0
    print("usage: holding_store.py list")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
