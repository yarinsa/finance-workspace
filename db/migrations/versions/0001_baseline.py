"""Baseline: the schema db/schema.sql used to apply on every connect.

Idempotent (IF NOT EXISTS), so a database created before Alembic upgrades in place.
Tables must match finance/tables.py; db/tests/test_schema.py checks that.

Revision ID: 0001
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SQL = r"""
CREATE TABLE IF NOT EXISTS scraped_transactions (
    txn_date     date          NOT NULL,
    abs_amount   numeric(12,2) NOT NULL,
    amount       numeric(12,2) NOT NULL,
    description  text          NOT NULL DEFAULT '',
    category     text,
    origin       text,
    sources      text[]        NOT NULL DEFAULT '{}',
    position     integer       NOT NULL,          -- index in the digested ledger (keeps its order)
    record       jsonb         NOT NULL,          -- the full digest row, so no field is lost
    imported_at  timestamptz   NOT NULL DEFAULT now(),
    PRIMARY KEY (txn_date, abs_amount)
);

-- Only the fields you changed are set; null falls through to the scraped value.
CREATE TABLE IF NOT EXISTS transaction_overrides (
    txn_date     date          NOT NULL,
    abs_amount   numeric(12,2) NOT NULL CHECK (abs_amount >= 0),
    category     text,
    note         text,
    excluded     boolean       NOT NULL DEFAULT false,   -- hidden from the ledger and every total
    created_at   timestamptz   NOT NULL DEFAULT now(),
    updated_at   timestamptz   NOT NULL DEFAULT now(),
    PRIMARY KEY (txn_date, abs_amount)
);

DROP VIEW IF EXISTS transactions;
CREATE VIEW transactions AS
SELECT s.txn_date,
       s.abs_amount,
       s.amount,
       s.description,
       COALESCE(o.category, s.category) AS category,
       s.category                       AS scraped_category,
       o.note,
       s.origin,
       s.sources,
       o.txn_date IS NOT NULL           AS overridden,
       s.position,
       s.record || jsonb_strip_nulls(jsonb_build_object(
           'category', o.category,
           'note',     o.note,
           'overridden', CASE WHEN o.txn_date IS NOT NULL THEN true END
       ))                               AS record
FROM scraped_transactions s
LEFT JOIN transaction_overrides o USING (txn_date, abs_amount)
WHERE NOT COALESCE(o.excluded, false);

-- Edits whose transaction no longer exists (a bank corrected its date or amount).
DROP VIEW IF EXISTS orphaned_overrides;
CREATE VIEW orphaned_overrides AS
SELECT o.*
FROM transaction_overrides o
LEFT JOIN scraped_transactions s USING (txn_date, abs_amount)
WHERE s.txn_date IS NULL;
"""


def upgrade():
    op.execute(SQL)


def downgrade():
    op.execute("DROP VIEW IF EXISTS orphaned_overrides; DROP VIEW IF EXISTS transactions; "
               "DROP TABLE IF EXISTS transaction_overrides; DROP TABLE IF EXISTS scraped_transactions;")
