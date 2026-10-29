"""Tenants, users and memberships; `tenant_id` on every customer-data table.

Steps (each reversible, in order): create users/tenants/memberships; the default tenant;
nullable `tenant_id` on the tenant-owned tables; backfill to the default tenant; NOT NULL
+ FK + a column default of `current_setting('app.tenant_id')::uuid` (inserts land in the
bound tenant, an unbound insert fails); keys and uniques that include the tenant; the five
views redefined with `security_invoker` (they must not run with the owner's rights, or
RLS would not see through them). RLS itself is migration 0017.

The tables are small (a household's ledger), so the backfill is one UPDATE each.
Allow-listed emails in FINANCE_API_ALLOWED_EMAILS become owners of the default tenant.

Revision ID: 0016
"""
import os

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

DEFAULT = "00000000-0000-4000-8000-000000000001"
TENANT_DEFAULT = "current_setting('app.tenant_id')::uuid"

# tables whose key or unique constraint does not already lead with tenant_id
INDEXED = ["override_audit", "assets"]
# table -> old primary key columns (None = surrogate `id`, kept)
OWNED = ["scraped_transactions", "transaction_overrides", "override_audit", "transaction_tags",
         "transaction_offsets", "tags", "categories", "merchant_rules", "horizons", "goals",
         "plan_targets", "notifications", "assets", "position_snapshots", "push_subscriptions"]
NEW_PK = {
    "scraped_transactions": ("txn_date, abs_amount", "scraped_transactions_pkey"),
    "transaction_overrides": ("txn_date, abs_amount", "transaction_overrides_pkey"),
    "transaction_tags": ("txn_date, abs_amount, tag_id", "transaction_tags_pkey"),
    "plan_targets": ("key", "plan_targets_pkey"),
    "notifications": ("id", "notifications_pkey"),
    "position_snapshots": ("date", "position_snapshots_pkey"),
}
# (table, old constraint, old columns, new columns)
UNIQUES = [
    ("categories", "categories_name_key", "name"),
    ("tags", "tags_name_key", "name"),
    ("horizons", "horizons_key_key", "key"),
    ("goals", "goals_slug_key", "slug"),
    ("merchant_rules", "merchant_rules_merchant_key", "merchant"),
    ("push_subscriptions", "push_subscriptions_endpoint_key", "endpoint"),
]

KINDS = r"""
CREATE VIEW transaction_kinds WITH (security_invoker = true) AS
SELECT s.tenant_id,
       s.txn_date,
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
LEFT JOIN transaction_overrides o USING (tenant_id, txn_date, abs_amount)
LEFT JOIN merchant_rules mr       ON mr.tenant_id = s.tenant_id AND mr.merchant = s.record->>'merchant'
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

TRANSACTIONS = r"""
CREATE VIEW transactions WITH (security_invoker = true) AS
SELECT s.tenant_id,
    s.txn_date,
    s.abs_amount,
    s.amount,
    s.description,
    c.name AS category,
    sc.name AS scraped_category,
    o.note,
    s.origin,
    s.sources,
    o.txn_date IS NOT NULL AS overridden,
    s."position",
    (s.record - 'category' - 'tags' - 'horizon' - 'category_group' - 'kind' - 'kind_source') ||
      jsonb_strip_nulls(jsonb_build_object('category', c.name, 'category_id', c.id,
        'category_group', tk.category_group, 'kind', tk.kind, 'kind_source', tk.kind_source,
        'note', o.note, 'horizon', COALESCE(h.key, s.record ->> 'horizon'), 'horizon_id', h.id,
        'goal_id', g.id, 'goal', g.description,
        'overridden', CASE WHEN o.txn_date IS NOT NULL THEN true ELSE NULL::boolean END,
        'tags', to_jsonb((SELECT array_agg(t.name ORDER BY t.name)
                          FROM transaction_tags tt JOIN tags t ON t.id = tt.tag_id
                          WHERE tt.tenant_id = s.tenant_id AND tt.txn_date = s.txn_date
                            AND tt.abs_amount = s.abs_amount)))) AS record,
    COALESCE(h.key, s.record ->> 'horizon') AS horizon,
    c.id AS category_id,
    (SELECT array_agg(t.name ORDER BY t.name)
       FROM transaction_tags tt JOIN tags t ON t.id = tt.tag_id
      WHERE tt.tenant_id = s.tenant_id AND tt.txn_date = s.txn_date
        AND tt.abs_amount = s.abs_amount) AS tags,
    h.id AS horizon_id,
    g.id AS goal_id,
    tk.category_group,
    tk.kind,
    tk.kind_source
FROM scraped_transactions s
JOIN transaction_kinds tk USING (tenant_id, txn_date, abs_amount)
LEFT JOIN transaction_overrides o ON o.tenant_id = s.tenant_id AND o.txn_date = s.txn_date
                                AND o.abs_amount = s.abs_amount
LEFT JOIN categories sc ON sc.id = s.category_id
LEFT JOIN categories c ON c.id = tk.category_id
LEFT JOIN horizons h ON h.id = COALESCE(o.horizon_id, s.horizon_id)
LEFT JOIN goals g ON g.id = o.goal_id
WHERE NOT COALESCE(o.excluded, false);
"""

ORPHANED_OVERRIDES = r"""
CREATE VIEW orphaned_overrides WITH (security_invoker = true) AS
SELECT o.tenant_id, o.txn_date, o.abs_amount, c.name AS category, o.note, o.excluded,
       h.key AS horizon, o.created_at, o.updated_at, o.category_id, o.horizon_id, o.goal_id, o.kind
FROM transaction_overrides o
LEFT JOIN scraped_transactions s USING (tenant_id, txn_date, abs_amount)
LEFT JOIN categories c ON c.id = o.category_id
LEFT JOIN horizons h ON h.id = o.horizon_id
WHERE s.txn_date IS NULL;
"""

ORPHANED_TAGS = r"""
CREATE VIEW orphaned_tags WITH (security_invoker = true) AS
SELECT tt.tenant_id, tt.txn_date, tt.abs_amount, t.name AS tag, tt.created_at, tt.tag_id
FROM transaction_tags tt
JOIN tags t ON t.id = tt.tag_id
LEFT JOIN scraped_transactions s ON s.tenant_id = tt.tenant_id AND s.txn_date = tt.txn_date
                                AND s.abs_amount = tt.abs_amount
WHERE s.txn_date IS NULL;
"""

ORPHANED_OFFSETS = r"""
CREATE VIEW orphaned_offsets WITH (security_invoker = true) AS
SELECT o.tenant_id, o.id, o.payback_date, o.payback_abs_amount, o.expense_date,
       o.expense_abs_amount, o.amount,
       p.txn_date IS NULL AS payback_missing,
       o.expense_date IS NOT NULL AND e.txn_date IS NULL AS expense_missing
FROM transaction_offsets o
LEFT JOIN scraped_transactions p ON p.tenant_id = o.tenant_id AND p.txn_date = o.payback_date
                                AND p.abs_amount = o.payback_abs_amount
LEFT JOIN scraped_transactions e ON e.tenant_id = o.tenant_id AND e.txn_date = o.expense_date
                                AND e.abs_amount = o.expense_abs_amount
WHERE p.txn_date IS NULL OR o.expense_date IS NOT NULL AND e.txn_date IS NULL;
"""

VIEWS = ["transactions", "transaction_kinds", "orphaned_overrides", "orphaned_tags", "orphaned_offsets"]


def _earlier(filename):
    """An earlier migration's module, to reuse its view SQL on downgrade."""
    import importlib.util
    from pathlib import Path
    path = Path(__file__).with_name(filename)
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _drop_views():
    for v in VIEWS:
        op.execute(f"DROP VIEW IF EXISTS {v}")


def _grants():
    op.execute("GRANT SELECT ON transactions, transaction_kinds, orphaned_overrides, orphaned_tags, "
               "orphaned_offsets TO finance_api")


def upgrade():
    op.execute("""
CREATE TABLE users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT users_email_lower CHECK (email = lower(email)),
    CONSTRAINT users_email_key UNIQUE (email));
CREATE TABLE tenants (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    slug text NOT NULL,
    status text NOT NULL DEFAULT 'active',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT tenants_slug_key UNIQUE (slug),
    CONSTRAINT tenants_status_check CHECK (status IN ('active', 'suspended')));
CREATE TABLE memberships (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT memberships_role_check CHECK (role IN ('owner', 'admin', 'member')),
    CONSTRAINT memberships_tenant_user_key UNIQUE (tenant_id, user_id));
CREATE INDEX ix_memberships_user_id ON memberships (user_id);
""")
    op.execute(f"INSERT INTO tenants (id, name, slug) VALUES ('{DEFAULT}', 'Default', 'default')")
    emails = [e.strip().lower() for e in os.environ.get("FINANCE_API_ALLOWED_EMAILS", "").split(",") if e.strip()]
    for e in emails:
        op.get_bind().exec_driver_sql("INSERT INTO users (email) VALUES (%s) ON CONFLICT DO NOTHING", (e,))
    op.execute(f"INSERT INTO memberships (tenant_id, user_id, role) "
               f"SELECT '{DEFAULT}', id, 'owner' FROM users")
    # finance_api reads who may act where; it never writes these (db/tenants.py does, as owner).
    op.execute("GRANT SELECT ON users, tenants, memberships TO finance_api")

    _drop_views()
    for t in OWNED:
        op.execute(f"ALTER TABLE {t} ADD COLUMN tenant_id uuid")
        op.execute(f"UPDATE {t} SET tenant_id = '{DEFAULT}'")
        op.execute(f"ALTER TABLE {t} ALTER COLUMN tenant_id SET NOT NULL, "
                   f"ADD CONSTRAINT {t}_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES tenants(id), "
                   f"ALTER COLUMN tenant_id SET DEFAULT {TENANT_DEFAULT}")
        if t in INDEXED:
            op.execute(f"CREATE INDEX ix_{t}_tenant_id ON {t} (tenant_id)")
    for t, (cols, pk) in NEW_PK.items():
        op.execute(f"ALTER TABLE {t} DROP CONSTRAINT {pk}, ADD CONSTRAINT {pk} PRIMARY KEY (tenant_id, {cols})")
    for t, name, col in UNIQUES:
        op.execute(f"ALTER TABLE {t} DROP CONSTRAINT {name}, ADD CONSTRAINT {name} UNIQUE (tenant_id, {col})")
    op.execute("ALTER TABLE transaction_offsets DROP CONSTRAINT transaction_offsets_link_key, "
               "ADD CONSTRAINT transaction_offsets_link_key UNIQUE (tenant_id, payback_date, "
               "payback_abs_amount, expense_date, expense_abs_amount)")
    # hot ledger reads are per tenant and by date
    op.execute("CREATE INDEX ix_scraped_transactions_tenant_date ON scraped_transactions (tenant_id, txn_date)")

    for v in (KINDS, TRANSACTIONS, ORPHANED_OVERRIDES, ORPHANED_TAGS, ORPHANED_OFFSETS):
        op.execute(v)
    _grants()


def downgrade():
    _drop_views()
    op.execute("DROP INDEX IF EXISTS ix_scraped_transactions_tenant_date")
    op.execute("ALTER TABLE transaction_offsets DROP CONSTRAINT transaction_offsets_link_key, "
               "ADD CONSTRAINT transaction_offsets_link_key UNIQUE (payback_date, payback_abs_amount, "
               "expense_date, expense_abs_amount)")
    for t, name, col in UNIQUES:
        op.execute(f"ALTER TABLE {t} DROP CONSTRAINT {name}, ADD CONSTRAINT {name} UNIQUE ({col})")
    for t, (cols, pk) in NEW_PK.items():
        op.execute(f"ALTER TABLE {t} DROP CONSTRAINT {pk}, ADD CONSTRAINT {pk} PRIMARY KEY ({cols})")
    for t in OWNED:
        op.execute(f"ALTER TABLE {t} DROP COLUMN tenant_id CASCADE")
    op.execute("DROP TABLE memberships; DROP TABLE tenants; DROP TABLE users")
    prev = _earlier("0015_category_merges.py"), _earlier("0013_category_kinds.py")
    op.execute(prev[0].KINDS.replace("CREATE OR REPLACE VIEW", "CREATE VIEW"))
    op.execute(prev[1].VIEW)
    op.execute("""
CREATE VIEW orphaned_overrides AS
SELECT o.txn_date, o.abs_amount, c.name AS category, o.note, o.excluded, h.key AS horizon,
       o.created_at, o.updated_at, o.category_id, o.horizon_id, o.goal_id, o.kind
FROM transaction_overrides o
LEFT JOIN scraped_transactions s USING (txn_date, abs_amount)
LEFT JOIN categories c ON c.id = o.category_id
LEFT JOIN horizons h ON h.id = o.horizon_id
WHERE s.txn_date IS NULL;
CREATE VIEW orphaned_tags AS
SELECT tt.txn_date, tt.abs_amount, t.name AS tag, tt.created_at, tt.tag_id
FROM transaction_tags tt JOIN tags t ON t.id = tt.tag_id
LEFT JOIN scraped_transactions s USING (txn_date, abs_amount)
WHERE s.txn_date IS NULL;
CREATE VIEW orphaned_offsets AS
SELECT o.id, o.payback_date, o.payback_abs_amount, o.expense_date, o.expense_abs_amount, o.amount,
       p.txn_date IS NULL AS payback_missing,
       o.expense_date IS NOT NULL AND e.txn_date IS NULL AS expense_missing
FROM transaction_offsets o
LEFT JOIN scraped_transactions p ON p.txn_date = o.payback_date AND p.abs_amount = o.payback_abs_amount
LEFT JOIN scraped_transactions e ON e.txn_date = o.expense_date AND e.abs_amount = o.expense_abs_amount
WHERE p.txn_date IS NULL OR o.expense_date IS NOT NULL AND e.txn_date IS NULL;
""")
    _grants()
