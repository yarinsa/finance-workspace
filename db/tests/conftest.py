"""Point the db tests at a throwaway `finance_test` database on the same server.

Skips the whole module when Postgres isn't reachable (docker compose not up).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg  # noqa: E402
from psycopg.conninfo import conninfo_to_dict, make_conninfo  # noqa: E402

import ledger  # noqa: E402

TEST_DB = "finance_test"


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
            admin.execute(f"CREATE DATABASE {TEST_DB}")
    return make_conninfo(**{**conninfo_to_dict(url), "dbname": TEST_DB})


@pytest.fixture
def conn(test_url):
    c = ledger.connect(test_url)
    c.execute("TRUNCATE scraped_transactions, transaction_overrides")
    c.commit()
    yield c
    c.close()
