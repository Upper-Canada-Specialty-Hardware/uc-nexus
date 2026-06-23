"""Add TRANSFER to the audit_action enum (issue #88 inventory transfer)

Revision ID: 034
Revises: 033
Create Date: 2026-06-23
"""

import sqlalchemy as sa

from alembic import op

revision = "034"
down_revision = "033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'TRANSFER'")


def downgrade() -> None:
    # Postgres has no DROP VALUE; rebuild the enum without TRANSFER (matches migration 027's pattern).
    op.execute("ALTER TYPE audit_action RENAME TO audit_action_old")
    new_action = sa.Enum(
        "ADJUSTMENT",
        "MOVE",
        "UNLOCATE",
        "RECEIVE",
        "PULL_DEDUCTION",
        "SPOT_CHECK",
        "PUT_AWAY",
        "DESTOCK",
        "ALLOCATE_FROM_STOCK",
        "RECLASSIFY",
        "REPORT_DEFICIENT",
        "RESOLVE_DEFICIENT",
        name="audit_action",
    )
    new_action.create(op.get_bind(), checkfirst=False)
    op.execute("ALTER TABLE inventory_audit_log ALTER COLUMN action TYPE audit_action USING action::text::audit_action")
    op.execute("DROP TYPE audit_action_old")
