"""NOTIFY payloads on `notifications` carry the tenant: `<tenant_id>:<id>`.

The API's SSE listener is one connection for every tenant; each stream forwards only the
events of its own tenant, so one tenant never learns that another's inbox changed.

Revision ID: 0018
"""
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
CREATE OR REPLACE FUNCTION notify_notifications() RETURNS trigger AS $$
BEGIN
    PERFORM pg_notify('notifications', NEW.tenant_id::text || ':' || NEW.id);
    RETURN NEW;
END $$ LANGUAGE plpgsql;
""")


def downgrade():
    op.execute("""
CREATE OR REPLACE FUNCTION notify_notifications() RETURNS trigger AS $$
BEGIN
    PERFORM pg_notify('notifications', NEW.id);
    RETURN NEW;
END $$ LANGUAGE plpgsql;
""")
