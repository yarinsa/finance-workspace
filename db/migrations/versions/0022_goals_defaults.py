"""Goals absorb the three general targets, and gain a projection.

The emergency fund, inheritance and retirement targets were `plan_targets` rows; they are now
goal rows with a stable `key` (a household's defaults, edited but not deleted). A goal can be
`hidden`, and carries a `projected_amount` with its `projection_source` (empty until the
projection logic exists). Rows move across with their amount; `plan_targets` is dropped.

Revision ID: 0022
"""
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None

NAMES = "CASE key WHEN 'emergency_fund' THEN 'קרן חירום' WHEN 'inheritance' THEN 'הורשה' ELSE 'פרישה' END"


def upgrade():
    op.execute(f"""
ALTER TABLE goals
    ADD COLUMN key               text,
    ADD COLUMN hidden            boolean       NOT NULL DEFAULT false,
    ADD COLUMN projected_amount  numeric(12,2),
    ADD COLUMN projection_source text;
ALTER TABLE goals ADD CONSTRAINT goals_key_check
    CHECK (key IS NULL OR key IN ('emergency_fund', 'inheritance', 'retirement'));
CREATE UNIQUE INDEX goals_tenant_key_key ON goals (tenant_id, key) WHERE key IS NOT NULL;

INSERT INTO goals (tenant_id, slug, description, amount, key)
SELECT tenant_id, 'default-' || key, {NAMES}, amount, key FROM plan_targets;
DROP TABLE plan_targets;
""")


def downgrade():
    op.execute("""
CREATE TABLE plan_targets (
    tenant_id   uuid           NOT NULL REFERENCES tenants(id)
                               DEFAULT current_setting('app.tenant_id')::uuid,
    key         text           NOT NULL,
    amount      numeric(12,2)  NOT NULL,
    updated_at  timestamptz    NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, key),
    CONSTRAINT plan_targets_key_check CHECK (key IN ('emergency_fund', 'inheritance', 'retirement'))
);
GRANT SELECT, INSERT, UPDATE ON plan_targets TO finance_api;
ALTER TABLE plan_targets ENABLE ROW LEVEL SECURITY;
ALTER TABLE plan_targets FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON plan_targets
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
INSERT INTO plan_targets (tenant_id, key, amount) SELECT tenant_id, key, amount FROM goals WHERE key IS NOT NULL;
DELETE FROM goals WHERE key IS NOT NULL;
DROP INDEX goals_tenant_key_key;
ALTER TABLE goals DROP CONSTRAINT goals_key_check;
ALTER TABLE goals DROP COLUMN key, DROP COLUMN hidden, DROP COLUMN projected_amount, DROP COLUMN projection_source;
""")
