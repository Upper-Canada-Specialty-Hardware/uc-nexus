"""name queued PO registrations by request number and job (issue #854)

A queued register-PO write was labelled "Register PO <id> in GP" - the draft has no GP number yet, so
the PO's internal id was the only handle - and that is what the held-registrations panel on the PO
table showed. New writes are named "Register PO-REQ-097 (job 80001) in GP"; this renames the ones
already in the queue the same way, matching each to its PO through the write's `po:<id>` entity key.

No downgrade: the old label was only ever the internal id, which the entity key still carries.

Revision ID: 120
Revises: 119
Create Date: 2026-09-28
"""

from alembic import op

revision = "120"
down_revision = "119"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE gp_write_outbox AS o
        SET label = 'Register ' || COALESCE(po.request_number, po.po_number, po.id::text)
                    || COALESCE(' (job ' || p.project_id || ')', '')
                    || ' in GP'
        FROM purchase_orders AS po
        LEFT JOIN projects AS p ON p.id = po.project_id
        WHERE o.relay_op = 'create_po'
          AND o.entity_key = 'po:' || po.id::text
          AND o.label = 'Register PO ' || po.id::text || ' in GP'
        """
    )


def downgrade() -> None:
    pass
