"""One category system: category groups, a fixed/variable `kind`, merchant rules.

`category_groups` and the new `categories` columns (group, default kind, usage_based,
position) are filled from finance/categories.py by db/ledger.py on every import, not
here, so the taxonomy has one home. `merchant_rules` is a human layer per merchant;
`transaction_overrides.kind` a human layer per transaction.

The precedence lives in one view, `transaction_kinds` (every scraped row, excluded
ones too, so db/overrides.py can read it): category = override > merchant rule >
digest default; kind = override > rule > the digest's merchant default > a
usage-based category is variable > the digest's recurring / one-off / RiseUp-fixed
signal > the category's default kind. Non-expenses (income, card bills, own transfers,
savings, a הכנסות וחיסכון category) have no kind. `transactions` reads it.

Revision ID: 0013
"""
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

UP = r"""
CREATE TABLE category_groups (
    id          serial       PRIMARY KEY,
    key         text         NOT NULL UNIQUE,
    name        text         NOT NULL,
    position    integer      NOT NULL,
    created_at  timestamptz  NOT NULL DEFAULT now()
);

ALTER TABLE categories
    DROP CONSTRAINT categories_source_check,
    ADD CONSTRAINT categories_source_check CHECK (source IN ('builtin', 'riseup', 'user')),
    ADD COLUMN group_id    integer REFERENCES category_groups(id) ON DELETE SET NULL,
    ADD COLUMN kind        text CONSTRAINT categories_kind_check CHECK (kind IN ('fixed', 'variable')),
    ADD COLUMN usage_based boolean NOT NULL DEFAULT false,
    ADD COLUMN position    integer NOT NULL DEFAULT 0;
CREATE INDEX ix_categories_group_id ON categories (group_id);

CREATE TABLE merchant_rules (
    id           serial       PRIMARY KEY,
    merchant     text         NOT NULL UNIQUE,
    category_id  integer      REFERENCES categories(id) ON DELETE SET NULL,
    kind         text         CONSTRAINT merchant_rules_kind_check CHECK (kind IN ('fixed', 'variable')),
    created_at   timestamptz  NOT NULL DEFAULT now(),
    updated_at   timestamptz  NOT NULL DEFAULT now()
);
CREATE INDEX ix_merchant_rules_category_id ON merchant_rules (category_id);

ALTER TABLE transaction_overrides
    ADD COLUMN kind text CONSTRAINT transaction_overrides_kind_check CHECK (kind IN ('fixed', 'variable'));

DROP VIEW orphaned_overrides;
DROP VIEW transactions;
"""

KINDS = r"""
CREATE VIEW transaction_kinds AS
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
LEFT JOIN categories c            ON c.id = COALESCE(o.category_id, mr.category_id, s.category_id)
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
       (s.record - 'category' - 'tags' - 'horizon' - 'category_group' - 'kind' - 'kind_source')
       || jsonb_strip_nulls(jsonb_build_object(
           'category',       c.name,
           'category_id',    c.id,
           'category_group', tk.category_group,
           'kind',           tk.kind,
           'kind_source',    tk.kind_source,
           'note',           o.note,
           'horizon',        COALESCE(h.key, s.record->>'horizon'),
           'horizon_id',     h.id,
           'goal_id',        g.id,
           'goal',           g.description,
           'overridden',     CASE WHEN o.txn_date IS NOT NULL THEN true END,
           'tags',           to_jsonb({TAGS})
       ))                               AS record,
       COALESCE(h.key, s.record->>'horizon') AS horizon,
       c.id                             AS category_id,
       {TAGS} AS tags,
       h.id                             AS horizon_id,
       g.id                             AS goal_id,
       tk.category_group,
       tk.kind,
       tk.kind_source
FROM scraped_transactions s
JOIN transaction_kinds tk USING (txn_date, abs_amount)
LEFT JOIN transaction_overrides o USING (txn_date, abs_amount)
LEFT JOIN categories sc ON sc.id = s.category_id
LEFT JOIN categories c  ON c.id = tk.category_id
LEFT JOIN horizons h    ON h.id = COALESCE(o.horizon_id, s.horizon_id)
LEFT JOIN goals g       ON g.id = o.goal_id
WHERE NOT COALESCE(o.excluded, false);
"""

ORPHANED = r"""
CREATE VIEW orphaned_overrides AS
SELECT o.txn_date, o.abs_amount, c.name AS category, o.note, o.excluded, h.key AS horizon,
       o.created_at, o.updated_at, o.category_id, o.horizon_id, o.goal_id, o.kind
FROM transaction_overrides o
LEFT JOIN scraped_transactions s USING (txn_date, abs_amount)
LEFT JOIN categories c ON c.id = o.category_id
LEFT JOIN horizons h   ON h.id = o.horizon_id
WHERE s.txn_date IS NULL;
"""

GRANTS = r"""
GRANT SELECT ON transactions, transaction_kinds, orphaned_overrides, category_groups TO finance_api;
GRANT SELECT, INSERT, UPDATE, DELETE ON merchant_rules TO finance_api;
GRANT USAGE ON SEQUENCE merchant_rules_id_seq TO finance_api;
"""

# As 0006 left them.
OLD_VIEW = rf"""
CREATE VIEW transactions AS
SELECT s.txn_date, s.abs_amount, s.amount, s.description,
       c.name AS category, sc.name AS scraped_category, o.note, s.origin, s.sources,
       o.txn_date IS NOT NULL AS overridden, s.position,
       (s.record - 'category' - 'tags' - 'horizon') || jsonb_strip_nulls(jsonb_build_object(
           'category', c.name, 'category_id', c.id, 'note', o.note,
           'horizon', COALESCE(h.key, s.record->>'horizon'), 'horizon_id', h.id,
           'goal_id', g.id, 'goal', g.description,
           'overridden', CASE WHEN o.txn_date IS NOT NULL THEN true END,
           'tags', to_jsonb({TAGS})
       )) AS record,
       COALESCE(h.key, s.record->>'horizon') AS horizon,
       c.id AS category_id, {TAGS} AS tags, h.id AS horizon_id, g.id AS goal_id
FROM scraped_transactions s
LEFT JOIN transaction_overrides o USING (txn_date, abs_amount)
LEFT JOIN categories sc ON sc.id = s.category_id
LEFT JOIN categories c  ON c.id = COALESCE(o.category_id, s.category_id)
LEFT JOIN horizons h    ON h.id = COALESCE(o.horizon_id, s.horizon_id)
LEFT JOIN goals g       ON g.id = o.goal_id
WHERE NOT COALESCE(o.excluded, false);
CREATE VIEW orphaned_overrides AS
SELECT o.txn_date, o.abs_amount, c.name AS category, o.note, o.excluded, h.key AS horizon,
       o.created_at, o.updated_at, o.category_id, o.horizon_id, o.goal_id
FROM transaction_overrides o
LEFT JOIN scraped_transactions s USING (txn_date, abs_amount)
LEFT JOIN categories c ON c.id = o.category_id
LEFT JOIN horizons h   ON h.id = o.horizon_id
WHERE s.txn_date IS NULL;
"""


def upgrade():
    op.execute(UP)
    op.execute(KINDS)
    op.execute(VIEW)
    op.execute(ORPHANED)
    op.execute(GRANTS)


def downgrade():
    op.execute("DROP VIEW orphaned_overrides; DROP VIEW transactions; DROP VIEW transaction_kinds;")
    op.execute("ALTER TABLE transaction_overrides DROP COLUMN kind; DROP TABLE merchant_rules;")
    op.execute("UPDATE categories SET source = 'riseup' WHERE source = 'builtin'")
    op.execute("ALTER TABLE categories DROP COLUMN group_id, DROP COLUMN kind, DROP COLUMN usage_based, "
               "DROP COLUMN position, DROP CONSTRAINT categories_source_check, "
               "ADD CONSTRAINT categories_source_check CHECK (source IN ('riseup', 'user')); "
               "DROP TABLE category_groups;")
    op.execute(OLD_VIEW)
    op.execute("GRANT SELECT ON transactions, orphaned_overrides TO finance_api")
