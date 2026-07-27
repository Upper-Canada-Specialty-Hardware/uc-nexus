import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index, Integer, SmallInteger, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base
from .enums import AssemblyStatus, PullStatus, ShopAssemblyRequestStatus


class ShopAssemblyRequest(Base):
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
    #     hardware may no longer match the schedule (and any openings that vanished were dropped);
    #   - the reservations backfill could not cover it, so it holds no claim on inventory and the
    #     pull can still come up short.
    # Null means nothing has happened to it. Surfaced as `integrityNote` on the accept UI.
    integrity_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)
    approved_at: Mapped[datetime | None] = mapped_column(nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(nullable=True)

    openings: Mapped[list["ShopAssemblyOpening"]] = relationship(back_populates="shop_assembly_request")


class ShopAssemblyOpening(Base):
    __tablename__ = "shop_assembly_openings"
    __table_args__ = (
        Index(
            "ix_shop_assembly_openings_request",
            "shop_assembly_request_id",
        ),
        Index(
            "ix_shop_assembly_openings_pull_request",
            "pull_request_id",
        ),
        Index(
            "ix_shop_assembly_openings_opening_pull",
            "opening_id",
            "pull_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Legacy parent, nullable since #222 and now unused for new rows: openings created from
    # Start a Task hang off a PullRequest (pull_request_id below), not a SAR. The SAR approval
    # flow that used to set this was retired in #223; the column is kept for existing rows.
    shop_assembly_request_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("shop_assembly_requests.id"), nullable=True
    )
    # Current parent (#222): the shop-assembly PullRequest this opening was created under.
    pull_request_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("pull_requests.id"), nullable=True)
    # Historical UUID of the source opening at request time. Not FK-enforced; the source
    # Opening row may be deleted in a later re-upload, but this stamp is preserved.
    opening_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    opening_number: Mapped[str] = mapped_column(String, nullable=False)
    building: Mapped[str | None] = mapped_column(String, nullable=True)
    floor: Mapped[str | None] = mapped_column(String, nullable=True)
    location: Mapped[str | None] = mapped_column(String, nullable=True)
    # Door leaf this assembly work unit is for (#311): 1 or 2. A pair produces two rows sharing
    # opening_number, one per leaf. Null = legacy whole-opening unit.
    leaf: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    # NOT_PULLED until the warehouse confirms this opening's cart is built, then PULLED (#343).
    # Only ever these two values: PARTIAL is an aggregate reading over a *set* of openings and is
    # derived for the pull as a whole, never written here - one cart cannot be half-built.
    pull_status: Mapped[PullStatus] = mapped_column(
        Enum(PullStatus, name="pull_status", create_constraint=True),
        nullable=False,
    )
    # When this opening was confirmed staged, and by whom (#343). Staging is per opening now, so the
    # pull's own completed_at can no longer say when *this* cart became workable - which is the
    # question the assembly floor asks when a leaf turns up late.
    staged_at: Mapped[datetime | None] = mapped_column(nullable=True)
    staged_by: Mapped[str | None] = mapped_column(String, nullable=True)
    # Stable Clerk user id the opening is claimed by (#324): the identity myWork filters on, so a
    # display-name change or a non-UI caller no longer detaches in-flight work. assigned_to below
    # stays the human-readable name for display; both are set/cleared together.
    assigned_to_user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    assigned_to: Mapped[str | None] = mapped_column(String, nullable=True)
    assembly_status: Mapped[AssemblyStatus] = mapped_column(
        Enum(AssemblyStatus, name="assembly_status", create_constraint=True),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)

    shop_assembly_request: Mapped["ShopAssemblyRequest"] = relationship(back_populates="openings")
    items: Mapped[list["ShopAssemblyOpeningItem"]] = relationship(back_populates="shop_assembly_opening")


class ShopAssemblyOpeningItem(Base):
    __tablename__ = "shop_assembly_opening_items"
    __table_args__ = (
        Index(
            "ix_shop_assembly_opening_items_opening",
            "shop_assembly_opening_id",
        ),
        CheckConstraint("quantity >= 1", name="ck_shop_assembly_opening_items_quantity_positive"),
        # Progress can never exceed the planned quantity, and no count can go negative (#340/#341).
        # The three buckets partition the line: installed + deficient + replacement_pending <=
        # quantity, and completion requires equality. That is what lets a replacement arriving on an
        # already-completed leaf move a unit out of `deficient` without the leaf reading as
        # un-dispositioned - the unit lands in replacement_pending, and the sum is unchanged.
        CheckConstraint(
            "installed_quantity >= 0 AND deficient_quantity >= 0 AND replacement_pending_quantity >= 0 "
            "AND installed_quantity + deficient_quantity + replacement_pending_quantity <= quantity",
            name="ck_shop_assembly_opening_items_progress_within_quantity",
        ),
        # The replacement-install work queue and the shipping deficiency guard both scan for lines
        # with something outstanding; a partial index keeps that off a full table scan.
        Index(
            "ix_shop_assembly_opening_items_replacement_pending",
            "shop_assembly_opening_id",
            postgresql_where=text("replacement_pending_quantity > 0"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_assembly_opening_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shop_assembly_openings.id"), nullable=False)
    hardware_category: Mapped[str] = mapped_column(String, nullable=False)
    product_code: Mapped[str] = mapped_column(String, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    # Per-item assembly progress (#340). The assembler records these incrementally at the bench;
    # completion reads them rather than taking an ephemeral checklist as input.
    #   installed_quantity - units physically fitted to the leaf. Absolute, editable both directions
    #     until the opening is completed, then frozen as the OpeningItemHardware quantity.
    #   deficient_quantity - units found defective and already handed to the deficiency flow
    #     (returned to inventory flagged deficient + a PR-REPL replacement line). Only ever grows;
    #     undoing a deficiency is deficiency review's job, not the assembler's.
    # Remaining (quantity - installed - deficient) is derived, never stored; completion is refused
    # while any line still has remaining > 0.
    installed_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    deficient_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # Units whose replacement hardware has arrived but is not on the leaf yet (#341). Only ever
    # non-zero on a COMPLETED opening: while the leaf is still on the bench a completed PR-REPL pull
    # simply decrements deficient_quantity, and the unit reappears as remaining work in My Work.
    # Once the leaf is finished that would break the completion invariant
    # (installed + deficient == quantity), so the unit moves deficient -> replacement_pending
    # instead: the sum is unchanged, the leaf stays legitimately complete, and the outstanding unit
    # stays visible as a replacement-install work item and as the shipping "awaiting replacement"
    # flag. Installing it moves replacement_pending -> installed and appends/increments the
    # OpeningItemHardware row - the one legitimate post-completion write.
    replacement_pending_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    shop_assembly_opening: Mapped["ShopAssemblyOpening"] = relationship(back_populates="items")
