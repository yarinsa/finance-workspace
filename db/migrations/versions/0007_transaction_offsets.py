"""Offsets (קיזוז): `transaction_offsets` links a payback to the expense it pays back.

Human layer keyed by ledger keys like overrides and tags, no FK to scraped rows. A
payback with any row here ignores the digest's auto suggestion (finance/offsets.py);
a row with null expense columns records "this payback offsets nothing".
`orphaned_offsets` lists links whose payback or expense vanished. The `transactions`
view is unchanged: db/ledger.py attaches the links when it materializes rows.

Revision ID: 0007
"""
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

UP = r"""
CREATE TABLE transaction_offsets (
    id                  serial         PRIMARY KEY,
    payback_date        date           NOT NULL,
    payback_abs_amount  numeric(12,2)  NOT NULL,
    expense_date        date,
    expense_abs_amount  numeric(12,2),
    amount              numeric(12,2),
    created_at          timestamptz    NOT NULL DEFAULT now(),
    CONSTRAINT transaction_offsets_payback_abs_amount_check CHECK (payback_abs_amount >= 0),
    CONSTRAINT transaction_offsets_expense_check CHECK (
        (expense_date IS NULL) = (expense_abs_amount IS NULL) AND (expense_date IS NULL) = (amount IS NULL)),
    CONSTRAINT transaction_offsets_amount_check CHECK (amount > 0),
    CONSTRAINT transaction_offsets_link_key
        UNIQUE (payback_date, payback_abs_amount, expense_date, expense_abs_amount)
);
CREATE INDEX ix_transaction_offsets_payback_date ON transaction_offsets (payback_date);
CREATE INDEX ix_transaction_offsets_expense_date ON transaction_offsets (expense_date);

CREATE VIEW orphaned_offsets AS
SELECT o.id, o.payback_date, o.payback_abs_amount, o.expense_date, o.expense_abs_amount, o.amount,
       p.txn_date IS NULL AS payback_missing,
       o.expense_date IS NOT NULL AND e.txn_date IS NULL AS expense_missing
FROM transaction_offsets o
LEFT JOIN scraped_transactions p ON (p.txn_date, p.abs_amount) = (o.payback_date, o.payback_abs_amount)
LEFT JOIN scraped_transactions e ON (e.txn_date, e.abs_amount) = (o.expense_date, o.expense_abs_amount)
WHERE p.txn_date IS NULL OR (o.expense_date IS NOT NULL AND e.txn_date IS NULL);

GRANT SELECT ON orphaned_offsets TO finance_api;
GRANT SELECT, INSERT, UPDATE, DELETE ON transaction_offsets TO finance_api;
GRANT USAGE ON SEQUENCE transaction_offsets_id_seq TO finance_api;
"""


def upgrade():
    op.execute(UP)


def downgrade():
    op.execute("DROP VIEW orphaned_offsets; DROP TABLE transaction_offsets;")
