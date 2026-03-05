"""Make hardware_items.material_id nullable

Revision ID: 014
Revises: 013
Create Date: 2026-03-05
"""

import sqlalchemy as sa

from alembic import op

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("hardware_items", "material_id", existing_type=sa.String(), nullable=True)


def downgrade() -> None:
    op.execute("UPDATE hardware_items SET material_id = '' WHERE material_id IS NULL")
    op.alter_column("hardware_items", "material_id", existing_type=sa.String(), nullable=False)
