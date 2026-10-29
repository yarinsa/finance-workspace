"""Row-Level Security on every tenant-owned table.

Policy: `tenant_id = current_setting('app.tenant_id')::uuid`, for reads (USING) and writes
(WITH CHECK), FORCEd so the table owner is held to it too. An unbound `app.tenant_id` makes
the cast fail: a data access without a tenant errors, it never returns every tenant's rows.

Roles that see data are subject to RLS: `finance_api` (the internet-facing API) and the new
NOLOGIN `finance_app`, which the host pipeline (digest, sync, push, db/*.py) takes with
`SET ROLE` right after connecting (db/ledger.py `connect(tenant_id=...)`). Neither has
BYPASSRLS nor owns a table. Migrations and `db/tenants.py` run as the privileged owner role.

Adding a tenant-owned table: see docs/tenancy.md (the checklist ends with this policy).

Revision ID: 0017
"""
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None

OWNED = ["scraped_transactions", "transaction_overrides", "override_audit", "transaction_tags",
         "transaction_offsets", "tags", "categories", "merchant_rules", "horizons", "goals",
         "plan_targets", "notifications", "assets", "position_snapshots", "push_subscriptions"]
USING = "tenant_id = current_setting('app.tenant_id')::uuid"


def upgrade():
    op.execute("""
DO $$ BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'finance_app') THEN
        CREATE ROLE finance_app NOLOGIN NOBYPASSRLS;
    END IF;
END $$;
GRANT finance_app TO CURRENT_USER;
GRANT USAGE ON SCHEMA public TO finance_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO finance_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO finance_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO finance_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO finance_app;
""")
    for t in OWNED:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {t} USING ({USING}) WITH CHECK ({USING})")


def downgrade():
    for t in OWNED:
        op.execute(f"DROP POLICY tenant_isolation ON {t}")
        op.execute(f"ALTER TABLE {t} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} DISABLE ROW LEVEL SECURITY")
    op.execute("""
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM finance_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE USAGE, SELECT ON SEQUENCES FROM finance_app;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM finance_app;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM finance_app;
REVOKE USAGE ON SCHEMA public FROM finance_app;
""")
