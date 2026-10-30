"""`budget_lines`: the household's planned amount per category.

Moved out of the gitignored data/budgets/budgets.json so the plan lives with the rest of the
household's decisions (and the ledger API can edit it later). Keyed by (tenant, category); a
line is deleted when it is unset, so finance_api gets nothing yet (host jobs use finance_app).

Revision ID: 0020
"""
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
CREATE TABLE budget_lines (
    tenant_id   uuid           NOT NULL REFERENCES tenants(id)
                               DEFAULT current_setting('app.tenant_id')::uuid,
    category    text           NOT NULL,
    amount      numeric(12,2)  NOT NULL,
    updated_at  timestamptz    NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, category),
    CONSTRAINT budget_lines_amount_check CHECK (amount >= 0)
);
ALTER TABLE budget_lines ENABLE ROW LEVEL SECURITY;
ALTER TABLE budget_lines FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON budget_lines
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
""")


def downgrade():
    op.execute("DROP TABLE budget_lines;")
