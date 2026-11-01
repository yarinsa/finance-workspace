"""`household_settings` (docs/json-to-db-migration.md, phase 2 slice 2).

One row per tenant; `cycle_start_day` is the day the budget cycle starts (budgets, bills), imported
once from RiseUp's `cashflowStartDay` by `db/input_store.py import settings`. Human layer: never
truncated by a digest. Until the row exists the views keep reading RiseUp's budget doc. Additive only;
`finance_api` may only read it.

Revision ID: 0026
"""
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None

USING = "tenant_id = current_setting('app.tenant_id')::uuid"


def upgrade():
    op.execute("""
CREATE TABLE household_settings (
    tenant_id        uuid         NOT NULL REFERENCES tenants(id) DEFAULT current_setting('app.tenant_id')::uuid,
    cycle_start_day  smallint,
    updated_at       timestamptz  NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id),
    CONSTRAINT household_settings_cycle_day CHECK (cycle_start_day BETWEEN 1 AND 31)
)""")
    op.execute("GRANT SELECT ON household_settings TO finance_api")
    op.execute("ALTER TABLE household_settings ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE household_settings FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON household_settings USING ({USING}) WITH CHECK ({USING})")


def downgrade():
    op.execute("DROP TABLE household_settings")
