import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from . import Base
from .enums import ReservationSource


class InventoryReservation(Base):
    """A claim on a quantity of one product in one project, held from the moment somebody commits to
    pulling it until the pull that spends it is picked (#342).

    Two holders raise one, and they commit at different moments:

    - a **shipping-out request**, at creation. The composer is held to what is really free, so a
      shortfall is refined away there rather than discovered at accept.
    - a **shop-assembly batch**, at batching (#646). The request that batch came off reserves
      nothing - it is a flag the PM raised, possibly months before the hardware exists - so the
      claim is minted when the Shop Assembly Manager actually allocates.

    Either way **available = on-hand - deficient - active reservations**, and by the time the
    warehouse picks the pull the units it is about to deduct were already spoken for by this holder.

    Note what is NOT here, deliberately:

    - **No opening, no door leaf.** Same rule as `InventoryLocation` - a hinge is a hinge
      (docs/HARDWARE_IDENTITY_LIFECYCLE.md). A reservation is a claim on fungible stock, and the
      identity is re-attached later by the pull line that tags the units onto a leaf.
    - **No `inventory_location_id`.** Reservations are aggregate-level, per
      (project, hardware_category, product_code). Pinning a claim to specific rows would fight FIFO
      deduction, which stays exactly as it was: at approval the pull walks the project's rows
      oldest-first, and the reservation only ever governed *how much* was free, never *which* row.

    Exactly one of `shop_assembly_batch_id` / `shipping_out_request_id` is set, matching `source`.
    Every claim has a holder behind it, and the holder is the thing a cancellation releases.
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
        # Release and consumption are both "every reservation of this holder".
        Index("ix_inventory_reservations_shop_assembly_batch", "shop_assembly_batch_id"),
        Index("ix_inventory_reservations_shipping_out_request", "shipping_out_request_id"),
        CheckConstraint("quantity >= 1", name="ck_inventory_reservations_quantity_positive"),
        # The discriminator and the FK cannot disagree, and a reservation can never be orphaned from
        # its holder (which is what would strand a claim nothing can ever release). Each source
        # requires exactly its own FK and nulls the other.
        #
        # `source::text` rather than a bare enum comparison, so a migration that changes the labels
        # never has to touch the enum type inside the same transaction that rewrites this - which is
        # exactly what #646 did when SHOP_ASSEMBLY_REQUEST became SHOP_ASSEMBLY_BATCH.
        CheckConstraint(
            "(source::text = 'SHOP_ASSEMBLY_BATCH' AND shop_assembly_batch_id IS NOT NULL "
            "AND shipping_out_request_id IS NULL) "
            "OR (source::text = 'SHIPPING_OUT_REQUEST' AND shipping_out_request_id IS NOT NULL "
            "AND shop_assembly_batch_id IS NULL)",
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
    shop_assembly_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("shop_assembly_batches.id", ondelete="CASCADE"), nullable=True
    )
    shipping_out_request_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("shipping_out_requests.id", ondelete="CASCADE"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)
