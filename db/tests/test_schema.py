"""The migrated database matches finance/tables.py, and the ledger model matches the data.

As the household, when a field is added to a model, the schema must follow in a
migration (`alembic revision --autogenerate`) — otherwise this fails before the
digest silently writes rows the database does not describe.
"""
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine
from sqlmodel import SQLModel

import finance.tables  # noqa: F401
import ledger


def test_migrations_match_the_sqlmodel_tables(test_url):
    ledger.migrate(test_url)
    with create_engine(ledger.sqlalchemy_url(test_url)).connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), SQLModel.metadata)
    diff = [d for d in diff if not (d[0] == "remove_table" and d[1].name == "alembic_version")]
    assert diff == [], f"schema drift — generate a migration: {diff}"
