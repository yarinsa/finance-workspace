"""Override audit log, and the least-privilege `finance_api` role for the ledger API.

The role is NOLOGIN here; db/ledger.py sets LOGIN PASSWORD from FINANCE_API_DB_PASSWORD
after migrating, so no secret lives in a migration. Roles are cluster-wide, so the
CREATE is guarded; the grants are per database.

Revision ID: 0002
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

SQL = r"""
CREATE TABLE override_audit (
    id          bigserial     PRIMARY KEY,
    at          timestamptz   NOT NULL DEFAULT now(),
    actor       text          NOT NULL,
    txn_date    date,
    abs_amount  numeric(12,2),
    field       text,
    old         jsonb,
    new         jsonb
);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'finance_api') THEN
        CREATE ROLE finance_api NOLOGIN;
    END IF;
END $$;

-- Read the ledger; edit only the human layer; append (never rewrite) the audit log.
GRANT SELECT ON scraped_transactions, transactions, orphaned_overrides TO finance_api;
GRANT SELECT, INSERT, UPDATE, DELETE ON transaction_overrides TO finance_api;
GRANT SELECT, INSERT ON override_audit TO finance_api;
GRANT USAGE ON SEQUENCE override_audit_id_seq TO finance_api;
"""

DOWN = r"""
REVOKE ALL ON scraped_transactions, transactions, orphaned_overrides,
              transaction_overrides, override_audit FROM finance_api;
REVOKE ALL ON SEQUENCE override_audit_id_seq FROM finance_api;
DROP TABLE override_audit;
"""


def upgrade():
    op.execute(SQL)


def downgrade():
    # The role itself is cluster-wide (other databases may use it), so it stays.
    op.execute(DOWN)
