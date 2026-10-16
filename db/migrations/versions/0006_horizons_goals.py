"""Horizons and goals as tables: transactions and goals are assigned a horizon by id.

`horizons` is the fixed current / near / future list (data/horizons.py), seeded here
with a label and a target share of income. `scraped_transactions.horizon_id` is the
digest's rule-based default; the override's free-text `horizon` becomes `horizon_id`,
and an override may also point a transaction at a goal (`goal_id`). `goals` replaces
the `goals` list of data/goals/goals.json (imported with `db/goal_store.py import`).
The views keep exposing the horizon's key as `horizon`, plus its id and the goal.

Revision ID: 0006
"""
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

UP = r"""
CREATE TABLE horizons (
    id          serial         PRIMARY KEY,
    key         text           NOT NULL UNIQUE,
    name        text           NOT NULL,
    target_pct  numeric(5,2)   NOT NULL,
    position    integer        NOT NULL,
    created_at  timestamptz    NOT NULL DEFAULT now()
);
INSERT INTO horizons (key, name, target_pct, position) VALUES
    ('current', 'אני של היום',        33.3, 0),
    ('near',    'אני של העתיד הקרוב', 33.3, 1),
    ('future',  'אני של העתיד',       33.3, 2);

CREATE TABLE goals (
    id             serial         PRIMARY KEY,
    slug           text           NOT NULL UNIQUE,
    description    text           NOT NULL,
    amount         numeric(12,2)  NOT NULL,
    start_date     date,
    end_date       date,
    interval       text,
    repetitions    integer        NOT NULL,
    rise           numeric(12,2)  NOT NULL,
    from_asset_id  text,
    horizon_id     integer        REFERENCES horizons(id) ON DELETE SET NULL,
    created_at     timestamptz    NOT NULL DEFAULT now()
);
CREATE INDEX ix_goals_horizon_id ON goals (horizon_id);

ALTER TABLE scraped_transactions
    ADD COLUMN horizon_id integer REFERENCES horizons(id) ON DELETE SET NULL;
CREATE INDEX ix_scraped_transactions_horizon_id ON scraped_transactions (horizon_id);
UPDATE scraped_transactions s SET horizon_id = h.id FROM horizons h WHERE h.key = s.record->>'horizon';

ALTER TABLE transaction_overrides
    ADD COLUMN horizon_id integer REFERENCES horizons(id) ON DELETE SET NULL,
    ADD COLUMN goal_id    integer REFERENCES goals(id)    ON DELETE SET NULL;
CREATE INDEX ix_transaction_overrides_horizon_id ON transaction_overrides (horizon_id);
CREATE INDEX ix_transaction_overrides_goal_id ON transaction_overrides (goal_id);
UPDATE transaction_overrides o SET horizon_id = h.id FROM horizons h WHERE h.key = o.horizon;

DROP VIEW orphaned_overrides;
DROP VIEW transactions;
ALTER TABLE transaction_overrides DROP COLUMN horizon;
"""

TAGS = r"""(SELECT array_agg(t.name ORDER BY t.name) FROM transaction_tags tt JOIN tags t ON t.id = tt.tag_id
        WHERE (tt.txn_date, tt.abs_amount) = (s.txn_date, s.abs_amount))"""

VIEW = rf"""
CREATE VIEW transactions AS
SELECT s.txn_date,
       s.abs_amount,
       s.amount,
       s.description,
       c.name                           AS category,
       sc.name                          AS scraped_category,
       o.note,
       s.origin,
       s.sources,
       o.txn_date IS NOT NULL           AS overridden,
       s.position,
       (s.record - 'category' - 'tags' - 'horizon') || jsonb_strip_nulls(jsonb_build_object(
           'category',    c.name,
           'category_id', c.id,
           'note',        o.note,
           'horizon',     COALESCE(h.key, s.record->>'horizon'),
           'horizon_id',  h.id,
           'goal_id',     g.id,
           'goal',        g.description,
           'overridden',  CASE WHEN o.txn_date IS NOT NULL THEN true END,
           'tags',        to_jsonb({TAGS})
       ))                               AS record,
       COALESCE(h.key, s.record->>'horizon') AS horizon,
       c.id                             AS category_id,
       {TAGS} AS tags,
       h.id                             AS horizon_id,
       g.id                             AS goal_id
FROM scraped_transactions s
LEFT JOIN transaction_overrides o USING (txn_date, abs_amount)
LEFT JOIN categories sc ON sc.id = s.category_id
LEFT JOIN categories c  ON c.id = COALESCE(o.category_id, s.category_id)
LEFT JOIN horizons h    ON h.id = COALESCE(o.horizon_id, s.horizon_id)
LEFT JOIN goals g       ON g.id = o.goal_id
WHERE NOT COALESCE(o.excluded, false);
"""

ORPHANED = r"""
CREATE VIEW orphaned_overrides AS
SELECT o.txn_date, o.abs_amount, c.name AS category, o.note, o.excluded, h.key AS horizon,
       o.created_at, o.updated_at, o.category_id, o.horizon_id, o.goal_id
FROM transaction_overrides o
LEFT JOIN scraped_transactions s USING (txn_date, abs_amount)
LEFT JOIN categories c ON c.id = o.category_id
LEFT JOIN horizons h   ON h.id = o.horizon_id
WHERE s.txn_date IS NULL;
"""

GRANTS = r"""
GRANT SELECT ON transactions, orphaned_overrides, horizons TO finance_api;
GRANT SELECT, INSERT, UPDATE, DELETE ON goals TO finance_api;
GRANT USAGE ON SEQUENCE goals_id_seq TO finance_api;
"""

OLD_VIEW = rf"""
CREATE VIEW transactions AS
SELECT s.txn_date, s.abs_amount, s.amount, s.description,
       c.name AS category, sc.name AS scraped_category, o.note, s.origin, s.sources,
       o.txn_date IS NOT NULL AS overridden, s.position,
       (s.record - 'category' - 'tags') || jsonb_strip_nulls(jsonb_build_object(
           'category', c.name, 'category_id', c.id, 'note', o.note, 'horizon', o.horizon,
           'overridden', CASE WHEN o.txn_date IS NOT NULL THEN true END,
           'tags', to_jsonb({TAGS})
       )) AS record,
       COALESCE(o.horizon, s.record->>'horizon') AS horizon,
       c.id AS category_id,
       {TAGS} AS tags
FROM scraped_transactions s
LEFT JOIN transaction_overrides o USING (txn_date, abs_amount)
LEFT JOIN categories sc ON sc.id = s.category_id
LEFT JOIN categories c  ON c.id = COALESCE(o.category_id, s.category_id)
WHERE NOT COALESCE(o.excluded, false);
CREATE VIEW orphaned_overrides AS
SELECT o.txn_date, o.abs_amount, c.name AS category, o.note, o.excluded, o.horizon,
       o.created_at, o.updated_at, o.category_id
FROM transaction_overrides o
LEFT JOIN scraped_transactions s USING (txn_date, abs_amount)
LEFT JOIN categories c ON c.id = o.category_id
WHERE s.txn_date IS NULL;
"""


def upgrade():
    op.execute(UP)
    op.execute(VIEW)
    op.execute(ORPHANED)
    op.execute(GRANTS)


def downgrade():
    op.execute("DROP VIEW orphaned_overrides; DROP VIEW transactions;")
    op.execute("ALTER TABLE transaction_overrides ADD COLUMN horizon text "
               "CONSTRAINT transaction_overrides_horizon_check CHECK (horizon IN ('current', 'near', 'future'))")
    op.execute("UPDATE transaction_overrides o SET horizon = h.key FROM horizons h WHERE h.id = o.horizon_id")
    op.execute("ALTER TABLE transaction_overrides DROP COLUMN horizon_id, DROP COLUMN goal_id; "
               "ALTER TABLE scraped_transactions DROP COLUMN horizon_id; DROP TABLE goals; DROP TABLE horizons;")
    op.execute(OLD_VIEW)
    op.execute("GRANT SELECT ON transactions, orphaned_overrides TO finance_api")
