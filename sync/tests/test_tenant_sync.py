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


# --- Cognito provisioning (the /tenants screen) -------------------------------------

def plan(**kw):
    from activities import access_plan
    return access_plan(**kw)


def test_a_new_member_of_an_active_tenant_gets_an_account_then_the_group():
    assert plan(is_member=True, tenant_active=True, has_access=True) == ["ensure-user", "add"]


def test_removing_someones_last_membership_takes_them_out_and_disables_the_account():
    assert plan(is_member=False, tenant_active=True, has_access=False) == ["remove", "disable-user"]


def test_removing_someone_who_still_belongs_elsewhere_keeps_their_account():
    assert plan(is_member=False, tenant_active=True, has_access=True) == ["ensure-user", "remove"]


def test_a_suspended_tenant_loses_its_group_but_members_keep_other_tenants():
    assert plan(is_member=True, tenant_active=False, has_access=True) == ["ensure-user", "remove"]
    assert plan(is_member=True, tenant_active=False, has_access=False) == ["remove", "disable-user"]


def test_nobody_is_added_to_a_group_without_an_account_first():
    for member in (True, False):
        steps = plan(is_member=member, tenant_active=True, has_access=member)
        if "add" in steps:
            assert steps.index("ensure-user") < steps.index("add")


def test_the_platform_admin_is_never_disabled(monkeypatch):
    import activities
    from finance import tenancy
    assert tenancy.is_platform_admin("yarinsasson2@gmail.com")
    # has_access is forced true for them in the activity, so the plan never contains disable-user
    assert "disable-user" not in plan(is_member=False, tenant_active=True, has_access=True)


def test_access_sync_refuses_malformed_input_before_touching_aws(monkeypatch):
    import asyncio
    import activities
    from temporalio.exceptions import ApplicationError

    ran = []

    async def fake_run_cmd(*a, **k):
        ran.append(a)
        return 0, ""
    monkeypatch.setattr(activities, "run_cmd", fake_run_cmd)
    for tenant, email in [("not-a-uuid", "a@b.cc"), (T, "no-at-sign"), (T, "a b@c.dd"), (T, "x" * 300 + "@b.cc")]:
        with pytest.raises(ApplicationError):
            asyncio.run(activities.sync_tenant_access(tenant, email))
    assert ran == []
