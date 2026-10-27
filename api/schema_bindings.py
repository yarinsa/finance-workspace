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


def _notification(*extra):
    """Every notification subtype reads the one `notifications` row; `extra` are its subject's fields."""
    return Binding(tables.Notification, resolved=frozenset({"id", *extra}), hidden=frozenset({"subject", "pushed_at"}),
                   never_null=frozenset({"created_at", "updated_at"}))   # filled by the database default


BINDINGS: dict[str, Binding] = {
    "Transaction": Binding(
        models.LedgerTransaction,
        renames={"isCardBillPayment": "card_bill_payment", "isInternalTransfer": "internal_transfer",
                 "isSavings": "savings", "isRoundTrip": "round_trip"},
        resolved=frozenset({"id", "absAmount", "direction", "merchant", "category", "tags", "excluded",
                            "raw", "auditLog", "horizon", "goal", "offsets", "netAmount", "offsetsManual",
                            "offsetCandidates", "kind", "kindSource"}),
        # exposed as the `category`, `direction`, `horizon` and `goal` objects; the stored
        # offset layers (auto/manual) are exposed resolved, as `offsets` + `offsetsManual`;
        # the category signals (source label, RiseUp envelope, recurring) only feed `category`/`kind`
        hidden=frozenset({"category_id", "is_income", "horizon_id", "goal_id", "auto_offsets", "manual_offsets",
                          "category_group", "source_category", "budget_type", "budget_category", "recurring",
                          "one_off"}),
        never_null=frozenset({"card_bill_payment", "internal_transfer", "savings", "overridden", "round_trip",
                              "offset_amount"}),
    ),
    "Category": Binding(tables.Category, resolved=frozenset({"id", "source", "transactions", "merchants", "tags", "horizons",
                                                             "goals", "group", "kind"}),
                        hidden=frozenset({"created_at", "group_id", "position"})),
    "Tag": Binding(tables.Tag, resolved=frozenset({"id", "transactions", "merchants", "categories", "horizons",
                                                   "goals"}), hidden=frozenset({"created_at"})),
    "AuditEntry": Binding(tables.OverrideAudit, hidden=frozenset({"id", "txn_date", "abs_amount"}),
                          never_null=frozenset({"at"})),   # filled by the database default
    "Horizon": Binding(tables.Horizon, resolved=frozenset({"id", "key", "transactions", "goals", "merchants",
                                                           "categories", "tags"}),
                       hidden=frozenset({"created_at"})),
    "Goal": Binding(tables.Goal, resolved=frozenset({"id", "interval", "horizon", "transactions", "merchants",
                                                     "categories", "tags"}),
                    hidden=frozenset({"created_at", "horizon_id"})),
    "Asset": Binding(tables.Asset, resolved=frozenset({"id", "kind", "valuationSource"}),
                     hidden=frozenset({"created_at"}),
                     never_null=frozenset({"updated_at"})),   # filled by the database default
    "SnapshotTotals": Binding(models.SnapshotTotals),
    "BankAccount": Binding(models.Account, hidden=frozenset({"currency"})),
    "CreditCard": Binding(models.CreditCard, hidden=frozenset({"currency"})),
    "Loan": Binding(models.Loan, hidden=frozenset({"currency"})),
    "Savings": Binding(models.Savings, hidden=frozenset({"currency", "account_id", "topic_id", "section",
                                                         "policies_count", "work_state"})),
    "IncomeSource": Binding(models.Income, hidden=frozenset({"currency", "detail"})),
    "CashflowNotification": _notification("date"),
    "BudgetNotification": _notification("budgetCategories", "cycleStart"),
    "BillNotification": _notification("billName", "dueDate"),
    "ServiceNotification": _notification("services"),
    "SyncNotification": _notification("sources"),
    "TransactionNotification": _notification("transaction"),
    "GenericNotification": _notification(),
}

# Object types with no model behind them: Relay plumbing, payloads, roots, and
# types assembled by resolvers (Merchant is derived from descriptions, not stored).
STRUCTURAL = frozenset({
    "Query", "Mutation", "PageInfo", "Merchant", "RawTransactionValues", "Snapshot",
    "TransactionConnection", "TransactionEdge", "MerchantConnection", "MerchantEdge",
    "CategoryConnection", "CategoryEdge", "TagConnection", "TagEdge", "TransactionTotals",
    "HorizonConnection", "HorizonEdge", "GoalConnection", "GoalEdge",
    "GoalPayload", "DeletePayload", "PlanTargets", "PlanTargetsPayload", "AssetPayload",
    "AssetConnection", "AssetEdge",
    "AuditEntryConnection", "AuditEntryEdge",
    "UpdateTransactionPayload", "ClearTransactionOverridePayload", "SetTransactionTagsPayload",
    "UpdateTagPayload", "DeleteTagPayload",
    "Offset", "OffsetPayload", "ResetOffsetsPayload",
    "NotificationAction", "NotificationConnection", "NotificationEdge", "NotificationPayload",
    "BulkNotificationPayload",
    "SyncSource", "SyncSourceConnection", "SyncSourceEdge", "SyncSourcePayload",   # a sync_status JSON entry
})


def snake(name):
    """camelCase -> snake_case, with digits kept on their word (cardLast4 -> card_last4)."""
    return "".join(f"_{c.lower()}" if c.isupper() else c for c in name)


def model_field(binding, sdl_field):
    """The model field an SDL field reads, or None when a resolver computes it."""
    if sdl_field in binding.resolved:
        return None
    return binding.renames.get(sdl_field, snake(sdl_field))
