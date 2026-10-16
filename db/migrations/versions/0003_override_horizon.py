"""Override `horizon` (current / near / future): who an expense is for.

Adds the column with a check, and exposes it on the `transactions` view, both as a
column and merged into `record` (overriding the digest's rule-based default).
CREATE OR REPLACE keeps the views' grants; new columns go last as Postgres requires.

Revision ID: 0003
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

VIEW = r"""
CREATE OR REPLACE VIEW transactions AS
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
           'horizon',  o.horizon,
           'overridden', CASE WHEN o.txn_date IS NOT NULL THEN true END
       ))                               AS record{extra}
FROM scraped_transactions s
LEFT JOIN transaction_overrides o USING (txn_date, abs_amount)
WHERE NOT COALESCE(o.excluded, false);
"""

ORPHANED = r"""
CREATE OR REPLACE VIEW orphaned_overrides AS
SELECT o.*
FROM transaction_overrides o
LEFT JOIN scraped_transactions s USING (txn_date, abs_amount)
WHERE s.txn_date IS NULL;
"""


def upgrade():
    op.execute("ALTER TABLE transaction_overrides ADD COLUMN horizon text "
               "CONSTRAINT transaction_overrides_horizon_check "
               "CHECK (horizon IN ('current', 'near', 'future'))")
    op.execute(VIEW.format(extra=",\n       COALESCE(o.horizon, s.record->>'horizon') AS horizon"))
    op.execute(ORPHANED)


def downgrade():
    # A view cannot drop columns in place; recreate both, then re-grant.
    op.execute("DROP VIEW orphaned_overrides; DROP VIEW transactions;")
    op.execute(VIEW.replace("CREATE OR REPLACE", "CREATE").replace("           'horizon',  o.horizon,\n", "")
               .format(extra=""))
    op.execute("ALTER TABLE transaction_overrides DROP COLUMN horizon")
    op.execute(ORPHANED.replace("CREATE OR REPLACE", "CREATE"))
    op.execute("GRANT SELECT ON transactions, orphaned_overrides TO finance_api")
