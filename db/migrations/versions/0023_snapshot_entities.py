"""The headline position's scraped entities as tables (docs/json-to-db-migration.md, phase 1).

`accounts`, `credit_cards`, `loans`, `savings_holdings`, `source_dumps` (+ `source_dump_entities`)
are the machine layer: every digest replaces them in the same transaction as
`scraped_transactions`. `digest_runs` records each such digest; its newest `finished_at` is the
data's as-of time. Totals are not stored: the API computes them from these rows. Additive only,
nothing reads them until the API's `snapshot` resolver does. `finance_api` may only read them.

Revision ID: 0023
"""
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None

TENANT = "tenant_id uuid NOT NULL REFERENCES tenants(id) DEFAULT current_setting('app.tenant_id')::uuid"
TABLES = ["digest_runs", "accounts", "credit_cards", "loans", "savings_holdings", "source_dumps",
          "source_dump_entities"]
USING = "tenant_id = current_setting('app.tenant_id')::uuid"


def upgrade():
    op.execute(f"""
CREATE TABLE digest_runs (
    {TENANT},
    id            serial       NOT NULL,
    started_at    timestamptz  NOT NULL,
    finished_at   timestamptz  NOT NULL DEFAULT now(),
    normalized    boolean      NOT NULL,
    transactions  integer      NOT NULL,
    PRIMARY KEY (tenant_id, id)
);
CREATE TABLE accounts (
    institution        varchar        NOT NULL,
    account_id         varchar        NOT NULL,
    kind               varchar        NOT NULL,
    balance            numeric(12,2)  NOT NULL,
    label              varchar,
    available_balance  numeric(12,2),
    overdraft_limit    numeric(12,2),
    {TENANT},
    PRIMARY KEY (tenant_id, institution, account_id)
);
CREATE TABLE credit_cards (
    issuer            varchar        NOT NULL,
    last4             varchar        NOT NULL,
    name              varchar,
    holder            varchar,
    active            boolean,
    owed              numeric(12,2)  NOT NULL,
    {TENANT},
    next_charge_date  date,
    PRIMARY KEY (tenant_id, issuer, last4)
);
CREATE TABLE loans (
    lender              varchar        NOT NULL,
    loan_id             varchar,
    name                varchar,
    category            varchar        NOT NULL,
    balance             numeric(12,2)  NOT NULL,
    original_amount     numeric(12,2),
    rate_pct            double precision,
    rate_type           varchar,
    index_linked        boolean,
    payments_remaining  integer,
    payments_total      integer,
    monthly_payment     numeric(12,2),
    final_date          date,
    {TENANT},
    position            integer        NOT NULL,
    PRIMARY KEY (tenant_id, position)
);
CREATE TABLE savings_holdings (
    institution     varchar        NOT NULL,
    kind            varchar        NOT NULL,
    balance         numeric(12,2)  NOT NULL,
    label           varchar,
    account_id      varchar,
    topic_id        varchar,
    section         varchar,
    policies_count  integer,
    work_state      varchar,
    liquid          boolean,
    liquidity_date  date,
    maturity_date   date,
    as_of           date,
    management_fee  double precision,
    yield_ytd       double precision,
    {TENANT},
    holding_id      varchar        NOT NULL,
    PRIMARY KEY (tenant_id, holding_id)
);
CREATE TABLE source_dumps (
    {TENANT},
    source           varchar      NOT NULL,
    dumped_at        timestamptz  NOT NULL,
    raw_files        integer      NOT NULL,
    latest_txn_date  date,
    PRIMARY KEY (tenant_id, source)
);
CREATE TABLE source_dump_entities (
    {TENANT},
    source   varchar  NOT NULL,
    entity   varchar  NOT NULL,
    records  integer  NOT NULL,
    PRIMARY KEY (tenant_id, source, entity),
    FOREIGN KEY (tenant_id, source) REFERENCES source_dumps (tenant_id, source) ON DELETE CASCADE
);
""")
    for t in TABLES:
        op.execute(f"GRANT SELECT ON {t} TO finance_api")
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {t} USING ({USING}) WITH CHECK ({USING})")


def downgrade():
    op.execute(f"DROP TABLE {', '.join(reversed(TABLES))}")
