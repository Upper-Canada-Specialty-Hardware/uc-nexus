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

    Exactly one of `shop_assembly_request_id` / `shipping_out_request_id` / `pull_request_id` is set,
    matching `source`.

    The third holder is a **replacement pull**, and it is the one claim with no request behind it: a
    deficiency found at the bench is not something anybody could have requested in advance. Before
    it existed, the PR-REPL pull went to the back of the queue - it held nothing, so any request
    created after the defect was found could claim the very stock the replacement was waiting on, and
    the pull stayed blocked while the warehouse watched the hardware walk. Reserving at flag time
    puts the replacement in the queue at the moment the defect is discovered, which is the moment the
    claim becomes real.
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
        Index("ix_inventory_reservations_pull_request", "pull_request_id"),
        CheckConstraint("quantity >= 1", name="ck_inventory_reservations_quantity_positive"),
        # The discriminator and the FKs cannot disagree, and a reservation can never be orphaned
        # from its holder (which is what would strand a claim nothing can ever release). Each source
        # requires exactly its own FK and nulls the other two.
        #
        # `source::text` rather than a bare enum comparison: the REPLACEMENT_PULL label and this
        # constraint were added in one migration, and PostgreSQL refuses to *use* a new enum label in
        # the transaction that created it. Comparing the column as text never touches the enum type,
        # so the migration needs no `COMMIT` in the middle of itself.
        CheckConstraint(
            "(source::text = 'SHOP_ASSEMBLY_REQUEST' AND shop_assembly_request_id IS NOT NULL "
            "AND shipping_out_request_id IS NULL AND pull_request_id IS NULL) "
            "OR (source::text = 'SHIPPING_OUT_REQUEST' AND shipping_out_request_id IS NOT NULL "
            "AND shop_assembly_request_id IS NULL AND pull_request_id IS NULL) "
            "OR (source::text = 'REPLACEMENT_PULL' AND pull_request_id IS NOT NULL "
            "AND shop_assembly_request_id IS NULL AND shipping_out_request_id IS NULL)",
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
    # The PR-REPL pull a REPLACEMENT_PULL claim is held for. CASCADE for the same reason as the other
    # two: `discard_pending_pull_request` hard-deletes a pull, and a claim outliving the only thing
    # that could ever spend or release it is a permanently stranded reservation.
    pull_request_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("pull_requests.id", ondelete="CASCADE"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)
