"""the log of manual hardware classification overrides (issue #735)

Once a schedule is imported, a product's classification could only be corrected by re-importing. The
Tenant Owner override page changes it in place, and this table records every change: which product,
from what, to what, who and when.

Revision ID: 117
Revises: 116
Create Date: 2026-09-25
"""

import sqlalchemy as sa

from alembic import op

revision = "117"
down_revision = "116"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hardware_classification_changes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("hardware_category", sa.String(), nullable=False),
        sa.Column("product_code", sa.String(), nullable=False),
        sa.Column("from_choice", sa.String(length=20), nullable=False),
        sa.Column("to_choice", sa.String(length=20), nullable=False),
        sa.Column("changed_by", sa.String(), nullable=False),
        sa.Column("changed_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_hardware_classification_changes_project",
        "hardware_classification_changes",
        ["project_id", "changed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_hardware_classification_changes_project", table_name="hardware_classification_changes")
    op.drop_table("hardware_classification_changes")
