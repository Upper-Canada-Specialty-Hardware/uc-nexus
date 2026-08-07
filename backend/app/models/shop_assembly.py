import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index, Integer, SmallInteger, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base
from .enums import AssemblyStatus, OpeningReviewStatus, PullStatus, ShopAssemblyRequestStatus


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
        # The pooled review queue reads by review status across every project (#495), so this is
        # the index that whole page is served from.
        Index(
            "ix_shop_assembly_openings_review_status",
            "review_status",
        ),
        Index(
            "ix_shop_assembly_openings_opening_pull",
            "opening_id",
            "pull_status",
        ),
        # One opening is one cart, and a cart is either built or it is not (#343). `PullStatus`
        # keeps a PARTIAL label because the *aggregate* reading over a set of openings needs it, and
        # that reading is derived per pull (`get_pull_staging_summaries`), never stored. The check is
        # what makes "PARTIAL is never persisted here" structural rather than a comment.
        CheckConstraint(
            "pull_status IN ('NOT_PULLED', 'PULLED')",
            name="ck_shop_assembly_openings_pull_status_binary",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # The request this opening was imported under. Nullable since #222, when the *operational*
    # parent became the shop-assembly PullRequest below - `pull_request_id` is what the assembly
    # floor, staging and cancellation all key on, and the SAR approval flow that used to drive
    # `pull_status` from here was retired in #223.
    #
    # It is **not** dead weight and it is **not** unset on new rows: `finalize_import_session` stamps
    # it at creation, and the whole pipeline (#344) groups on it - `_opening_stage_counts`,
    # `_unit_counts`, `_shipped_counts` and `get_assembly_pipeline` all read a request's openings
    # through this column, because it is the only link that survives a pull being cancelled
    # (cancellation nulls `pull_request_id`). Null means a legacy #222-era opening that hangs off a
    # PullRequest alone; those are invisible to the pipeline, which is why it has no request to be a
    # pipeline of.
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
    # #495: review is per leaf now, not per request. One contentious leaf used to hold up every
    # other leaf on the same request, and the reviewer works a pooled queue across projects rather
    # than a request at a time. The request's own status becomes a derived display value: PENDING
    # while any opening is PENDING, APPROVED once none are.
    review_status: Mapped[OpeningReviewStatus] = mapped_column(
        Enum(OpeningReviewStatus, name="opening_review_status", create_constraint=True),
        nullable=False,
        default=OpeningReviewStatus.PENDING,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String, nullable=True)
    # Why it was rejected or deferred. Null on an accept - there is nothing to explain.
    review_reason: Mapped[str | None] = mapped_column(String, nullable=True)

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
        # Progress can never exceed what was actually pulled for the line, and no count can go
        # negative (#340/#341). The three buckets partition `allocated_quantity`, not `quantity`:
        # installed + deficient + replacement_pending <= allocated, and completion requires
        # equality. That is what lets a replacement arriving on an already-completed leaf move a unit
        # out of `deficient` without the leaf reading as un-dispositioned - the unit lands in
        # replacement_pending, and the sum is unchanged - while the short units (quantity -
        # allocated) sit outside the partition entirely, because they were never pulled.
        CheckConstraint(
            "installed_quantity >= 0 AND deficient_quantity >= 0 AND replacement_pending_quantity >= 0 "
            "AND allocated_quantity >= 0 AND allocated_quantity <= quantity "
            "AND installed_quantity + deficient_quantity + replacement_pending_quantity <= allocated_quantity",
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
    # What the schedule says this leaf is owed, vs what the requester could actually claim out of
    # available inventory when the request was sent. Shop assembly is not all-or-nothing: a partially
    # covered leaf still goes to the bench, and the requester makes the informed send/don't-send call.
    #   quantity           - owed. The schedule's number, never reduced by scarcity.
    #   allocated_quantity - what was reserved, pulled and will physically arrive on the cart.
    # **Short is derived, never stored**: short = quantity - allocated_quantity. There is no separate
    # state for it and nothing downstream may write one, because the authority on what is still
    # missing is the *current* schedule compared against what is physically on the leaf - the short
    # count here is evidence of what this request executed, not a backlog anybody works off.
    # Backfilling a short leaf when stock turns up later belongs to the reallocation module.
    #
    # 0 is legal: a line can be fully short on a leaf that other lines do cover. A leaf with *every*
    # line at 0 has an empty cart and is dropped before it reaches here.
    #
    # **No default, client-side or server-side.** Migration 070 uses a server default only to get the
    # NOT NULL column onto a populated table and drops it in the same step, and mirroring a default
    # here would put the footgun straight back: an insert that forgot this column would quietly write
    # 0, pass the check constraint, and produce a line that reads as entirely short. Omitting it is
    # meant to fail loudly.
    allocated_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    # Per-item assembly progress (#340). The assembler records these incrementally at the bench;
    # completion reads them rather than taking an ephemeral checklist as input.
    #   installed_quantity - units physically fitted to the leaf. Absolute, editable both directions
    #     until the opening is completed, then frozen as the OpeningItemHardware quantity.
    #   deficient_quantity - units found defective and already handed to the deficiency flow
    #     (returned to inventory flagged deficient + a PR-REPL replacement line). Only ever grows;
    #     undoing a deficiency is deficiency review's job, not the assembler's.
    # Remaining (allocated - installed - deficient) is derived, never stored; completion is refused
    # while any line still has remaining > 0. It counts against `allocated_quantity`, not `quantity`:
    # a short unit was never pulled, so there is nothing for the assembler to disposition.
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
