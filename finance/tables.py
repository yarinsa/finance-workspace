"""Postgres tables for the transactions database, as SQLModel models.

This is the schema's source of truth: Alembic (db/migrations) autogenerates from
`SQLModel.metadata`, and db/tests/test_schema.py fails if the migrated database
and these classes disagree. Columns pulled out of a ledger row are typed from
`finance.models.LedgerTransaction`; the full row is kept in `record`.

The `transactions`, `transaction_kinds`, `orphaned_overrides`, `orphaned_tags` and `orphaned_offsets` views are plain SQL in the migrations.
"""
import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import ARRAY, BigInteger, CheckConstraint, Column, ForeignKey, ForeignKeyConstraint, Index, PrimaryKeyConstraint, Integer, Numeric, SmallInteger, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlmodel import Field, Relationship, SQLModel

from finance import models
from finance.models import AccountFields, BalanceDayFields, CreditCardFields, LoanFields, MoneySQL, SavingsFields

Money = MoneySQL


def _now():
    return Column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))


def _tenant(primary_key=False, index=False):
    """The owning tenant. The default reads `app.tenant_id` (finance/tenancy.py `bind`), so an
    insert lands in the bound tenant and fails when none is bound. RLS (migration 0017) filters on it."""
    return Column(UUID(as_uuid=True), ForeignKey("tenants.id"), primary_key=primary_key, index=index,
                  nullable=False, server_default=text("current_setting('app.tenant_id')::uuid"))


def _category_fk():
    return Column(Integer, ForeignKey("categories.id", ondelete="SET NULL"), nullable=True, index=True)


def _fk(table):
    return Column(Integer, ForeignKey(f"{table}.id", ondelete="SET NULL"), nullable=True, index=True)


class User(SQLModel, table=True):
    """A person who can sign in (global: one user can belong to several tenants). Keyed by the
    verified, lower-cased Cognito email."""
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("email = lower(email)", name="users_email_lower"),
                      UniqueConstraint("email", name="users_email_key"))

    id: uuid.UUID | None = Field(default=None, sa_column=Column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")))
    email: str = Field(sa_type=Text)
    created_at: dt.datetime | None = Field(default=None, sa_column=_now())


class Tenant(SQLModel, table=True):
    """One household / customer. Every customer-data row belongs to exactly one."""
    __tablename__ = "tenants"
    __table_args__ = (CheckConstraint("status IN ('active', 'suspended')", name="tenants_status_check"),
                      UniqueConstraint("slug", name="tenants_slug_key"))

    id: uuid.UUID | None = Field(default=None, sa_column=Column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")))
    name: str = Field(sa_type=Text)
    slug: str = Field(sa_type=Text)
    status: str = Field(default="active", sa_column=Column(Text, nullable=False, server_default="active"))
    created_at: dt.datetime | None = Field(default=None, sa_column=_now())
    updated_at: dt.datetime | None = Field(default=None, sa_column=_now())


class Membership(SQLModel, table=True):
    """A user's role in a tenant (owner | admin | member)."""
    __tablename__ = "memberships"
    __table_args__ = (CheckConstraint("role IN ('owner', 'admin', 'member')", name="memberships_role_check"),
                      UniqueConstraint("tenant_id", "user_id", name="memberships_tenant_user_key"))

    id: uuid.UUID | None = Field(default=None, sa_column=Column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")))
    tenant_id: uuid.UUID = Field(sa_column=Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
                                                  nullable=False))
    user_id: uuid.UUID = Field(sa_column=Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
                                                nullable=False, index=True))
    role: str = Field(sa_type=Text)
    created_at: dt.datetime | None = Field(default=None, sa_column=_now())


class Horizon(SQLModel, table=True):
    """Who a shekel out is for: current me, near-future me, future me (data/horizons.py).

    A fixed list seeded by migration 0006; `key` is the stable code the ledger and API
    use, `name` the label and `target_pct` the share of net income aimed for."""
    __tablename__ = "horizons"
    __table_args__ = (UniqueConstraint("tenant_id", "key", name="horizons_key_key"),)

    tenant_id: uuid.UUID = Field(sa_column=_tenant())
    id: int | None = Field(default=None, primary_key=True)
    key: str = Field(sa_column=Column(Text, nullable=False))
    name: str = Field(sa_type=Text)
    target_pct: Decimal = Field(sa_type=Numeric(5, 2))
    position: int = Field(default=0)
    created_at: dt.datetime | None = Field(default=None, sa_column=_now())

    scraped_transactions: list["ScrapedTransaction"] = Relationship(back_populates="horizon_ref")
    overrides: list["TransactionOverride"] = Relationship(back_populates="horizon_ref")
    goals: list["Goal"] = Relationship(back_populates="horizon_ref")


class Goal(SQLModel, table=True):
    """A savings goal (docs/plangram-prd/04-goals.md), assigned to a horizon.

    `key` marks one of the household's three defaults (emergency_fund, inheritance, retirement:
    the former `plan_targets`); they are edited and hidden, never deleted. amount 0 on a default
    = unset. `projected_amount` / `projection_source`: what the goal is expected to reach, and
    where that figure came from (empty until the projection logic exists).

    Was data/goals/goals.json's `goals` list; `slug` keeps that store's string id."""
    __tablename__ = "goals"
    __table_args__ = (UniqueConstraint("tenant_id", "slug", name="goals_slug_key"),
                      CheckConstraint("key IS NULL OR key IN ('emergency_fund', 'inheritance', 'retirement')",
                                      name="goals_key_check"),
                      Index("goals_tenant_key_key", "tenant_id", "key", unique=True,
                            postgresql_where=text("key IS NOT NULL")))

    tenant_id: uuid.UUID = Field(sa_column=_tenant())
    id: int | None = Field(default=None, primary_key=True)
    slug: str = Field(sa_column=Column(Text, nullable=False))
    description: str = Field(sa_type=Text)
    amount: Decimal = Field(sa_type=Money)
    start_date: dt.date | None = None
    end_date: dt.date | None = None
    interval: str | None = Field(default=None, sa_type=Text)
    repetitions: int = Field(default=1)
    rise: Decimal = Field(default=Decimal(0), sa_type=Money)
    from_asset_id: str | None = Field(default=None, sa_type=Text)
    horizon_id: int | None = Field(default=None, sa_column=_fk("horizons"))
    key: str | None = Field(default=None, sa_type=Text)
    hidden: bool = Field(default=False)
    projected_amount: Decimal | None = Field(default=None, sa_type=Money)
    projection_source: str | None = Field(default=None, sa_type=Text)
    created_at: dt.datetime | None = Field(default=None, sa_column=_now())

    horizon_ref: Horizon | None = Relationship(back_populates="goals")
    overrides: list["TransactionOverride"] = Relationship(back_populates="goal_ref")


class BudgetLine(SQLModel, table=True):
    """The household's planned monthly amount for one category (data/budgets.py).

    Was data/budgets/budgets.json (`{category: amount}`). `category` is the category name as
    the budget uses it, not a foreign key: a line may name a category the ledger has not
    seen yet, and merges are applied when the budget is built (budgets.fold_merges)."""
    __tablename__ = "budget_lines"

    tenant_id: uuid.UUID = Field(sa_column=_tenant(primary_key=True))
    category: str = Field(sa_column=Column(Text, primary_key=True))
    amount: Decimal = Field(sa_type=Money)
    updated_at: dt.datetime | None = Field(default=None, sa_column=_now())


class HoldingAssignment(SQLModel, table=True):
    """Where a savings holding (pension, study fund, deposit) belongs, set by hand.

    A holding is an asset from the snapshot, not a ledger row, so it has no table of its own:
    `holding_id` is the app's id for it (`institution:topic_id`, else the label). The horizon a
    holding falls in is otherwise derived from its liquidity date; a row here overrides that.
    A row with neither field set is deleted (db/holding_store.py)."""
    __tablename__ = "holding_assignments"

    tenant_id: uuid.UUID = Field(sa_column=_tenant(primary_key=True))
    holding_id: str = Field(sa_column=Column(Text, primary_key=True))
    horizon_id: int | None = Field(default=None, sa_column=_fk("horizons"))
    goal_id: int | None = Field(default=None, sa_column=_fk("goals"))
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
    yet is kept as a `riseup` row (no group); a name first typed by hand is `user`.
    `merged_into_id` folds it into another category (`transaction_kinds` resolves it)."""
    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="categories_name_key"), CheckConstraint("source IN ('builtin', 'riseup', 'user')", name="categories_source_check"),
                      CheckConstraint(KIND_CHECK, name="categories_kind_check"))

    tenant_id: uuid.UUID = Field(sa_column=_tenant())
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(sa_column=Column(Text, nullable=False))
    source: str = Field(sa_column=Column(Text, nullable=False, server_default="user"))
    created_at: dt.datetime | None = Field(default=None, sa_column=_now())
    group_id: int | None = Field(default=None, sa_column=_fk("category_groups"))
    kind: str | None = Field(default=None, sa_type=Text)   # default kind; null = not an expense category
    usage_based: bool = Field(default=False, sa_column_kwargs={"server_default": text("false")})
    position: int = Field(default=0, sa_column_kwargs={"server_default": text("0")})
    # Merged by hand into another category (the app's "מיזוג"): its rows count as that one.
    merged_into_id: int | None = Field(default=None, sa_column=_fk("categories"))

    group_ref: CategoryGroup | None = Relationship(back_populates="categories")
    scraped_transactions: list["ScrapedTransaction"] = Relationship(back_populates="category_ref")
    overrides: list["TransactionOverride"] = Relationship(back_populates="category_ref")
    merchant_rules: list["MerchantRule"] = Relationship(back_populates="category_ref")


class MerchantRule(SQLModel, table=True):
    """Human layer, per merchant: every transaction of `merchant` (finance/merchants.py
    key, the ledger row's `merchant`) gets this category and/or kind, unless that
    transaction has its own override. Kept forever, like transaction_overrides."""
    __tablename__ = "merchant_rules"
    __table_args__ = (UniqueConstraint("tenant_id", "merchant", name="merchant_rules_merchant_key"), CheckConstraint(KIND_CHECK, name="merchant_rules_kind_check"),)

    tenant_id: uuid.UUID = Field(sa_column=_tenant())
    id: int | None = Field(default=None, primary_key=True)
    merchant: str = Field(sa_column=Column(Text, nullable=False))
    category_id: int | None = Field(default=None, sa_column=_category_fk())
    kind: str | None = Field(default=None, sa_type=Text)
    created_at: dt.datetime | None = Field(default=None, sa_column=_now())
    updated_at: dt.datetime | None = Field(default=None, sa_column=_now())

    category_ref: Category | None = Relationship(back_populates="merchant_rules")


class ScrapedTransaction(SQLModel, table=True):
    """Machine layer: the digested ledger, replaced in full on each import."""
    __tablename__ = "scraped_transactions"
    __table_args__ = (Index("ix_scraped_transactions_tenant_date", "tenant_id", "txn_date"),)

    tenant_id: uuid.UUID = Field(sa_column=_tenant(primary_key=True))
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
        "primaryjoin": "and_(ScrapedTransaction.tenant_id == foreign(TransactionTag.tenant_id), "
                       "ScrapedTransaction.txn_date == foreign(TransactionTag.txn_date), "
                       "ScrapedTransaction.abs_amount == foreign(TransactionTag.abs_amount))",
        "secondaryjoin": "Tag.id == foreign(TransactionTag.tag_id)"})


class TransactionOverride(SQLModel, table=True):
    """Human layer: sparse edits, kept forever. Null falls through to the scraped value."""
    __tablename__ = "transaction_overrides"
    __table_args__ = (
        CheckConstraint("abs_amount >= 0", name="transaction_overrides_abs_amount_check"),
        CheckConstraint(KIND_CHECK, name="transaction_overrides_kind_check"),
    )

    tenant_id: uuid.UUID = Field(sa_column=_tenant(primary_key=True))
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

    tenant_id: uuid.UUID = Field(sa_column=_tenant(index=True))
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
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="tags_name_key"),)

    tenant_id: uuid.UUID = Field(sa_column=_tenant())
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(sa_column=Column(Text, nullable=False))
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

    tenant_id: uuid.UUID = Field(sa_column=_tenant(primary_key=True))
    txn_date: dt.date = Field(primary_key=True)
    abs_amount: Decimal = Field(primary_key=True, sa_type=Money)
    tag_id: int = Field(sa_column=Column(Integer, ForeignKey("tags.id", ondelete="CASCADE"),
                                         primary_key=True, index=True))
    created_at: dt.datetime | None = Field(default=None, sa_column=_now())

    tag_ref: Tag = Relationship(back_populates="links")
    transaction: ScrapedTransaction | None = Relationship(sa_relationship_kwargs={
        "viewonly": True,
        "primaryjoin": "and_(foreign(TransactionTag.tenant_id) == ScrapedTransaction.tenant_id, "
                       "foreign(TransactionTag.txn_date) == ScrapedTransaction.txn_date, "
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
        UniqueConstraint("tenant_id", "payback_date", "payback_abs_amount", "expense_date", "expense_abs_amount",
                         name="transaction_offsets_link_key"),
    )

    tenant_id: uuid.UUID = Field(sa_column=_tenant())
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
    __table_args__ = (UniqueConstraint("tenant_id", "endpoint", name="push_subscriptions_endpoint_key"),)

    tenant_id: uuid.UUID = Field(sa_column=_tenant())
    id: int | None = Field(default=None, primary_key=True)
    endpoint: str = Field(sa_column=Column(Text, nullable=False))
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

    tenant_id: uuid.UUID = Field(sa_column=_tenant(primary_key=True))
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



class Asset(SQLModel, table=True):
    """Something the household owns that no scraper sees: the apartment, for now.

    The value is typed in by hand (`valuation_source` 'manual'); an automatic estimate will
    write 'estimate' later. The digest adds the property value to `snapshot.totals`
    (`property_value`, `net_worth_with_property`). `finance_api` may read, add and edit."""
    __tablename__ = "assets"
    __table_args__ = (
        CheckConstraint("kind IN ('property')", name="assets_kind_check"),
        CheckConstraint("valuation_source IN ('manual', 'estimate')", name="assets_valuation_source_check"),
    )

    tenant_id: uuid.UUID = Field(sa_column=_tenant(index=True))
    id: int | None = Field(default=None, primary_key=True)
    kind: str = Field(sa_type=Text)
    label: str = Field(sa_type=Text)
    value: Decimal = Field(sa_type=Money)
    valued_at: dt.date
    valuation_source: str = Field(default="manual", sa_type=Text)
    created_at: dt.datetime | None = Field(default=None, sa_column=_now())
    updated_at: dt.datetime | None = Field(default=None, sa_column=_now())


class PositionSnapshot(SQLModel, table=True):
    """The household's position on one day, recorded by every digest (data/history.py).

    One row per date, overwritten by later digests the same day. This is the only
    record of how net worth moved over time: scraped sources only know today."""
    __tablename__ = "position_snapshots"

    tenant_id: uuid.UUID = Field(sa_column=_tenant(primary_key=True))
    date: dt.date = Field(primary_key=True)
    cash: Decimal = Field(sa_type=Money)              # bank_balances_sum
    card_debt: Decimal = Field(sa_type=Money)
    consumer_loans: Decimal = Field(sa_type=Money)
    mortgage: Decimal = Field(sa_type=Money)
    savings: Decimal = Field(sa_type=Money)           # long_term_savings (liquid + illiquid)
    property: Decimal | None = Field(default=None, sa_type=Money)
    net_worth: Decimal = Field(sa_type=Money)         # incl. savings and property
    recorded_at: dt.datetime | None = Field(default=None, sa_column=_now())


# The machine layer of the headline position: the reconciled scraped entities, replaced in full
# by every digest in the same transaction as `scraped_transactions` (db/ledger.py `load`). The
# columns are the entity's `*Fields` list from finance/models.py; a row adds the tenant and key.
# Totals are not stored: finance/views/snapshot.py computes them from these rows.

class DigestRun(SQLModel, table=True):
    """One digest that reached the database. The newest `finished_at` is the data's as-of time."""
    __tablename__ = "digest_runs"
    __table_args__ = (PrimaryKeyConstraint("tenant_id", "id"),)

    tenant_id: uuid.UUID = Field(sa_column=_tenant(primary_key=True))
    id: int | None = Field(default=None, sa_column=Column(Integer, primary_key=True, autoincrement=True))
    started_at: dt.datetime = Field(sa_type=TIMESTAMP(timezone=True))
    finished_at: dt.datetime | None = Field(default=None, sa_column=_now())
    normalized: bool                    # False for --no-normalize (the dumps were not re-read)
    transactions: int                   # ledger rows imported


class AccountRow(AccountFields, table=True):
    """A bank account, one per institution (the direct scrape beats RiseUp's copy)."""
    __tablename__ = "accounts"
    __table_args__ = (PrimaryKeyConstraint("tenant_id", "institution", "account_id"),)

    tenant_id: uuid.UUID = Field(sa_column=_tenant(primary_key=True))
    institution: str = Field(primary_key=True)
    account_id: str = Field(primary_key=True)


class CreditCardRow(CreditCardFields, table=True):
    """A card with money owed: the issuer's own next charge, else RiseUp's figure."""
    __tablename__ = "credit_cards"
    __table_args__ = (PrimaryKeyConstraint("tenant_id", "issuer", "last4"),)

    tenant_id: uuid.UUID = Field(sa_column=_tenant(primary_key=True))
    issuer: str = Field(primary_key=True)
    last4: str = Field(primary_key=True)
    owed: models.Money                  # required here: a card without money owed is not stored
    next_charge_date: dt.date | None = None


class LoanRow(LoanFields, table=True):
    """A loan or mortgage track. `loan_id` can be missing, so the key is the digest's order."""
    __tablename__ = "loans"
    __table_args__ = (PrimaryKeyConstraint("tenant_id", "position"),)

    tenant_id: uuid.UUID = Field(sa_column=_tenant(primary_key=True))
    position: int = Field(primary_key=True)


class SavingsRow(SavingsFields, table=True):
    """A savings holding (pension, study fund, gemel, deposit): an asset, never cashflow.
    `holding_id` (models.holding_id) is the key `holding_assignments` joins on, without an FK:
    this row is replaced by every digest, the assignment is kept forever."""
    __tablename__ = "savings_holdings"
    __table_args__ = (PrimaryKeyConstraint("tenant_id", "holding_id"),)

    tenant_id: uuid.UUID = Field(sa_column=_tenant(primary_key=True))
    holding_id: str = Field(primary_key=True)


class BalanceDayRow(BalanceDayFields, table=True):
    """A checking account's measured end-of-day balance (the `balance_days` entity), replaced by every
    digest: what history's cash line reads instead of the banks' raw running-balance chains."""
    __tablename__ = "account_balance_days"
    __table_args__ = (PrimaryKeyConstraint("tenant_id", "institution", "account_id", "date"),)

    tenant_id: uuid.UUID = Field(sa_column=_tenant())


class SourceDump(SQLModel, table=True):
    """A scraped source's latest dump on disk: when the scraper last wrote, and how far its data reaches."""
    __tablename__ = "source_dumps"
    __table_args__ = (PrimaryKeyConstraint("tenant_id", "source"),)

    tenant_id: uuid.UUID = Field(sa_column=_tenant(primary_key=True))
    source: str = Field(primary_key=True)
    dumped_at: dt.datetime = Field(sa_type=TIMESTAMP(timezone=True))   # newest raw file's mtime
    raw_files: int
    latest_txn_date: dt.date | None = None


class SourceDumpEntity(SQLModel, table=True):
    """How many records of one entity a source's normalized output holds."""
    __tablename__ = "source_dump_entities"
    __table_args__ = (
        PrimaryKeyConstraint("tenant_id", "source", "entity"),
        ForeignKeyConstraint(["tenant_id", "source"], ["source_dumps.tenant_id", "source_dumps.source"],
                             ondelete="CASCADE"),)

    tenant_id: uuid.UUID = Field(sa_column=_tenant(primary_key=True))
    source: str = Field(primary_key=True)
    entity: str = Field(primary_key=True)
    records: int


# Hand-kept inputs that lived in side files (docs/json-to-db-migration.md, phase 2). Human layer:
# kept forever, never truncated by a digest. Months are stored as their first day.

class OffsetRule(SQLModel, table=True):
    """A household קיזוז rule: transfers from `payer` pay back expenses matching `against`
    (finance/offsets.py `suggest`), e.g. a roommate's share of the rent. Was data/offsets/rules.json."""
    __tablename__ = "offset_rules"
    __table_args__ = (PrimaryKeyConstraint("tenant_id", "id"),)

    tenant_id: uuid.UUID = Field(sa_column=_tenant())
    id: int | None = Field(default=None, sa_column=Column(Integer, autoincrement=True, nullable=False))
    payer: str = Field(sa_type=Text)
    against: list[str] = Field(sa_column=Column(ARRAY(Text), nullable=False))
    note: str | None = Field(default=None, sa_type=Text)
    created_at: dt.datetime | None = Field(default=None, sa_column=_now())


class MortgageSchedulePeriod(SQLModel, table=True):
    """One band of the bank's amortization schedule (לוח סילוקין): the installment from `from_month`
    through `to_month`. Was data/mortgage_schedule.json."""
    __tablename__ = "mortgage_schedule_periods"
    __table_args__ = (PrimaryKeyConstraint("tenant_id", "from_month"),
                      CheckConstraint("to_month >= from_month", name="mortgage_schedule_periods_order"))

    tenant_id: uuid.UUID = Field(sa_column=_tenant())
    from_month: dt.date
    to_month: dt.date
    payment: Decimal = Field(sa_type=Money)
    source: str | None = Field(default=None, sa_type=Text)   # where the band came from (the PDF, its date)


class LoanFreeze(SQLModel, table=True):
    """A user-confirmed mortgage freeze on one track (data/detect_freeze.py): the frozen installment
    until `resume_month`, then `resume_payment`. Deleted when the freeze is over. Was data/freeze.json."""
    __tablename__ = "loan_freezes"
    __table_args__ = (PrimaryKeyConstraint("tenant_id", "loan_id"),)

    tenant_id: uuid.UUID = Field(sa_column=_tenant())
    loan_id: str = Field(sa_type=Text)                 # the track's LoanAccount in the mortgage dump
    frozen_payment: Decimal = Field(sa_type=Money)
    resume_month: dt.date
    resume_payment: Decimal = Field(sa_type=Money)
    note: str | None = Field(default=None, sa_type=Text)
    detected_at: dt.datetime | None = Field(default=None, sa_column=_now())


class HouseholdSettings(SQLModel, table=True):
    """The household's own settings, one row per tenant. `cycle_start_day` is the day the budget
    cycle (budgets, bills) starts; imported once from RiseUp's `cashflowStartDay`."""
    __tablename__ = "household_settings"
    __table_args__ = (CheckConstraint("cycle_start_day BETWEEN 1 AND 31", name="household_settings_cycle_day"),)

    tenant_id: uuid.UUID = Field(sa_column=_tenant(primary_key=True))
    cycle_start_day: int | None = Field(default=None, sa_type=SmallInteger)
    updated_at: dt.datetime | None = Field(default=None, sa_column=_now())
