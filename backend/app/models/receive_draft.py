import uuid
from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base
from .enums import ReceiveDraftStatus


class ReceiveDraft(Base):
    """A counted delivery waiting on a Warehouse Manager.

    Receiving is GP-first: the relay posts the eConnect receipt, GP mints the RCT######, and only
    then does Nexus write a ReceiveRecord and credit inventory. That whole pipeline now runs at
    *approval* rather than at submission, and this row is what sits in between - a Nexus-only record
    of what somebody counted off a truck. Nothing here has touched GP and nothing is on a shelf.

    Two identities matter and they are deliberately different people:

    - `created_by_*` is the person who counted the hardware. Their display name is captured at
      creation and becomes `ReceiveRecord.received_by` at approval, because the receive is a record
      of who did the receiving, not of who signed it off.
    - `reviewed_by_*` is the approver or rejecter, stamped from the Clerk-authenticated caller (#427).

    `approval_idempotency_key` is what makes the claim safe. The approve path cannot hold a database
    lock across the relay round trip, so it flips the status to APPROVING in its own committed
    transaction and stores the key it was called with. A retry carrying the same key resumes through
    the GP idempotency ledger; anybody else gets a conflict naming the reviewer holding it.
    """

    __tablename__ = "receive_drafts"
    __table_args__ = (
        Index("ix_receive_drafts_po_id", "po_id"),
        Index("ix_receive_drafts_status", "status"),
        Index("ix_receive_drafts_created_by", "created_by_user_id"),
        Index("ix_receive_drafts_create_idempotency_key", "create_idempotency_key", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    po_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("purchase_orders.id"), nullable=False)
    warehouse_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("warehouses.id"), nullable=True)
    # #504: the packing slip this count was made against. Required at creation, but nullable in the
    # database so drafts raised before the requirement existed still load - those render as
    # "created before the requirement" rather than pretending a slip is missing.
    packing_slip_document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("po_documents.id"), nullable=True)
    status: Mapped[ReceiveDraftStatus] = mapped_column(
        Enum(ReceiveDraftStatus, name="receive_draft_status", create_constraint=True),
        nullable=False,
    )
    created_by_user_id: Mapped[str] = mapped_column(String, nullable=False)
    created_by_name: Mapped[str] = mapped_column(String, nullable=False)
    reviewed_by_user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    reviewed_by_name: Mapped[str | None] = mapped_column(String, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Deduplicates a resubmitted create: the browser mints one key per submit action and re-sends it
    # on a network retry, so a timeout that actually committed cannot leave two drafts on one PO.
    create_idempotency_key: Mapped[str | None] = mapped_column(String, nullable=True)
    approval_idempotency_key: Mapped[str | None] = mapped_column(String, nullable=True)
    # The outbox row the approval was queued onto when the relay was down. Set together with status
    # APPROVED; the ReceiveRecord appears later, when the worker drains it.
    approved_outbox_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("gp_write_outbox.id", ondelete="SET NULL"), nullable=True
    )
    receive_record_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("receive_records.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    line_items: Mapped[list["ReceiveDraftLineItem"]] = relationship(
        back_populates="receive_draft", cascade="all, delete-orphan"
    )


class ReceiveDraftLineItem(Base):
    """One PO line's counted quantity, and where the counter wants it put away.

    `locations` is JSON rather than rows because the aisle/row/bay triples reference nothing yet -
    the InventoryLocation rows they will become do not exist until approval - and the shape is
    already the system's lingua franca for exactly this: it is what `CreateReceiveDraftInput` sends
    and what `gp_write_outbox.persist_context` carries for a queued receipt. Storing it any other way
    would mean two translations where there is currently one.

    The line itself is a row: `po_line_item_id` is a real foreign key worth constraining, and it lets
    SQL answer "how much of this PO line is spoken for by drafts that are mid-approval" without
    unpacking JSON. Edits replace the whole set, mirroring `save_pick_draft` - a re-count is a new
    sheet, not a merge.
    """

    __tablename__ = "receive_draft_line_items"
    __table_args__ = (
        Index("ix_receive_draft_line_items_draft", "receive_draft_id"),
        Index("ix_receive_draft_line_items_po_line_item", "po_line_item_id"),
        CheckConstraint("quantity_received >= 1", name="ck_receive_draft_line_items_quantity_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    receive_draft_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("receive_drafts.id", ondelete="CASCADE"), nullable=False
    )
    po_line_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("po_line_items.id"), nullable=False)
    hardware_category: Mapped[str] = mapped_column(String, nullable=False)
    product_code: Mapped[str] = mapped_column(String, nullable=False)
    quantity_received: Mapped[int] = mapped_column(Integer, nullable=False)
    # [{aisle, row, bay, quantity, deficient_quantity}] - the CreateReceiveDraftInput shape verbatim.
    locations: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)

    receive_draft: Mapped["ReceiveDraft"] = relationship(back_populates="line_items")
