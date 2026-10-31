"""The assistant reads through the request's tenant: a household's chat never surfaces another's rows.

Same two tenants as test_tenancy (A: ₪11.11 "A shop", B: ₪22.22 "B shop"), real finance_api role."""
import pytest

from api.assistant_ledger import DbLedger
from api.tests.test_tenancy import A, B, world  # noqa: F401 - fixture
from assistant.tools import Toolbox
from finance import tenancy


def toolbox_for(pool, tenant):
    conn = pool.getconn()
    try:
        tenancy.bind(conn, tenant, local=False)
        box = Toolbox(DbLedger(conn))
        box.rows()          # load while bound
        return box
    finally:
        tenancy.unbind(conn)
        conn.commit()
        pool.putconn(conn)


@pytest.mark.parametrize("tenant,mine,theirs,total", [(A, "A shop", "B shop", 11.11), (B, "B shop", "A shop", 22.22)])
def test_tools_only_see_their_own_tenant(world, pool, tenant, mine, theirs, total):  # noqa: F811
    box = toolbox_for(pool, tenant)
    assert [r["description"] for r in box.search_transactions("shop")] == [mine]
    assert box.search_transactions(theirs) == []
    assert box.spending_by_category("2026-02") == [{"category": "קניות", "total": total}]
    assert box.monthly_totals() == [{"month": "2026-02", "spent": total, "income": 0.0}]


def test_snapshot_tool_is_not_offered_from_the_database(world, pool):  # noqa: F811
    assert "snapshot_totals" not in toolbox_for(pool, A).names()
