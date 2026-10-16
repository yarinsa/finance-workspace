"""Which Pydantic model backs each GraphQL object type in api/schema/*.graphql.

The SDL is the source of truth for the API's shape; the models are the source of
truth for the data. `api/tests/test_graphql_schema.py` holds the two together: every
SDL field must map to a model field (camelCase -> snake_case, or an explicit rename)
or be listed as resolved, every model field must be exposed or listed as hidden, and
a non-null SDL field may not sit on an optional model field unless the resolver
guarantees a value (`never_null`). Resolvers read these bindings too.
"""
from dataclasses import dataclass, field
from pathlib import Path

from graphql import build_schema

from finance import models, tables

SCHEMA_DIR = Path(__file__).resolve().parent / "schema"


def load_sdl():
    """All schema files concatenated, in a stable order."""
    return "\n".join(p.read_text() for p in sorted(SCHEMA_DIR.glob("*.graphql")))


def load_schema():
    return build_schema(load_sdl())


@dataclass(frozen=True)
class Binding:
    model: type
    renames: dict[str, str] = field(default_factory=dict)   # SDL field -> model field
    resolved: frozenset[str] = frozenset()                  # SDL fields computed by a resolver
    hidden: frozenset[str] = frozenset()                    # model fields deliberately not exposed
    never_null: frozenset[str] = frozenset()                # optional model fields the resolver fills in


BINDINGS: dict[str, Binding] = {
    "Transaction": Binding(
        models.LedgerTransaction,
        renames={"isCardBillPayment": "card_bill_payment", "isInternalTransfer": "internal_transfer",
                 "isSavings": "savings"},
        resolved=frozenset({"id", "absAmount", "direction", "merchant", "category", "tags", "excluded",
                            "raw", "auditLog"}),
        hidden=frozenset({"category_id", "is_income",   # exposed as `category` and `direction`
                          "horizon_id", "goal_id", "goal"}),   # not in the SDL yet (REST only)
        never_null=frozenset({"card_bill_payment", "internal_transfer", "savings", "overridden"}),
    ),
    "Category": Binding(tables.Category, resolved=frozenset({"id", "source", "transactions", "merchants", "tags"}),
                        hidden=frozenset({"created_at"})),
    "Tag": Binding(tables.Tag, resolved=frozenset({"id", "transactions", "merchants", "categories"}), hidden=frozenset({"created_at"})),
    "AuditEntry": Binding(tables.OverrideAudit, hidden=frozenset({"id", "txn_date", "abs_amount"}),
                          never_null=frozenset({"at"})),   # filled by the database default
    "SnapshotTotals": Binding(models.SnapshotTotals),
    "BankAccount": Binding(models.Account, hidden=frozenset({"currency"})),
    "CreditCard": Binding(models.CreditCard, hidden=frozenset({"currency"})),
    "Loan": Binding(models.Loan, hidden=frozenset({"currency"})),
    "Savings": Binding(models.Savings, hidden=frozenset({"currency", "account_id", "topic_id", "section",
                                                         "policies_count", "work_state"})),
    "IncomeSource": Binding(models.Income, hidden=frozenset({"currency", "detail"})),
}

# Object types with no model behind them: Relay plumbing, payloads, roots, and
# types assembled by resolvers (Merchant is derived from descriptions, not stored).
STRUCTURAL = frozenset({
    "Query", "Mutation", "PageInfo", "Merchant", "RawTransactionValues", "Snapshot",
    "TransactionConnection", "TransactionEdge", "MerchantConnection", "MerchantEdge",
    "CategoryConnection", "CategoryEdge", "TagConnection", "TagEdge", "TransactionTotals",
    "AuditEntryConnection", "AuditEntryEdge",
    "UpdateTransactionPayload", "ClearTransactionOverridePayload", "SetTransactionTagsPayload",
    "UpdateTagPayload", "DeleteTagPayload",
})


def snake(name):
    """camelCase -> snake_case, with digits kept on their word (cardLast4 -> card_last4)."""
    return "".join(f"_{c.lower()}" if c.isupper() else c for c in name)


def model_field(binding, sdl_field):
    """The model field an SDL field reads, or None when a resolver computes it."""
    if sdl_field in binding.resolved:
        return None
    return binding.renames.get(sdl_field, snake(sdl_field))
