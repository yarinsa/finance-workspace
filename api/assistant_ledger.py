"""The assistant's ledger backend for the API: the request's tenant-bound connection, through the
same `Ledger` loader the GraphQL resolvers use, so overrides, exclusions and offsets already apply
and Row-Level Security decides whose rows these are. The assistant never names a tenant."""
from finance.offsets import cashflow_view

from .gql.ledger import Ledger


class DbLedger:
    """`assistant.ledger` interface over one tenant-scoped connection (see `api.app.db`)."""

    def __init__(self, conn):
        self.lg = Ledger(conn)

    def rows(self):
        return cashflow_view([
            {**t.as_ledger_row(), "category": t.category.name if t.category else None,
             "kind": t.kind, "merchant": t.merchant.name}
            for t in self.lg.rows if not t.excluded])

    def snapshot(self):
        """Not served by the API yet (the snapshot resolver raises), so the tool is not offered."""
        return None
