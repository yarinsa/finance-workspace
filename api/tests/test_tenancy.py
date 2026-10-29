"""Tenant isolation through the API: user A never sees, changes or creates B's data.

Two tenants, each with a member and its own ledger row (A: ₪11.11, B: ₪22.22). Every check
goes through HTTP with the real finance_api role, so Row-Level Security is in the loop.
"""
import uuid

import pytest
from fastapi.testclient import TestClient

import ledger
from api.app import create_app
from api.auth import COOKIE, TokenVerifier
from api.tests.conftest import FakeJwks, SECRET, WRITE, make_member, settings

A = uuid.UUID("aaaaaaaa-0000-4000-8000-00000000000a")
B = uuid.UUID("bbbbbbbb-0000-4000-8000-00000000000b")
USER_A, USER_B, BOTH, NOBODY = "a@example.com", "b@example.com", "both@example.com", "nobody@example.com"
ROW_A = {"date": "2026-02-01", "amount": -11.11, "description": "A shop", "category": "קניות", "origin": "cal",
         "is_income": False, "sources": ["cal"]}
ROW_B = {"date": "2026-02-01", "amount": -22.22, "description": "B shop", "category": "קניות", "origin": "cal",
         "is_income": False, "sources": ["cal"]}
URL_A, URL_B = "/api/transactions/2026-02-01/11.11", "/api/transactions/2026-02-01/22.22"
EMAILS = frozenset({USER_A, USER_B, BOTH, NOBODY})


@pytest.fixture
def world(owner, admin, test_url):
    for t, slug in ((A, "a"), (B, "b")):
        admin.execute("INSERT INTO tenants (id, name, slug) VALUES (%s, %s, %s)", (t, slug, slug))
    make_member(admin, USER_A, A)
    make_member(admin, USER_B, B)
    make_member(admin, BOTH, A, "member")
    make_member(admin, BOTH, B, "admin")
    make_member(admin, NOBODY, A)
    admin.execute("DELETE FROM memberships WHERE user_id = (SELECT id FROM users WHERE email = %s)", (NOBODY,))
    admin.commit()
    for t, row in ((A, ROW_A), (B, ROW_B)):
        c = ledger.connect(test_url, tenant_id=t)
        ledger.load(c, [row])
        c.commit()
        c.close()


@pytest.fixture
def as_user(world, pool, rebuilder, key_pair, make_token):
    def make(email, tenant=None):
        s = settings(allowed_emails=EMAILS)
        app = create_app(s, pool=pool, rebuilder=rebuilder, verifier=TokenVerifier(s, jwk_client=FakeJwks(key_pair)))
        c = TestClient(app)
        c.headers.update({"X-Origin-Secret": SECRET})
        if tenant:
            c.headers["X-Tenant-Id"] = str(tenant)
        c.cookies.set(COOKIE, make_token(email=email))
        return c
    return make


def gql(client, query, variables=None):
    return client.post("/api/graphql", json={"query": query, "variables": variables or {}}, headers=WRITE).json()


def amounts(client):
    return sorted(float(t["abs_amount"]) for t in client.get("/api/transactions").json()["transactions"])


def test_each_user_lists_only_their_tenants_rows(as_user):
    assert amounts(as_user(USER_A)) == [11.11]
    assert amounts(as_user(USER_B)) == [22.22]


def test_user_a_cannot_read_update_or_delete_b_by_id(as_user, admin):
    a = as_user(USER_A)
    assert a.get(URL_B).status_code == 404
    assert a.patch(URL_B, json={"note": "hacked"}, headers=WRITE).status_code == 404
    assert a.delete(URL_B + "/override", headers=WRITE).status_code in (200, 404)
    b_notes = admin.execute("SELECT count(*) FROM transaction_overrides WHERE tenant_id = %s", (B,)).fetchone()
    assert b_notes == (0,)
    assert a.get(URL_A).status_code == 200


def test_graphql_lookups_by_key_are_tenant_filtered(as_user):
    a = as_user(USER_A)
    q = "query($d: Date!, $m: Money!) { transactionByKey(date: $d, absAmount: $m) { description } }"
    assert gql(a, q, {"d": "2026-02-01", "m": "22.22"})["data"]["transactionByKey"] is None
    assert gql(a, q, {"d": "2026-02-01", "m": "11.11"})["data"]["transactionByKey"] == {"description": "A shop"}


def test_forged_tenant_id_in_the_body_is_ignored(as_user, admin):
    a = as_user(USER_A)
    r = a.post("/api/goals", json={"slug": "g1", "description": "x", "amount": 5, "tenant_id": str(B)},
               headers={**WRITE, "X-Tenant-Id": str(A)})
    assert r.status_code in (200, 201, 400, 422)
    assert admin.execute("SELECT count(*) FROM goals WHERE tenant_id = %s", (B,)).fetchone() == (0,)
    r = a.post("/api/graphql", headers=WRITE, json={
        "query": "mutation { goalCreate(input: {description: \"x\", amount: 5, tenantId: \"%s\"}) { goal { id } } }" % B})
    assert admin.execute("SELECT count(*) FROM goals WHERE tenant_id = %s", (B,)).fetchone() == (0,)


def test_a_member_cannot_name_a_tenant_they_do_not_belong_to(as_user):
    r = as_user(USER_A, tenant=B).get("/api/transactions")
    assert r.status_code == 403 and r.json()["error"] == "forbidden"


def test_header_for_an_unknown_tenant_gives_the_same_answer(as_user):
    r = as_user(USER_A, tenant=uuid.uuid4()).get("/api/transactions")
    assert r.status_code == 403 and r.json()["error"] == "forbidden"


def test_malformed_tenant_header_is_400(as_user):
    c = as_user(USER_A)
    c.headers["X-Tenant-Id"] = "not-a-uuid"
    assert c.get("/api/transactions").status_code == 400


def test_user_with_two_tenants_must_choose_and_gets_exactly_that_one(as_user):
    assert as_user(BOTH).get("/api/transactions").status_code == 400
    assert amounts(as_user(BOTH, tenant=A)) == [11.11]
    assert amounts(as_user(BOTH, tenant=B)) == [22.22]


def test_user_without_a_membership_is_403(as_user):
    r = as_user(NOBODY).get("/api/transactions")
    assert r.status_code == 403 and r.json()["error"] == "no_tenant"


def test_suspended_tenant_is_403(as_user, admin):
    admin.execute("UPDATE tenants SET status = 'suspended' WHERE id = %s", (A,))
    admin.commit()
    r = as_user(USER_A).get("/api/transactions")
    assert r.status_code == 403 and r.json()["error"] == "tenant_suspended"


def test_a_write_lands_in_the_callers_tenant(as_user, admin):
    assert as_user(USER_A).patch(URL_A, json={"note": "mine"}, headers=WRITE).status_code == 200
    rows = admin.execute("SELECT tenant_id, note FROM transaction_overrides").fetchall()
    assert rows == [(A, "mine")]


def test_a_pooled_connection_goes_back_without_a_tenant(as_user, pool):
    assert as_user(USER_A).get("/api/transactions").status_code == 200
    with pool.connection() as conn:
        assert conn.execute("SELECT current_setting('app.tenant_id', true)").fetchone()[0] in ("", None)
