"""Let the API role manage tenants, for platform admins only.

The API checks `finance.tenancy.is_platform_admin` before any of these writes (GraphQL
`tenantCreate` and friends). `finance_api` gets just what that needs: add tenants and users,
change a tenant's name/status, manage memberships, and seed a new tenant's horizons (the RLS
policy still confines that insert to the tenant the connection is bound to).

Revision ID: 0019
"""
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
GRANT INSERT ON tenants, users TO finance_api;
GRANT UPDATE (name, status, updated_at) ON tenants TO finance_api;
GRANT INSERT, DELETE ON memberships TO finance_api;
GRANT UPDATE (role) ON memberships TO finance_api;
GRANT INSERT ON horizons TO finance_api;
GRANT USAGE ON SEQUENCE horizons_id_seq TO finance_api;
""")


def downgrade():
    op.execute("""
REVOKE USAGE ON SEQUENCE horizons_id_seq FROM finance_api;
REVOKE INSERT ON horizons FROM finance_api;
REVOKE UPDATE (role) ON memberships FROM finance_api;
REVOKE INSERT, DELETE ON memberships FROM finance_api;
REVOKE UPDATE (name, status, updated_at) ON tenants FROM finance_api;
REVOKE INSERT ON tenants, users FROM finance_api;
""")
