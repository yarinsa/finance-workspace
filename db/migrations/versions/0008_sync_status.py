"""Live sync status per source, with a NOTIFY on every change.

`sync_status` holds one SourceStatus entry per source (written by the host sync
worker). An AFTER INSERT OR UPDATE row trigger runs `pg_notify('sync_status', source)`
so the API can push changes over SSE. `finance_api` may only SELECT.

Revision ID: 0008
"""
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

UP = r"""
CREATE TABLE sync_status (
    source      text         PRIMARY KEY,
    entry       jsonb        NOT NULL,
    updated_at  timestamptz  NOT NULL DEFAULT now()
);

CREATE FUNCTION notify_sync_status() RETURNS trigger AS $$
BEGIN
    PERFORM pg_notify('sync_status', NEW.source);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER sync_status_notify
AFTER INSERT OR UPDATE ON sync_status
FOR EACH ROW EXECUTE FUNCTION notify_sync_status();

GRANT SELECT ON sync_status TO finance_api;
"""

DOWN = r"""
DROP TRIGGER sync_status_notify ON sync_status;
DROP FUNCTION notify_sync_status();
DROP TABLE sync_status;
"""


def upgrade():
    op.execute(UP)


def downgrade():
    op.execute(DOWN)
