"""wizard-drafted po lines book to the job (issue #850)

The import wizard created its PO lines without `job_cost` or `cost_code`, so they took the column
defaults - off, none - and a buyer who registered one of those drafts as it stood sent GP
non-inventoried lines with no cost code: the hardware never booked to the job. The wizard now writes
job cost on with the draft's own cost code; this puts the drafts already waiting in the same state.

Only lines that are plainly the wizard's and still untouched: on an unregistered (DRAFT), not
cancelled, project PO; covered by an imported hardware item, which only the wizard links; with job
cost off and no cost code of their own. A registered PO is GP's record and is never rewritten, and a
line a buyer has already set either way keeps what they set.

No downgrade: after the fact a backfilled line cannot be told apart from one a buyer ticked.

Revision ID: 119
Revises: 118
Create Date: 2026-09-28
"""

from alembic import op

revision = "119"
down_revision = "118"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE po_line_items AS li
        SET job_cost = true,
            cost_code = po.cost_code
        FROM purchase_orders AS po
        WHERE li.po_id = po.id
          AND po.status = 'DRAFT'
          AND po.deleted_at IS NULL
          AND po.project_id IS NOT NULL
          AND li.job_cost = false
          AND li.cost_code IS NULL
          AND EXISTS (SELECT 1 FROM hardware_items AS hi WHERE hi.po_line_item_id = li.id)
        """
    )


def downgrade() -> None:
    pass
