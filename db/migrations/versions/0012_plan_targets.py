"""`plan_targets`: the Goals screen's emergency-fund / inheritance / retirement targets.

Moved out of the gitignored data/goals/goals.json so the read-only ledger API can edit
them. A missing row means "not decided yet" (the JSON store still applies); an unset target
is a row with amount 0. Rows are never deleted, so finance_api gets SELECT/INSERT/UPDATE only.

Revision ID: 0012
"""
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

UP = r"""
CREATE TABLE plan_targets (
    key         text           PRIMARY KEY,
    amount      numeric(12,2)  NOT NULL,
    updated_at  timestamptz    NOT NULL DEFAULT now(),
    CONSTRAINT plan_targets_key_check CHECK (key IN ('emergency_fund', 'inheritance', 'retirement'))
);

GRANT SELECT, INSERT, UPDATE ON plan_targets TO finance_api;
"""


def upgrade():
    op.execute(UP)


def downgrade():
    op.execute("DROP TABLE plan_targets;")
