import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from . import Base
from .enums import ReservationSource


class InventoryReservation(Base):
    """A request's claim on a quantity of one product in one project, held from the moment the
    request is created until the pull that spends it is approved (#342).

    Creating a shop-assembly or shipping-out request reserves the hardware it needs, so
    **available = on-hand - deficient - active reservations**. That is what makes the creator abide
    by what is really free at creation time (they refine the selection when it does not fit) instead
    of discovering a shortfall at accept, and it is what removed the accept-vs-pull TOCTOU race: by
    the time the warehouse approves the pull, the units it is about to deduct were already spoken
    for by this very request.

    Note what is NOT here, deliberately:

    - **No opening, no door leaf.** Same rule as `InventoryLocation` - a hinge is a hinge
      (docs/HARDWARE_IDENTITY_LIFECYCLE.md). A reservation is a claim on fungible stock, and the
      identity is re-attached later by the pull line that tags the units onto a leaf.
    - **No `inventory_location_id`.** Reservations are aggregate-level, per
      (project, hardware_category, product_code). Pinning a claim to specific rows would fight FIFO
      deduction, which stays exactly as it was: at approval the pull walks the project's rows
      oldest-first, and the reservation only ever governed *how much* was free, never *which* row.

    Exactly one of `shop_assembly_request_id` / `shipping_out_request_id` is set, matching `source`.
    """

    __tablename__ = "inventory_reservations"
    __table_args__ = (
        # The availability sum is per project + combo, and it runs on every request creation and
        # every pull approval.
        Index(
            "ix_inventory_reservations_project_combo",
            "project_id",
            "hardware_category",
            "product_code",
        ),
        # Release and consumption are both "every reservation of this request".
        Index("ix_inventory_reservations_shop_assembly_request", "shop_assembly_request_id"),
        Index("ix_inventory_reservations_shipping_out_request", "shipping_out_request_id"),
        CheckConstraint("quantity >= 1", name="ck_inventory_reservations_quantity_positive"),
        # The discriminator and the FKs cannot disagree, and a reservation can never be orphaned
        # from its request (which is what would strand a claim nothing can ever release).
        CheckConstraint(
            "(source = 'SHOP_ASSEMBLY_REQUEST' AND shop_assembly_request_id IS NOT NULL "
            "AND shipping_out_request_id IS NULL) "
            "OR (source = 'SHIPPING_OUT_REQUEST' AND shipping_out_request_id IS NOT NULL "
            "AND shop_assembly_request_id IS NULL)",
            name="ck_inventory_reservations_source_matches_request",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    hardware_category: Mapped[str] = mapped_column(String, nullable=False)
    product_code: Mapped[str] = mapped_column(String, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[ReservationSource] = mapped_column(
        Enum(ReservationSource, name="reservation_source", create_constraint=True),
        nullable=False,
    )
    shop_assembly_request_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("shop_assembly_requests.id", ondelete="CASCADE"), nullable=True
    )
    shipping_out_request_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("shipping_out_requests.id", ondelete="CASCADE"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)
