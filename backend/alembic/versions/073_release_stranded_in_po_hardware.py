"""Release hardware stranded IN_PO by a dead purchase order (#402)

Revision ID: 073
Revises: 072
Create Date: 2026-07-29

Before #398, cancelling a PO left its hardware rows behind: the PO went to CANCELLED (or was
soft-deleted via `deleted_at`) but the `hardware_items` rows it had claimed kept `state = 'IN_PO'`
and kept pointing at the now-dead `po_line_items` row. `cancel_po` releases them properly now -
back to `state = 'AVAILABLE'` with `po_line_item_id = NULL` - but that only fixes cancels from here
on. Every environment still carries the rows the old cancels stranded, and nothing in the app can
reach them: they are attached to a PO no screen will ever open again.

Three symptoms come out of that, all of them from the same stranded rows:

- required_quantity rollups double-count. The stranded row still reads as ordered, and the
  replacement the user raised afterwards reads as ordered too.
- the admin Hardware Items stat is inflated by exactly the stranded count.
- finalize cannot recreate the items as AVAILABLE, because the stranded row already holds the
  (opening, product, category, leaf) key it needs.

This is a data migration rather than a one-off admin action on purpose. The backend entrypoint runs
`alembic upgrade head` on every deploy, so it repairs each environment exactly once, needs no UI,
and no-ops from then on.

Both statements are idempotent and safe on an empty database. `downgrade()` is a no-op: the pre-#398
state is a bug, and there is no record of which rows were stranded to put back.
"""

from alembic import op

revision = "073"
down_revision = "072"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Anything pointing at a line item of a cancelled or soft-deleted PO, whatever state it claims to
    # be in. No `state` filter here on purpose: a dead PO cannot own hardware, so both fields get
    # normalized regardless of how the row got there.
    op.execute(
        """
        UPDATE hardware_items SET state = 'AVAILABLE', po_line_item_id = NULL
        WHERE po_line_item_id IN (
          SELECT li.id FROM po_line_items li JOIN purchase_orders po ON po.id = li.po_id
          WHERE po.status = 'CANCELLED' OR po.deleted_at IS NOT NULL)
        """
    )

    # Register-edit orphans: the link was cleared but the state was not, so the row is claimed by a
    # PO that is not named anywhere.
    op.execute(
        """
        UPDATE hardware_items SET state = 'AVAILABLE'
        WHERE state = 'IN_PO' AND po_line_item_id IS NULL
        """
    )


def downgrade() -> None:
    """No-op. Re-stranding the rows would restore the defect, and which rows were stranded is not
    recorded anywhere."""
