"""A sync for another tenant: its id reaches every activity, and it runs only self-login scrapers."""
import pytest
from temporalio.client import WorkflowFailureError

from fakes import Fake, result_of, run
from workflows import FinanceSyncWorkflow, LedgerRebuildWorkflow

T = "aaaaaaaa-0000-4000-8000-00000000000a"
SELF_LOGIN = ["discount-business", "discount-mortgage", "discount", "leumi", "cal", "amex", "max"]   # sources.check == SELF


def test_a_tenant_sync_runs_only_self_login_sources_and_tells_every_activity_the_tenant():
    fake = Fake()
    result = result_of(fake, args=(None, {"tenant_id": T}))
    assert fake.of("scrape") == SELF_LOGIN
    assert {k for k in result if k != "_finish"} == set(SELF_LOGIN)
    told = {(a, t) for a, t in fake.tenants}
    assert told == {("scrape", T), ("validate", T), ("digest", T), ("publish", T)}


def test_the_master_tenant_sync_is_unchanged():
    fake = Fake()
    result_of(fake)
    assert {t for _, t in fake.tenants} == {None}   # no tenant given = the master tenant
    assert len(fake.of("scrape")) == 10


def test_a_tenant_cannot_ask_for_a_chrome_driven_source():
    with pytest.raises(WorkflowFailureError) as e:
        result_of(Fake(), args=(["harel"], {"tenant_id": T}))
    assert "a tenant can only sync self-login sources" in str(e.value.cause)


def test_a_tenants_rebuild_digests_and_publishes_for_that_tenant():
    fake = Fake()

    async def scenario(env, handle):
        await handle.signal(LedgerRebuildWorkflow.edited)
        return await handle.result()
    run(fake, scenario, workflow=LedgerRebuildWorkflow,
        args=({"tenant_id": T, "idle_seconds": 5, "debounce_seconds": 0.1, "max_passes": 1},))
    assert ("digest", T) in fake.tenants and ("publish", T) in fake.tenants
