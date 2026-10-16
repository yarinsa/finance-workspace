"""A `categories` table: transactions are assigned a category by id, not free text.

Seeded from the RiseUp-sourced categories already in `scraped_transactions` (and
every import keeps it current, see db/ledger.py). `scraped_transactions.category`
stays as the raw scraped label; `category_id` is RiseUp's assignment. The override's
free-text `category` becomes `category_id`; existing override texts become "user"
categories. The views expose the category's name (and id) instead of free text.

Revision ID: 0004
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

VIEW = r"""
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
       (s.record - 'category') || jsonb_strip_nulls(jsonb_build_object(
           'category',    c.name,
           'category_id', c.id,
           'note',        o.note,
           'horizon',     o.horizon,
           'overridden',  CASE WHEN o.txn_date IS NOT NULL THEN true END
       ))                               AS record,
       COALESCE(o.horizon, s.record->>'horizon') AS horizon,
       c.id                             AS category_id
FROM scraped_transactions s
LEFT JOIN transaction_overrides o USING (txn_date, abs_amount)
LEFT JOIN categories sc ON sc.id = s.category_id
LEFT JOIN categories c  ON c.id = COALESCE(o.category_id, s.category_id)
WHERE NOT COALESCE(o.excluded, false);
"""

ORPHANED = r"""
CREATE VIEW orphaned_overrides AS
SELECT o.txn_date, o.abs_amount, c.name AS category, o.note, o.excluded, o.horizon,
       o.created_at, o.updated_at, o.category_id
FROM transaction_overrides o
LEFT JOIN scraped_transactions s USING (txn_date, abs_amount)
LEFT JOIN categories c ON c.id = o.category_id
WHERE s.txn_date IS NULL;
"""

UP = r"""
CREATE TABLE categories (
    id          serial       PRIMARY KEY,
    name        text         NOT NULL UNIQUE,
    source      text         NOT NULL DEFAULT 'user'
                             CONSTRAINT categories_source_check CHECK (source IN ('riseup', 'user')),
    created_at  timestamptz  NOT NULL DEFAULT now()
);

ALTER TABLE scraped_transactions
    ADD COLUMN category_id integer REFERENCES categories(id) ON DELETE SET NULL;
CREATE INDEX ix_scraped_transactions_category_id ON scraped_transactions (category_id);
ALTER TABLE transaction_overrides
    ADD COLUMN category_id integer REFERENCES categories(id) ON DELETE SET NULL;
CREATE INDEX ix_transaction_overrides_category_id ON transaction_overrides (category_id);

INSERT INTO categories (name, source)
SELECT DISTINCT category, 'riseup' FROM scraped_transactions
WHERE 'riseup' = ANY(sources) AND category IS NOT NULL AND category <> ''
ON CONFLICT (name) DO NOTHING;
INSERT INTO categories (name, source)
SELECT DISTINCT category, 'user' FROM transaction_overrides
WHERE category IS NOT NULL AND category <> ''
ON CONFLICT (name) DO NOTHING;

UPDATE scraped_transactions s SET category_id = c.id FROM categories c
WHERE c.name = s.category AND 'riseup' = ANY(s.sources);
UPDATE transaction_overrides o SET category_id = c.id FROM categories c WHERE c.name = o.category;

DROP VIEW orphaned_overrides;
DROP VIEW transactions;
ALTER TABLE transaction_overrides DROP COLUMN category;
"""

GRANTS = r"""
GRANT SELECT ON transactions, orphaned_overrides TO finance_api;
GRANT SELECT, INSERT ON categories TO finance_api;
GRANT USAGE ON SEQUENCE categories_id_seq TO finance_api;
"""

OLD_VIEW = r"""
CREATE VIEW transactions AS
SELECT s.txn_date, s.abs_amount, s.amount, s.description,
       COALESCE(o.category, s.category) AS category,
       s.category                       AS scraped_category,
       o.note, s.origin, s.sources,
       o.txn_date IS NOT NULL           AS overridden,
       s.position,
       s.record || jsonb_strip_nulls(jsonb_build_object(
           'category', o.category, 'note', o.note, 'horizon', o.horizon,
           'overridden', CASE WHEN o.txn_date IS NOT NULL THEN true END
       ))                               AS record,
       COALESCE(o.horizon, s.record->>'horizon') AS horizon
FROM scraped_transactions s
LEFT JOIN transaction_overrides o USING (txn_date, abs_amount)
WHERE NOT COALESCE(o.excluded, false);
CREATE VIEW orphaned_overrides AS
SELECT o.* FROM transaction_overrides o
LEFT JOIN scraped_transactions s USING (txn_date, abs_amount)
WHERE s.txn_date IS NULL;
"""


def upgrade():
    op.execute(UP)
    op.execute(VIEW)
    op.execute(ORPHANED)
    op.execute(GRANTS)


def downgrade():
    op.execute("DROP VIEW orphaned_overrides; DROP VIEW transactions;")
    op.execute("ALTER TABLE transaction_overrides ADD COLUMN category text")
    op.execute("UPDATE transaction_overrides o SET category = c.name FROM categories c WHERE c.id = o.category_id")
    op.execute("ALTER TABLE transaction_overrides DROP COLUMN category_id; "
               "ALTER TABLE scraped_transactions DROP COLUMN category_id; DROP TABLE categories;")
    op.execute(OLD_VIEW)
    op.execute("GRANT SELECT ON transactions, orphaned_overrides TO finance_api")
