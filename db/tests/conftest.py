"""Point the db tests at a throwaway `finance_test` database on the same server.

Skips the whole module when Postgres isn't reachable (docker compose not up).
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg  # noqa: E402
from psycopg.conninfo import conninfo_to_dict, make_conninfo  # noqa: E402

import ledger  # noqa: E402
from finance.tenancy import DEFAULT_TENANT_ID  # noqa: E402

TEST_DB = os.environ.get("FINANCE_TEST_DB", "finance_test")   # a branch with other migrations uses its own


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
    admin = ledger.connect_admin(test_url)
    admin.execute("TRUNCATE scraped_transactions, transaction_overrides, merchant_rules, categories, category_groups, transaction_tags, tags, override_audit, goals, budget_lines, transaction_offsets, holding_assignments, notifications, assets, position_snapshots, digest_runs, accounts, credit_cards, loans, savings_holdings, source_dump_entities, source_dumps, offset_rules, mortgage_schedule_periods, loan_freezes, household_settings")
    admin.commit()
    admin.close()
    c = ledger.connect(test_url, tenant_id=DEFAULT_TENANT_ID)
    yield c
    c.close()
