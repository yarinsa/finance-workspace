"""Push subscription endpoints: same auth/CSRF as other writes, upsert by endpoint, least privilege."""
import pytest
from fastapi.testclient import TestClient

from .conftest import ME, SECRET, WRITE

ENDPOINT = "https://push.example.com/send/abc123456789"
SUB = {"endpoint": ENDPOINT, "expirationTime": None,
       "keys": {"p256dh": "BNcRdreALRFXTkOOUHK1EtK2wtaz5Ry4YfYCA_0QTpQtUbVlUls0VJXg7A8u-Ts1XbjhazAkj7I99e8QcYP7DkM",
                "auth": "tBHItJI5svbpez7KI4CCXg"}}


@pytest.fixture(autouse=True)
def clean(owner):
    owner.execute("DELETE FROM push_subscriptions")
    owner.commit()


def rows(owner):
    return owner.execute("SELECT endpoint, p256dh, email FROM push_subscriptions").fetchall()


def test_subscribe_stores_and_resubscribe_upserts(client, owner):
    assert client.post("/api/push/subscribe", json=SUB, headers=WRITE).status_code == 200
    again = {**SUB, "keys": {**SUB["keys"], "auth": "anotherAuthSecret"}}
    assert client.post("/api/push/subscribe", json=again, headers=WRITE).status_code == 200
    got = rows(owner)
    assert len(got) == 1 and got[0][0] == ENDPOINT and got[0][2] == ME
    assert owner.execute("SELECT auth FROM push_subscriptions").fetchone()[0] == "anotherAuthSecret"


def test_subscribe_needs_csrf_and_a_session(client, owner):
    assert client.post("/api/push/subscribe", json=SUB).status_code == 403
    client.cookies.clear()
    assert client.post("/api/push/subscribe", json=SUB, headers=WRITE).status_code == 401
    assert rows(owner) == []


@pytest.mark.parametrize("bad", [
    {**SUB, "endpoint": "http://insecure.example.com/send/abcdefgh"},
    {"endpoint": ENDPOINT},
    {**SUB, "keys": {"p256dh": "short", "auth": "x"}},
])
def test_invalid_subscription_is_422(client, bad):
    assert client.post("/api/push/subscribe", json=bad, headers=WRITE).status_code == 422


def test_unsubscribe_deletes_and_is_idempotent(client, owner):
    client.post("/api/push/subscribe", json=SUB, headers=WRITE)
    r = client.post("/api/push/unsubscribe", json={"endpoint": ENDPOINT}, headers=WRITE)
    assert r.json() == {"ok": True, "removed": 1} and rows(owner) == []
    assert client.post("/api/push/unsubscribe", json={"endpoint": ENDPOINT}, headers=WRITE).json()["removed"] == 0


def test_key_endpoint_serves_only_the_public_key(build, make_token):
    from api.auth import COOKIE
    c = TestClient(build(push_public_key="PUBKEY"))
    c.headers.update({"X-Origin-Secret": SECRET})
    c.cookies.set(COOKIE, make_token())
    assert c.get("/api/push/key").json() == {"key": "PUBKEY"}


def test_key_endpoint_is_404_when_unconfigured(client):
    assert client.get("/api/push/key").status_code == 404
