"""Relay receipt mapping: purchase_orders.gp_company + po_line_items.gp_line_ord
(uc nexus <-> relay full spec, receiving workflow - the po_number/company/ORD a relay /receipt needs)

Revision ID: 038
Revises: 037
Create Date: 2026-06-29
"""

import sqlalchemy as sa

from alembic import op

revision = "038"
down_revision = "037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The GP company the PO was created in (TUBC/TUCSH for the POC). Recorded at GP registration
    # alongside the returned po_number; a relay /receipt needs it to target the right company DB.
    op.add_column("purchase_orders", sa.Column("gp_company", sa.String(length=15), nullable=True))

    # GP POP10110.ORD for this line (16384, 32768, ...). The relay assigns ORD = line index * 16384 in
    # the order lines are sent, and Create PO sends GP lines and UC Nexus lines from the same array in the
    # same order, so this is the authoritative UC-Nexus-line -> GP-ORD mapping a relay /receipt targets.
    op.add_column("po_line_items", sa.Column("gp_line_ord", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("po_line_items", "gp_line_ord")
    op.drop_column("purchase_orders", "gp_company")
