"""GP's per-line PO entry fields, one column order for every line, and the buyer gate dropped

Revision ID: 113
Revises: 112
Create Date: 2026-09-10

GP's Purchase Order Entry takes a cost code, a product indicator and a unit of measure per LINE, so
a GP PO LINE ITEM's Nexus copy carries all three. `job_cost` is the product indicator (true is a
job-cost line, false a non-inventoried one), backfilled from whether the PO has a project; `cost_code`
is backfilled from the PO's own code on the lines that book to a job; `uofm` is 'Each', which is what
every registration has sent GP so far.

The two identity columns are also put the same way round on every line. They already held GP's item
number in `hardware_category` and GP's description in `product_code` on a NEXUS REGISTERED LINE, but
the mirror wrote them the other way round on every line it created - so a register showing both kinds
of line showed the two columns swapped against each other. The mirrored lines are swapped here to
match, and nothing else in the schema moves.

Last, the per-project buyer gate is gone. `buyer_assignments` and `buyer_assignment_projects` said
which jobs a GP buyer was allowed to raise a PO for; that answer now comes from GP alone, so both
tables go. The downgrade rebuilds them exactly as the model declared them, empty.
"""

import sqlalchemy as sa

from alembic import op

revision = "113"
down_revision = "112"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("po_line_items", sa.Column("cost_code", sa.String(length=50), nullable=True))
    op.add_column("po_line_items", sa.Column("uofm", sa.String(length=9), nullable=True))
    op.add_column(
        "po_line_items",
        sa.Column("job_cost", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # A line books to a job exactly when its PO has a project, which is the rule every registration
    # has applied so far: a project PO made all of its lines job-cost, a stock PO none of them.
    op.execute(
        "UPDATE po_line_items SET job_cost = true "
        "WHERE po_id IN (SELECT id FROM purchase_orders WHERE project_id IS NOT NULL)"
    )
    # Only a job-cost line has a cost code in GP, and Nexus held exactly one per PO until now.
    op.execute(
        "UPDATE po_line_items li SET cost_code = po.cost_code "
        "FROM purchase_orders po WHERE po.id = li.po_id AND li.job_cost"
    )
    op.execute("UPDATE po_line_items SET uofm = 'Each'")
    # Put GP's item number in hardware_category and GP's description in product_code on the lines the
    # mirror wrote the other way round. A NEXUS REGISTERED LINE already holds them this way.
    op.execute(
        "UPDATE po_line_items SET hardware_category = product_code, product_code = hardware_category "
        "WHERE nexus_registered = false"
    )

    op.drop_table("buyer_assignment_projects")
    op.drop_table("buyer_assignments")


def downgrade() -> None:
    op.create_table(
        "buyer_assignments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("buyer_id", sa.String(length=15), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("buyer_id", name="uq_buyer_assignments_buyer_id"),
    )
    op.create_table(
        "buyer_assignment_projects",
        sa.Column("buyer_assignment_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["buyer_assignment_id"], ["buyer_assignments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("buyer_assignment_id", "project_id"),
    )

    op.execute(
        "UPDATE po_line_items SET hardware_category = product_code, product_code = hardware_category "
        "WHERE nexus_registered = false"
    )
    op.drop_column("po_line_items", "job_cost")
    op.drop_column("po_line_items", "uofm")
    op.drop_column("po_line_items", "cost_code")
