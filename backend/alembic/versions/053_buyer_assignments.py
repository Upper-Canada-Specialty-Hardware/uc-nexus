"""Buyer assignments (issue #216)

Per-GP-buyer authorization: the projects a buyer may create POs for (M2M) and the GP cost codes
they may use (JSON list of 'cc1-cc2'). Strict enforcement - an unassigned buyer cannot create
project POs. The user->buyer link lives in Clerk publicMetadata.gpBuyerId, not here.

Revision ID: 053
Revises: 052
Create Date: 2026-07-16
"""

import sqlalchemy as sa

from alembic import op

revision = "053"
down_revision = "052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "buyer_assignments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("buyer_id", sa.String(15), nullable=False),
        sa.Column("cost_codes", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("buyer_id", name="uq_buyer_assignments_buyer_id"),
    )
    op.create_table(
        "buyer_assignment_projects",
        sa.Column(
            "buyer_assignment_id",
            sa.Uuid(),
            sa.ForeignKey("buyer_assignments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.PrimaryKeyConstraint("buyer_assignment_id", "project_id"),
    )


def downgrade() -> None:
    op.drop_table("buyer_assignment_projects")
    op.drop_table("buyer_assignments")
