"""Add inventory_audit_log table

Revision ID: 021
Revises: 020
Create Date: 2026-04-03
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    audit_entity_type = sa.Enum("INVENTORY_LOCATION", "OPENING_ITEM", name="audit_entity_type")
    audit_action = sa.Enum(
        "ADJUSTMENT",
        "MOVE",
        "UNLOCATE",
        "RECEIVE",
        "PULL_DEDUCTION",
        "SPOT_CHECK",
        "PUT_AWAY",
        name="audit_action",
    )

    op.create_table(
        "inventory_audit_log",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("entity_type", audit_entity_type, nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("action", audit_action, nullable=False),
        sa.Column("detail", JSONB(), nullable=True),
        sa.Column("performed_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_index("ix_audit_log_entity", "inventory_audit_log", ["entity_type", "entity_id"])
    op.create_index("ix_audit_log_project_created", "inventory_audit_log", ["project_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_log_project_created", table_name="inventory_audit_log")
    op.drop_index("ix_audit_log_entity", table_name="inventory_audit_log")
    op.drop_table("inventory_audit_log")
    op.execute("DROP TYPE IF EXISTS audit_action")
    op.execute("DROP TYPE IF EXISTS audit_entity_type")
