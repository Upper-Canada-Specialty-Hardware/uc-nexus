"""a PO line GP cancelled before anything arrived may order zero (issue #1228)

- ck_po_line_items_ordered_quantity_positive is relaxed from ordered_quantity >= 1 to >= 0. The GP PO
  sync zeroes a line GP cancelled; with the old floor it had to pin a never-received one at 1, which
  left a phantom unit outstanding: receiving offered it, the PO never auto-closed, and a receipt
  against it posted to a cancelled GP line. Every input path still refuses a quantity below 1.
- Existing pinned lines cannot be told apart from a genuine one-unit line, so none are rewritten; the
  next sync pass over their PO writes the 0.

Downgrade puts any zero line back at 1 (the old pin) and restores the >= 1 check.

Revision ID: 129
Revises: 128
Create Date: 2026-10-03
"""

from alembic import op

# Numbered 129 because 128 is taken by a sibling branch (#1188). Whichever of the two merges second
# sets its down_revision to the other's revision, so master keeps a single head.
revision = "129"
down_revision = "128"
branch_labels = None
depends_on = None

_NAME = "ck_po_line_items_ordered_quantity_positive"


def upgrade() -> None:
    op.drop_constraint(_NAME, "po_line_items", type_="check")
    op.create_check_constraint(_NAME, "po_line_items", "ordered_quantity >= 0")


def downgrade() -> None:
    op.execute("UPDATE po_line_items SET ordered_quantity = 1 WHERE ordered_quantity < 1")
    op.drop_constraint(_NAME, "po_line_items", type_="check")
    op.create_check_constraint(_NAME, "po_line_items", "ordered_quantity >= 1")
