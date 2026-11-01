"""`account_balance_days` (docs/json-to-db-migration.md, phase 2 slice 2).

The checking accounts' measured end-of-day balances: the Discount and Leumi normalizers turn the
banks' running-balance chains into the `balance_days` entity, and every digest replaces this table
with it (machine layer). History's cash line reads it instead of the raw `transactions.json` dumps.
Additive only; `finance_api` may only read it.

Revision ID: 0027
"""
from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None

USING = "tenant_id = current_setting('app.tenant_id')::uuid"


def upgrade():
    op.execute("""
CREATE TABLE account_balance_days (
    tenant_id    uuid           NOT NULL REFERENCES tenants(id) DEFAULT current_setting('app.tenant_id')::uuid,
    institution  varchar        NOT NULL,
    account_id   varchar        NOT NULL,
    date         date           NOT NULL,
    balance      numeric(12,2)  NOT NULL,
    PRIMARY KEY (tenant_id, institution, account_id, date)
)""")
    op.execute("GRANT SELECT ON account_balance_days TO finance_api")
    op.execute("ALTER TABLE account_balance_days ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE account_balance_days FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON account_balance_days USING ({USING}) WITH CHECK ({USING})")


def downgrade():
    op.execute("DROP TABLE account_balance_days")
