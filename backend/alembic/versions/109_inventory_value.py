"""DOORS ON HAND and AVERAGE DOOR COST, the stored half of INVENTORY VALUE

Revision ID: 109
Revises: 108
Create Date: 2026-09-09

Hardware in the building already prices itself off inventory rows and PO lines. Doors do not - they
never enter Nexus - so the count and the cost have to be kept by hand. These two tables are that, and
nothing more: the three INVENTORY VALUE figures are computed on read, so no total is stored anywhere
to fall out of step with the shelves.

`doors_on_hand.project_id` NULL is the company's general row (the doors that belong to no job). The
partial unique index is what holds it to one per company - a plain UNIQUE (company, project_id) does
not, because Postgres treats two NULLs as distinct and would happily take a second general row.
"""

import sqlalchemy as sa

from alembic import op

revision = "109"
down_revision = "108"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "doors_on_hand",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("company", sa.String(15), nullable=False),
        # ON DELETE CASCADE: a project that is gone has no doors, and a stranded count would be shown
        # on the page with no name against it.
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("company", "project_id", name="uq_doors_on_hand_company_project"),
        sa.CheckConstraint("quantity >= 0", name="ck_doors_on_hand_quantity_nonneg"),
    )
    op.create_index("ix_doors_on_hand_company", "doors_on_hand", ["company"])
    # Exactly one general row per company - see the module docstring.
    op.create_index(
        "uq_doors_on_hand_general_row",
        "doors_on_hand",
        ["company"],
        unique=True,
        postgresql_where=sa.text("project_id IS NULL"),
    )

    op.create_table(
        "inventory_value_settings",
        sa.Column("company", sa.String(15), primary_key=True),
        sa.Column("average_door_cost", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("inventory_value_settings")
    op.drop_index("uq_doors_on_hand_general_row", table_name="doors_on_hand")
    op.drop_index("ix_doors_on_hand_company", table_name="doors_on_hand")
    op.drop_table("doors_on_hand")
