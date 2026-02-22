"""core entities: projects, openings, hardware_items

Revision ID: 001
Revises: None
Create Date: 2026-02-18
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("job_site_name", sa.String(), nullable=True),
        sa.Column("address", sa.String(), nullable=True),
        sa.Column("city", sa.String(), nullable=True),
        sa.Column("state", sa.String(), nullable=True),
        sa.Column("zip", sa.String(), nullable=True),
        sa.Column("contractor", sa.String(), nullable=True),
        sa.Column("project_manager", sa.String(), nullable=True),
        sa.Column("application", sa.String(), nullable=True),
        sa.Column("submittal_job_no", sa.String(), nullable=True),
        sa.Column("submittal_assignment_count", sa.Integer(), nullable=True),
        sa.Column("estimator_code", sa.String(), nullable=True),
        sa.Column("titan_user_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "openings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("opening_number", sa.String(), nullable=False),
        sa.Column("building", sa.String(), nullable=True),
        sa.Column("floor", sa.String(), nullable=True),
        sa.Column("location", sa.String(), nullable=True),
        sa.Column("location_to", sa.String(), nullable=True),
        sa.Column("location_from", sa.String(), nullable=True),
        sa.Column("hand", sa.String(), nullable=True),
        sa.Column("width", sa.String(), nullable=True),
        sa.Column("length", sa.String(), nullable=True),
        sa.Column("door_thickness", sa.String(), nullable=True),
        sa.Column("jamb_thickness", sa.String(), nullable=True),
        sa.Column("door_type", sa.String(), nullable=True),
        sa.Column("frame_type", sa.String(), nullable=True),
        sa.Column("interior_exterior", sa.String(), nullable=True),
        sa.Column("keying", sa.String(), nullable=True),
        sa.Column("heading_no", sa.String(), nullable=True),
        sa.Column("single_pair", sa.String(), nullable=True),
        sa.Column("assignment_multiplier", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "hardware_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("opening_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("openings.id"), nullable=False),
        sa.Column("hardware_category", sa.String(), nullable=False),
        sa.Column("product_code", sa.String(), nullable=False),
        sa.Column("material_id", sa.String(), nullable=False),
        sa.Column("item_quantity", sa.Integer(), nullable=False),
        sa.Column("unit_cost", sa.Numeric(10, 4), nullable=True),
        sa.Column("unit_price", sa.Numeric(10, 4), nullable=True),
        sa.Column("list_price", sa.Numeric(10, 4), nullable=True),
        sa.Column("vendor_discount", sa.Numeric(10, 4), nullable=True),
        sa.Column("markup_pct", sa.Numeric(10, 4), nullable=True),
        sa.Column("vendor_no", sa.String(), nullable=True),
        sa.Column("phase_code", sa.String(), nullable=True),
        sa.Column("item_category_code", sa.String(), nullable=True),
        sa.Column("product_group_code", sa.String(), nullable=True),
        sa.Column("submittal_id", sa.String(), nullable=True),
        sa.Column(
            "classification",
            sa.Enum(
                "SITE_HARDWARE",
                "SHOP_HARDWARE",
                name="classification",
            ),
            nullable=True,
        ),
        sa.Column(
            "state",
            sa.Enum(
                "IN_PO",
                name="hardware_item_state",
            ),
            nullable=False,
        ),
        sa.Column("po_line_item_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("hardware_items")
    op.drop_table("openings")
    op.drop_table("projects")
    op.execute("DROP TYPE IF EXISTS hardware_item_state")
    op.execute("DROP TYPE IF EXISTS classification")
