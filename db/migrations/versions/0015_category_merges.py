"""Categories merged by hand: `categories.merged_into_id`.

The household merges a category into another from the app (GraphQL `categoryMerge`):
its transactions, overrides and merchant rules keep pointing at it, and
`transaction_kinds` resolves it to the target, so an unmerge restores everything. One
level only: db/overrides.py refuses to merge into a category that is itself merged.
finance_api may update just that column.

Revision ID: 0015
"""
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

KINDS = r"""
CREATE OR REPLACE VIEW transaction_kinds AS
SELECT s.txn_date,
       s.abs_amount,
       c.id    AS category_id,
       cg.name AS category_group,
       CASE ks.kind_source
           WHEN 'manual'    THEN o.kind
           WHEN 'rule'      THEN mr.kind
           WHEN 'category'  THEN COALESCE(c.kind, 'variable')
           ELSE s.record->>'kind'
       END     AS kind,
       ks.kind_source
FROM scraped_transactions s
LEFT JOIN transaction_overrides o USING (txn_date, abs_amount)
LEFT JOIN merchant_rules mr       ON mr.merchant = s.record->>'merchant'
LEFT JOIN categories c0           ON c0.id = COALESCE(o.category_id, mr.category_id, s.category_id)
LEFT JOIN categories c            ON c.id = COALESCE(c0.merged_into_id, c0.id)
LEFT JOIN category_groups cg      ON cg.id = c.group_id
CROSS JOIN LATERAL (SELECT CASE
    WHEN NOT (s.amount < 0
              AND NOT COALESCE((s.record->>'is_income')::boolean, false)
              AND NOT COALESCE((s.record->>'card_bill_payment')::boolean, false)
              AND NOT COALESCE((s.record->>'internal_transfer')::boolean, false)
              AND NOT COALESCE((s.record->>'savings')::boolean, false))
         OR cg.key = 'income_savings'                         THEN NULL
    WHEN o.kind IS NOT NULL                                   THEN 'manual'
    WHEN mr.kind IS NOT NULL                                  THEN 'rule'
    WHEN s.record->>'kind_source' = 'merchant'                THEN 'merchant'
    WHEN c.usage_based                                        THEN 'category'
    WHEN s.record->>'kind_source' IN ('recurring', 'one_off', 'riseup') THEN s.record->>'kind_source'
    ELSE 'category'
END AS kind_source) ks;
"""


def upgrade():
    op.execute("ALTER TABLE categories ADD COLUMN merged_into_id integer "
               "REFERENCES categories(id) ON DELETE SET NULL")
    op.execute("CREATE INDEX ix_categories_merged_into_id ON categories (merged_into_id)")
    op.execute(KINDS)
    op.execute("GRANT UPDATE (merged_into_id) ON categories TO finance_api")


def downgrade():
    op.execute("REVOKE UPDATE (merged_into_id) ON categories FROM finance_api")
    op.execute(KINDS.replace(
        "LEFT JOIN categories c0           ON c0.id = COALESCE(o.category_id, mr.category_id, s.category_id)\n"
        "LEFT JOIN categories c            ON c.id = COALESCE(c0.merged_into_id, c0.id)",
        "LEFT JOIN categories c            ON c.id = COALESCE(o.category_id, mr.category_id, s.category_id)"))
    op.execute("ALTER TABLE categories DROP COLUMN merged_into_id")
