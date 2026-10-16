"""The ledger API, against the throwaway finance_test database.

Each test is a real decision the API must get right: who may call it, what a
write does to the override and the audit log, and what a role without privileges cannot do.
"""
import psycopg
import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.auth import COOKIE
from api.config import ConfigError, Settings
from api.rebuild import Rebuilder
from api.tests.conftest import CARD_BILL, ME, PURCHASE, SALARY, PURCHASE_URL, SECRET, WRITE, settings

SALARY_URL = "/api/transactions/2026-01-10/1000.00"


# --- origin secret ---------------------------------------------------------------------

def test_missing_origin_secret_is_403(client):
    client.headers.pop("X-Origin-Secret")
    r = client.get("/api/transactions")
    assert r.status_code == 403
    assert r.json()["error"] == "forbidden"


def test_wrong_origin_secret_is_403_even_with_a_valid_session(client):
    r = client.get("/api/transactions", headers={"X-Origin-Secret": SECRET + "x"})
    assert r.status_code == 403


def test_health_needs_only_the_secret_and_reports_dependencies(client):
    client.cookies.clear()
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "db": True, "temporal": True}
    client.headers.pop("X-Origin-Secret")
    assert client.get("/api/health").status_code == 403


def test_api_refuses_to_start_without_an_origin_secret():
    with pytest.raises(ConfigError, match="ORIGIN_SECRET"):
        Settings.from_env({"FINANCE_API_DEV_USER": "dev@example.com"})


def test_api_refuses_to_start_without_jwt_config_unless_dev_user():
    with pytest.raises(ConfigError, match="COGNITO"):
        Settings.from_env({"FINANCE_API_ORIGIN_SECRET": "s" * 32})
    assert Settings.from_env({"FINANCE_API_ORIGIN_SECRET": "s" * 32, "FINANCE_API_DEV_USER": "d@example.com"}).dev_user


# --- JWT -------------------------------------------------------------------------------

def test_no_cookie_is_401(client):
    client.cookies.clear()
    r = client.get("/api/transactions")
    assert r.status_code == 401
    assert r.json()["error"] == "unauthenticated"


def test_garbage_token_is_401(client):
    client.cookies.clear()
    client.cookies.set(COOKIE, "not-a-jwt")
    assert client.get("/api/transactions").status_code == 401


@pytest.mark.parametrize("bad", [
    {"exp_in": -10},                       # expired
    {"aud": "someone-elses-client"},       # token minted for another app client
    {"iss": "https://evil.example.com/x"}, # wrong issuer
    {"token_use": "access"},               # access token, not an id token
])
def test_invalid_tokens_are_401(client, make_token, bad):
    client.cookies.clear()
    client.cookies.set(COOKIE, make_token(**bad))
    assert client.get("/api/transactions").status_code == 401


def test_token_signed_by_another_key_is_401(client, make_token):
    from cryptography.hazmat.primitives.asymmetric import rsa
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    client.cookies.clear()
    client.cookies.set(COOKIE, make_token(signer=other))
    assert client.get("/api/transactions").status_code == 401


def test_unsigned_alg_none_token_is_401(client):
    import base64
    import json

    def b64(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    forged = f"{b64({'alg': 'none', 'typ': 'JWT'})}.{b64({'email': ME, 'token_use': 'id'})}."
    client.cookies.clear()
    client.cookies.set(COOKIE, forged)
    assert client.get("/api/transactions").status_code == 401


def test_valid_token_for_an_email_not_on_the_list_is_403(client, make_token):
    client.cookies.clear()
    client.cookies.set(COOKIE, make_token(email="stranger@example.com"))
    r = client.get("/api/transactions")
    assert r.status_code == 403
    assert r.json()["error"] == "forbidden"


def test_email_match_ignores_case(client, make_token):
    client.cookies.clear()
    client.cookies.set(COOKIE, make_token(email=ME.upper()))
    assert client.get("/api/transactions").status_code == 200


def test_dev_user_skips_jwt_but_not_the_origin_secret(build):
    c = TestClient(build(dev_user="dev@example.com", allowed_emails=frozenset()))
    assert c.get("/api/transactions", headers={"X-Origin-Secret": SECRET}).status_code == 200
    assert c.get("/api/transactions").status_code == 403
    assert c.get("/api/health", headers={"X-Origin-Secret": SECRET}).json()["dev"] is True


def test_dev_user_is_the_audit_actor(build, owner):
    c = TestClient(build(dev_user="dev@example.com"))
    c.patch(PURCHASE_URL, json={"note": "x"}, headers={**WRITE, "X-Origin-Secret": SECRET})
    assert owner.execute("SELECT actor FROM override_audit").fetchone()[0] == "dev@example.com"


# --- CSRF and body limits ---------------------------------------------------------------

def test_write_without_csrf_header_is_403_and_changes_nothing(client, owner, rebuilder):
    r = client.patch(PURCHASE_URL, content='{"note":"x"}', headers={"Content-Type": "application/json"})
    assert r.status_code == 403
    assert r.json()["error"] == "csrf"
    assert owner.execute("SELECT count(*) FROM transaction_overrides").fetchone()[0] == 0
    assert rebuilder.signals == 0


def test_write_with_form_content_type_is_403(client):
    r = client.patch(PURCHASE_URL, content="note=x",
                     headers={"Content-Type": "application/x-www-form-urlencoded", "X-Requested-With": "finance-app"})
    assert r.status_code == 403


def test_delete_also_needs_the_csrf_header(client):
    assert client.delete(PURCHASE_URL + "/override").status_code == 403


def test_oversized_body_is_413(client):
    r = client.patch(PURCHASE_URL, content='{"note":"' + "a" * 9000 + '"}', headers=WRITE)
    assert r.status_code == 413
    assert r.json()["error"] == "too_large"


@pytest.mark.parametrize("body", [
    {"category": "x" * 65},        # category <= 64
    {"note": "x" * 501},           # note <= 500
    {"excluded": "maybe"},
    {"amount": 5},                 # not an editable field
    {},                            # nothing to change
])
def test_invalid_patch_bodies_are_422(client, body):
    r = client.patch(PURCHASE_URL, json=body, headers=WRITE)
    assert r.status_code == 422
    assert r.json()["error"] == "invalid"


# --- reading ---------------------------------------------------------------------------

def test_get_transaction_shape(client):
    r = client.get(PURCHASE_URL)
    assert r.status_code == 200
    assert r.json() == {
        "date": "2026-01-15", "abs_amount": "123.45", "amount": -123.45, "description": "חנות לדוגמה",
        "category": "קניות", "scraped_category": "קניות", "note": None, "excluded": False,
        "overridden": False, "origin": "cal", "sources": ["cal", "riseup"],
        "horizon": None, "scraped_horizon": None, "tags": []}


def test_unknown_key_is_404_on_every_verb(client, rebuilder):
    url = "/api/transactions/2026-01-15/999.99"
    assert client.get(url).status_code == 404
    assert client.patch(url, json={"note": "x"}, headers=WRITE).status_code == 404
    assert client.delete(url + "/override", headers=WRITE).status_code == 404
    assert client.get(url).json()["error"] == "not_found"
    assert rebuilder.signals == 0


@pytest.mark.parametrize("url", ["/api/transactions/not-a-date/1.00", "/api/transactions/2026-01-15/abc",
                                 "/api/transactions/2026-01-15/1.234", "/api/transactions/2026-01-15/-5"])
def test_malformed_key_is_400(client, url):
    assert client.get(url).status_code == 400


def test_list_filters_by_date_and_hides_excluded_by_default(client):
    assert [t["date"] for t in client.get("/api/transactions").json()["transactions"]] == \
        ["2026-01-15", "2026-01-10", "2026-01-02"]
    only_mid = client.get("/api/transactions", params={"from": "2026-01-05", "to": "2026-01-12"})
    assert [t["date"] for t in only_mid.json()["transactions"]] == ["2026-01-10"]

    client.patch(SALARY_URL, json={"excluded": True}, headers=WRITE)
    assert [t["date"] for t in client.get("/api/transactions").json()["transactions"]] == ["2026-01-15", "2026-01-02"]
    both = client.get("/api/transactions", params={"excluded": "include"}).json()["transactions"]
    assert len(both) == 3
    hidden = client.get("/api/transactions", params={"excluded": "only"}).json()["transactions"]
    assert [(t["date"], t["excluded"]) for t in hidden] == [("2026-01-10", True)]


def test_bad_query_values_are_422(client):
    assert client.get("/api/transactions", params={"from": "yesterday"}).status_code == 422
    assert client.get("/api/transactions", params={"excluded": "all"}).status_code == 422


def test_unknown_route_is_a_json_404(client):
    r = client.get("/api/nope")
    assert r.status_code == 404
    assert r.json()["error"] == "not_found"


# --- writes: patch / clear / exclude / include / reset ----------------------------------

def audit(owner):
    return owner.execute("SELECT actor, field, old, new FROM override_audit ORDER BY id").fetchall()


def test_patch_clear_exclude_include_reset_round_trip(client, owner, rebuilder):
    # As the household, I recategorise the 123.45 charge and add a note.
    r = client.patch(PURCHASE_URL, json={"category": "אלקטרוניקה", "note": "gift"}, headers=WRITE)
    assert r.status_code == 200
    row = r.json()
    assert (row["category"], row["scraped_category"], row["note"], row["overridden"]) == \
        ("אלקטרוניקה", "קניות", "gift", True)
    assert rebuilder.signals == 1

    # null clears one field and leaves the other.
    row = client.patch(PURCHASE_URL, json={"note": None}, headers=WRITE).json()
    assert (row["category"], row["note"]) == ("אלקטרוניקה", None)

    # exclude / include.
    assert client.patch(PURCHASE_URL, json={"excluded": True}, headers=WRITE).json()["excluded"] is True
    assert client.patch(PURCHASE_URL, json={"excluded": False}, headers=WRITE).json()["excluded"] is False

    # clearing the last field prunes the override entirely.
    row = client.patch(PURCHASE_URL, json={"category": None}, headers=WRITE).json()
    assert row["overridden"] is False and row["category"] == "קניות"
    assert owner.execute("SELECT count(*) FROM transaction_overrides").fetchone()[0] == 0

    # reset puts back scraped values and drops several fields at once.
    client.patch(PURCHASE_URL, json={"category": "מתנות", "note": "n", "excluded": True}, headers=WRITE)
    row = client.delete(PURCHASE_URL + "/override", headers=WRITE).json()
    assert (row["category"], row["note"], row["excluded"], row["overridden"]) == ("קניות", None, False, False)
    assert owner.execute("SELECT count(*) FROM transaction_overrides").fetchone()[0] == 0
    assert rebuilder.signals == 7


def test_every_change_is_audited_with_old_and_new_and_the_actor(client, owner):
    client.patch(PURCHASE_URL, json={"category": "אלקטרוניקה", "note": "gift"}, headers=WRITE)
    client.patch(PURCHASE_URL, json={"category": "מתנות"}, headers=WRITE)
    client.patch(PURCHASE_URL, json={"note": "gift"}, headers=WRITE)          # no change: no audit row
    client.delete(PURCHASE_URL + "/override", headers=WRITE)
    assert audit(owner) == [
        (ME, "category", None, "אלקטרוניקה"),
        (ME, "note", None, "gift"),
        (ME, "category", "אלקטרוניקה", "מתנות"),
        (ME, "category", "מתנות", None),
        (ME, "note", "gift", None),
    ]
    entries = client.get("/api/audit", params={"limit": 2}).json()["entries"]
    assert len(entries) == 2
    assert entries[0]["field"] == "note" and entries[0]["old"] == "gift" and entries[0]["new"] is None
    assert entries[0]["date"] == "2026-01-15" and entries[0]["abs_amount"] == "123.45"


def test_excluded_audit_records_booleans(client, owner):
    client.patch(SALARY_URL, json={"excluded": True}, headers=WRITE)
    client.patch(SALARY_URL, json={"excluded": None}, headers=WRITE)          # null clears: back to false
    assert audit(owner) == [(ME, "excluded", False, True), (ME, "excluded", True, False)]


def test_blank_category_clears_it(client):
    client.patch(PURCHASE_URL, json={"category": "מתנות"}, headers=WRITE)
    row = client.patch(PURCHASE_URL, json={"category": "   "}, headers=WRITE).json()
    assert row["overridden"] is False


def test_key_ignores_sign_and_trailing_zeros(client):
    r = client.patch("/api/transactions/2026-01-10/1000", json={"note": "x"}, headers=WRITE)
    assert r.status_code == 200 and r.json()["abs_amount"] == "1000.00"


def test_categories_are_the_riseup_ones_plus_user_added_sorted(client):
    client.patch(PURCHASE_URL, json={"category": "אלקטרוניקה"}, headers=WRITE)
    cats = client.get("/api/categories").json()["categories"]
    assert cats == sorted(set(cats))
    assert {"אלקטרוניקה", "קניות"} == set(cats)   # only the purchase has a RiseUp category


def test_orphaned_overrides_listed(client, owner):
    # A bank corrects the charge to 123.40: the edit no longer matches any row.
    client.patch(PURCHASE_URL, json={"category": "אלקטרוניקה"}, headers=WRITE)
    import ledger
    ledger.load(owner, [{**PURCHASE, "amount": -123.40}, SALARY, CARD_BILL])
    assert client.get("/api/overrides/orphaned").json() == {"overrides": [
        {"date": "2026-01-15", "abs_amount": "123.45", "category": "אלקטרוניקה", "note": None, "excluded": False,
         "horizon": None}]}
    assert client.get(PURCHASE_URL).status_code == 404


def test_put_tags_replaces_the_set_creates_tags_and_signals(client, owner, rebuilder):
    # As the household, I tag the 123.45 charge for a trip, then swap one tag.
    r = client.put(PURCHASE_URL + "/tags", json={"tags": ["טיול", " החזר "]}, headers=WRITE)
    assert r.status_code == 200 and r.json()["tags"] == ["החזר", "טיול"]
    row = client.put(PURCHASE_URL + "/tags", json={"tags": ["טיול"]}, headers=WRITE).json()
    assert row["tags"] == ["טיול"] and rebuilder.signals == 2
    assert [(a, f, o, n) for a, f, o, n in audit(owner)] == [
        (ME, "tags", None, "החזר"), (ME, "tags", None, "טיול"), (ME, "tags", "החזר", None)]
    listed = client.get("/api/tags").json()["tags"]
    assert [(t["name"], t["count"]) for t in listed] == [("החזר", 0), ("טיול", 1)]


@pytest.mark.parametrize("body", [{"tags": [""]}, {"tags": ["x" * 41]}, {"tags": "טיול"},
                                  {"tags": ["a"] * 21}, {"tag": ["a"]}])
def test_invalid_tag_bodies_are_422(client, body):
    assert client.put(PURCHASE_URL + "/tags", json=body, headers=WRITE).status_code == 422


def test_tag_writes_need_csrf_and_a_real_transaction(client):
    assert client.put(PURCHASE_URL + "/tags", json={"tags": ["a"]}).status_code == 403
    r = client.put("/api/transactions/2026-01-15/999.99/tags", json={"tags": ["a"]}, headers=WRITE)
    assert r.status_code == 404


def test_rename_recolor_and_delete_a_tag(client):
    client.put(PURCHASE_URL + "/tags", json={"tags": ["טיול", "עבודה"]}, headers=WRITE)
    ids = {t["name"]: t["id"] for t in client.get("/api/tags").json()["tags"]}
    r = client.patch(f"/api/tags/{ids['טיול']}", json={"name": "טיול ליוון", "color": "#22aa88"}, headers=WRITE)
    assert r.json() == {"id": ids["טיול"], "name": "טיול ליוון", "color": "#22aa88"}
    assert client.patch(f"/api/tags/{ids['טיול']}", json={"name": "עבודה"}, headers=WRITE).status_code == 409
    assert client.patch(f"/api/tags/{ids['טיול']}", json={"color": "red"}, headers=WRITE).status_code == 422
    assert client.delete(f"/api/tags/{ids['עבודה']}", headers=WRITE).status_code == 200
    assert client.get(PURCHASE_URL).json()["tags"] == ["טיול ליוון"]
    assert client.delete(f"/api/tags/{ids['עבודה']}", headers=WRITE).status_code == 404


def test_horizon_override_wins_and_rejects_unknown(client, rebuilder):
    r = client.patch(PURCHASE_URL, json={"horizon": "future"}, headers=WRITE)
    assert r.status_code == 200 and r.json()["horizon"] == "future" and r.json()["overridden"]
    assert client.patch(PURCHASE_URL, json={"horizon": "someday"}, headers=WRITE).status_code == 422
    r = client.patch(PURCHASE_URL, json={"horizon": None}, headers=WRITE)
    assert r.json()["horizon"] is None and not r.json()["overridden"]   # empty override pruned


def test_rebuild_status_comes_from_the_workflow_query(client, rebuilder):
    assert client.get("/api/rebuild").json() == {"state": "idle", "last_published_at": None, "last_error": None}
    rebuilder.state = {"state": "running", "last_published_at": "2026-01-15T10:00:00+00:00", "last_error": None}
    assert client.get("/api/rebuild").json()["state"] == "running"


# --- Temporal ---------------------------------------------------------------------------

def test_a_failed_signal_does_not_fail_the_edit(build, make_token, owner, rebuilder):
    # Nothing listens on this port: the signal fails, the edit must still succeed and persist.
    rebuilder.signal_edited = Rebuilder("127.0.0.1:1").signal_edited
    c = TestClient(build())
    c.headers.update({"X-Origin-Secret": SECRET})
    c.cookies.set(COOKIE, make_token())
    r = c.patch(PURCHASE_URL, json={"note": "kept"}, headers=WRITE)
    assert r.status_code == 200 and r.json()["note"] == "kept"
    assert owner.execute("SELECT note FROM transaction_overrides").fetchone()[0] == "kept"


def test_status_and_ping_fall_back_when_temporal_is_down():
    dead = Rebuilder("127.0.0.1:1")
    assert dead.status() == {"state": "idle", "last_published_at": None, "last_error": None}
    assert dead.ping() is False
    assert dead.signal_edited() is False


def test_signal_with_start_targets_the_contract_names(monkeypatch):
    """The workflow is referred to by name: type, id, queue and signal are the documented ones."""
    calls = {}

    class FakeClient:
        async def start_workflow(self, workflow, **kw):
            calls.update(workflow=workflow, **kw)

    async def connect(address):
        return FakeClient()
    monkeypatch.setattr("api.rebuild.Client.connect", connect)
    assert Rebuilder("temporal:7233").signal_edited() is True
    assert (calls["workflow"], calls["id"], calls["task_queue"], calls["start_signal"]) == \
        ("LedgerRebuildWorkflow", "ledger-rebuild", "finance-sync", "edited")


# --- least privilege --------------------------------------------------------------------

@pytest.fixture
def as_api(test_url, owner):
    c = psycopg.connect(test_url)
    c.execute("SET ROLE finance_api")
    yield c
    c.rollback()
    c.close()


@pytest.mark.parametrize("sql", [
    "TRUNCATE scraped_transactions",
    "DELETE FROM scraped_transactions",
    "UPDATE scraped_transactions SET description = 'x'",
    "INSERT INTO scraped_transactions (txn_date, abs_amount, amount, position, record) "
    "VALUES ('2026-02-01', 1, 1, 9, '{}')",
    "UPDATE override_audit SET actor = 'x'",
    "DELETE FROM override_audit",
    "TRUNCATE override_audit",
    "TRUNCATE transaction_overrides",
    "DROP TABLE transaction_overrides",
    "CREATE TABLE evil (x int)",
])
def test_api_role_cannot_touch_the_scraped_layer_or_rewrite_the_audit(as_api, sql):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        as_api.execute(sql)


def test_api_role_can_do_exactly_what_the_api_needs(as_api):
    as_api.execute("SELECT count(*) FROM scraped_transactions")
    as_api.execute("SELECT count(*) FROM transactions")
    as_api.execute("SELECT count(*) FROM orphaned_overrides")
    as_api.execute("INSERT INTO transaction_overrides (txn_date, abs_amount, note) VALUES ('2026-01-15', 123.45, 'x')")
    as_api.execute("UPDATE transaction_overrides SET note = 'y'")
    as_api.execute("INSERT INTO override_audit (actor) VALUES ('t')")
    as_api.execute("SELECT count(*) FROM override_audit")
    as_api.execute("DELETE FROM transaction_overrides")


def test_api_role_is_nologin_until_a_password_is_configured(owner):
    # The migration creates it NOLOGIN; db/ledger.py grants LOGIN only when FINANCE_API_DB_PASSWORD is set.
    row = owner.execute("SELECT rolcanlogin, rolsuper, rolcreatedb, rolcreaterole FROM pg_roles "
                        "WHERE rolname = 'finance_api'").fetchone()
    assert row[1:] == (False, False, False)


def test_short_origin_secret_is_refused():
    with pytest.raises(ConfigError):
        Settings.from_env({"FINANCE_API_ORIGIN_SECRET": "short", "FINANCE_API_DEV_USER": "d@example.com"}).validate()
