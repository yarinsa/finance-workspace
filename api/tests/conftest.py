"""Fixtures for the ledger API tests.

The database is the throwaway `finance_test` on the same Postgres server as db/tests.
The API's pool runs `SET ROLE finance_api` on each connection, so the tests exercise the
real least-privilege grants without touching the role's (cluster-wide) password.
JWTs are signed with a key generated here and verified through a fake JWKS client:
nothing calls AWS. All transactions are made up.
"""
import os
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
from finance.tenancy import DEFAULT_TENANT_ID  # noqa: E402
from api.app import create_app  # noqa: E402
from api.auth import COOKIE, TokenVerifier  # noqa: E402
from api.config import Settings  # noqa: E402

SECRET = "test-origin-secret-0123456789abcdef"
CLIENT_ID = "test-client"
POOL_ID = "eu-west-1_TESTPOOL"
REGION = "eu-west-1"
ME = "me@example.com"
TEST_DB = os.environ.get("FINANCE_TEST_DB", "finance_test")   # a branch with other migrations uses its own
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
        if not admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DB,)).fetchone():
            admin.execute(f'CREATE DATABASE "{TEST_DB}"')
    return make_conninfo(**{**conninfo_to_dict(url), "dbname": TEST_DB})


OWNED = ["scraped_transactions", "transaction_overrides", "override_audit", "transaction_tags",
         "transaction_offsets", "tags", "categories", "merchant_rules", "goals",
         "notifications", "assets", "position_snapshots", "push_subscriptions"]   # horizons keep their seed


def make_member(admin, email, tenant_id, role="owner"):
    """Create the user (if new) and a membership in `tenant_id`; returns the user id."""
    admin.execute("INSERT INTO users (email) VALUES (%s) ON CONFLICT DO NOTHING", (email,))
    uid = admin.execute("SELECT id FROM users WHERE email = %s", (email,)).fetchone()[0]
    admin.execute("INSERT INTO memberships (tenant_id, user_id, role) VALUES (%s, %s, %s) "
                  "ON CONFLICT DO NOTHING", (tenant_id, uid, role))
    return uid


@pytest.fixture
def owner(test_url):
    """Tenant-scoped connection to the default tenant (RLS applies, as in the host jobs).

    The user ME is an owner of the default tenant, the household as it was before tenants."""
    admin = ledger.connect_admin(test_url)
    admin.execute(f"TRUNCATE {', '.join(OWNED)}, memberships, users, category_groups CASCADE")
    admin.execute("DELETE FROM horizons WHERE tenant_id <> %s", (DEFAULT_TENANT_ID,))
    admin.execute("DELETE FROM tenants WHERE id <> %s", (DEFAULT_TENANT_ID,))
    make_member(admin, ME, DEFAULT_TENANT_ID)
    admin.commit()
    admin.close()
    c = ledger.connect(test_url, tenant_id=DEFAULT_TENANT_ID)
    ledger.load(c, LEDGER)
    yield c
    c.close()


@pytest.fixture
def admin(test_url):
    """The privileged owner role: creates tenants and users (the API role may not)."""
    c = ledger.connect_admin(test_url)
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
        self.logins, self.codes, self.retries, self.runs = [], [], [], []
        self.state = {"state": "idle", "last_published_at": None, "last_error": None}

    def signal_edited(self, tenant_id=None):
        self.signals += 1
        self.tenants = [*getattr(self, "tenants", []), tenant_id]
        return True

    def status(self, tenant_id=None):
        return self.state

    access_calls: list
    access_result = (True, "added")

    def sync_tenant_access(self, tenant_id, email):
        self.access_calls = [*getattr(self, "access_calls", []), (tenant_id, email)]
        return self.access_result

    def ping(self):
        return True

    # App logins (Harel): what was asked of Temporal, and whether it "answered".
    logins: list
    runs: list
    codes: list
    up = True
    waiting = True

    def start_login(self, source):
        self.logins.append(source)
        return self.up

    def retry(self, source, resume):
        self.retries.append((source, resume))
        return self.up

    def run(self, source):
        self.runs.append(source)
        return self.up

    def submit_otp(self, source, code):
        self.codes.append((source, code))
        return self.up and self.waiting


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
