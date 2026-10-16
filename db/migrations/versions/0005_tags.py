"""Tags: free-form, many-to-many labels on transactions (`tags` + `transaction_tags`).

Like overrides, links are human-layer and keyed by the ledger key (date, abs_amount)
with no FK to scraped_transactions, so a re-import never drops them; `orphaned_tags`
lists links whose transaction vanished. The `transactions` view gains a sorted `tags`
array (also in `record`, omitted when empty).

Revision ID: 0005
"""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

UP = r"""
CREATE TABLE tags (
    id          serial       PRIMARY KEY,
    name        text         NOT NULL UNIQUE,
    color       text,
    created_at  timestamptz  NOT NULL DEFAULT now()
);
CREATE TABLE transaction_tags (
    txn_date    date           NOT NULL,
    abs_amount  numeric(12,2)  NOT NULL CONSTRAINT transaction_tags_abs_amount_check CHECK (abs_amount >= 0),
    tag_id      integer        NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    created_at  timestamptz    NOT NULL DEFAULT now(),
    PRIMARY KEY (txn_date, abs_amount, tag_id)
);
CREATE INDEX ix_transaction_tags_tag_id ON transaction_tags (tag_id);

DROP VIEW transactions;
"""

TAGS = r"""(SELECT array_agg(t.name ORDER BY t.name) FROM transaction_tags tt JOIN tags t ON t.id = tt.tag_id
        WHERE (tt.txn_date, tt.abs_amount) = (s.txn_date, s.abs_amount))"""


def view(tags):
    """The `transactions` view, with the tags column (upgrade) or as 0004 left it (downgrade)."""
    def when(sql):
        return sql if tags else ""
    return rf"""
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
       (s.record - 'category'{when(" - 'tags'")}) || jsonb_strip_nulls(jsonb_build_object(
           'category',    c.name,
           'category_id', c.id,
           'note',        o.note,
           'horizon',     o.horizon,
           'overridden',  CASE WHEN o.txn_date IS NOT NULL THEN true END{when(''',
           'tags',        to_jsonb(''' + TAGS + ''')''')}
       ))                               AS record,
       COALESCE(o.horizon, s.record->>'horizon') AS horizon,
       c.id                             AS category_id{when(''',
       ''' + TAGS + ''' AS tags''')}
FROM scraped_transactions s
LEFT JOIN transaction_overrides o USING (txn_date, abs_amount)
LEFT JOIN categories sc ON sc.id = s.category_id
LEFT JOIN categories c  ON c.id = COALESCE(o.category_id, s.category_id)
WHERE NOT COALESCE(o.excluded, false);
"""


ORPHANED = r"""
CREATE VIEW orphaned_tags AS
SELECT tt.txn_date, tt.abs_amount, t.name AS tag, tt.created_at, tt.tag_id
FROM transaction_tags tt
JOIN tags t ON t.id = tt.tag_id
LEFT JOIN scraped_transactions s USING (txn_date, abs_amount)
WHERE s.txn_date IS NULL;
"""

GRANTS = r"""
GRANT SELECT ON transactions, orphaned_tags TO finance_api;
GRANT SELECT, INSERT, UPDATE, DELETE ON tags, transaction_tags TO finance_api;
GRANT USAGE ON SEQUENCE tags_id_seq TO finance_api;
"""


def upgrade():
    op.execute(UP)
    op.execute(view(True))
    op.execute(ORPHANED)
    op.execute(GRANTS)


def downgrade():
    op.execute("DROP VIEW orphaned_tags; DROP VIEW transactions;")
    op.execute(view(False))
    op.execute("GRANT SELECT ON transactions TO finance_api")
    op.execute("DROP TABLE transaction_tags; DROP TABLE tags;")
