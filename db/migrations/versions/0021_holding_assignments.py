"""`holding_assignments`: the horizon and goal the user assigns a savings holding by hand.

Holdings (pension, study funds, deposits) are snapshot assets with no ledger row, so the
assignment is keyed by the app's holding id (`institution:topic_id`). The horizon is otherwise
derived from the liquidity date; a row here wins. Deleting a horizon or goal clears the field. `finance_api` may write it (the ledger API places holdings).

Revision ID: 0021
"""
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
CREATE TABLE holding_assignments (
    tenant_id   uuid         NOT NULL REFERENCES tenants(id)
                             DEFAULT current_setting('app.tenant_id')::uuid,
    holding_id  text         NOT NULL,
    horizon_id  integer      REFERENCES horizons(id) ON DELETE SET NULL,
    goal_id     integer      REFERENCES goals(id) ON DELETE SET NULL,
    updated_at  timestamptz  NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, holding_id)
);
CREATE INDEX ix_holding_assignments_horizon_id ON holding_assignments (horizon_id);
CREATE INDEX ix_holding_assignments_goal_id ON holding_assignments (goal_id);
GRANT SELECT, INSERT, UPDATE, DELETE ON holding_assignments TO finance_api;
ALTER TABLE holding_assignments ENABLE ROW LEVEL SECURITY;
ALTER TABLE holding_assignments FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON holding_assignments
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
""")


def downgrade():
    op.execute("DROP TABLE holding_assignments;")
