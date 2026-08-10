import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base
from .enums import ShopAssemblyRequestStatus


class ShopAssemblyRequest(Base):
    """A shop-assembly task minted by Start-a-Request. It waits PENDING until a reviewer accepts it,
    at which point the accept mints the warehouse PullRequest (SHOP_ASSEMBLY, PENDING) and stamps
    pull_request_id.

    Structurally identical to ShippingOutRequest now that v1 stopped managing doors as objects: the
    request holds flat lines, not a request -> openings -> items tree. The door survives only as the
    `opening_number` tag on each line, which is what the pick sheet groups its carts by.
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
    # Something happened to this request after it was created that the acceptor has to know about
    # before they act on it (#342). Two writers, one field, because the acceptor's question is the
    # same either way - "can I still trust this request?":
    #   - a `replace_schedule=True` re-upload landed while the request was in flight, so its bill of
    #     hardware may no longer match the schedule;
    #   - the reservations backfill could not cover it, so it holds no claim on inventory and the
    #     pull can still come up short.
    # Null means nothing has happened to it. Surfaced as `integrityNote` on the accept UI.
    integrity_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)
    approved_at: Mapped[datetime | None] = mapped_column(nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(nullable=True)
    # Backfilled at accept: the warehouse PullRequest this request minted.
    pull_request_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("pull_requests.id"), nullable=True)

    items: Mapped[list["ShopAssemblyRequestItem"]] = relationship(back_populates="shop_assembly_request")


class ShopAssemblyRequestItem(Base):
    """One flat line on a shop-assembly request: this much of this product, tagged to this opening.

    The `opening_number` tag is the whole of what remains of the door. It is informational - grouping
    by it is a UI concern - and it is what re-attaches demand identity to hardware that receiving made
    fungible (docs/HARDWARE_IDENTITY_LIFECYCLE.md). Nothing keys off it, and no row anywhere hangs
    beneath it.
    """

    __tablename__ = "shop_assembly_request_items"
    __table_args__ = (
        Index("ix_shop_assembly_request_items_request", "shop_assembly_request_id"),
        CheckConstraint("quantity >= 1", name="ck_shop_assembly_request_items_quantity_positive"),
        CheckConstraint(
            "allocated_quantity >= 0 AND allocated_quantity <= quantity",
            name="ck_shop_assembly_request_items_allocated_within_quantity",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_assembly_request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shop_assembly_requests.id"), nullable=False)
    # Which door this quantity is owed to, as a tag. Null on a line raised straight off inventory -
    # a hinge on a shelf belongs to the project, not to a door.
    opening_number: Mapped[str | None] = mapped_column(String, nullable=True)
    hardware_category: Mapped[str] = mapped_column(String, nullable=False)
    product_code: Mapped[str] = mapped_column(String, nullable=False)
    # What the schedule says is owed, vs what the requester could actually claim out of available
    # inventory when the request was sent. Short is derived, never stored: short = quantity -
    # allocated_quantity. The authority on what is still missing is the *current* schedule compared
    # against what has been sent, not a backlog anybody works off this row.
    #
    # **No default.** An insert that forgot allocated_quantity would quietly write 0, pass the check
    # constraint, and produce a line that reads as entirely short. Omitting it is meant to fail loudly.
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    allocated_quantity: Mapped[int] = mapped_column(Integer, nullable=False)

    shop_assembly_request: Mapped["ShopAssemblyRequest"] = relationship(back_populates="items")
