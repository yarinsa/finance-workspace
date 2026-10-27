"""Postgres tables for the transactions database, as SQLModel models.

This is the schema's source of truth: Alembic (db/migrations) autogenerates from
`SQLModel.metadata`, and db/tests/test_schema.py fails if the migrated database
and these classes disagree. Columns pulled out of a ledger row are typed from
`finance.models.LedgerTransaction`; the full row is kept in `record`.

The `transactions`, `transaction_kinds`, `orphaned_overrides`, `orphaned_tags` and `orphaned_offsets` views are plain SQL in the migrations.
"""
import datetime as dt
from decimal import Decimal

from sqlalchemy import ARRAY, BigInteger, CheckConstraint, Column, ForeignKey, Integer, Numeric, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlmodel import Field, Relationship, SQLModel

Money = Numeric(12, 2)


def _now():
    return Column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))


def _category_fk():
    return Column(Integer, ForeignKey("categories.id", ondelete="SET NULL"), nullable=True, index=True)


def _fk(table):
    return Column(Integer, ForeignKey(f"{table}.id", ondelete="SET NULL"), nullable=True, index=True)


class Horizon(SQLModel, table=True):
    """Who a shekel out is for: current me, near-future me, future me (data/horizons.py).

    A fixed list seeded by migration 0006; `key` is the stable code the ledger and API
    use, `name` the label and `target_pct` the share of net income aimed for."""
    __tablename__ = "horizons"

    id: int | None = Field(default=None, primary_key=True)
    key: str = Field(sa_column=Column(Text, nullable=False, unique=True))
    name: str = Field(sa_type=Text)
    target_pct: Decimal = Field(sa_type=Numeric(5, 2))
    position: int = Field(default=0)
    created_at: dt.datetime | None = Field(default=None, sa_column=_now())

    scraped_transactions: list["ScrapedTransaction"] = Relationship(back_populates="horizon_ref")
    overrides: list["TransactionOverride"] = Relationship(back_populates="horizon_ref")
    goals: list["Goal"] = Relationship(back_populates="horizon_ref")


class Goal(SQLModel, table=True):
    """A personal savings goal (docs/plangram-prd/04-goals.md), assigned to a horizon.

    Was data/goals/goals.json's `goals` list; `slug` keeps that store's string id."""
    __tablename__ = "goals"

    id: int | None = Field(default=None, primary_key=True)
    slug: str = Field(sa_column=Column(Text, nullable=False, unique=True))
    description: str = Field(sa_type=Text)
    amount: Decimal = Field(sa_type=Money)
    start_date: dt.date | None = None
    end_date: dt.date | None = None
    interval: str | None = Field(default=None, sa_type=Text)
    repetitions: int = Field(default=1)
    rise: Decimal = Field(default=Decimal(0), sa_type=Money)
    from_asset_id: str | None = Field(default=None, sa_type=Text)
    horizon_id: int | None = Field(default=None, sa_column=_fk("horizons"))
    created_at: dt.datetime | None = Field(default=None, sa_column=_now())

    horizon_ref: Horizon | None = Relationship(back_populates="goals")
    overrides: list["TransactionOverride"] = Relationship(back_populates="goal_ref")


class PlanTarget(SQLModel, table=True):
    """One of the Goals screen's three general targets (data/goals.py): emergency fund,
    inheritance, retirement. Was data/goals/goals.json's `*_target` keys.

    No row = not decided yet (data/goals.py falls back to the JSON store); amount 0 = unset
    (db/goal_store.py)."""
    __tablename__ = "plan_targets"
    __table_args__ = (CheckConstraint("key IN ('emergency_fund', 'inheritance', 'retirement')",
                                      name="plan_targets_key_check"),)

    key: str = Field(sa_column=Column(Text, primary_key=True))
    amount: Decimal = Field(sa_type=Money)
    updated_at: dt.datetime | None = Field(default=None, sa_column=_now())


KIND_CHECK = "kind IN ('fixed', 'variable')"


class CategoryGroup(SQLModel, table=True):
    """A group of categories (דיור, תחבורה, ...), from finance/categories.py `GROUPS`.

    Upserted by `key` on every import (db/ledger.py `sync_taxonomy`)."""
    __tablename__ = "category_groups"

    id: int | None = Field(default=None, primary_key=True)
    key: str = Field(sa_column=Column(Text, nullable=False, unique=True))
    name: str = Field(sa_type=Text)
    position: int = Field(default=0)
    created_at: dt.datetime | None = Field(default=None, sa_column=_now())

    categories: list["Category"] = Relationship(back_populates="group_ref")


class Category(SQLModel, table=True):
    """The one list of categories a transaction can be assigned to.

    `builtin` rows are finance/categories.py `CATEGORIES`, upserted on every import with
    their group, default `kind` and `usage_based` flag. A source label nobody mapped
    yet is kept as a `riseup` row (no group); a name first typed by hand is `user`."""
    __tablename__ = "categories"
    __table_args__ = (CheckConstraint("source IN ('builtin', 'riseup', 'user')", name="categories_source_check"),
                      CheckConstraint(KIND_CHECK, name="categories_kind_check"))

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(sa_column=Column(Text, nullable=False, unique=True))
    source: str = Field(sa_column=Column(Text, nullable=False, server_default="user"))
    created_at: dt.datetime | None = Field(default=None, sa_column=_now())
    group_id: int | None = Field(default=None, sa_column=_fk("category_groups"))
    kind: str | None = Field(default=None, sa_type=Text)   # default kind; null = not an expense category
    usage_based: bool = Field(default=False, sa_column_kwargs={"server_default": text("false")})
    position: int = Field(default=0, sa_column_kwargs={"server_default": text("0")})

    group_ref: CategoryGroup | None = Relationship(back_populates="categories")
    scraped_transactions: list["ScrapedTransaction"] = Relationship(back_populates="category_ref")
    overrides: list["TransactionOverride"] = Relationship(back_populates="category_ref")
    merchant_rules: list["MerchantRule"] = Relationship(back_populates="category_ref")


class MerchantRule(SQLModel, table=True):
    """Human layer, per merchant: every transaction of `merchant` (finance/merchants.py
    key, the ledger row's `merchant`) gets this category and/or kind, unless that
    transaction has its own override. Kept forever, like transaction_overrides."""
    __tablename__ = "merchant_rules"
    __table_args__ = (CheckConstraint(KIND_CHECK, name="merchant_rules_kind_check"),)

    id: int | None = Field(default=None, primary_key=True)
    merchant: str = Field(sa_column=Column(Text, nullable=False, unique=True))
    category_id: int | None = Field(default=None, sa_column=_category_fk())
    kind: str | None = Field(default=None, sa_type=Text)
    created_at: dt.datetime | None = Field(default=None, sa_column=_now())
    updated_at: dt.datetime | None = Field(default=None, sa_column=_now())

    category_ref: Category | None = Relationship(back_populates="merchant_rules")


class ScrapedTransaction(SQLModel, table=True):
    """Machine layer: the digested ledger, replaced in full on each import."""
    __tablename__ = "scraped_transactions"

    txn_date: dt.date = Field(primary_key=True)
    abs_amount: Decimal = Field(primary_key=True, sa_type=Money)
    amount: Decimal = Field(sa_type=Money)
    description: str = Field(sa_column=Column(Text, nullable=False, server_default=""))
    category: str | None = Field(default=None, sa_type=Text)   # the source's raw label, as scraped
    category_id: int | None = Field(default=None, sa_column=_category_fk())   # finance/categories.py default
    origin: str | None = Field(default=None, sa_type=Text)
    sources: list[str] = Field(sa_column=Column(ARRAY(Text), nullable=False, server_default="{}"))
    position: int                                    # index in the digested ledger (keeps its order)
    record: dict = Field(sa_column=Column(JSONB, nullable=False))   # the full LedgerTransaction
    imported_at: dt.datetime | None = Field(default=None, sa_column=_now())
    horizon_id: int | None = Field(default=None, sa_column=_fk("horizons"))   # data/horizons.py default

    category_ref: Category | None = Relationship(back_populates="scraped_transactions")
    horizon_ref: Horizon | None = Relationship(back_populates="scraped_transactions")
    tags: list["Tag"] = Relationship(sa_relationship_kwargs={
        "secondary": "transaction_tags", "viewonly": True, "order_by": "Tag.name",
        "primaryjoin": "and_(ScrapedTransaction.txn_date == foreign(TransactionTag.txn_date), "
                       "ScrapedTransaction.abs_amount == foreign(TransactionTag.abs_amount))",
        "secondaryjoin": "Tag.id == foreign(TransactionTag.tag_id)"})


class TransactionOverride(SQLModel, table=True):
    """Human layer: sparse edits, kept forever. Null falls through to the scraped value."""
    __tablename__ = "transaction_overrides"
    __table_args__ = (
        CheckConstraint("abs_amount >= 0", name="transaction_overrides_abs_amount_check"),
        CheckConstraint(KIND_CHECK, name="transaction_overrides_kind_check"),
    )

    txn_date: dt.date = Field(primary_key=True)
    abs_amount: Decimal = Field(primary_key=True, sa_type=Money)
    category_id: int | None = Field(default=None, sa_column=_category_fk())
    note: str | None = Field(default=None, sa_type=Text)
    excluded: bool = Field(default=False, sa_column_kwargs={"server_default": text("false")})
    created_at: dt.datetime | None = Field(default=None, sa_column=_now())
    updated_at: dt.datetime | None = Field(default=None, sa_column=_now())
    horizon_id: int | None = Field(default=None, sa_column=_fk("horizons"))
    goal_id: int | None = Field(default=None, sa_column=_fk("goals"))   # money that went to this goal
    kind: str | None = Field(default=None, sa_type=Text)   # fixed / variable, beats every default

    category_ref: Category | None = Relationship(back_populates="overrides")
    horizon_ref: Horizon | None = Relationship(back_populates="overrides")
    goal_ref: Goal | None = Relationship(back_populates="overrides")


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


class Tag(SQLModel, table=True):
    """A label the household puts on transactions (a trip, a project, "reimbursable").

    Free-form and many-to-many, unlike a category: a transaction can carry several."""
    __tablename__ = "tags"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(sa_column=Column(Text, nullable=False, unique=True))
    color: str | None = Field(default=None, sa_type=Text)   # "#rrggbb", or null for the default
    created_at: dt.datetime | None = Field(default=None, sa_column=_now())

    links: list["TransactionTag"] = Relationship(
        back_populates="tag_ref", sa_relationship_kwargs={"cascade": "all, delete-orphan", "passive_deletes": True})


class TransactionTag(SQLModel, table=True):
    """A tag on a transaction, by ledger key — human layer, kept forever like an override.

    No FK to scraped_transactions (replaced on every import): a link whose transaction
    vanished is reported by the `orphaned_tags` view, never deleted."""
    __tablename__ = "transaction_tags"
    __table_args__ = (CheckConstraint("abs_amount >= 0", name="transaction_tags_abs_amount_check"),)

    txn_date: dt.date = Field(primary_key=True)
    abs_amount: Decimal = Field(primary_key=True, sa_type=Money)
    tag_id: int = Field(sa_column=Column(Integer, ForeignKey("tags.id", ondelete="CASCADE"),
                                         primary_key=True, index=True))
    created_at: dt.datetime | None = Field(default=None, sa_column=_now())

    tag_ref: Tag = Relationship(back_populates="links")
    transaction: ScrapedTransaction | None = Relationship(sa_relationship_kwargs={
        "viewonly": True,
        "primaryjoin": "and_(foreign(TransactionTag.txn_date) == ScrapedTransaction.txn_date, "
                       "foreign(TransactionTag.abs_amount) == ScrapedTransaction.abs_amount)"})


class TransactionOffset(SQLModel, table=True):
    """A קיזוז the user decided: payback `payback_*` nets `amount` off expense `expense_*`.

    Human layer keyed by ledger keys, no FK (scraped rows are replaced on every import);
    the `orphaned_offsets` view lists links whose rows vanished. A payback with any
    row here ignores the digest's auto suggestion; a row with no expense (all three
    expense columns null) records "this payback offsets nothing"."""
    __tablename__ = "transaction_offsets"
    __table_args__ = (
        CheckConstraint("payback_abs_amount >= 0", name="transaction_offsets_payback_abs_amount_check"),
        CheckConstraint("(expense_date IS NULL) = (expense_abs_amount IS NULL) "
                        "AND (expense_date IS NULL) = (amount IS NULL)",
                        name="transaction_offsets_expense_check"),
        CheckConstraint("amount > 0", name="transaction_offsets_amount_check"),
        UniqueConstraint("payback_date", "payback_abs_amount", "expense_date", "expense_abs_amount",
                         name="transaction_offsets_link_key"),
    )

    id: int | None = Field(default=None, primary_key=True)
    payback_date: dt.date = Field(index=True)
    payback_abs_amount: Decimal = Field(sa_type=Money)
    expense_date: dt.date | None = Field(default=None, index=True)
    expense_abs_amount: Decimal | None = Field(default=None, sa_type=Money)
    amount: Decimal | None = Field(default=None, sa_type=Money)
    created_at: dt.datetime | None = Field(default=None, sa_column=_now())


class SyncStatus(SQLModel, table=True):
    """Live sync status of one source (sync/activities.py merge_status), one row per source.

    `entry` is the SourceStatus dict exactly as the worker writes it (state, message, times…).
    Every insert/update fires `pg_notify('sync_status', source)` (trigger in migration 0008)
    so the API can stream changes over SSE. Written by the host worker only; `finance_api` can read."""
    __tablename__ = "sync_status"

    source: str = Field(sa_column=Column(Text, primary_key=True))
    entry: dict = Field(sa_column=Column(JSONB, nullable=False))
    updated_at: dt.datetime | None = Field(default=None, sa_column=_now())

class PushSubscription(SQLModel, table=True):
    """A browser's Web Push subscription (the installed PWA), one row per endpoint.

    The API role may only insert and delete these; the sender on the Mac (sync/push.py) reads
    them with the owner connection, stamps `last_success_at` and prunes dead endpoints."""
    __tablename__ = "push_subscriptions"

    id: int | None = Field(default=None, primary_key=True)
    endpoint: str = Field(sa_column=Column(Text, nullable=False, unique=True))
    p256dh: str = Field(sa_column=Column(Text, nullable=False))
    auth: str = Field(sa_column=Column(Text, nullable=False))
    email: str = Field(sa_column=Column(Text, nullable=False))
    user_agent: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    created_at: dt.datetime | None = Field(default=None, sa_column=_now())
    last_success_at: dt.datetime | None = Field(default=None, sa_column=Column(TIMESTAMP(timezone=True), nullable=True))


def _when(**kw):
    return Column(TIMESTAMP(timezone=True), nullable=True, **kw)


class Notification(SQLModel, table=True):
    """One inbox entry: a "לטיפול" action (data/actions.py) the household can read, snooze or archive.

    The action `id` is the key and is period-stable, so the same situation is the same row on
    every digest. The digest (db/inbox.py `sync`) refreshes the content columns and stamps
    `resolved_at` when the action disappears; it never touches `read_at`, `snoozed_until_at`
    or `archived_at`, the household's own state, which `finance_api` may update. Every
    insert/update fires `pg_notify('notifications', id)` (trigger in migration 0009)."""
    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint("category IN ('PROBLEM', 'WARNING', 'REMINDER', 'SUGGESTION', 'INFO')",
                        name="notifications_category_check"),
        CheckConstraint("severity IN ('critical', 'high', 'medium', 'low')", name="notifications_severity_check"),
    )

    id: str = Field(sa_column=Column(Text, primary_key=True))
    type: str = Field(sa_type=Text)                 # camelCase event: limitBreach, budgetOver, ...
    category: str = Field(sa_type=Text)
    severity: str = Field(sa_type=Text)
    title: str = Field(sa_type=Text)
    detail: str | None = Field(default=None, sa_type=Text)
    amount: Decimal | None = Field(default=None, sa_type=Money)
    cta: dict | None = Field(default=None, sa_column=Column(JSONB))       # {label, to}
    subject: dict | None = Field(default=None, sa_column=Column(JSONB))   # {kind, ...}: what it is about
    created_at: dt.datetime | None = Field(default=None, sa_column=_now())   # first produced
    updated_at: dt.datetime | None = Field(default=None, sa_column=_now())   # last produced
    read_at: dt.datetime | None = Field(default=None, sa_column=_when())
    snoozed_until_at: dt.datetime | None = Field(default=None, sa_column=_when())
    archived_at: dt.datetime | None = Field(default=None, sa_column=_when())
    resolved_at: dt.datetime | None = Field(default=None, sa_column=_when())
    pushed_at: dt.datetime | None = Field(default=None, sa_column=_when())   # Web Push sent it (finance/push.py only)

