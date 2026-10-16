"""Alembic env: targets finance.tables (SQLModel.metadata), URL from DATABASE_URL."""
import sys
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine
from sqlmodel import SQLModel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # db/, for ledger
import finance.tables  # noqa: E402,F401  (registers the tables)
import ledger  # noqa: E402

target_metadata = SQLModel.metadata


def run():
    url = context.config.attributes.get("url") or ledger.database_url()
    connection = context.config.attributes.get("connection")
    if connection is not None:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
        return
    with create_engine(ledger.sqlalchemy_url(url)).connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


run()
