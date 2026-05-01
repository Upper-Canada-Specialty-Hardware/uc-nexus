"""Add client column to projects, enforce unique project_id

Revision ID: 024
Revises: 023
Create Date: 2026-05-01
"""

import sqlalchemy as sa

from alembic import op

revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Dev DB only — wipe project-tied data so the unique constraint applies cleanly.
    # Order respects FK dependencies (children before parents).
    op.execute("DELETE FROM inventory_audit_log")
    op.execute("DELETE FROM project_excluded_items")
    op.execute("DELETE FROM notifications")
    op.execute("DELETE FROM opening_item_hardware")
    op.execute("DELETE FROM shop_assembly_opening_items")
    op.execute("DELETE FROM po_documents")
    op.execute("DELETE FROM packing_slip_items")
    op.execute("DELETE FROM pull_request_items")
    op.execute("DELETE FROM inventory_locations")
    op.execute("DELETE FROM shop_assembly_openings")
    op.execute("DELETE FROM shop_assembly_requests")
    op.execute("DELETE FROM packing_slips")
    op.execute("DELETE FROM pull_requests")
    op.execute("DELETE FROM opening_items")
    op.execute("DELETE FROM hardware_items")
    op.execute("DELETE FROM receive_line_items")
    op.execute("DELETE FROM receive_records")
    op.execute("DELETE FROM po_line_items")
    op.execute("DELETE FROM purchase_orders")
    op.execute("DELETE FROM openings")
    op.execute("DELETE FROM projects")

    op.add_column("projects", sa.Column("client", sa.String(), nullable=True))
    op.create_unique_constraint("uq_projects_project_id", "projects", ["project_id"])


def downgrade() -> None:
    op.drop_constraint("uq_projects_project_id", "projects", type_="unique")
    op.drop_column("projects", "client")
