"""Make purchase_orders.project_id nullable for manual PO creation

Revision ID: 017
Revises: 016
Create Date: 2026-03-26
"""

from alembic import op

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Make project_id nullable
    op.alter_column("purchase_orders", "project_id", nullable=True)

    # Drop the existing partial unique index on (project_id, po_number)
    op.drop_index("ix_purchase_orders_project_po_number", table_name="purchase_orders")

    # Recreate for project-scoped POs (project_id IS NOT NULL)
    op.create_index(
        "ix_purchase_orders_project_po_number",
        "purchase_orders",
        ["project_id", "po_number"],
        unique=True,
        postgresql_where="project_id IS NOT NULL AND po_number IS NOT NULL",
    )

    # New partial unique index for project-less POs
    op.create_index(
        "ix_purchase_orders_no_project_po_number",
        "purchase_orders",
        ["po_number"],
        unique=True,
        postgresql_where="project_id IS NULL AND po_number IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_index("ix_purchase_orders_no_project_po_number", table_name="purchase_orders")
    op.drop_index("ix_purchase_orders_project_po_number", table_name="purchase_orders")

    # Restore original index
    op.create_index(
        "ix_purchase_orders_project_po_number",
        "purchase_orders",
        ["project_id", "po_number"],
        unique=True,
        postgresql_where="po_number IS NOT NULL",
    )

    # Make project_id NOT NULL again
    op.alter_column("purchase_orders", "project_id", nullable=False)
