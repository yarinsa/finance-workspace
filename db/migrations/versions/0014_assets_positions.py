"""`assets` (the apartment's hand-typed value) and `position_snapshots` (one row a day).

`assets` is edited from the app, so finance_api may read, add and update rows (never
delete: a wrong value is corrected, not removed). `position_snapshots` is written by the
digest with the owner connection; the API only reads it.

Revision ID: 0014
"""
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

UP = r"""
CREATE TABLE assets (
    id                serial         PRIMARY KEY,
    kind              text           NOT NULL,
    label             text           NOT NULL,
    value             numeric(12,2)  NOT NULL,
    valued_at         date           NOT NULL,
    valuation_source  text           NOT NULL,
    created_at        timestamptz    NOT NULL DEFAULT now(),
    updated_at        timestamptz    NOT NULL DEFAULT now(),
    CONSTRAINT assets_kind_check CHECK (kind IN ('property')),
    CONSTRAINT assets_valuation_source_check CHECK (valuation_source IN ('manual', 'estimate'))
);

CREATE TABLE position_snapshots (
    date            date           PRIMARY KEY,
    cash            numeric(12,2)  NOT NULL,
    card_debt       numeric(12,2)  NOT NULL,
    consumer_loans  numeric(12,2)  NOT NULL,
    mortgage        numeric(12,2)  NOT NULL,
    savings         numeric(12,2)  NOT NULL,
    property        numeric(12,2),
    net_worth       numeric(12,2)  NOT NULL,
    recorded_at     timestamptz    NOT NULL DEFAULT now()
);

GRANT SELECT, INSERT, UPDATE ON assets TO finance_api;
GRANT USAGE ON SEQUENCE assets_id_seq TO finance_api;
GRANT SELECT ON position_snapshots TO finance_api;
"""


def upgrade():
    op.execute(UP)


def downgrade():
    op.execute("DROP TABLE position_snapshots; DROP TABLE assets;")
