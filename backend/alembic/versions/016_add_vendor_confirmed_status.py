"""Add VENDOR_CONFIRMED to po_status enum

Revision ID: 016
Revises: 015
Create Date: 2026-03-26
"""

from alembic import op

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE po_status ADD VALUE 'VENDOR_CONFIRMED' AFTER 'ORDERED'")


def downgrade() -> None:
    # PostgreSQL cannot remove enum values directly.
    # Recreate the type without VENDOR_CONFIRMED and update the column.
    op.execute("ALTER TYPE po_status RENAME TO po_status_old")
    op.execute("CREATE TYPE po_status AS ENUM ('DRAFT', 'ORDERED', 'PARTIALLY_RECEIVED', 'CLOSED', 'CANCELLED')")
    op.execute("ALTER TABLE purchase_orders ALTER COLUMN status TYPE po_status USING status::text::po_status")
    op.execute("DROP TYPE po_status_old")
