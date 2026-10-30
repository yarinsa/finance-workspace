"""Tenant isolation at the database: Row-Level Security under the roles the app really uses.

As tenant A's household, with `app.tenant_id` = A, tenant B's rows must be invisible,
unwritable and undeletable; a forged tenant_id must not stick; and with no tenant bound a
query must fail rather than return everything.
"""
import uuid

import psycopg
import pytest

import ledger
from finance import tenancy
from finance.tenancy import DEFAULT_TENANT_ID

A = uuid.UUID("aaaaaaaa-0000-4000-8000-00000000000a")
B = uuid.UUID("bbbbbbbb-0000-4000-8000-00000000000b")

OWNED = ["scraped_transactions", "transaction_overrides", "override_audit", "transaction_tags",
         "transaction_offsets", "tags", "categories", "merchant_rules", "horizons", "goals",
         "plan_targets", "budget_lines", "notifications", "assets", "position_snapshots", "push_subscriptions"]


@pytest.fixture
def two_tenants(test_url):
    """Tenants A and B, each with a tag, a goal and a ledger row, made as the privileged owner."""
    admin = ledger.connect_admin(test_url)
    # horizons keep the default tenant's seeded buckets (other tests rely on them)
    admin.execute(f"TRUNCATE {', '.join(t for t in OWNED if t != 'horizons')}, memberships, users")
    admin.execute("DELETE FROM horizons WHERE tenant_id <> %s", (DEFAULT_TENANT_ID,))
    admin.execute("DELETE FROM tenants WHERE id <> %s", (DEFAULT_TENANT_ID,))
    for t, slug in ((A, "a"), (B, "b")):
        admin.execute("INSERT INTO tenants (id, name, slug) VALUES (%s, %s, %s)", (t, slug.upper(), slug))
        admin.execute("INSERT INTO tags (tenant_id, name) VALUES (%s, %s)", (t, f"tag-{slug}"))
        admin.execute("INSERT INTO goals (tenant_id, slug, description, amount, repetitions, rise) VALUES (%s, %s, 'g', 1, 1, 0)",
                      (t, f"goal-{slug}"))
        admin.execute(
            "INSERT INTO scraped_transactions (tenant_id, txn_date, abs_amount, amount, position, record) "
            "VALUES (%s, '2026-10-01', 10, -10, 0, '{}')", (t,))
    admin.commit()
    yield admin
    admin.close()


_opened = []


@pytest.fixture(autouse=True)
def _close_connections():
    """Close every as_role connection: an open transaction would hold locks and block the
    next test's TRUNCATE."""
    yield
    while _opened:
        _opened.pop().close()


def as_role(test_url, role, tenant=None):
    """A connection that took `role` (what the app does), pinned to `tenant` for the session."""
    c = psycopg.connect(test_url)
    _opened.append(c)
    c.execute(f"SET ROLE {role}")
    if tenant:
        c.execute("SELECT set_config('app.tenant_id', %s, false)", (str(tenant),))
    c.commit()   # else a later rollback undoes SET ROLE and the test runs as the superuser
    return c


@pytest.mark.parametrize("role", ["finance_app", "finance_api"])
def test_other_tenants_rows_are_invisible(two_tenants, test_url, role):
    c = as_role(test_url, role, A)
    assert c.execute("SELECT name FROM tags").fetchall() == [("tag-a",)]
    assert c.execute("SELECT count(*) FROM scraped_transactions").fetchone() == (1,)
    assert c.execute("SELECT count(*) FROM transactions").fetchone() == (1,)   # security_invoker views too
    assert c.execute("SELECT count(*) FROM tags WHERE name = 'tag-b'").fetchone() == (0,)


def test_update_and_delete_cannot_touch_another_tenant(two_tenants, test_url):
    c = as_role(test_url, "finance_app", A)
    assert c.execute("UPDATE goals SET description = 'hijacked' WHERE slug = 'goal-b'").rowcount == 0
    assert c.execute("DELETE FROM tags WHERE name = 'tag-b'").rowcount == 0
    assert c.execute("DELETE FROM scraped_transactions").rowcount == 1   # only A's
    c.commit()
    assert two_tenants.execute("SELECT description FROM goals WHERE slug = 'goal-b'").fetchone() == ("g",)
    assert two_tenants.execute("SELECT count(*) FROM tags WHERE name = 'tag-b'").fetchone() == (1,)
    assert two_tenants.execute("SELECT count(*) FROM scraped_transactions WHERE tenant_id = %s", (B,)).fetchone() == (1,)


def test_insert_without_a_tenant_column_lands_in_the_bound_tenant(two_tenants, test_url):
    c = as_role(test_url, "finance_app", A)
    c.execute("INSERT INTO tags (name) VALUES ('mine')")
    c.commit()
    assert two_tenants.execute("SELECT tenant_id FROM tags WHERE name = 'mine'").fetchone() == (A,)


def test_forged_tenant_id_is_rejected(two_tenants, test_url):
    c = as_role(test_url, "finance_app", A)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        c.execute("INSERT INTO tags (tenant_id, name) VALUES (%s, 'planted')", (B,))
    c.rollback()
    with pytest.raises(psycopg.errors.InsufficientPrivilege):   # moving a row to B
        c.execute("UPDATE tags SET tenant_id = %s WHERE name = 'tag-a'", (B,))


@pytest.mark.parametrize("role", ["finance_app", "finance_api"])
def test_missing_tenant_context_errors_instead_of_returning_rows(two_tenants, test_url, role):
    c = as_role(test_url, role)   # no app.tenant_id at all
    with pytest.raises(psycopg.errors.UndefinedObject):
        c.execute("SELECT * FROM tags").fetchall()
    c.rollback()
    c.execute("SELECT set_config('app.tenant_id', '', false)")   # the value once a setting was reset
    with pytest.raises(psycopg.errors.InvalidTextRepresentation):
        c.execute("SELECT * FROM tags").fetchall()


def test_app_roles_cannot_bypass_rls_or_own_tables(two_tenants):
    rows = two_tenants.execute("SELECT rolname, rolbypassrls, rolsuper FROM pg_roles "
                               "WHERE rolname IN ('finance_app', 'finance_api')").fetchall()
    assert sorted(rows) == [("finance_api", False, False), ("finance_app", False, False)]
    owned = two_tenants.execute("SELECT tableowner FROM pg_tables WHERE tablename = ANY(%s)", (OWNED,)).fetchall()
    assert not {o for (o,) in owned} & {"finance_app", "finance_api"}


def test_every_tenant_owned_table_has_forced_rls_and_a_policy(two_tenants):
    for t in OWNED:
        enabled, forced = two_tenants.execute(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = %s", (t,)).fetchone()
        assert (enabled, forced) == (True, True), t
        assert two_tenants.execute("SELECT count(*) FROM pg_policies WHERE tablename = %s", (t,)).fetchone() == (1,), t
        nullable = two_tenants.execute(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_name = %s AND column_name = 'tenant_id'", (t,)).fetchone()
        assert nullable == ("NO",), t


def test_every_public_table_is_classified(two_tenants):
    """A new table must be added to OWNED (tenant_id + RLS) or to GLOBAL on purpose."""
    GLOBAL = {"users", "tenants", "memberships", "category_groups", "sync_status", "alembic_version"}
    tables = {t for (t,) in two_tenants.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")}
    assert tables - GLOBAL - set(OWNED) == set()


def test_connect_requires_a_tenant(test_url, monkeypatch):
    monkeypatch.delenv("FINANCE_TENANT_ID", raising=False)
    token = tenancy.set_context(None)   # a CLI test earlier in the process may have bound one
    try:
        with pytest.raises(tenancy.TenantContextMissing):
            ledger.connect(test_url)
    finally:
        tenancy.reset_context(token)


def test_a_job_scoped_to_a_cannot_read_or_write_b(two_tenants, test_url):
    job = ledger.connect(test_url, tenant_id=A)
    assert job.execute("SELECT name FROM tags").fetchall() == [("tag-a",)]
    assert job.execute("DELETE FROM tags WHERE name = 'tag-b'").rowcount == 0
    ledger.load(job, [])   # replaces A's ledger only
    assert two_tenants.execute("SELECT count(*) FROM scraped_transactions WHERE tenant_id = %s", (B,)).fetchone() == (1,)
    job.close()


def test_one_name_per_tenant_not_per_database(two_tenants, test_url):
    """Uniques include the tenant: both can have a tag with the same name."""
    two_tenants.execute("INSERT INTO tags (tenant_id, name) VALUES (%s, 'shared'), (%s, 'shared')", (A, B))
    two_tenants.commit()
    with pytest.raises(psycopg.errors.UniqueViolation):
        two_tenants.execute("INSERT INTO tags (tenant_id, name) VALUES (%s, 'shared')", (A,))
