import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base
from .enums import ShopAssemblyBatchStatus, ShopAssemblyOpeningStatus, ShopAssemblyRequestStatus


class ShopAssemblyRequest(Base):
    """A PM's flag that these openings need assembling as soon as the hardware is there (#646).

    Creation is pure flagging: no allocation, no availability gate, no reservation, no pull. The
    request records which openings were flagged and what each was still owed at the moment it was
    raised, and then it waits - indefinitely, if the hardware never arrives.

    The Shop Assembly Manager works it in BATCHES. A batch is a chosen subset of the still-pending
    openings with a per-line allocated quantity, and creating one is what gates on availability,
    reserves stock and mints the warehouse PullRequest. That is why there is no `pull_request_id`
    here any more: a request has many pulls over its life, one per batch, and the link lives on the
    batch (`ShopAssemblyBatch.pull_request_id`).

    `approved_by` / `approved_at` keep their column names and widen their meaning: who finished the
    request off (last batch or dismissal) and when. There is no single accept moment to record.
    """

    __tablename__ = "shop_assembly_requests"
    __table_args__ = (Index("ix_shop_assembly_requests_project_status", "project_id", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    request_number: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    status: Mapped[ShopAssemblyRequestStatus] = mapped_column(
        Enum(
            ShopAssemblyRequestStatus,
            name="shop_assembly_request_status",
            create_constraint=True,
        ),
        nullable=False,
    )
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String, nullable=True)
    rejected_by: Mapped[str | None] = mapped_column(String, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Something happened to this request after it was created that the manager has to know about
    # before they work it (#342): a `replace_schedule=True` re-upload landed while it was in flight,
    # so its bill of hardware may no longer match the schedule. Null means nothing has. Surfaced as
    # `integrityNote` on the review screen.
    #
    # The second writer this field used to have is gone: nothing can strip a *pending* request's
    # claim any more, because a pending request never holds one.
    integrity_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)
    approved_at: Mapped[datetime | None] = mapped_column(nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(nullable=True)

    items: Mapped[list["ShopAssemblyRequestItem"]] = relationship(back_populates="shop_assembly_request")
    openings: Mapped[list["ShopAssemblyRequestOpening"]] = relationship(back_populates="shop_assembly_request")
    batches: Mapped[list["ShopAssemblyBatch"]] = relationship(back_populates="shop_assembly_request")


class ShopAssemblyRequestItem(Base):
    """One flat line on a shop-assembly request: this much of this product, owed to this opening.

    `requested_quantity` is what the opening was still owed when the PM raised the request - the
    composer's `max(owed - sent - claimed, 0)`, not the schedule's raw figure. There is deliberately
    NO allocated quantity here: nothing is allocated at creation, and a column reading 0 on every
    fresh line would say the opposite of what is true. Allocation lives on `ShopAssemblyBatchItem`,
    which is where a number was actually decided.
    """

    __tablename__ = "shop_assembly_request_items"
    __table_args__ = (
        Index("ix_shop_assembly_request_items_request", "shop_assembly_request_id"),
        CheckConstraint("requested_quantity >= 1", name="ck_shop_assembly_request_items_quantity_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_assembly_request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shop_assembly_requests.id"), nullable=False)
    # Which opening this quantity is owed to. Nullable for the rows that predate #646; every line
    # written since then carries one, because the request IS a list of openings and a line hanging
    # off none of them could never be batched.
    opening_number: Mapped[str | None] = mapped_column(String, nullable=True)
    hardware_category: Mapped[str] = mapped_column(String, nullable=False)
    product_code: Mapped[str] = mapped_column(String, nullable=False)
    requested_quantity: Mapped[int] = mapped_column(Integer, nullable=False)

    shop_assembly_request: Mapped["ShopAssemblyRequest"] = relationship(back_populates="items")


class ShopAssemblyRequestOpening(Base):
    """One flagged opening's own state on the request (#646).

    The opening is the unit the manager decides about, so it needs somewhere to hold that decision.
    This is deliberately NOT the request -> openings -> items tree v1 dropped: the request's lines
    stay flat and tagged, and this row carries only the decision. Nothing hangs beneath it.
    """

    __tablename__ = "shop_assembly_request_openings"
    __table_args__ = (
        UniqueConstraint(
            "shop_assembly_request_id",
            "opening_number",
            name="uq_shop_assembly_request_openings_request_opening",
        ),
        Index("ix_shop_assembly_request_openings_request", "shop_assembly_request_id"),
        Index("ix_shop_assembly_request_openings_batch", "batch_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_assembly_request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shop_assembly_requests.id"), nullable=False)
    opening_number: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[ShopAssemblyOpeningStatus] = mapped_column(
        Enum(
            ShopAssemblyOpeningStatus,
            name="shop_assembly_opening_status",
            create_constraint=True,
        ),
        nullable=False,
    )
    # The batch that consumed this opening, while it is BATCHED. Cleared when that batch's pull is
    # cancelled and the opening comes back to PENDING.
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("shop_assembly_batches.id", ondelete="SET NULL"), nullable=True
    )
    dismissed_by: Mapped[str | None] = mapped_column(String, nullable=True)
    dismissed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    dismissal_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    shop_assembly_request: Mapped["ShopAssemblyRequest"] = relationship(back_populates="openings")


class ShopAssemblyBatch(Base):
    """One dispatch off a shop-assembly request: a subset of its pending openings, allocated (#646).

    Creating a batch is the whole of what accepting a request used to be, moved to where the numbers
    actually exist: it gates on available inventory for exactly its allocations, writes the
    reservations under its own id, and mints the warehouse PullRequest.

    `batch_number` is what the pull carries as its `request_number`, so the pick sheet reads as a
    dispatch of the request that raised it. `{request_number}-B{sequence}` - unique across the table
    because the request number is, and therefore unique among live pulls, which is what a re-mint
    after a discard relies on.
    """

    __tablename__ = "shop_assembly_batches"
    __table_args__ = (
        Index("ix_shop_assembly_batches_request", "shop_assembly_request_id"),
        Index("ix_shop_assembly_batches_pull_request", "pull_request_id"),
        UniqueConstraint(
            "shop_assembly_request_id",
            "sequence",
            name="uq_shop_assembly_batches_request_sequence",
        ),
        CheckConstraint("sequence >= 1", name="ck_shop_assembly_batches_sequence_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_assembly_request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shop_assembly_requests.id"), nullable=False)
    # Monotonic within the request, never reused - a discarded batch's number is spent, so a fresh
    # batch cannot collide with the cancelled pull that kept the old one for the record.
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    batch_number: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    status: Mapped[ShopAssemblyBatchStatus] = mapped_column(
        Enum(
            ShopAssemblyBatchStatus,
            name="shop_assembly_batch_status",
            create_constraint=True,
        ),
        nullable=False,
    )
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)
    pull_request_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("pull_requests.id"), nullable=True)

    shop_assembly_request: Mapped["ShopAssemblyRequest"] = relationship(back_populates="batches")
    items: Mapped[list["ShopAssemblyBatchItem"]] = relationship(back_populates="batch")


class ShopAssemblyBatchItem(Base):
    """What one batch actually allocated on one line: the number the manager decided.

    Equal to what is reserved and to what the minted pull asks for, which is the invariant the pick
    relies on. A line the manager allocated nothing to is simply not here - a zero row would put a
    pick on the sheet the warehouse cannot fill.
    """

    __tablename__ = "shop_assembly_batch_items"
    __table_args__ = (
        Index("ix_shop_assembly_batch_items_batch", "shop_assembly_batch_id"),
        CheckConstraint("allocated_quantity >= 1", name="ck_shop_assembly_batch_items_allocated_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_assembly_batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shop_assembly_batches.id"), nullable=False)
    opening_number: Mapped[str] = mapped_column(String, nullable=False)
    hardware_category: Mapped[str] = mapped_column(String, nullable=False)
    product_code: Mapped[str] = mapped_column(String, nullable=False)
    allocated_quantity: Mapped[int] = mapped_column(Integer, nullable=False)

    batch: Mapped["ShopAssemblyBatch"] = relationship(back_populates="items")
