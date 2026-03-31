"""Add project_excluded_items table for By Others scope classification

Revision ID: 019
Revises: 018
Create Date: 2026-03-31
"""

import sqlalchemy as sa

from alembic import op

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_excluded_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("hardware_category", sa.String(), nullable=False),
        sa.Column("product_code", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "hardware_category", "product_code", name="uq_project_excluded_items"),
    )
    op.create_index("ix_project_excluded_items_project", "project_excluded_items", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_project_excluded_items_project", table_name="project_excluded_items")
    op.drop_table("project_excluded_items")
