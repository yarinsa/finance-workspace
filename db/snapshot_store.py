"""The headline position as the last digest stored it (read side).

`db/ledger.py load` replaces `accounts`, `credit_cards`, `loans`, `savings_holdings` and
`source_dumps` in the digest's transaction; this reads them back as the `finance.tables` rows,
for the ledger API's `snapshot`, `dataAsOf` and `syncSources`. The totals are not stored:
`totals` runs finance/views/snapshot.py over the rows, the same code that wrote snapshot.json.
(The daily net-worth history is a different table: db/position_store.py.)

    .venv/bin/python db/snapshot_store.py     # the stored totals' inputs and the as-of time
"""
import json
import sys

from sqlmodel import func, select

from finance.tables import AccountRow, CreditCardRow, DigestRun, LoanRow, SavingsRow, SourceDump, SourceDumpEntity
from finance.views import snapshot as views
from ledger import orm_session


def position(conn):
    """{bank_accounts, credit_cards, loans, savings}: the stored rows, loans in the digest's order."""
    with orm_session(conn) as s:
        return {
            "bank_accounts": s.exec(select(AccountRow).order_by(AccountRow.institution, AccountRow.account_id)).all(),
            "credit_cards": s.exec(select(CreditCardRow).order_by(CreditCardRow.issuer, CreditCardRow.last4)).all(),
            "loans": s.exec(select(LoanRow).order_by(LoanRow.position)).all(),
            "savings": s.exec(select(SavingsRow).order_by(SavingsRow.holding_id)).all(),
        }


def totals(rows, assets=None):
    """The snapshot's totals over `position(conn)`, by the digest's own arithmetic (on floats,
    as snapshot.json was summed). `assets` as db/asset_store.all_assets returns them."""
    as_json = {k: [r.model_dump(mode="json") for r in v] for k, v in rows.items()}
    return views.totals(as_json, assets)


def as_of(conn):
    """When the newest digest that reached the database finished, or None before the first."""
    with orm_session(conn) as s:
        return s.exec(select(func.max(DigestRun.finished_at))).one()


def dumps(conn):
    """{source: (SourceDump, {entity: records})} for every source with a dump on disk."""
    with orm_session(conn) as s:
        counts = {}
        for e in s.exec(select(SourceDumpEntity).order_by(SourceDumpEntity.entity)).all():
            counts.setdefault(e.source, {})[e.entity] = e.records
        return {d.source: (d, counts.get(d.source, {}))
                for d in s.exec(select(SourceDump).order_by(SourceDump.source)).all()}


def main():
    from finance.tenancy import use_cli_tenant
    from ledger import connect
    import asset_store
    use_cli_tenant()
    with connect() as conn:
        out = {"as_of": str(as_of(conn)), "totals": totals(position(conn), asset_store.all_assets(conn))}
    json.dump(out, sys.stdout, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
