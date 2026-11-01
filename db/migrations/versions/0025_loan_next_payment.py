"""`loans.next_payment_date` (docs/json-to-db-migration.md, phase 2 slice 2).

The mortgage dump's per-track `NextPaymentDate`, so the forecast reads the installment and its day
from the stored loans instead of `discount-mortgage/raw/mortgage_details.json`. Machine layer: the
next digest fills it. Additive only.

Revision ID: 0025
"""
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE loans ADD COLUMN next_payment_date date")


def downgrade():
    op.execute("ALTER TABLE loans DROP COLUMN next_payment_date")
