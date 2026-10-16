"""Fixtures for the ledger API tests.

The database is the throwaway `finance_test` on the same Postgres server as db/tests.
The API's pool runs `SET ROLE finance_api` on each connection, so the tests exercise the
real least-privilege grants without touching the role's (cluster-wide) password.
JWTs are signed with a key generated here and verified through a fake JWKS client:
nothing calls AWS. All transactions are made up.
"""
import sys
import time
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "db"))

import psycopg  # noqa: E402
from psycopg.conninfo import conninfo_to_dict, make_conninfo  # noqa: E402
from psycopg_pool import ConnectionPool  # noqa: E402

import ledger  # noqa: E402
from api.app import create_app  # noqa: E402
from api.auth import COOKIE, TokenVerifier  # noqa: E402
from api.config import Settings  # noqa: E402

SECRET = "test-origin-secret-0123456789abcdef"
CLIENT_ID = "test-client"
POOL_ID = "eu-west-1_TESTPOOL"
REGION = "eu-west-1"
ME = "me@example.com"
ISSUER = f"https://cognito-idp.{REGION}.amazonaws.com/{POOL_ID}"

# Made-up rows in the digested ledger's shape.
PURCHASE = {"date": "2026-01-15", "amount": -123.45, "description": "חנות לדוגמה",
            "category": "קניות", "origin": "cal", "is_income": False, "sources": ["cal", "riseup"]}
SALARY = {"date": "2026-01-10", "amount": 1000.0, "description": "העברת משכורת",
          "category": "משכורת", "origin": "discount", "is_income": True, "sources": ["discount"]}
CARD_BILL = {"date": "2026-01-02", "amount": -500.0, "description": "כאל-חיוב לכרטיס",
             "category": "חיובי כרטיס", "origin": "discount", "is_income": False, "sources": ["discount"]}
LEDGER = [PURCHASE, SALARY, CARD_BILL]
PURCHASE_URL = "/api/transactions/2026-01-15/123.45"


@pytest.fixture(scope="session")
def test_url():
    url = ledger.database_url()
    if not url:
        pytest.skip("DATABASE_URL not set")
    try:
        admin = psycopg.connect(url, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as e:
        pytest.skip(f"Postgres not reachable: {e}")
    with admin:
        if not admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", ("finance_test",)).fetchone():
            admin.execute("CREATE DATABASE finance_test")
    return make_conninfo(**{**conninfo_to_dict(url), "dbname": "finance_test"})


@pytest.fixture
def owner(test_url):
    """The schema owner: migrates, seeds, and checks what the API wrote."""
    c = ledger.connect(test_url)
    c.execute("TRUNCATE scraped_transactions, transaction_overrides, categories, transaction_tags, tags, override_audit, goals")
    c.commit()
    ledger.load(c, LEDGER)
    yield c
    c.close()


@pytest.fixture
def pool(test_url, owner):
    def as_api(conn):
        conn.execute("SET ROLE finance_api")
        conn.commit()
    p = ConnectionPool(test_url, min_size=1, max_size=3, configure=as_api, open=True)
    yield p
    p.close()


class FakeRebuilder:
    def __init__(self):
        self.signals = 0
        self.state = {"state": "idle", "last_published_at": None, "last_error": None}

    def signal_edited(self):
        self.signals += 1
        return True

    def status(self):
        return self.state

    def ping(self):
        return True


@pytest.fixture
def rebuilder():
    return FakeRebuilder()


@pytest.fixture(scope="session")
def key_pair():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


class FakeJwks:
    """Stands in for jwt.PyJWKClient: always hands back our public key."""
    def __init__(self, key):
        self.key = key

    def get_signing_key_from_jwt(self, token):
        return type("SigningKey", (), {"key": self.key.public_key()})()


@pytest.fixture
def make_token(key_pair):
    def make(email=ME, aud=CLIENT_ID, iss=ISSUER, exp_in=3600, token_use="id", signer=None, **extra):
        claims = {"email": email, "aud": aud, "iss": iss, "token_use": token_use,
                  "exp": int(time.time()) + exp_in, "sub": "abc", **extra}
        return jwt.encode(claims, signer or key_pair, algorithm="RS256")
    return make


def settings(**over):
    base = dict(origin_secret=SECRET, allowed_emails=frozenset({ME}), cognito_region=REGION,
                cognito_pool_id=POOL_ID, cognito_client_id=CLIENT_ID)
    return Settings(**{**base, **over}).validate()


@pytest.fixture
def build(pool, rebuilder, key_pair):
    def make(**over):
        s = settings(**over)
        verifier = None if s.dev_user else TokenVerifier(s, jwk_client=FakeJwks(key_pair))
        return create_app(s, pool=pool, rebuilder=rebuilder, verifier=verifier)
    return make


@pytest.fixture
def client(build, make_token):
    """An authenticated client: origin secret, session cookie, and the CSRF headers on writes."""
    c = TestClient(build())
    c.headers.update({"X-Origin-Secret": SECRET})
    c.cookies.set(COOKIE, make_token())
    return c


WRITE = {"Content-Type": "application/json", "X-Requested-With": "finance-app"}
