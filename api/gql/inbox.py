"""A notification as GraphQL resolvers see it: one inbox row (db/inbox.py) plus the subtype its subject picks.

The SDL has one object type per kind of subject (`BudgetNotification`, `SyncNotification`, …)
so a client can ask `... on BudgetNotification { budgetCategories }`. The row stores the
subject as the jsonb `{kind, ...}` the digest wrote (data/actions.py); the kind-specific
SDL fields read it from here and are null or empty when the subject lacks them.
"""
import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from .ledger import CENT

EPOCH = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)
SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}
GENERIC = "GenericNotification"
KIND_TYPES = {"cashflow": "CashflowNotification", "budget": "BudgetNotification", "bill": "BillNotification",
              "service": "ServiceNotification", "sync": "SyncNotification",
              "transaction": "TransactionNotification"}
TYPENAMES = (*KIND_TYPES.values(), GENERIC)


def _date(v):
    return dt.date.fromisoformat(v[:10]) if v else None


@dataclass(frozen=True)
class Notification:
    id: str
    type: str
    category: str
    severity: str
    title: str
    detail: str | None
    amount: Decimal | None
    cta: dict | None
    subject: dict | None
    created_at: dt.datetime
    updated_at: dt.datetime
    read_at: dt.datetime | None
    snoozed_until_at: dt.datetime | None
    archived_at: dt.datetime | None
    resolved_at: dt.datetime | None

    @classmethod
    def from_row(cls, row):
        return cls(**row)

    @property
    def TYPENAME(self):
        return KIND_TYPES.get((self.subject or {}).get("kind"), GENERIC)

    @property
    def sort_key(self):
        """Most severe first, then most recently updated, then id: unique, so a safe cursor."""
        return (SEVERITY_RANK[self.severity], -((self.updated_at - EPOCH) // dt.timedelta(microseconds=1)), self.id)

    # --- fields of the subject kinds -------------------------------------------------------

    def _s(self, key, default=None):
        return (self.subject or {}).get(key, default)

    @property
    def date(self):
        return _date(self._s("date"))

    @property
    def budget_categories(self):
        return self._s("categories", [])

    @property
    def cycle_start(self):
        return _date(self._s("cycle_start"))

    @property
    def bill_name(self):
        return self._s("name")

    @property
    def due_date(self):
        return _date(self._s("due_date"))

    @property
    def services(self):
        return self._s("services", [])

    @property
    def sources(self):
        return self._s("sources", [])

    @property
    def transaction_key(self):
        """The ledger key of a transaction subject, or None."""
        d, a = self._s("date"), self._s("abs_amount")
        return (_date(d), Decimal(str(a)).quantize(CENT)) if d and a is not None else None
