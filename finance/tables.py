"""Postgres tables for the transactions database, as SQLModel models.

This is the schema's source of truth: Alembic (db/migrations) autogenerates from
`SQLModel.metadata`, and db/tests/test_schema.py fails if the migrated database
and these classes disagree. Columns pulled out of a ledger row are typed from
`finance.models.LedgerTransaction`; the full row is kept in `record`.

The `transactions` and `orphaned_overrides` views are plain SQL in the migrations.
"""
import datetime as dt
from decimal import Decimal

from sqlalchemy import ARRAY, BigInteger, CheckConstraint, Column, ForeignKey, Integer, Numeric, Text, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlmodel import Field, Relationship, SQLModel

Money = Numeric(12, 2)


def _now():
    return Column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))


def _category_fk():
    return Column(Integer, ForeignKey("categories.id", ondelete="SET NULL"), nullable=True, index=True)


class Category(SQLModel, table=True):
    """The fixed list of spending categories a transaction can be assigned to.

    Seeded from RiseUp's categories on every import (`source` "riseup"); a category
    first assigned by hand is added with `source` "user"."""
    __tablename__ = "categories"
    __table_args__ = (CheckConstraint("source IN ('riseup', 'user')", name="categories_source_check"),)

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(sa_column=Column(Text, nullable=False, unique=True))
    source: str = Field(sa_column=Column(Text, nullable=False, server_default="user"))
    created_at: dt.datetime | None = Field(default=None, sa_column=_now())

    scraped_transactions: list["ScrapedTransaction"] = Relationship(back_populates="category_ref")
    overrides: list["TransactionOverride"] = Relationship(back_populates="category_ref")


class ScrapedTransaction(SQLModel, table=True):
    """Machine layer: the digested ledger, replaced in full on each import."""
    __tablename__ = "scraped_transactions"

    txn_date: dt.date = Field(primary_key=True)
    abs_amount: Decimal = Field(primary_key=True, sa_type=Money)
    amount: Decimal = Field(sa_type=Money)
    description: str = Field(sa_column=Column(Text, nullable=False, server_default=""))
    category: str | None = Field(default=None, sa_type=Text)   # the source's raw label, as scraped
    category_id: int | None = Field(default=None, sa_column=_category_fk())   # RiseUp's assignment
    origin: str | None = Field(default=None, sa_type=Text)
    sources: list[str] = Field(sa_column=Column(ARRAY(Text), nullable=False, server_default="{}"))
    position: int                                    # index in the digested ledger (keeps its order)
    record: dict = Field(sa_column=Column(JSONB, nullable=False))   # the full LedgerTransaction
    imported_at: dt.datetime | None = Field(default=None, sa_column=_now())

    category_ref: Category | None = Relationship(back_populates="scraped_transactions")


class TransactionOverride(SQLModel, table=True):
    """Human layer: sparse edits, kept forever. Null falls through to the scraped value."""
    __tablename__ = "transaction_overrides"
    __table_args__ = (
        CheckConstraint("abs_amount >= 0", name="transaction_overrides_abs_amount_check"),
        CheckConstraint("horizon IN ('current', 'near', 'future')", name="transaction_overrides_horizon_check"),
    )

    txn_date: dt.date = Field(primary_key=True)
    abs_amount: Decimal = Field(primary_key=True, sa_type=Money)
    category_id: int | None = Field(default=None, sa_column=_category_fk())
    note: str | None = Field(default=None, sa_type=Text)
    excluded: bool = Field(default=False, sa_column_kwargs={"server_default": text("false")})
    horizon: str | None = Field(default=None, sa_type=Text)   # current | near | future (data/horizons.py)
    created_at: dt.datetime | None = Field(default=None, sa_column=_now())
    updated_at: dt.datetime | None = Field(default=None, sa_column=_now())

    category_ref: Category | None = Relationship(back_populates="overrides")


class OverrideAudit(SQLModel, table=True):
    """Append-only log of every override change: who, which field, old and new value.

    `old`/`new` are jsonb scalars (a string, a boolean or null). A reset writes one row
    per field that was set. Written by db/overrides.py for both the CLI and the API."""
    __tablename__ = "override_audit"

    id: int | None = Field(default=None, sa_column=Column(BigInteger, primary_key=True, autoincrement=True))
    at: dt.datetime | None = Field(default=None, sa_column=_now())
    actor: str = Field(sa_type=Text)
    txn_date: dt.date | None = Field(default=None)
    abs_amount: Decimal | None = Field(default=None, sa_type=Money)
    field: str | None = Field(default=None, sa_type=Text)
    old: object | None = Field(default=None, sa_column=Column(JSONB))
    new: object | None = Field(default=None, sa_column=Column(JSONB))
