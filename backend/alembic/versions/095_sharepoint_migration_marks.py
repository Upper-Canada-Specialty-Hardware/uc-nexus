"""Persist the SharePoint migration's purchased-marking targets

Revision ID: 095
Revises: 094
Create Date: 2026-08-14

The migration's purchased-marking lives as null-linked IN_PO HardwareItem rows, and a
`replace_schedule` re-import wipes every HardwareItem - so the marking silently vanished with them
and the project read as never-purchased again. `sharepoint_migration_marks` records the coverage
target per (project, category, code); finalize re-applies it against whatever rows the current
schedule carries. Like the runs table it is not preserved across a data reset, on purpose.
"""

import sqlalchemy as sa

from alembic import op

revision = "095"
down_revision = "094"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sharepoint_migration_marks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("hardware_category", sa.String(), nullable=False),
        sa.Column("product_code", sa.String(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["sharepoint_migration_runs.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sharepoint_migration_marks_project", "sharepoint_migration_marks", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_sharepoint_migration_marks_project", table_name="sharepoint_migration_marks")
    op.drop_table("sharepoint_migration_marks")
