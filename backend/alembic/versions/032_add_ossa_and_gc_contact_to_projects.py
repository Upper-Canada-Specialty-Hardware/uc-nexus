"""Add off-site storage agreement flag and GC contact fields to projects

Revision ID: 032
Revises: 031
Create Date: 2026-06-22
"""

import sqlalchemy as sa

from alembic import op

revision = "032"
down_revision = "031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("off_site_storage_agreement", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("projects", sa.Column("gc_contact_name", sa.String(), nullable=True))
    op.add_column("projects", sa.Column("gc_phone", sa.String(), nullable=True))
    op.add_column("projects", sa.Column("gc_email", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("projects", "gc_email")
    op.drop_column("projects", "gc_phone")
    op.drop_column("projects", "gc_contact_name")
    op.drop_column("projects", "off_site_storage_agreement")
