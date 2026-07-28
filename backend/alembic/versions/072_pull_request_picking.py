"""User-dictated per-location pull picking (#367)

Revision ID: 072
Revises: 071
Create Date: 2026-07-28

Approving a pull deducted inventory FIFO by `received_at` and nobody recorded where the hardware
physically came from - the warehouse user never chose. This moves the deduction moment out of
approval and into an explicit **pick confirmation** the picker dictates: which location each unit
came off, per product code, entered against a printable paper sheet.

Three schema pieces:

- `pull_pick_lines` is the dictation itself: one row per (pull, product code, location) the picker
  named, DRAFT while the sheet is being keyed in and APPLIED once it has moved inventory. It is what
  makes a cancel able to restock to the *exact* rows the units came off, which the old per-combo
  inverse could only approximate (docs/HARDWARE_IDENTITY_LIFECYCLE.md - inventory is fungible, so
  the old approximation was defensible; a recorded source row is simply better). `inventory_location_id`
  is nullable with ON DELETE SET NULL so a location deleted later degrades to the per-combo restock
  instead of blocking the delete or stranding a dangling id.
- `pull_requests.picked_at` / `picked_by` is the new commitment stamp. `approved_at` keeps its old
  meaning ("the warehouse started on this"), and `picked_at` is what staging and completion now gate
  on, because it is the moment stock actually left.
- `pull_request_items.fetched_at` / `fetched_by` are the shipping-out fetch check-offs: an
  OPENING_ITEM line moves an assembled leaf that was already tagged at assembly, so there is nothing
  to deduct - only to walk to the rack and collect. Ticking that off now survives a page reload.

The backfill is what keeps in-flight pulls coherent. Every pull approved under the old model has
already been deducted, so it is stamped picked at its approval - otherwise a live pull would come
back from this deploy presenting a pick sheet for hardware that is already on a cart, and staging
(now gated on `picked_at`) would refuse it. `picked_by` takes `assigned_to`, which is exactly who
the old approve recorded.

Downgrade drops all of it. It is lossy only in the direction of the old model: the per-location
record disappears and a cancel goes back to restocking per combo, which is what it did before.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "072"
down_revision = "071"
branch_labels = None
depends_on = None

_STATE_ENUM = "pull_pick_line_state"


def upgrade() -> None:
    op.create_table(
        "pull_pick_lines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "pull_request_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("pull_requests.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("hardware_category", sa.String(), nullable=False),
        sa.Column("product_code", sa.String(), nullable=False),
        # SET NULL, not RESTRICT: a location can be merged or deleted long after the pick, and the
        # pick line's job by then is the historical record "these units came from somewhere that no
        # longer exists" - which the restock path reads as "fall back to the per-combo return".
        sa.Column(
            "inventory_location_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("inventory_locations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column(
            "state",
            sa.Enum("DRAFT", "APPLIED", name=_STATE_ENUM),
            nullable=False,
        ),
        sa.Column("entered_by", sa.String(), nullable=False),
        sa.Column("entered_at", sa.DateTime(), nullable=False),
        sa.Column("applied_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("quantity >= 1", name="ck_pull_pick_lines_quantity_positive"),
    )
    op.create_index("ix_pull_pick_lines_pull_request", "pull_pick_lines", ["pull_request_id"])
    op.create_index("ix_pull_pick_lines_inventory_location", "pull_pick_lines", ["inventory_location_id"])

    op.add_column("pull_requests", sa.Column("picked_at", sa.DateTime(), nullable=True))
    op.add_column("pull_requests", sa.Column("picked_by", sa.String(), nullable=True))

    op.add_column("pull_request_items", sa.Column("fetched_at", sa.DateTime(), nullable=True))
    op.add_column("pull_request_items", sa.Column("fetched_by", sa.String(), nullable=True))

    # Every pull approved under the old model was deducted at approval. Stamping it picked is what
    # stops this deploy from presenting a pick sheet for hardware that already left inventory, and
    # what keeps staging - which now gates on picked_at - working for pulls that are mid-flight.
    op.execute(
        "UPDATE pull_requests SET picked_at = approved_at, picked_by = assigned_to WHERE approved_at IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("pull_request_items", "fetched_by")
    op.drop_column("pull_request_items", "fetched_at")
    op.drop_column("pull_requests", "picked_by")
    op.drop_column("pull_requests", "picked_at")
    op.drop_index("ix_pull_pick_lines_inventory_location", table_name="pull_pick_lines")
    op.drop_index("ix_pull_pick_lines_pull_request", table_name="pull_pick_lines")
    op.drop_table("pull_pick_lines")
    sa.Enum(name=_STATE_ENUM).drop(op.get_bind(), checkfirst=True)
