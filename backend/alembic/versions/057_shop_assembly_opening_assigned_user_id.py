"""Stable assignment identity (#324): shop_assembly_openings.assigned_to_user_id

Revision ID: 057
Revises: 056
Create Date: 2026-07-23

Adds a nullable assigned_to_user_id column holding the stable Clerk user id an opening is claimed
by. myWork now filters on this instead of the display-name string in assigned_to (which stays for
display). Additive, nullable, no backfill: dev-only data, and any in-flight assignment is re-claimed
through the UI (existing rows keep their assigned_to name but a null user id, so they drop off My
Work until re-assigned).
"""

import sqlalchemy as sa

from alembic import op

revision = "057"
down_revision = "056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "shop_assembly_openings",
        sa.Column("assigned_to_user_id", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("shop_assembly_openings", "assigned_to_user_id")
