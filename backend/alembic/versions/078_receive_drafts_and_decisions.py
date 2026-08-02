"""Receives become drafts a Warehouse Manager approves, and an approved receive asks where it goes

Revision ID: 078
Revises: 077
Create Date: 2026-08-02

Recording a receive was one action with no second pair of eyes: whoever counted the truck posted the
GP receipt and credited inventory in the same click. Two tables split that in half and add the
question nobody was being asked afterwards.

- `receive_drafts` / `receive_draft_line_items` hold a counted delivery that has not reached GP. The
  GP-first pipeline (relay receipt -> RCT###### -> persist -> inventory) now runs at approval, so a
  draft is purely a Nexus record of what somebody counted. Line quantities are rows because
  `po_line_item_id` is a real FK worth constraining and because the double-approve guard sums them in
  SQL; the aisle/row/bay triples are JSON because they reference nothing until approval and the shape
  is already what `gp_write_outbox.persist_context` carries for a queued receipt.
- `receive_decisions` is the question the PO's originator gets when their hardware lands: does this
  shipment stay in the project's inventory or go straight back out to site. One row per receive,
  never for a stock PO (a decision about which project's inventory to keep something in needs a
  project).
- `purchase_orders.created_by_user_id` is who that question is addressed to. Deliberately NOT
  backfilled: every pre-existing PO keeps a NULL and the decisions read falls back to matching the
  PO's GP buyer against the caller's own gpBuyerId, which costs one Clerk lookup for the person
  asking instead of a roster sweep inside the persist transaction of a receipt GP has already posted.

Downgrade drops all three tables and the column. It is lossy for anything mid-flight - a draft that
has not been approved is a count that only exists here - so it is a rollback of the feature, not a
routine reversal.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "078"
down_revision = "077"
branch_labels = None
depends_on = None

_DRAFT_STATUS_ENUM = "receive_draft_status"
_DECISION_STATUS_ENUM = "receive_decision_status"
_DECISION_CHOICE_ENUM = "receive_decision_choice"


def upgrade() -> None:
    op.create_table(
        "receive_drafts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("po_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("purchase_orders.id"), nullable=False),
        sa.Column("warehouse_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("warehouses.id"), nullable=True),
        sa.Column(
            "status",
            sa.Enum("PENDING_APPROVAL", "APPROVING", "APPROVED", "REJECTED", name=_DRAFT_STATUS_ENUM),
            nullable=False,
        ),
        sa.Column("created_by_user_id", sa.String(), nullable=False),
        sa.Column("created_by_name", sa.String(), nullable=False),
        sa.Column("reviewed_by_user_id", sa.String(), nullable=True),
        sa.Column("reviewed_by_name", sa.String(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("create_idempotency_key", sa.String(), nullable=True),
        sa.Column("approval_idempotency_key", sa.String(), nullable=True),
        # SET NULL rather than RESTRICT: an outbox row can be cleaned up long after it drained, and by
        # then receive_record_id is the link that matters.
        sa.Column(
            "approved_outbox_entry_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("gp_write_outbox.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "receive_record_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("receive_records.id"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_receive_drafts_po_id", "receive_drafts", ["po_id"])
    op.create_index("ix_receive_drafts_status", "receive_drafts", ["status"])
    op.create_index("ix_receive_drafts_created_by", "receive_drafts", ["created_by_user_id"])
    op.create_index(
        "ix_receive_drafts_create_idempotency_key",
        "receive_drafts",
        ["create_idempotency_key"],
        unique=True,
    )

    op.create_table(
        "receive_draft_line_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "receive_draft_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("receive_drafts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "po_line_item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("po_line_items.id"),
            nullable=False,
        ),
        sa.Column("hardware_category", sa.String(), nullable=False),
        sa.Column("product_code", sa.String(), nullable=False),
        sa.Column("quantity_received", sa.Integer(), nullable=False),
        sa.Column("locations", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("quantity_received >= 1", name="ck_receive_draft_line_items_quantity_positive"),
    )
    op.create_index("ix_receive_draft_line_items_draft", "receive_draft_line_items", ["receive_draft_id"])
    op.create_index("ix_receive_draft_line_items_po_line_item", "receive_draft_line_items", ["po_line_item_id"])

    op.create_table(
        "receive_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "receive_record_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("receive_records.id"),
            nullable=False,
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
        sa.UniqueConstraint("receive_record_id", name="uq_receive_decisions_receive_record"),
    )
    op.create_index("ix_receive_decisions_target_status", "receive_decisions", ["target_user_id", "status"])
    op.create_index("ix_receive_decisions_po_id", "receive_decisions", ["po_id"])

    op.add_column("purchase_orders", sa.Column("created_by_user_id", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("purchase_orders", "created_by_user_id")
    op.drop_index("ix_receive_decisions_po_id", table_name="receive_decisions")
    op.drop_index("ix_receive_decisions_target_status", table_name="receive_decisions")
    op.drop_table("receive_decisions")
    op.drop_index("ix_receive_draft_line_items_po_line_item", table_name="receive_draft_line_items")
    op.drop_index("ix_receive_draft_line_items_draft", table_name="receive_draft_line_items")
    op.drop_table("receive_draft_line_items")
    op.drop_index("ix_receive_drafts_create_idempotency_key", table_name="receive_drafts")
    op.drop_index("ix_receive_drafts_created_by", table_name="receive_drafts")
    op.drop_index("ix_receive_drafts_status", table_name="receive_drafts")
    op.drop_index("ix_receive_drafts_po_id", table_name="receive_drafts")
    op.drop_table("receive_drafts")
    sa.Enum(name=_DECISION_CHOICE_ENUM).drop(op.get_bind(), checkfirst=True)
    sa.Enum(name=_DECISION_STATUS_ENUM).drop(op.get_bind(), checkfirst=True)
    sa.Enum(name=_DRAFT_STATUS_ENUM).drop(op.get_bind(), checkfirst=True)
