"""The hand-kept side files as tables (docs/json-to-db-migration.md, phase 2).

`offset_rules` (was data/offsets/rules.json), `mortgage_schedule_periods` (data/mortgage_schedule.json)
and `loan_freezes` (data/freeze.json, written by data/detect_freeze.py). Human layer: never truncated
by a digest. Additive only; the readers fall back to the files while a table is empty, and the
`import` commands copy each file in. `finance_api` may only read them.

Revision ID: 0024
"""
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None

TENANT = "tenant_id uuid NOT NULL REFERENCES tenants(id) DEFAULT current_setting('app.tenant_id')::uuid"
TABLES = ["offset_rules", "mortgage_schedule_periods", "loan_freezes"]
USING = "tenant_id = current_setting('app.tenant_id')::uuid"


def upgrade():
    op.execute(f"""
CREATE TABLE offset_rules (
    {TENANT},
    id          serial       NOT NULL,
    payer       text         NOT NULL,
    against     text[]       NOT NULL,
    note        text,
    created_at  timestamptz  NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);
CREATE TABLE mortgage_schedule_periods (
    {TENANT},
    from_month  date           NOT NULL,
    to_month    date           NOT NULL,
    payment     numeric(12,2)  NOT NULL,
    source      text,
    PRIMARY KEY (tenant_id, from_month),
    CONSTRAINT mortgage_schedule_periods_order CHECK (to_month >= from_month)
);
CREATE TABLE loan_freezes (
    {TENANT},
    loan_id         text           NOT NULL,
    frozen_payment  numeric(12,2)  NOT NULL,
    resume_month    date           NOT NULL,
    resume_payment  numeric(12,2)  NOT NULL,
    note            text,
    detected_at     timestamptz    NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, loan_id)
);
""")
    for t in TABLES:
        op.execute(f"GRANT SELECT ON {t} TO finance_api")
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {t} USING ({USING}) WITH CHECK ({USING})")


def downgrade():
    op.execute(f"DROP TABLE {', '.join(reversed(TABLES))}")
