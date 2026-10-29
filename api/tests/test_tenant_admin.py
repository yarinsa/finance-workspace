"""Tenant management is for the hard-coded platform admin only, and never opens another tenant's data."""
import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.auth import COOKIE, TokenVerifier
from api.tests.conftest import FakeJwks, SECRET, WRITE, make_member, settings
from finance.tenancy import DEFAULT_TENANT_ID, PLATFORM_ADMIN_EMAILS

ADMIN = "yarinsasson2@gmail.com"
OTHER = "member@example.com"
NEWBIE = "new@example.com"
assert ADMIN in PLATFORM_ADMIN_EMAILS


@pytest.fixture
def as_user(owner, admin, pool, rebuilder, key_pair, make_token):
    make_member(admin, ADMIN, DEFAULT_TENANT_ID)
    make_member(admin, OTHER, DEFAULT_TENANT_ID, "member")
    admin.commit()

    def make(email):
        s = settings(allowed_emails=frozenset({ADMIN, OTHER, NEWBIE}))
        c = TestClient(create_app(s, pool=pool, rebuilder=rebuilder, verifier=TokenVerifier(s, jwk_client=FakeJwks(key_pair))))
        c.headers.update({"X-Origin-Secret": SECRET})
        c.cookies.set(COOKIE, make_token(email=email))
        return c
    return make


def gql(c, q):
    return c.post("/api/graphql", json={"query": q}, headers=WRITE).json()


CREATE = 'mutation { tenantCreate(input: {slug: "acme", name: "Acme", ownerEmail: "owner@acme.example"}) { tenant { id slug status members { email role } } } }'


def test_only_the_platform_admin_can_list_or_change_tenants(as_user):
    c = as_user(OTHER)
    for q in ("{ tenants { slug } }", CREATE):
        r = gql(c, q)
        assert r["errors"][0]["message"] == "only a platform admin can manage tenants", q
    assert gql(as_user(ADMIN), "{ tenants { slug } }")["data"]["tenants"] == [{"slug": "default"}]


def test_admin_creates_a_tenant_owns_it_and_it_has_horizons(as_user, admin):
    r = gql(as_user(ADMIN), CREATE)["data"]["tenantCreate"]["tenant"]
    assert r["slug"] == "acme" and r["members"] == [{"email": "owner@acme.example", "role": "OWNER"}]   # the admin is not a member
    row = admin.execute("SELECT id FROM tenants WHERE slug = 'acme'").fetchone()
    assert admin.execute("SELECT count(*) FROM horizons WHERE tenant_id = %s", (row[0],)).fetchone() == (3,)


def test_admin_adds_and_removes_members_and_suspends(as_user, admin):
    a = as_user(ADMIN)
    tid = gql(a, CREATE)["data"]["tenantCreate"]["tenant"]["id"]
    add = 'mutation { tenantMemberSet(id: "%s", input: {email: "New@Example.com", role: MEMBER}) { tenant { members { email role } } } }' % tid
    assert {"email": NEWBIE, "role": "MEMBER"} in gql(a, add)["data"]["tenantMemberSet"]["tenant"]["members"]
    # the new member reaches only that tenant
    assert as_user(NEWBIE).get("/api/transactions").status_code == 200
    rm = 'mutation { tenantMemberRemove(id: "%s", input: {email: "new@example.com"}) { tenant { members { email } } } }' % tid
    assert {"email": NEWBIE} not in gql(a, rm)["data"]["tenantMemberRemove"]["tenant"]["members"]
    sus = 'mutation { tenantSetStatus(id: "%s", input: {status: SUSPENDED}) { tenant { status } } }' % tid
    assert gql(a, sus)["data"]["tenantSetStatus"]["tenant"]["status"] == "SUSPENDED"


def test_the_last_owner_and_the_master_tenant_are_protected(as_user):
    a = as_user(ADMIN)
    tid = gql(a, CREATE)["data"]["tenantCreate"]["tenant"]["id"]
    demote = 'mutation { tenantMemberSet(id: "%s", input: {email: "owner@acme.example", role: MEMBER}) { tenant { slug } } }' % tid
    assert gql(a, demote)["errors"][0]["message"] == "a tenant needs at least one owner"
    tenants = {t["slug"]: t["id"] for t in gql(a, "{ tenants { id slug } }")["data"]["tenants"]}
    sus = 'mutation { tenantSetStatus(id: "%s", input: {status: SUSPENDED}) { tenant { status } } }' % tenants["default"]
    assert gql(a, sus)["errors"][0]["message"] == "the master tenant cannot be suspended"


def test_platform_admin_gets_no_access_to_a_tenant_they_are_not_in(as_user, admin):
    a = as_user(ADMIN)
    gql(a, CREATE)
    new_id = admin.execute("SELECT id FROM tenants WHERE slug = 'acme'").fetchone()[0]
    a.headers["X-Tenant-Id"] = str(new_id)
    r = a.get("/api/transactions")
    assert r.status_code == 403 and r.json()["error"] == "forbidden"
    del a.headers["X-Tenant-Id"]
    assert a.get("/api/transactions").status_code == 200   # still just the master tenant, no header needed
