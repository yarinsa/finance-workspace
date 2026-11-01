"""Pydantic models for every normalized entity and the digested ledger row.

These are the one definition of what the pipeline writes: each `normalize.py`
validates its records through `write_envelope`, and `finance/tables.py` builds the
Postgres tables from `LedgerTransaction`, so the JSON and the schema cannot drift.

Records are `extra="forbid"`: a new field must be declared here first.
"""
import datetime as dt
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, PlainSerializer
from sqlalchemy import Numeric
from sqlmodel import Field, SQLModel


def _date(v):
    """Accept ISO dates, ISO datetimes and Discount's compact YYYYMMDD; "" is no date."""
    if v == "":
        return None
    if isinstance(v, str):
        if re.fullmatch(r"\d{8}", v):
            return f"{v[:4]}-{v[4:6]}-{v[6:]}"
        if "T" in v:
            return v.split("T", 1)[0]
    return v


Date = Annotated[dt.date, BeforeValidator(_date)]
OptDate = Annotated[dt.date | None, BeforeValidator(_date)]


def _money(v):
    """Decimal from float/int/str via its text, so 0.1 stays 0.1 (Decimal(0.1) would not)."""
    if isinstance(v, Decimal):
        return v
    try:
        return Decimal(str(v))
    except InvalidOperation:
        raise ValueError(f"not an amount: {v!r}") from None


# The SQL type of every money column; `Money` carries it, finance/tables.py reuses it.
MoneySQL = Numeric(12, 2)

# Decimal in Python, JSON float in `mode="json"` dumps (so normalized/*.json stay byte-identical),
# and `sa_type` tells SQLModel table classes to make the column Numeric(12, 2).
Money = Annotated[
    Decimal,
    BeforeValidator(_money),
    PlainSerializer(float, return_type=float, when_used="json"),
    Field(sa_type=MoneySQL),
]

# Optional money: the sa_type has to sit outside the union or SQLModel does not see it.
OptMoney = Annotated[Money | None, Field(sa_type=MoneySQL)]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Transaction(Record):
    """Money out is negative, income/refunds positive."""
    date: Date
    amount: float
    currency: str = "ILS"
    description: str = ""
    id: str | None = None
    account_id: str | None = None
    account_type: str | None = None
    origin: str | None = None
    category: str | None = None
    processed_date: OptDate = None
    billing_date: OptDate = None
    status: str | None = None
    balance_after: float | None = None
    card_last4: str | None = None
    card_name: str | None = None
    original_amount: float | None = None
    original_currency: str | None = None
    installments: int | None = None
    is_abroad: bool | None = None
    is_income: bool | None = None
    excluded: bool | None = None
    budget_type: str | None = None       # riseup: envelope type (fixed / trackingCategory / variable)
    budget_category: str | None = None   # riseup: tracking envelope name, the household's budget line


# Each scraped entity's fields are declared once, in a `*Fields` base (SQLModel without
# table=True is a Pydantic model). The normalized record adds `extra="forbid"` and the
# envelope-only `currency`; the table row in finance/tables.py adds the tenant and its key.

class AccountFields(SQLModel):
    institution: str
    account_id: str
    kind: str
    balance: Money
    label: str | None = None
    available_balance: OptMoney = None
    overdraft_limit: OptMoney = None


class Account(AccountFields, Record):
    currency: str = "ILS"


class CreditCardFields(SQLModel):
    issuer: str
    last4: str
    name: str | None = None
    holder: str | None = None
    active: bool | None = None
    owed: OptMoney = None


class CreditCard(CreditCardFields, Record):
    currency: str = "ILS"


class LoanFields(SQLModel):
    lender: str
    loan_id: str | None
    name: str | None
    category: str
    balance: Money
    original_amount: OptMoney = None
    rate_pct: float | None = None
    rate_type: str | None = None
    index_linked: bool | None = None
    payments_remaining: int | None = None
    payments_total: int | None = None
    monthly_payment: OptMoney = None
    final_date: OptDate = None


class Loan(LoanFields, Record):
    currency: str = "ILS"


class SavingsFields(SQLModel):
    """Pension / study fund / gemel balance: an asset, never a transaction."""
    institution: str
    kind: str
    balance: Money
    label: str | None = None
    account_id: str | None = None
    topic_id: str | None = None
    section: str | None = None
    policies_count: int | None = None
    work_state: str | None = None
    liquid: bool | None = None
    liquidity_date: OptDate = None
    maturity_date: OptDate = None
    as_of: OptDate = None
    management_fee: float | None = None
    yield_ytd: float | None = None


class Savings(SavingsFields, Record):
    currency: str = "ILS"


def holding_id(s):
    """A savings holding's stable id, `institution:topic_id` else the label. The app
    (savingsView.holdingId) and `holding_assignments` key on the same string."""
    return f"{s['institution']}:{s['topic_id'] if s.get('topic_id') is not None else s.get('label')}"


ENTITIES: dict[str, type[Record]] = {
    "transactions": Transaction,
    "accounts": Account,
    "credit_cards": CreditCard,
    "loans": Loan,
    "savings": Savings,
}


class OffsetLink(Record):
    """One side of a קיזוז: the other transaction (by ledger key) and the ₪ netted.

    On a payback it names an expense; on an expense, the payback. `amount` is the
    positive share of money netted out, at most either row's magnitude."""
    date: Date
    abs_amount: float
    amount: float
    kind: Literal["refund", "rule", "manual"]
    description: str | None = None


class LedgerTransaction(Record):
    """One row of data/digested/transactions.json (and `scraped_transactions.record`)."""
    date: Date
    amount: float
    description: str = ""
    sources: list[str] = []
    origin: str | None = None
    category: str | None = None      # finance/categories.py default; overridable
    category_id: int | None = None   # set by the transactions view: id in the `categories` table
    category_group: str | None = None   # the category's group name (דיור, תחבורה, ...)
    source_category: str | None = None  # RiseUp's raw `expense` label, as scraped
    budget_type: str | None = None      # RiseUp envelope type it was reconciled into
    budget_category: str | None = None  # RiseUp tracking envelope name
    merchant: str | None = None         # finance/merchants.py key; merchant rules match on it
    kind: Literal["fixed", "variable"] | None = None   # expenses only: קבוע / משתנה
    kind_source: Literal["manual", "rule", "merchant", "recurring", "one_off", "riseup", "category"] | None = None
    recurring: bool | None = None       # same merchant + amount in >=3 months (categories.stamp_recurring)
    one_off: bool | None = None         # the merchant recurs but this charge is not the recurring one
    tags: list[str] | None = None    # set by the transactions view: names from `transaction_tags`, sorted
    is_income: bool | None = None
    account_id: str | None = None
    card_last4: str | None = None
    card_bill_payment: bool | None = None
    internal_transfer: bool | None = None
    savings: bool | None = None
    horizon: Literal["current", "near", "future"] | None = None   # data/horizons.py default; overridable
    horizon_id: int | None = None    # set by the transactions view: id in the `horizons` table
    goal_id: int | None = None       # set by the transactions view: the goal this money went to
    goal: str | None = None          # ... and that goal's description
    # set by the transactions view when a manual override applies
    note: str | None = None
    overridden: bool | None = None
    # offsets (finance/offsets.py): a payback netted against the expense it pays back
    round_trip: bool | None = None                    # one leg of a PayBox load + cash-out
    auto_offsets: list[OffsetLink] | None = None      # digest's suggestion, on a payback
    manual_offsets: list[OffsetLink] | None = None    # db transaction_offsets, on a payback ([] = none)
    offsets: list[OffsetLink] | None = None           # the effective links, on both sides
    offset_amount: float | None = None                # ₪ netted out of this row (positive)


class SnapshotTotals(BaseModel):
    """`totals` in data/digested/snapshot.json (written by digest.py)."""
    bank_balances_sum: float
    credit_card_debt: float
    mortgage_balance: float
    consumer_loan_balance: float
    total_debt: float
    tracked_net_position: float          # liquid position vs debt; excludes savings
    long_term_savings: float
    liquid_savings: float
    illiquid_savings: float
    net_position_with_savings: float
    property_value: float | None = None          # the apartment, typed in by hand (assets table)
    net_worth_with_property: float | None = None
    monthly_loan_service: float


def validate_records(entity, records):
    """Validate dict records as `entity`; returns JSON-ready dicts (unset fields omitted)."""
    model = ENTITIES[entity]
    return [model.model_validate(r).model_dump(mode="json", exclude_unset=True) for r in records]


def write_envelope(out_dir: Path, source, entity, generated_at, records):
    """Validate and write one `{source, entity, generated_at, records}` envelope."""
    path = Path(out_dir) / f"{entity}.json"
    path.write_text(json.dumps(
        {"source": source, "entity": entity, "generated_at": generated_at,
         "records": validate_records(entity, records)},
        ensure_ascii=False, indent=2))
    print(f"  {source}/{path.name}: {len(records)} records")
    return path
