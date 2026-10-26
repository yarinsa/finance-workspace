"""Web Push: `push_subscriptions` holds each installed PWA's subscription.

The ledger API (role finance_api) only inserts and deletes rows; the sender on the Mac
reads them as the owner, stamps `last_success_at` and drops endpoints the push service
reports gone (404/410). Upserting by endpoint is an INSERT ... ON CONFLICT DO UPDATE, which
Postgres also checks against UPDATE privileges, so the API gets UPDATE on the key columns only.

Revision ID: 0009
"""
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

UP = r"""
CREATE TABLE push_subscriptions (
    id               serial       PRIMARY KEY,
    endpoint         text         NOT NULL,
    p256dh           text         NOT NULL,
    auth             text         NOT NULL,
    email            text         NOT NULL,
    user_agent       text,
    created_at       timestamptz  NOT NULL DEFAULT now(),
    last_success_at  timestamptz,
    CONSTRAINT push_subscriptions_endpoint_key UNIQUE (endpoint)
);

GRANT SELECT, INSERT, DELETE ON push_subscriptions TO finance_api;
GRANT UPDATE (p256dh, auth, email, user_agent) ON push_subscriptions TO finance_api;
GRANT USAGE ON SEQUENCE push_subscriptions_id_seq TO finance_api;
"""


def upgrade():
    op.execute(UP)


def downgrade():
    op.execute("DROP TABLE push_subscriptions;")
