"""notifications.pushed_at: when the Mac's Web Push announced the item.

The inbox is the single record of what was pushed (it replaces data/push/sent.json). Only the
owner role writes it (finance/push.py); `finance_api` keeps SELECT and its three household
columns, so the API cannot mark or unmark a push.

Revision ID: 0011
"""
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE notifications ADD COLUMN pushed_at timestamptz")


def downgrade():
    op.execute("ALTER TABLE notifications DROP COLUMN pushed_at")
