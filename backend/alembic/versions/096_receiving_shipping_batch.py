"""Drop the keep-or-ship decision workflow; manual container lines; server-minted packing slips

Revision ID: 096
Revises: 095
Create Date: 2026-08-20

Four schema ops behind one PR:

- The keep-or-ship receive decision (#499, migration 090) is removed outright. A counted receive is
  now approved by a Warehouse Manager and booked straight to inventory, with no per-shipment decision
  ahead of it. This drops the `receive_decisions` table, its two enum types, and the
  RECEIVE_DECISION_REQUIRED notification value (deleting any row that carried it - none should, the
  question was answered in-app and never left a standing notification once decided).
- `is_manual` lands on `shipment_container_items` and `packing_slip_items`: a free-text, off-inventory
  line a shipping user types straight into a container. It never touches the staged-pool arithmetic
  and is not returnable.
- `packing_slip_counter` is a single-row global sequence for server-minted PS-NNNNN packing slip
  numbers, seeded at 1.

Downgrade restores all of it: the notification value comes back, the decision enums and table are
recreated in their post-090 shape (record-or-draft, both unique, the has-source check), and the two
columns and the counter table are dropped. The recreated table is empty - the decision rows
themselves are not recoverable, which is expected for a feature rollback.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "096"
down_revision = "095"
branch_labels = None
depends_on = None

_DECISION_STATUS_ENUM = "receive_decision_status"
_DECISION_CHOICE_ENUM = "receive_decision_choice"

# notification_type as it stands after 092, minus RECEIVE_DECISION_REQUIRED.
_NOTIFICATION_TYPE_WITHOUT_DECISION = (
    "'PULL_REQUEST_CANCELLED', 'PULL_REQUEST_COMPLETED', 'SHIPMENT_COMPLETED', "
    "'INVENTORY_SHORTFALL', 'GP_WRITE_FAILED', 'RECEIVE_DRAFT_SUBMITTED', 'RECEIVE_DRAFT_REJECTED'"
)


def upgrade() -> None:
    # --- Drop the keep-or-ship decision workflow -------------------------------------------------
    op.drop_table("receive_decisions")
    sa.Enum(name=_DECISION_CHOICE_ENUM).drop(op.get_bind(), checkfirst=True)
    sa.Enum(name=_DECISION_STATUS_ENUM).drop(op.get_bind(), checkfirst=True)

    # Recast notification_type to drop RECEIVE_DECISION_REQUIRED, the same rename/create/cast/drop
    # shape 092 used - PostgreSQL cannot remove a label from an enum in place. The DELETE keeps the
    # cast valid even though no standing row should carry the value.
    op.execute("DELETE FROM notifications WHERE type::text = 'RECEIVE_DECISION_REQUIRED'")
    op.execute("ALTER TYPE notification_type RENAME TO notification_type_old")
    op.execute(f"CREATE TYPE notification_type AS ENUM ({_NOTIFICATION_TYPE_WITHOUT_DECISION})")
    op.execute("ALTER TABLE notifications ALTER COLUMN type TYPE notification_type USING type::text::notification_type")
    op.execute("DROP TYPE notification_type_old")

    # --- Manual container lines ------------------------------------------------------------------
    op.add_column(
        "shipment_container_items",
        sa.Column("is_manual", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "packing_slip_items",
        sa.Column("is_manual", sa.Boolean(), nullable=False, server_default="false"),
    )

    # --- Server-minted packing slip numbers ------------------------------------------------------
    op.create_table(
        "packing_slip_counter",
        sa.Column("is_singleton", sa.Boolean(), primary_key=True),
        sa.Column("next_value", sa.Integer(), nullable=False),
    )
    op.execute("INSERT INTO packing_slip_counter (is_singleton, next_value) VALUES (true, 1)")


def downgrade() -> None:
    # --- Server-minted packing slip numbers ------------------------------------------------------
    op.drop_table("packing_slip_counter")

    # --- Manual container lines ------------------------------------------------------------------
    op.drop_column("packing_slip_items", "is_manual")
    op.drop_column("shipment_container_items", "is_manual")

    # --- Restore the keep-or-ship decision workflow ----------------------------------------------
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'RECEIVE_DECISION_REQUIRED'")

    # Recreate the table in its post-090 shape: record-or-draft sourced, both ends unique, the
    # has-source check. Empty - the decision rows themselves are not recoverable on a feature rollback.
    op.create_table(
        "receive_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "receive_record_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("receive_records.id"),
            nullable=True,
        ),
        sa.Column("po_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("purchase_orders.id"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("target_user_id", sa.String(), nullable=True),
        sa.Column("status", sa.Enum("PENDING", "DECIDED", name=_DECISION_STATUS_ENUM), nullable=False),
        sa.Column(
            "decision",
            sa.Enum("KEEP_IN_INVENTORY", "SHIP_OUT", name=_DECISION_CHOICE_ENUM),
            nullable=True,
        ),
        sa.Column("decided_by_user_id", sa.String(), nullable=True),
        sa.Column("decided_by_name", sa.String(), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column(
            "receive_draft_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("receive_drafts.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.UniqueConstraint("receive_record_id", name="uq_receive_decisions_receive_record"),
        sa.UniqueConstraint("receive_draft_id", name="uq_receive_decisions_receive_draft"),
        sa.CheckConstraint(
            "receive_record_id IS NOT NULL OR receive_draft_id IS NOT NULL",
            name="ck_receive_decisions_has_source",
        ),
    )
    op.create_index("ix_receive_decisions_target_status", "receive_decisions", ["target_user_id", "status"])
    op.create_index("ix_receive_decisions_po_id", "receive_decisions", ["po_id"])
