"""The notifications inbox: the digest's "לטיפול" actions plus the household's state on them.

`notifications` is keyed by the period-stable action id. The digest refreshes the content
columns; the household's `read_at` / `snoozed_until_at` / `archived_at` are the only columns
`finance_api` may update. An AFTER INSERT OR UPDATE row trigger runs
`pg_notify('notifications', id)` so the API can push changes over SSE.

Revision ID: 0010
"""
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

UP = r"""
CREATE TABLE notifications (
    id                text         PRIMARY KEY,
    type              text         NOT NULL,
    category          text         NOT NULL,
    severity          text         NOT NULL,
    title             text         NOT NULL,
    detail            text,
    amount            numeric(12,2),
    cta               jsonb,
    subject           jsonb,
    created_at        timestamptz  NOT NULL DEFAULT now(),
    updated_at        timestamptz  NOT NULL DEFAULT now(),
    read_at           timestamptz,
    snoozed_until_at  timestamptz,
    archived_at       timestamptz,
    resolved_at       timestamptz,
    CONSTRAINT notifications_category_check
        CHECK (category IN ('PROBLEM', 'WARNING', 'REMINDER', 'SUGGESTION', 'INFO')),
    CONSTRAINT notifications_severity_check
        CHECK (severity IN ('critical', 'high', 'medium', 'low'))
);

CREATE FUNCTION notify_notifications() RETURNS trigger AS $$
BEGIN
    PERFORM pg_notify('notifications', NEW.id);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER notifications_notify
AFTER INSERT OR UPDATE ON notifications
FOR EACH ROW EXECUTE FUNCTION notify_notifications();

GRANT SELECT ON notifications TO finance_api;
GRANT UPDATE (read_at, snoozed_until_at, archived_at) ON notifications TO finance_api;
"""

DOWN = r"""
DROP TRIGGER notifications_notify ON notifications;
DROP FUNCTION notify_notifications();
REVOKE ALL ON notifications FROM finance_api;
DROP TABLE notifications;
"""


def upgrade():
    op.execute(UP)


def downgrade():
    op.execute(DOWN)
