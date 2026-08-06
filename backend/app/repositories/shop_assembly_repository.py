"""Repository for shop assembly data access."""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, func, or_, select, true
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.errors import (
    ConflictError,
    InvalidStateTransitionError,
    NotFoundError,
    ValidationError,
)
from app.models.enums import (
    AssemblyStatus,
    AuditAction,
    AuditEntityType,
    OpeningItemState,
    OpeningReviewStatus,
    PullRequestItemType,
    PullRequestSource,
    PullRequestStatus,
    PullStatus,
    ReservationSource,
    ShopAssemblyRequestStatus,
)
from app.models.opening_item import OpeningItem as OpeningItemModel
from app.models.opening_item import OpeningItemHardware as OIHModel
from app.models.project import Project
from app.models.pull_request import (
    PullRequest as PullRequestModel,
)
from app.models.pull_request import (
    PullRequestItem as PullRequestItemModel,
)
from app.models.shop_assembly import (
    ShopAssemblyOpening,
    ShopAssemblyOpeningItem,
    ShopAssemblyRequest,
)
from app.repositories.stock.common import _log_audit_event
from app.services.locking import lock_rows

MAX_DEFICIENT_REASON_LENGTH = 500

# Assembly statuses an opening can still be worked in (#340). COMPLETED is terminal.
_WORKABLE_ASSEMBLY_STATUSES = (AssemblyStatus.PENDING, AssemblyStatus.IN_PROGRESS)

# Pull-request statuses under which an opening's own pull_status is meaningful (#343).
#
# This used to be `== COMPLETED` in three places, on the assumption that a pull is staged as one
# thing, so "the pull is done" and "this opening's hardware is on a cart" were the same fact. Since
# staging is per opening they are not: an opening staged first thing in the morning is workable
# while the rest of the pull is still being picked, and the pull only reaches COMPLETED when the
# last cart is built. Every one of those checks is now keyed on `ShopAssemblyOpening.pull_status ==
# PULLED` - the fact that actually governs - with the pull-status filter kept only to exclude a pull
# that was never accepted (PENDING) or was cancelled (hardware restocked; cancellation also detaches
# its openings, so this is belt-and-braces).
#
# Since #367 IN_PROGRESS no longer implies "stock deducted": a pull is IN_PROGRESS from the moment
# its pick is started, and `picked_at` is what says the hardware actually left. That does not weaken
# anything here, because every gate that lets work *happen* keys on the opening's own
# `pull_status == PULLED`, and staging is itself refused until the pick is confirmed. It does mean
# `assemble_list` shows an un-picked pull's openings as waiting, which is the same reading it already
# gives a picked-but-unstaged one, and is why that list is deliberately not a workability gate.
_APPROVED_PULL_STATUSES = (PullRequestStatus.IN_PROGRESS, PullRequestStatus.COMPLETED)


@dataclass
class AssemblyProgressUpdate:
    """One line of a progress save (#340).

    installed_quantity is ABSOLUTE - the total number of units of this line now fitted to the leaf.
    Sending the same value twice is a no-op, so a retried save cannot double-count, and a miscount can
    be corrected downward right up until the opening is completed. None leaves it untouched.

    flag_deficient_quantity is INCREMENTAL - units being condemned *now*, on top of whatever was
    already flagged. It is not absolute because flagging is not a state the assembler owns: each unit
    is immediately returned to inventory flagged deficient and given a PR-REPL replacement line, and
    unwinding that is deficiency review's job. A reason is required with it.
    """

    shop_assembly_opening_item_id: uuid.UUID
    installed_quantity: int | None = None
    flag_deficient_quantity: int | None = None
    deficient_reason: str | None = None


def get_assemble_list(
    session: Session,
    project_id: uuid.UUID | None = None,
) -> list[ShopAssemblyOpening]:
    """Query ShopAssemblyOpenings on an approved shop-assembly PullRequest (#222, re-keyed in #343).

    Approved, not completed. The pull is staged opening by opening now, so this list fills
    incrementally: an opening the warehouse has confirmed comes back PULLED and is workable straight
    away, while its neighbours on the same pull are still NOT_PULLED. The page groups on exactly that
    column, so the un-staged openings render as "waiting" rather than being invisible until the whole
    pull is picked - which is what the assembly floor wants to see coming.

    Workability is *not* decided here: `assign_openings`, `record_assembly_progress` and
    `complete_opening` each gate on the opening's own `pull_status`, so a NOT_PULLED row in this list
    can be looked at and not acted on.
    """
    stmt = (
        select(ShopAssemblyOpening)
        .join(
            PullRequestModel,
            ShopAssemblyOpening.pull_request_id == PullRequestModel.id,
        )
        .options(selectinload(ShopAssemblyOpening.items))
        .where(
            PullRequestModel.source == PullRequestSource.SHOP_ASSEMBLY,
            PullRequestModel.status.in_(_APPROVED_PULL_STATUSES),
        )
    )
    if project_id is not None:
        stmt = stmt.where(PullRequestModel.project_id == project_id)
    return list(session.scalars(stmt).unique().all())


def get_my_work(
    session: Session,
    assigned_to_user_id: str,
) -> list[ShopAssemblyOpening]:
    """Query ShopAssemblyOpenings claimed by a user (by stable Clerk user id, #324) that are still
    unfinished - PENDING or, since progress is persisted (#340), IN_PROGRESS. A leaf the assembler
    saved partial progress on has to stay in My Work or the work would be unreachable.

    Keyed on the *opening's* pull_status since #343: My Work is the list of leaves somebody can
    actually go and build, and a staged opening is buildable whether or not the rest of its pull has
    been picked. The old `PullRequest.status == COMPLETED` filter would have held a claimed,
    fully-staged leaf out of its own assembler's board until the last cart on the pull was finished.
    """
    stmt = (
        select(ShopAssemblyOpening)
        .join(
            PullRequestModel,
            ShopAssemblyOpening.pull_request_id == PullRequestModel.id,
        )
        .options(selectinload(ShopAssemblyOpening.items))
        .where(
            ShopAssemblyOpening.assigned_to_user_id == assigned_to_user_id,
            ShopAssemblyOpening.assembly_status.in_(_WORKABLE_ASSEMBLY_STATUSES),
            ShopAssemblyOpening.pull_status == PullStatus.PULLED,
            PullRequestModel.source == PullRequestSource.SHOP_ASSEMBLY,
            PullRequestModel.status.in_(_APPROVED_PULL_STATUSES),
        )
        .order_by(ShopAssemblyOpening.opening_number.asc())
    )
    return list(session.scalars(stmt).unique().all())


def assign_openings(
    session: Session,
    opening_ids: list[uuid.UUID],
    assigned_to_user_id: str,
    assigned_to_name: str,
    allow_reassign: bool = False,
) -> list[ShopAssemblyOpening]:
    """Assign ShopAssemblyOpenings to a user with pessimistic locking. Keyed on the stable Clerk
    user id (#324); assigned_to_name is the display name stored alongside for the UI.

    allow_reassign (#340) is the data-layer half of the reassignment rule. Progress is persisted on
    the item rows now, so moving a half-built leaf to another assembler is safe - the new owner opens
    it and sees exactly what the last one recorded - but "safe" is not "anyone's to take". Only the
    manager branch of the resolver passes allow_reassign=True; a self-claim never does, so a user
    cannot take an opening off the person holding it by claiming it themselves. Re-claiming an
    opening already assigned to the same user stays a no-op either way (it only refreshes the display
    name), so a stale UI does not turn a double-click into an error.
    """
    if not opening_ids:
        raise ValidationError("opening_ids must not be empty", field="opening_ids")
    if not assigned_to_user_id:
        raise ValidationError("assigned_to_user_id must not be empty", field="assigned_to_user_id")
    # Keep the pre-#324 invariant that an assigned opening always carries a display name.
    if not assigned_to_name:
        raise ValidationError("assigned_to must not be empty", field="assigned_to")

    locked = lock_rows(session, ShopAssemblyOpening, opening_ids)
    if len(locked) != len(opening_ids):
        found_ids = {o.id for o in locked}
        missing = [str(oid) for oid in opening_ids if oid not in found_ids]
        raise NotFoundError(f"ShopAssemblyOpenings not found: {missing}")

    # A COMPLETED opening is assignable only while it has replacement installs outstanding (#341) -
    # that is the "reassignable" half of the replacement work item, and it rides the existing manager
    # flow rather than a second assignment system. One scalar aggregate for the whole batch.
    completed_ids = {o.id for o in locked if o.assembly_status == AssemblyStatus.COMPLETED}
    with_pending_replacements: set[uuid.UUID] = set()
    if completed_ids:
        with_pending_replacements = set(
            session.scalars(
                select(ShopAssemblyOpeningItem.shop_assembly_opening_id)
                .where(
                    ShopAssemblyOpeningItem.shop_assembly_opening_id.in_(completed_ids),
                    ShopAssemblyOpeningItem.replacement_pending_quantity > 0,
                )
                .group_by(ShopAssemblyOpeningItem.shop_assembly_opening_id)
            ).all()
        )

    for opening in locked:
        if opening.pull_status != PullStatus.PULLED:
            raise InvalidStateTransitionError("Opening is not ready for assignment - hardware has not been pulled")
        if opening.assembly_status not in _WORKABLE_ASSEMBLY_STATUSES and opening.id not in with_pending_replacements:
            raise InvalidStateTransitionError("Opening assembly is already completed")
        already_held_by_someone_else = (
            opening.assigned_to_user_id is not None and opening.assigned_to_user_id != assigned_to_user_id
        )
        if already_held_by_someone_else and not allow_reassign:
            raise ConflictError(f"Opening already assigned to {opening.assigned_to}")
        opening.assigned_to_user_id = assigned_to_user_id
        opening.assigned_to = assigned_to_name

    return locked


def remove_opening_from_user(
    session: Session,
    opening_id: uuid.UUID,
) -> ShopAssemblyOpening:
    """Unassign a ShopAssemblyOpening.

    Allowed while the opening is PENDING or IN_PROGRESS (#340): saved progress lives on the item rows,
    not on the assignment, so returning a half-built leaf to the pool loses nothing - the next person
    to claim it picks up where the last one stopped. COMPLETED is terminal and refused.
    """
    stmt = (
        select(ShopAssemblyOpening)
        .options(selectinload(ShopAssemblyOpening.items))
        .where(ShopAssemblyOpening.id == opening_id)
    )
    opening = session.scalars(stmt).unique().first()
    if opening is None:
        raise NotFoundError(f"ShopAssemblyOpening {opening_id} not found")

    if opening.assembly_status not in _WORKABLE_ASSEMBLY_STATUSES:
        raise InvalidStateTransitionError("Cannot unassign a completed opening")
    if opening.assigned_to_user_id is None:
        raise ValidationError("Opening is not assigned to anyone", field="assigned_to_user_id")

    opening.assigned_to_user_id = None
    opening.assigned_to = None
    return opening


def _load_workable_opening(session: Session, opening_id: uuid.UUID) -> ShopAssemblyOpening:
    """Lock a ShopAssemblyOpening and re-read it with its items eager-loaded.

    lock_rows takes the row lock; the second read is what populates `items` (SELECT ... FOR UPDATE
    cannot be combined with the selectinload without locking the child rows too, which nothing here
    needs). Both statements hit the same identity map, so this is one row, locked.
    """
    if not lock_rows(session, ShopAssemblyOpening, [opening_id]):
        raise NotFoundError(f"ShopAssemblyOpening {opening_id} not found")
    stmt = (
        select(ShopAssemblyOpening)
        .options(selectinload(ShopAssemblyOpening.items))
        .where(ShopAssemblyOpening.id == opening_id)
    )
    return session.scalars(stmt).unique().first()


def _opening_project_id(session: Session, sa_opening: ShopAssemblyOpening) -> uuid.UUID | None:
    """The project an opening belongs to, via its shop-assembly PullRequest. Audit rows want it and
    a legacy opening may not have a PR yet, so this returns None rather than raising."""
    if sa_opening.pull_request_id is None:
        return None
    return session.scalar(select(PullRequestModel.project_id).where(PullRequestModel.id == sa_opening.pull_request_id))


def record_assembly_progress(
    session: Session,
    opening_id: uuid.UUID,
    updates: list[AssemblyProgressUpdate],
    performed_by: str | None = None,
) -> ShopAssemblyOpening:
    """Record what an assembler has actually fitted to a door leaf so far (#340).

    This is the write that makes assembly resumable. Before it, the checklist existed only in the
    browser until Mark Complete posted it, so a leaf half-built at the end of a shift lost everything
    and a defect found at 9am was not visible to the warehouse until the leaf was finished.

    Two kinds of update, deliberately asymmetric (see AssemblyProgressUpdate):

    - installed_quantity is set absolutely, so a save is idempotent and a miscount stays correctable
      in both directions right up until completion. Nothing leaves inventory here: the hardware was
      already deducted when the pull was approved, so counting it onto the leaf is work-tracking, not
      a stock movement.
    - flag_deficient_quantity condemns units immediately - report_deficiency_at_assembly returns them
      to project inventory flagged deficient and appends a PR-REPL replacement line the moment the
      defect is found, not at completion. That is the whole point of moving it here: the warehouse can
      start sourcing the replacement while the leaf is still on the bench. It is one-way from the
      assembler's side; deficiency review owns the undo.

    Nothing else is decremented for a deficient unit - deficient_quantity on the item is the record
    that those units are spoken for, and the remaining-must-be-zero gate at completion is what makes
    that count load-bearing.

    The first save flips the opening PENDING -> IN_PROGRESS. Returns the opening with items loaded.
    """
    if not updates:
        raise ValidationError("updates must not be empty", field="updates")

    sa_opening = _load_workable_opening(session, opening_id)

    if sa_opening.pull_status != PullStatus.PULLED:
        raise InvalidStateTransitionError("Opening hardware has not been pulled - there is nothing to assemble yet")
    if sa_opening.assembly_status not in _WORKABLE_ASSEMBLY_STATUSES:
        raise InvalidStateTransitionError("Opening assembly is already completed")
    if sa_opening.assigned_to_user_id is None:
        raise ValidationError(
            "Opening must be assigned before progress can be recorded",
            field="assigned_to_user_id",
        )

    item_by_id = {item.id: item for item in sa_opening.items}
    seen: set[uuid.UUID] = set()
    for update in updates:
        if update.shop_assembly_opening_item_id not in item_by_id:
            raise ValidationError(
                f"Item {update.shop_assembly_opening_item_id} does not belong to opening {opening_id}",
                field="shop_assembly_opening_item_id",
            )
        # Two updates for one line would make the absolute installed_quantity order-dependent, which
        # is exactly the ambiguity "absolute" is meant to remove. Refuse rather than pick a winner.
        if update.shop_assembly_opening_item_id in seen:
            raise ValidationError(
                f"Item {update.shop_assembly_opening_item_id} appears more than once in one save",
                field="shop_assembly_opening_item_id",
            )
        seen.add(update.shop_assembly_opening_item_id)

    from app.repositories import stock as stock_repository

    actor = performed_by or "Assembler"
    project_id = _opening_project_id(session, sa_opening)
    now = datetime.utcnow()

    # Validate every line before writing any of them, so a bad line at the end cannot leave the first
    # few lines applied (and, worse, their deficiencies already returned to inventory).
    planned: list[tuple] = []
    for update in updates:
        item = item_by_id[update.shop_assembly_opening_item_id]
        flagged = update.flag_deficient_quantity or 0
        reason: str | None = None
        if flagged:
            if flagged < 1:
                raise ValidationError("flag_deficient_quantity must be >= 1", field="flag_deficient_quantity")
            reason = (update.deficient_reason or "").strip()
            if not reason:
                raise ValidationError(
                    "A deficiency reason is required when flagging units deficient",
                    field="deficient_reason",
                )
            if len(reason) > MAX_DEFICIENT_REASON_LENGTH:
                raise ValidationError(
                    f"Deficiency reason must be {MAX_DEFICIENT_REASON_LENGTH} characters or fewer",
                    field="deficient_reason",
                )

        new_installed = item.installed_quantity if update.installed_quantity is None else update.installed_quantity
        new_deficient = item.deficient_quantity + flagged
        if new_installed < 0:
            raise ValidationError("installed_quantity must be >= 0", field="installed_quantity")
        # The cap is what was **allocated**, not what the schedule owed. Short units never left
        # inventory, so there is no unit on the cart for the assembler to install or condemn; letting
        # progress run to `quantity` would mean recording hardware onto a leaf that never arrived.
        if new_installed + new_deficient + item.replacement_pending_quantity > item.allocated_quantity:
            short_note = (
                f" ({item.quantity - item.allocated_quantity} of the {item.quantity} owed were never pulled)"
                if item.allocated_quantity < item.quantity
                else ""
            )
            raise ValidationError(
                f"{item.product_code}: {new_installed} installed + {new_deficient} deficient exceeds the "
                f"{item.allocated_quantity} unit(s) pulled for this leaf{short_note}",
                field="installed_quantity",
            )
        planned.append((item, new_installed, new_deficient, flagged, reason))

    changed = False
    for item, new_installed, new_deficient, flagged, reason in planned:
        previous_installed = item.installed_quantity
        if new_installed == previous_installed and not flagged:
            continue
        changed = True
        item.installed_quantity = new_installed
        item.deficient_quantity = new_deficient

        if flagged:
            # Immediate, not deferred to completion: the unit goes back to inventory flagged deficient
            # and the replacement pull is minted now.
            stock_repository.report_deficiency_at_assembly(
                session,
                sa_opening_item_id=item.id,
                quantity=flagged,
                reason_text=reason,
                performed_by=actor,
            )

        _log_audit_event(
            session,
            project_id=project_id,
            entity_type=AuditEntityType.SHOP_ASSEMBLY_OPENING,
            entity_id=sa_opening.id,
            action=AuditAction.INSTALL_PROGRESS,
            performed_by=actor,
            detail={
                "shopAssemblyOpeningItemId": str(item.id),
                "hardwareCategory": item.hardware_category,
                "productCode": item.product_code,
                "plannedQuantity": item.quantity,
                "allocatedQuantity": item.allocated_quantity,
                "previousInstalledQuantity": previous_installed,
                "installedQuantity": new_installed,
                "flaggedDeficientQuantity": flagged,
                "deficientQuantity": new_deficient,
                "remainingQuantity": item.allocated_quantity - new_installed - new_deficient,
                "reasonText": reason,
                "openingNumber": sa_opening.opening_number,
                "leaf": sa_opening.leaf,
                "recordedAt": now.isoformat(),
            },
        )

    if changed and sa_opening.assembly_status == AssemblyStatus.PENDING:
        sa_opening.assembly_status = AssemblyStatus.IN_PROGRESS

    return sa_opening


def complete_opening(
    session: Session,
    opening_id: uuid.UUID,
    completed_by: str | None = None,
) -> OpeningItemModel:
    """Mark an opening's assembly as complete. Creates OpeningItem + OpeningItemHardware records.

    Completion takes no checklist any more (#340). It reads the per-item counters
    record_assembly_progress has been persisting, so what is snapshotted onto the assembled leaf is
    what the assembler actually recorded fitting, unit by unit - not a claim made in the same call.
    Deficiencies were already returned to inventory and replaced when they were flagged, so this
    function no longer writes any of that.

    Completion no longer records a location either (#498). It used to take free-text aisle/row/bay
    from the ASSEMBLER, against no warehouse choice and no validation that the place existed - so
    the "put-away location" on an assembled leaf was whatever the person at the bench typed, and
    warehouse staff could not correct it. The leaf lands unlocated and joins the warehouse put-away
    queue, which is the same route received stock takes.
    """
    # 1. Load and validate ShopAssemblyOpening (with pessimistic lock)
    sa_opening = _load_workable_opening(session, opening_id)

    if sa_opening.assembly_status not in _WORKABLE_ASSEMBLY_STATUSES:
        raise InvalidStateTransitionError("Opening assembly is already completed")
    # This opening's own hardware has to be on a cart (#343). Until staging was per opening, the
    # `PullRequest.status == COMPLETED` lookup below carried this check implicitly; now that a pull
    # can be part-staged, the fact that governs is the opening's own pull_status, and it is checked
    # explicitly - the same gate record_assembly_progress and assign_openings already use.
    if sa_opening.pull_status != PullStatus.PULLED:
        raise InvalidStateTransitionError("Opening hardware has not been pulled - there is nothing to assemble yet")
    if sa_opening.assigned_to is None:
        raise ValidationError(
            "Opening must be assigned before it can be completed",
            field="assigned_to",
        )

    # 2. Load the shop-assembly PR this opening hangs off (#222). The FK gives it to us
    #    directly - no PR-number string parsing, no SAR lookup. It carries project_id and
    #    the LOOSE items that were pulled.
    if sa_opening.pull_request_id is None:
        raise NotFoundError(f"ShopAssemblyOpening {opening_id} is not linked to a pull request")
    # Only pr.project_id is read below (step 6 snapshots from sa_opening.items, not pr.items),
    # so don't eager-load pr.items - it would be a wasted query.
    pr_stmt = select(PullRequestModel).where(
        PullRequestModel.id == sa_opening.pull_request_id,
        PullRequestModel.source == PullRequestSource.SHOP_ASSEMBLY,
        PullRequestModel.status.in_(_APPROVED_PULL_STATUSES),
    )
    pr = session.scalars(pr_stmt).first()
    if pr is None:
        raise NotFoundError(f"Approved shop-assembly pull request for opening {opening_id} not found")

    # 3. Duplicate-completion guard (#339). Two shop-assembly openings can name the same
    #    (opening_id, leaf) - e.g. a request was reopened and re-imported, or the same leaf was sent
    #    to the shop twice - and completing both would mint a second assembled unit for one physical
    #    door leaf, double-counting inventory and letting the same leaf ship twice. Refuse if a live
    #    OpeningItem already exists for this leaf, using exactly the keying the pre-request REQ-5
    #    guard uses (find_already_assembled_openings: any state except SHIPPED_OUT, and a legacy
    #    null-leaf unit matches only a null-leaf spec).
    if find_already_assembled_openings(
        session, pr.project_id, [(sa_opening.opening_number, sa_opening.opening_id, sa_opening.leaf)]
    ):
        leaf_suffix = f" leaf {sa_opening.leaf}" if sa_opening.leaf is not None else ""
        raise ConflictError(
            f"Opening {sa_opening.opening_number}{leaf_suffix} has already been assembled - "
            "an assembled unit for it is still in the system",
            field="opening_id",
        )

    # 4. Every unit that arrived must be accounted for (#340). Business decision: block, never
    #    auto-default. An unrecorded unit is an unanswered question - was it fitted, is it still on
    #    the cart, is it missing? - and silently treating it as installed is what would put hardware
    #    on a leaf that was never there, while silently treating it as deficient would mint
    #    replacement pulls nobody asked for. Name the lines so the assembler knows which to finish.
    #
    #    Accounting is against `allocated_quantity`. **Short units are excused**: they were never
    #    pulled, so no amount of work at the bench can disposition them, and holding the leaf open
    #    for them would strand it forever waiting on hardware that was never requested. What is still
    #    owed is recorded by `quantity - allocated_quantity` and is the reallocation module's
    #    problem, not this assembler's.
    def _dispositioned(item) -> int:
        return item.installed_quantity + item.deficient_quantity + item.replacement_pending_quantity

    undispositioned = [
        f"{item.product_code} ({item.allocated_quantity - _dispositioned(item)} of "
        f"{item.allocated_quantity} unrecorded)"
        for item in sa_opening.items
        if _dispositioned(item) != item.allocated_quantity
    ]
    if undispositioned:
        raise ValidationError(
            "Cannot complete assembly while hardware is unaccounted for. Record each unit as "
            "installed or flag it deficient first: " + ", ".join(undispositioned),
            field="items",
        )

    # 4b. Refuse a completion with nothing installed on it (#339). If every unit was flagged
    #     deficient - or, since partial allocation, if nothing was ever pulled - the OpeningItem would
    #     be minted with zero OpeningItemHardware rows: an "assembled" leaf that had nothing on it,
    #     which then reads as ship-ready inventory. The deficiencies themselves stand (they were
    #     recorded when they were found, #340) and so does the shortfall; what is refused is calling
    #     the leaf assembled. One guard covers both causes, because the thing that makes it wrong is
    #     the same either way - an empty leaf is not a leaf.
    if sa_opening.items and all(item.installed_quantity == 0 for item in sa_opening.items):
        raise ValidationError(
            "Cannot complete an opening with nothing installed on it - every unit was either flagged "
            "deficient or never pulled, so nothing would be assembled. Leave the opening open until "
            "hardware is installed on it.",
            field="items",
        )

    # 5. Create OpeningItem (snapshot opening identity from the ShopAssemblyOpening row)
    now = datetime.utcnow()
    from app.repositories import warehouse_admin_repository

    opening_item = OpeningItemModel(
        id=uuid.uuid4(),
        project_id=pr.project_id,
        opening_id=sa_opening.opening_id,
        warehouse_id=warehouse_admin_repository.get_primary_warehouse_id(session),
        opening_number=sa_opening.opening_number,
        # Assembled unit is a single door leaf (#311): one OpeningItem per leaf, stamped from the
        # ShopAssemblyOpening. A pair yields two independently-located, independently-shippable units.
        leaf=sa_opening.leaf,
        building=sa_opening.building,
        floor=sa_opening.floor,
        location=sa_opening.location,
        quantity=1,
        assembly_completed_at=now,
        state=OpeningItemState.IN_INVENTORY,
        # #498: unlocated on purpose. The warehouse assigns a real warehouse + aisle/row/bay from
        # the put-away queue; until then this leaf reads "not put away yet".
        aisle=None,
        row=None,
        bay=None,
    )
    session.add(opening_item)
    try:
        session.flush()  # Get opening_item.id for OpeningItemHardware FK
    except IntegrityError as exc:
        # `uq_opening_items_live_leaf` (#345) is step 3's guard as a database invariant, and it is
        # what actually holds when two assemblers finish two ShopAssemblyOpenings naming the same
        # leaf at once: step 3 is a read-then-write, and both readers can see nothing. Translate it
        # into the same typed conflict the guard raises so the loser gets the identical message
        # rather than a 500.
        if "uq_opening_items_live_leaf" not in str(getattr(exc, "orig", exc)):
            raise
        leaf_suffix = f" leaf {sa_opening.leaf}" if sa_opening.leaf is not None else ""
        raise ConflictError(
            f"Opening {sa_opening.opening_number}{leaf_suffix} has already been assembled - "
            "an assembled unit for it is still in the system",
            field="opening_id",
        ) from exc

    # 6. Snapshot what was actually installed (#340): the recorded installed_quantity, not the
    #    planned quantity. A line whose units were all flagged deficient contributes no row at all -
    #    the leaf must not claim hardware that is sitting in the deficiency queue awaiting a
    #    replacement pull.
    for item in sa_opening.items:
        if item.installed_quantity <= 0:
            continue
        oih = OIHModel(
            id=uuid.uuid4(),
            opening_item_id=opening_item.id,
            product_code=item.product_code,
            hardware_category=item.hardware_category,
            quantity=item.installed_quantity,
        )
        session.add(oih)

    # 7. Mark ShopAssemblyOpening as Completed
    sa_opening.assembly_status = AssemblyStatus.COMPLETED
    sa_opening.completed_at = now

    # 8. Record the moment the tag became physical (#340). Progress saves and completion are separate
    #    calls now, so completion needs its own audit row - and it is the only place completed_by is
    #    written down, the assignment holding the name of whoever claimed the leaf, not who finished it.
    _log_audit_event(
        session,
        project_id=pr.project_id,
        entity_type=AuditEntityType.OPENING_ITEM,
        entity_id=opening_item.id,
        action=AuditAction.ASSEMBLY_COMPLETE,
        performed_by=completed_by or sa_opening.assigned_to or "Assembler",
        detail={
            "shopAssemblyOpeningId": str(sa_opening.id),
            "openingNumber": sa_opening.opening_number,
            "leaf": sa_opening.leaf,
            "assignedTo": sa_opening.assigned_to,
            "installedHardware": [
                {
                    "productCode": item.product_code,
                    "hardwareCategory": item.hardware_category,
                    "plannedQuantity": item.quantity,
                    "allocatedQuantity": item.allocated_quantity,
                    "installedQuantity": item.installed_quantity,
                    "deficientQuantity": item.deficient_quantity,
                    # What the schedule owed that this request never pulled. Recorded on the leaf's
                    # completion event so the execution is auditable after the fact.
                    "shortQuantity": item.quantity - item.allocated_quantity,
                }
                for item in sa_opening.items
            ],
            # #498: no location here any more. Completion does not place the leaf; the PUT_AWAY
            # audit row written when the warehouse assigns it is what records where it went.
        },
    )

    return opening_item


def find_assembled_leaf(
    session: Session,
    project_id: uuid.UUID,
    opening_id: uuid.UUID,
    leaf: int | None,
) -> OpeningItemModel | None:
    """The OpeningItem a completed shop-assembly work unit materialized as (#341).

    There is no FK from a ShopAssemblyOpening to the leaf it produced, so this keys it exactly the
    way find_already_assembled_openings does: (project, opening_id, leaf), with a legacy null leaf
    matching only a null leaf. A leaf can end up with more than one row over its life (it shipped,
    then a correction minted another), so a live row wins over a shipped one and the most recently
    assembled wins among equals - a shipped row is returned only when it is all there is, which is
    precisely the "replacement arrived after the leaf shipped" case.
    """
    rows = list(
        session.scalars(
            select(OpeningItemModel).where(
                OpeningItemModel.project_id == project_id,
                OpeningItemModel.opening_id == opening_id,
                OpeningItemModel.leaf.is_not_distinct_from(leaf),
            )
        ).all()
    )
    if not rows:
        return None
    live = [oi for oi in rows if oi.state != OpeningItemState.SHIPPED_OUT]
    return sorted(live or rows, key=lambda oi: oi.assembly_completed_at)[-1]


def _latest_assembly_lateral():
    """The ShopAssemblyOpening that produced the correlated `OpeningItemModel` row.

    **Exactly one assembly per leaf.** A leaf can be sent to the shop more than once - it shipped and
    a correction re-assembled it, or a request was reopened and re-imported - and (opening_id, leaf)
    alone matches every one of those work units. A plain join therefore made a newly assembled leaf
    inherit the *previous* assembly's counters. This resolves it the way `find_assembled_leaf`
    resolves the other direction: latest completion wins, bounded by the leaf's own
    `assembly_completed_at` so each assembled unit reads its own work unit and not a later one.

    Scoped to the leaf's own project, because `opening_id` is a historical stamp, not an FK, and a
    re-upload can reissue it.
    """
    return (
        select(ShopAssemblyOpening.id.label("sa_opening_id"))
        .join(PullRequestModel, PullRequestModel.id == ShopAssemblyOpening.pull_request_id)
        .where(
            ShopAssemblyOpening.opening_id == OpeningItemModel.opening_id,
            ShopAssemblyOpening.leaf.is_not_distinct_from(OpeningItemModel.leaf),
            ShopAssemblyOpening.assembly_status == AssemblyStatus.COMPLETED,
            PullRequestModel.project_id == OpeningItemModel.project_id,
            # The work unit that produced *this* leaf finished no later than the leaf did -
            # `complete_opening` stamps both from the same `now`. A legacy row with no completion
            # stamp is allowed through and ordered last, so it is picked only when nothing else fits.
            or_(
                ShopAssemblyOpening.completed_at.is_(None),
                ShopAssemblyOpening.completed_at <= OpeningItemModel.assembly_completed_at,
            ),
        )
        .order_by(
            ShopAssemblyOpening.completed_at.desc().nulls_last(),
            ShopAssemblyOpening.id.desc(),
        )
        .limit(1)
        .lateral("latest_assembly")
    )


@dataclass(frozen=True)
class LeafShortfall:
    """The two ways an assembled leaf can be short of the bill of hardware it ships under (#341).

    They are counted apart because the remedies are not the same, and a shipper deciding whether to
    send a leaf needs to know which one they are looking at:

    - `awaiting_replacement` - a unit arrived and failed. It was condemned, a PR-REPL pull already
      exists for it, and waiting is a real option.
    - `never_pulled` - a unit never arrived at all: the allocator could not claim it out of available
      inventory when the request was sent, so nothing was ever pulled and nothing is in flight.
      Waiting achieves nothing; that gap is closed by purchasing and, later, by reallocation.
    """

    awaiting_replacement: int
    never_pulled: int

    @property
    def total(self) -> int:
        return self.awaiting_replacement + self.never_pulled


def get_leaf_shortfalls(
    session: Session,
    opening_item_ids: Iterable[uuid.UUID],
) -> dict[uuid.UUID, LeafShortfall]:
    """Both shortfall readings per assembled leaf, in ONE grouped aggregate.

    Never a len() over loaded collections, and never one query per reading (CLAUDE.md perf rules):
    the shipping selection lists every assembled leaf in a project, so a per-leaf query would be an
    N+1 on the heaviest list in the module, and running the correlated lateral twice to get two sums
    out of the same rows would double the cost of the heaviest query in it. Only leaves with
    something outstanding are returned, so callers treat a missing key as "nothing outstanding".
    """
    ids = list(opening_item_ids)
    if not ids:
        return {}
    latest_assembly = _latest_assembly_lateral()
    awaiting = func.sum(
        ShopAssemblyOpeningItem.deficient_quantity + ShopAssemblyOpeningItem.replacement_pending_quantity
    )
    never_pulled = func.sum(ShopAssemblyOpeningItem.quantity - ShopAssemblyOpeningItem.allocated_quantity)
    stmt = (
        select(
            OpeningItemModel.id,
            awaiting.label("awaiting"),
            never_pulled.label("never_pulled"),
        )
        .select_from(OpeningItemModel)
        .join(latest_assembly, true())
        .join(
            ShopAssemblyOpeningItem,
            ShopAssemblyOpeningItem.shop_assembly_opening_id == latest_assembly.c.sa_opening_id,
        )
        .where(OpeningItemModel.id.in_(ids))
        .group_by(OpeningItemModel.id)
        .having(or_(awaiting > 0, never_pulled > 0))
    )
    return {
        row.id: LeafShortfall(awaiting_replacement=int(row.awaiting), never_pulled=int(row.never_pulled))
        for row in session.execute(stmt).all()
    }


def get_awaiting_replacement_quantities(
    session: Session,
    opening_item_ids: Iterable[uuid.UUID],
) -> dict[uuid.UUID, int]:
    """Per assembled leaf, how many units of its hardware are still owed *and were pulled* (#341):
    units condemned and not yet replaced, plus units whose replacement has arrived but is not fitted
    yet. Zero entries are dropped, so a missing key means "nothing outstanding".

    A named reading of `get_leaf_shortfalls` for the callers that only surface this half.
    """
    return {
        oi_id: shortfall.awaiting_replacement
        for oi_id, shortfall in get_leaf_shortfalls(session, opening_item_ids).items()
        if shortfall.awaiting_replacement > 0
    }


def get_never_pulled_quantities(
    session: Session,
    opening_item_ids: Iterable[uuid.UUID],
) -> dict[uuid.UUID, int]:
    """Per assembled leaf, how many units its schedule owed that the request never pulled.

    A named reading of `get_leaf_shortfalls` for the callers that only surface this half.
    """
    return {
        oi_id: shortfall.never_pulled
        for oi_id, shortfall in get_leaf_shortfalls(session, opening_item_ids).items()
        if shortfall.never_pulled > 0
    }


@dataclass(frozen=True)
class ReplacementWorkItem:
    """One outstanding replacement install on an already-completed leaf (#341).

    It is deliberately not a ShopAssemblyOpening: the opening is COMPLETED and must stay that way,
    so this cannot ride in My Work's normal list without either lying about the leaf's status or
    reopening a finished work unit. It is a separate, narrower unit of work - "fit these N units of
    this product to a leaf that is otherwise done".
    """

    shop_assembly_opening_item_id: uuid.UUID
    shop_assembly_opening_id: uuid.UUID
    project_id: uuid.UUID
    opening_number: str
    leaf: int | None
    building: str | None
    floor: str | None
    hardware_category: str
    product_code: str
    pending_quantity: int
    assigned_to_user_id: str | None
    assigned_to: str | None
    opening_item_id: uuid.UUID | None
    opening_item_state: OpeningItemState | None


def get_replacement_work(
    session: Session,
    assigned_to_user_id: str | None = None,
    project_id: uuid.UUID | None = None,
) -> list[ReplacementWorkItem]:
    """Outstanding replacement installs (#341), optionally scoped to one assembler.

    The natural assignee is the leaf's last assembler - the ShopAssemblyOpening keeps the assignment
    it was completed under - so filtering on assigned_to_user_id puts the work in that person's My
    Work with no new assignment system. A manager can still move it with the existing assign_openings
    mutation, which allows a COMPLETED opening exactly while it has pending replacements.

    Rows whose leaf has already SHIPPED_OUT are included on purpose: item 4 of #341 is that such a
    replacement must stay visible rather than be silently stranded. The caller can tell from
    opening_item_state that it cannot be installed and needs reallocation instead.
    """
    stmt = (
        select(ShopAssemblyOpeningItem, ShopAssemblyOpening, PullRequestModel.project_id)
        .join(
            ShopAssemblyOpening,
            ShopAssemblyOpening.id == ShopAssemblyOpeningItem.shop_assembly_opening_id,
        )
        .join(PullRequestModel, PullRequestModel.id == ShopAssemblyOpening.pull_request_id)
        .where(ShopAssemblyOpeningItem.replacement_pending_quantity > 0)
        .order_by(ShopAssemblyOpening.opening_number.asc(), ShopAssemblyOpeningItem.product_code.asc())
    )
    if assigned_to_user_id is not None:
        stmt = stmt.where(ShopAssemblyOpening.assigned_to_user_id == assigned_to_user_id)
    if project_id is not None:
        stmt = stmt.where(PullRequestModel.project_id == project_id)
    rows = session.execute(stmt).all()
    if not rows:
        return []

    # One batched lookup of the assembled leaves rather than one per row: the pending set is small,
    # but "small today" is how N+1s get written. Filtered on `opening_id` alone - an opening id is a
    # globally unique FK, so neither the project nor the leaf narrows it further, and a
    # row-constructor `IN` over tuples is the shape that overflowed Postgres' parser stack in
    # reconcile_schedule. The leaf could not be filtered here anyway: a legacy null leaf has to match
    # only a null leaf, which SQL's `IN` cannot express. So the leaf match and `find_assembled_leaf`'s
    # tie-break (a live row beats a shipped one, latest assembly wins among equals, via `_leaf_wins`)
    # are applied in Python below, and both call sites resolve a re-assembled leaf identically.
    opening_ids = {opening.opening_id for _item, opening, _proj_id in rows}
    leaf_by_key: dict[tuple[uuid.UUID, uuid.UUID, int | None], OpeningItemModel] = {}
    for oi in session.scalars(select(OpeningItemModel).where(OpeningItemModel.opening_id.in_(opening_ids))).all():
        key = (oi.project_id, oi.opening_id, oi.leaf)
        incumbent = leaf_by_key.get(key)
        if incumbent is None or _leaf_wins(oi, incumbent):
            leaf_by_key[key] = oi

    result: list[ReplacementWorkItem] = []
    for item, opening, proj_id in rows:
        leaf_row = leaf_by_key.get((proj_id, opening.opening_id, opening.leaf))
        result.append(
            ReplacementWorkItem(
                shop_assembly_opening_item_id=item.id,
                shop_assembly_opening_id=opening.id,
                project_id=proj_id,
                opening_number=opening.opening_number,
                leaf=opening.leaf,
                building=opening.building,
                floor=opening.floor,
                hardware_category=item.hardware_category,
                product_code=item.product_code,
                pending_quantity=item.replacement_pending_quantity,
                assigned_to_user_id=opening.assigned_to_user_id,
                assigned_to=opening.assigned_to,
                opening_item_id=leaf_row.id if leaf_row is not None else None,
                opening_item_state=leaf_row.state if leaf_row is not None else None,
            )
        )
    return result


def install_replacement(
    session: Session,
    sa_opening_item_id: uuid.UUID,
    quantity: int,
    performed_by: str | None = None,
) -> OpeningItemModel:
    """Fit arrived replacement hardware to an already-completed door leaf (#341).

    This is the one legitimate write to an assembled leaf's hardware after completion, and it is
    narrow on purpose: it can only consume units the replacement pull actually delivered
    (`replacement_pending_quantity`), so it cannot be used to inflate a leaf.

    The unit moves `replacement_pending -> installed` on the checklist line, which leaves
    `installed + deficient + replacement_pending == quantity` intact, and the leaf's
    `OpeningItemHardware` row for that (product_code, hardware_category) is incremented - or created,
    if the line had nothing installed at completion time. Both cases are real: #339 refuses a
    completion where *nothing at all* was installed, but a line that was entirely deficient while
    other lines were fine contributes no row, so the leaf may or may not already carry the product.

    Refused if the leaf has shipped: the hardware cannot be fitted to something that has left the
    building, and quietly recording it as installed would make the packing slip a lie. That case is
    already flagged and notified at pull completion, and belongs to reallocation.
    """
    if quantity < 1:
        raise ValidationError("quantity must be >= 1", field="quantity")

    item = session.get(ShopAssemblyOpeningItem, sa_opening_item_id)
    if item is None:
        raise NotFoundError(f"ShopAssemblyOpeningItem {sa_opening_item_id} not found")

    # Lock the work unit, then re-read the line under that lock so two installers cannot both spend
    # the same pending unit.
    if not lock_rows(session, ShopAssemblyOpening, [item.shop_assembly_opening_id]):
        raise NotFoundError(f"ShopAssemblyOpening {item.shop_assembly_opening_id} not found")
    opening = session.get(ShopAssemblyOpening, item.shop_assembly_opening_id)
    session.refresh(item)

    if opening.assembly_status != AssemblyStatus.COMPLETED:
        raise InvalidStateTransitionError(
            "This leaf is still on the bench - record the replacement as installed progress instead"
        )
    if item.replacement_pending_quantity < quantity:
        raise ValidationError(
            f"Only {item.replacement_pending_quantity} replacement unit(s) of {item.product_code} have "
            f"arrived for this leaf; cannot install {quantity}",
            field="quantity",
        )

    project_id = _opening_project_id(session, opening)
    if project_id is None:
        raise NotFoundError(f"ShopAssemblyOpening {opening.id} is not linked to a pull request")

    opening_item = find_assembled_leaf(session, project_id, opening.opening_id, opening.leaf)
    if opening_item is None:
        raise NotFoundError(f"No assembled unit found for opening {opening.opening_number}")
    if opening_item.state == OpeningItemState.SHIPPED_OUT:
        raise InvalidStateTransitionError(
            f"Opening {opening.opening_number} has already shipped - this replacement has to be "
            "routed through reallocation or a site shipment, not installed here"
        )
    # SHIP_READY is the same problem one step earlier. The leaf is staged at the dock against a
    # confirmed pull, and `confirm_shipment` snapshots its hardware onto the PackingSlipItem from
    # whatever the leaf carries at that moment - so hardware added here lands on a packing slip for a
    # unit that was picked and checked without it. The unit stays in replacement_pending and stays
    # queryable; unwinding the shipment (or reallocation) is the route, not a quiet late write.
    if opening_item.state == OpeningItemState.SHIP_READY:
        raise InvalidStateTransitionError(
            f"Opening {opening.opening_number} is staged for shipment - the packing slip is already "
            "built against what is on the leaf. Unwind the shipping-out request first, or route this "
            "replacement through reallocation"
        )

    oih = session.scalars(
        select(OIHModel).where(
            OIHModel.opening_item_id == opening_item.id,
            OIHModel.product_code == item.product_code,
            OIHModel.hardware_category == item.hardware_category,
        )
    ).first()
    previous_installed_on_leaf = oih.quantity if oih is not None else 0
    if oih is None:
        # The line was fully deficient when the leaf was completed, so it contributed no row.
        oih = OIHModel(
            id=uuid.uuid4(),
            opening_item_id=opening_item.id,
            product_code=item.product_code,
            hardware_category=item.hardware_category,
            quantity=quantity,
        )
        session.add(oih)
    else:
        oih.quantity += quantity

    item.replacement_pending_quantity -= quantity
    item.installed_quantity += quantity
    opening_item.updated_at = datetime.utcnow()

    _log_audit_event(
        session,
        project_id=project_id,
        entity_type=AuditEntityType.OPENING_ITEM,
        entity_id=opening_item.id,
        action=AuditAction.REPLACEMENT_INSTALL,
        performed_by=performed_by or opening.assigned_to or "Assembler",
        detail={
            "shopAssemblyOpeningId": str(opening.id),
            "shopAssemblyOpeningItemId": str(item.id),
            "openingNumber": opening.opening_number,
            "leaf": opening.leaf,
            "hardwareCategory": item.hardware_category,
            "productCode": item.product_code,
            "installedQuantity": quantity,
            "previousQuantityOnLeaf": previous_installed_on_leaf,
            "newQuantityOnLeaf": oih.quantity,
            "remainingPendingQuantity": item.replacement_pending_quantity,
        },
    )
    session.flush()
    return opening_item


def get_openings_with_items(session: Session, opening_ids: list[uuid.UUID]) -> list[ShopAssemblyOpening]:
    """Shop-assembly openings by id with items eagerly loaded (mutation response reload)."""
    stmt = (
        select(ShopAssemblyOpening)
        .options(selectinload(ShopAssemblyOpening.items))
        .where(ShopAssemblyOpening.id.in_(opening_ids))
    )
    return list(session.scalars(stmt).unique().all())


def get_request_with_openings(session: Session, request_id: uuid.UUID):
    """Shop-assembly request with openings + their items eagerly loaded (finalize-import reload)."""
    stmt = (
        select(ShopAssemblyRequest)
        .options(selectinload(ShopAssemblyRequest.openings).selectinload(ShopAssemblyOpening.items))
        .where(ShopAssemblyRequest.id == request_id)
    )
    return session.scalars(stmt).unique().first()


def find_already_assembled_openings(
    session: Session,
    project_id: uuid.UUID,
    opening_leaf_specs: list[tuple[str, uuid.UUID, int | None]],
) -> list[tuple[str, int | None]]:
    """REQ-5 guard (#293), per door leaf (#311): given (opening_number, opening_id, leaf) specs,
    return the (opening_number, leaf) pairs whose (opening_id, leaf) already has an assembled
    OpeningItem in this project (any state except SHIPPED_OUT). Keying on leaf means assembling
    Leaf 1 does NOT block sending Leaf 2 to shop assembly. Legacy null-leaf assembled units only
    match a null-leaf spec."""
    if not opening_leaf_specs:
        return []
    opening_ids = [oid for _, oid, _ in opening_leaf_specs]
    rows = session.execute(
        select(OpeningItemModel.opening_id, OpeningItemModel.leaf).where(
            OpeningItemModel.project_id == project_id,
            OpeningItemModel.opening_id.in_(opening_ids),
            OpeningItemModel.state != OpeningItemState.SHIPPED_OUT,
        )
    ).all()
    assembled = {(r.opening_id, r.leaf) for r in rows}
    return [(num, leaf) for num, oid, leaf in opening_leaf_specs if (oid, leaf) in assembled]


def find_in_flight_assembly_leaves(
    session: Session,
    opening_leaf_specs: list[tuple[str, uuid.UUID, int | None]],
) -> list[tuple[str, int | None, str | None]]:
    """Duplicate in-flight guard (#342): the (opening_number, leaf, request_number) triples whose
    leaf is already inside a **live** shop-assembly work unit.

    `find_already_assembled_openings` catches the leaf that has already been *built*. This catches
    the one that is on its way there - requested, accepted, pulled, or half-assembled on somebody's
    bench - which the pre-#342 creation path let through: two requests for the same leaf both
    reserved and both pulled hardware, and the second one had nowhere to put it.

    Live means the work unit is not finished and its request is not dead:

    - `assembly_status != COMPLETED` (a completed leaf is the already-assembled guard's business,
      and re-requesting it is legitimate only after the assembled unit ships);
    - the parent ShopAssemblyRequest is not REJECTED - or there is no parent at all, which is the
      legacy #222 shape where the opening hangs straight off a PullRequest.

    Scoping is by `opening_id`, which is a project's own Opening UUID, so this is project-scoped by
    construction without joining a table whose rows a re-upload may have deleted. One query, and the
    request_number comes back with the row so the refusal can name what is holding the leaf.
    """
    if not opening_leaf_specs:
        return []
    opening_ids = [oid for _, oid, _ in opening_leaf_specs]
    rows = session.execute(
        select(
            ShopAssemblyOpening.opening_id,
            ShopAssemblyOpening.leaf,
            ShopAssemblyRequest.request_number,
        )
        .outerjoin(ShopAssemblyRequest, ShopAssemblyOpening.shop_assembly_request_id == ShopAssemblyRequest.id)
        .where(
            ShopAssemblyOpening.opening_id.in_(opening_ids),
            ShopAssemblyOpening.assembly_status != AssemblyStatus.COMPLETED,
            or_(
                ShopAssemblyRequest.id.is_(None),
                ShopAssemblyRequest.status != ShopAssemblyRequestStatus.REJECTED,
            ),
        )
    ).all()
    claimed = {(opening_id, leaf): request_number for opening_id, leaf, request_number in rows}
    return [(num, leaf, claimed[(oid, leaf)]) for num, oid, leaf in opening_leaf_specs if (oid, leaf) in claimed]


def get_shop_assembly_requests(
    session: Session,
    project_id: uuid.UUID | None = None,
    status: ShopAssemblyRequestStatus | None = None,
    reopenable_only: bool = False,
) -> list[ShopAssemblyRequest]:
    """List shop-assembly requests for the accept UI (#293). Defaults to PENDING when no status is
    given. Openings + their items are eagerly loaded (shop_assembly_request_to_type walks both).

    reopenable_only (#325): keep only requests still in the reopen window - their minted warehouse
    PullRequest is still PENDING (the warehouse has not started the pull). The Approved view passes this
    so it lists exactly the requests Reopen can act on, not every request ever accepted. The minted PR
    carries the request's request_number (unique on pull_requests), so it is matched on that."""
    effective_status = status if status is not None else ShopAssemblyRequestStatus.PENDING
    stmt = (
        select(ShopAssemblyRequest)
        .options(selectinload(ShopAssemblyRequest.openings).selectinload(ShopAssemblyOpening.items))
        .where(ShopAssemblyRequest.status == effective_status)
        .order_by(ShopAssemblyRequest.created_at.asc())
    )
    if project_id is not None:
        stmt = stmt.where(ShopAssemblyRequest.project_id == project_id)
    if reopenable_only:
        stmt = stmt.join(PullRequestModel, ShopAssemblyRequest.request_number == PullRequestModel.request_number).where(
            PullRequestModel.status == PullRequestStatus.PENDING
        )
    return list(session.scalars(stmt).unique().all())


def accept_shop_assembly_request(
    session: Session,
    request_id: uuid.UUID,
    accepted_by: str,
) -> ShopAssemblyRequest:
    """Accept a PENDING shop-assembly request (#293). Since #342 this is a **pure human approval
    gate**: it flips the request to APPROVED and mints the warehouse PullRequest (SHOP_ASSEMBLY,
    PENDING) with one LOOSE item per opening item, then repoints the request's ShopAssemblyOpenings
    at that PR (pull_request_id) so the unchanged warehouse pull/complete flow works as before.

    The reactive inventory-sufficiency re-check that used to live here is gone. The hardware was
    reserved when the request was created, so it is already this request's; re-checking at accept
    could only ever fail for stock that was never free to begin with, and it made the accept step a
    second place a shortfall could surface - with no action the acceptor could take about it. The
    check now happens once, at creation (where the creator can still refine the selection), and the
    claim is spent at pull approval. Accepting does not touch the reservations: the request keeps
    holding them, exactly as it did while PENDING.

    The pull asks for the **allocated** quantity, and a line with nothing allocated mints no pull
    line at all. That is what keeps the pull equal to the reservation: the request reserved its
    allocation at creation, so the pull it mints spends exactly that, and `approve_pull_request`
    stays all-or-nothing by construction. Sending the owed quantity instead would ask the warehouse
    for stock nobody claimed and the pull would sit blocked - which is the shortfall this whole slice
    moves back to the requester.
    """
    stmt = (
        select(ShopAssemblyRequest)
        .options(selectinload(ShopAssemblyRequest.openings).selectinload(ShopAssemblyOpening.items))
        .where(ShopAssemblyRequest.id == request_id)
    )
    sar = session.scalars(stmt).unique().first()
    if sar is None:
        raise NotFoundError(f"Shop-assembly request {request_id} not found")
    if sar.status != ShopAssemblyRequestStatus.PENDING:
        raise InvalidStateTransitionError(f"Shop-assembly request must be Pending to accept, got {sar.status.value}")

    now = datetime.utcnow()
    sar.status = ShopAssemblyRequestStatus.APPROVED
    sar.approved_by = accepted_by
    sar.approved_at = now

    pr = PullRequestModel(
        id=uuid.uuid4(),
        request_number=sar.request_number,
        project_id=sar.project_id,
        source=PullRequestSource.SHOP_ASSEMBLY,
        status=PullRequestStatus.PENDING,
        requested_by=accepted_by,
    )
    session.add(pr)
    session.flush()

    for opening in sar.openings:
        opening.pull_request_id = pr.id
        for item in opening.items:
            if item.allocated_quantity <= 0:
                # Fully short line: nothing was reserved for it and nothing is coming. A zero-quantity
                # pull line would put a pick on the sheet the warehouse cannot fill.
                continue
            session.add(
                PullRequestItemModel(
                    id=uuid.uuid4(),
                    pull_request_id=pr.id,
                    item_type=PullRequestItemType.LOOSE,
                    opening_number=opening.opening_number,
                    # Snapshot the door leaf (#311) so a leaf-1 pull reads distinct from a leaf-2 pull.
                    leaf=opening.leaf,
                    hardware_category=item.hardware_category,
                    product_code=item.product_code,
                    requested_quantity=item.allocated_quantity,
                )
            )

    return sar


def reject_shop_assembly_request(
    session: Session,
    request_id: uuid.UUID,
    rejected_by: str,
    reason: str | None,
) -> ShopAssemblyRequest:
    """Reject a PENDING shop-assembly request (#293). Mints no PullRequest, and **releases the
    request's inventory reservations** (#342) - the request is dead, so the hardware it has been
    holding since creation goes back to the available pool for whoever asks next.

    This is also the recovery path for a reopened request: reopen returns it to PENDING still
    holding its claim, and rejecting it from there runs exactly this code."""
    from app.repositories import warehouse as warehouse_repository

    stmt = (
        select(ShopAssemblyRequest)
        .options(selectinload(ShopAssemblyRequest.openings).selectinload(ShopAssemblyOpening.items))
        .where(ShopAssemblyRequest.id == request_id)
    )
    sar = session.scalars(stmt).unique().first()
    if sar is None:
        raise NotFoundError(f"Shop-assembly request {request_id} not found")
    if sar.status != ShopAssemblyRequestStatus.PENDING:
        raise InvalidStateTransitionError(f"Shop-assembly request must be Pending to reject, got {sar.status.value}")

    sar.status = ShopAssemblyRequestStatus.REJECTED
    sar.rejected_by = rejected_by
    sar.rejection_reason = (reason or "").strip() or None
    sar.rejected_at = datetime.utcnow()
    warehouse_repository.release_reservations(session, ReservationSource.SHOP_ASSEMBLY_REQUEST, sar.id)
    return sar


def reopen_shop_assembly_request(
    session: Session,
    request_id: uuid.UUID,
) -> ShopAssemblyRequest:
    """Reopen an APPROVED shop-assembly request back to PENDING (#325): undo an erroneous accept by
    hard-deleting the warehouse PullRequest the accept minted (and its items), re-pointing the
    request's openings off it, and flipping the request back to PENDING so it can be re-accepted or
    rejected. The minted PR is found via the openings' pull_request_id (there is no direct link on the
    request, mirroring accept). Only allowed while the PR is still PENDING - if the warehouse has
    already approved/completed it, inventory has moved and the reopen is refused."""
    from app.repositories import warehouse as warehouse_repository

    stmt = (
        select(ShopAssemblyRequest)
        .options(selectinload(ShopAssemblyRequest.openings))
        .where(ShopAssemblyRequest.id == request_id)
    )
    sar = session.scalars(stmt).unique().first()
    if sar is None:
        raise NotFoundError(f"Shop-assembly request {request_id} not found")
    if sar.status != ShopAssemblyRequestStatus.APPROVED:
        raise InvalidStateTransitionError(f"Shop-assembly request must be Approved to reopen, got {sar.status.value}")

    # Find the minted PR by the stable request_number, not by deriving it from the openings'
    # pull_request_id. accept mints the PR unconditionally (even a zero-opening request gets one), so an
    # openings-derived lookup can miss it and leave a PENDING PR orphaned - and since request_number is
    # unique, the next accept would then collide, re-creating the stuck state #325 removes. accept stamps
    # the PR with request_number == sar.request_number, which is unique among *live* pull requests
    # (#343 made that uniqueness partial: a cancelled pull keeps its number, and re-accepting mints a
    # new pull carrying the same one). Excluding CANCELLED is therefore what keeps this a single-row
    # lookup after a cancel-then-re-accept cycle.
    pr = session.scalar(
        select(PullRequestModel).where(
            PullRequestModel.request_number == sar.request_number,
            PullRequestModel.status != PullRequestStatus.CANCELLED,
        )
    )

    # Re-point the openings + flip the request, then flush BEFORE discarding the PR, so deleting it does
    # not trip the shop_assembly_openings.pull_request_id foreign key. discard_pending_pull_request still
    # guards the PR is unworked (PENDING) and rolls the whole transaction back (nothing commits) if not.
    for opening in sar.openings:
        opening.pull_request_id = None
    sar.status = ShopAssemblyRequestStatus.PENDING
    sar.approved_by = None
    sar.approved_at = None
    session.flush()

    warehouse_repository.discard_pending_pull_request(session, pr.id if pr is not None else None)
    return sar


# ---------------------------------------------------------------------------
# Pipeline observability (#344)
# ---------------------------------------------------------------------------
#
# Slices 1-5 each added a state, and each one is legible only from the screen that writes it. A
# request holds a reservation (#342), its pull is part-staged (#343), one leaf is half-built (#340),
# another is finished but owed a replacement (#341) - and answering "where is opening A01 leaf 2?"
# meant opening four views and joining them up by eye.
#
# Nothing below stores anything. Every value is derived from state slices 1-5 already persist, which
# is deliberate: a denormalised `pipeline_stage` column would be a fifth thing that can disagree with
# the other four, and this slice exists because the four already disagree on screen.
#
# **Everything is a scalar aggregate.** The rollups are `count`/`sum` with `FILTER`, grouped by
# request, one statement each for the entire result set - never a `len()` over loaded openings
# (CLAUDE.md perf rules). `get_assembly_pipeline_summaries` runs a fixed FIVE statements whether it
# is scoped to one project or to all of them, and `get_assembly_pipeline` runs a fixed EIGHT however
# many openings a request has. That flatness is what the tests assert, because it is the property
# that makes the All-Projects view survivable.

# Order of the ladder. The stage of a *request* is the stage of its least-advanced opening: what a
# pipeline is asked is "what is holding this up", not "what is the best news in it". REJECTED sits
# below everything because it is not a point on the journey but leaving it, and CANCELLED shares the
# floor with REQUESTED because that is literally where a cancelled pull puts its openings back
# (#343: the request returns to PENDING for re-acceptance).
PIPELINE_STAGE_RANK = {
    "REJECTED": -1,
    "CANCELLED": 0,
    "REQUESTED": 0,
    "ACCEPTED": 1,
    "PULLING": 2,
    "STAGED": 3,
    "ASSIGNED": 4,
    "IN_PROGRESS": 5,
    "COMPLETED": 6,
    "SHIPPED": 7,
}


@dataclass(frozen=True)
class PipelineOpening:
    """Where one door leaf is, and what it is carrying (#344).

    `stage` is the derived ladder position; every raw fact it was derived from is on the row too, so
    a caller that reads the situation differently can show its own reading rather than be stuck with
    this one.
    """

    shop_assembly_opening_id: uuid.UUID
    opening_number: str
    leaf: int | None
    building: str | None
    floor: str | None
    location: str | None
    stage: str
    pull_status: PullStatus
    staged_at: datetime | None
    staged_by: str | None
    assigned_to_user_id: str | None
    assigned_to: str | None
    assembly_status: AssemblyStatus
    completed_at: datetime | None
    planned_unit_count: int
    # What the request could actually claim for this leaf. The three progress counters partition
    # this, not `planned_unit_count`; the difference was never pulled.
    allocated_unit_count: int
    installed_unit_count: int
    deficient_unit_count: int
    replacement_pending_unit_count: int
    opening_item_id: uuid.UUID | None
    opening_item_state: OpeningItemState | None
    # Where the assembled leaf physically is, once there is one - the "completed (location)" rung.
    assembled_location: str | None

    @property
    def short_unit_count(self) -> int:
        """Units the schedule owed this leaf that the request never pulled - it could not claim them
        out of available inventory when it was sent. Not outstanding *work*: nothing arrived, so the
        leaf completes without them and closing the gap belongs to purchasing and reallocation."""
        return self.planned_unit_count - self.allocated_unit_count

    @property
    def awaiting_replacement_unit_count(self) -> int:
        """Units this leaf is still owed: condemned-and-unreplaced plus arrived-but-not-fitted. The
        same reading `get_awaiting_replacement_quantities` gives the shipping guard (#341), taken
        here from counts the row already carries."""
        return self.deficient_unit_count + self.replacement_pending_unit_count

    @property
    def replacement_arrived_after_ship(self) -> bool:
        """Replacement hardware is sitting for a leaf that has already left the building (#341).
        `installReplacement` refuses it and it needs reallocation, so it is the one flag on this row
        that is somebody else's job entirely."""
        return self.replacement_pending_unit_count > 0 and self.opening_item_state == OpeningItemState.SHIPPED_OUT


@dataclass(frozen=True)
class AssemblyPipelineSummary:
    """One shop-assembly request's whole journey, in counts (#344).

    Safe to list at All-Projects scale: every field comes from a grouped aggregate over the whole
    result set, so adding requests adds rows to five queries rather than adding queries.
    """

    request_id: uuid.UUID
    request_number: str
    project_id: uuid.UUID
    # The project this request belongs to, so the All-Projects list can say which one without a
    # second lookup: `project_code` is the human job number, `project_name` its description.
    project_code: str | None
    project_name: str | None
    request_status: ShopAssemblyRequestStatus
    created_by: str
    created_at: datetime
    accepted_by: str | None
    accepted_at: datetime | None
    rejected_by: str | None
    rejected_at: datetime | None
    # The #342 flag the accept screen already shows as an amber alert - carried here too, so the
    # pipeline does not quietly become a second, more trusting view of the same request.
    integrity_note: str | None

    # The live pull (the one a re-accept minted, never a cancelled one - #343 made request_number
    # unique only among live pulls).
    pull_request_id: uuid.UUID | None
    pull_request_status: PullRequestStatus | None
    pull_approved_at: datetime | None
    pull_completed_at: datetime | None
    # Derived staging rollup, the same reading PullRequest.stagingStatus gives (#343).
    staging_status: PullStatus | None

    # Cancellation history. A cancelled pull keeps its number and its openings go back to a PENDING
    # request, so without this a cancelled-and-returned request would read as never having been
    # accepted at all.
    cancelled_pull_count: int
    last_cancelled_at: datetime | None
    last_cancelled_by: str | None
    last_cancellation_reason: str | None

    opening_count: int
    staged_opening_count: int
    assigned_opening_count: int
    in_progress_opening_count: int
    completed_opening_count: int
    shipped_opening_count: int

    planned_unit_count: int
    # Sent short: `planned - allocated` across the whole request. The number the pipeline exists to
    # surface for this slice - a request can now be legitimately complete and still not have
    # delivered its full bill of hardware, and nothing else on this row would say so.
    allocated_unit_count: int
    short_unit_count: int
    installed_unit_count: int
    deficient_unit_count: int
    replacement_pending_unit_count: int

    # Openings with something still owed to them, and the subset whose leaf has already shipped.
    awaiting_replacement_opening_count: int
    replacement_after_ship_opening_count: int
    # Openings carrying at least one line that was never fully pulled.
    short_opening_count: int

    stage: str


@dataclass(frozen=True)
class AssemblyPipeline:
    """A request's summary plus a row per door leaf - the detail view (#344)."""

    summary: AssemblyPipelineSummary
    openings: list[PipelineOpening]


def _opening_stage(
    *,
    request_status: ShopAssemblyRequestStatus,
    pull_request_id: uuid.UUID | None,
    pull_status: PullStatus,
    assembly_status: AssemblyStatus,
    assigned_to_user_id: str | None,
    opening_item_state: OpeningItemState | None,
    live_pull_status: PullRequestStatus | None,
    had_cancelled_pull: bool,
) -> str:
    """The furthest rung one opening has provably reached (#344).

    Read top-down; the first true statement wins, so a completed leaf that has shipped reports
    SHIPPED rather than COMPLETED. The two facts that are *not* about this opening - the request
    being rejected, and the pull being cancelled - are checked at the ends rather than the middle: a
    rejection kills the whole request however far any leaf got, and a cancellation is only reachable
    once the opening has been detached from its pull.
    """
    if request_status == ShopAssemblyRequestStatus.REJECTED:
        return "REJECTED"
    if opening_item_state == OpeningItemState.SHIPPED_OUT:
        return "SHIPPED"
    if assembly_status == AssemblyStatus.COMPLETED:
        return "COMPLETED"
    if assembly_status == AssemblyStatus.IN_PROGRESS:
        return "IN_PROGRESS"
    if pull_status == PullStatus.PULLED:
        return "ASSIGNED" if assigned_to_user_id else "STAGED"
    if pull_request_id is None:
        # Detached: either the accept has not happened yet, or a cancellation released it (#343),
        # which also put the request back to PENDING. The cancelled pull is the only way to tell
        # those two apart, and telling them apart is the whole point of showing a cancellation.
        return "CANCELLED" if had_cancelled_pull else "REQUESTED"
    if live_pull_status == PullRequestStatus.PENDING:
        return "ACCEPTED"
    if live_pull_status == PullRequestStatus.CANCELLED:
        return "CANCELLED"
    # The pull is approved and stock has left inventory, but this opening's own cart is not built.
    return "PULLING"


def _request_stage(counts: dict, unstaged_stage: str, request_status: ShopAssemblyRequestStatus) -> str:
    """The stage of a request's least-advanced opening - what the request is waiting on - derived
    from the **counts alone**, never from loaded opening rows.

    This is the one place the ladder is collapsed for a whole request, and it is written against
    aggregates on purpose: the All-Projects list needs it on every row, and the detail view uses the
    very same summary rather than a second implementation, so the number under the header and the
    rows beneath it cannot disagree. A test pins the two together by asserting that this equals the
    minimum of the per-opening stages `_opening_stage` produces.

    `unstaged_stage` is what an opening of this request that is *not yet staged* reads as - REQUESTED,
    ACCEPTED, PULLING or CANCELLED. It is a property of the request's pull, not of any one opening,
    which is why it can be passed in: every opening of a request shares one `pull_request_id` (accept
    links them all, reopen and cancel detach them all).
    """
    if request_status == ShopAssemblyRequestStatus.REJECTED:
        return "REJECTED"
    total = counts["opening_count"]
    if total == 0:
        # #342 refuses to create a request with no openings, but legacy rows exist and must not take
        # the list down.
        return unstaged_stage
    if total - counts["staged_opening_count"] > 0:
        return unstaged_stage
    if counts["staged_unassigned_pending_count"] > 0:
        return "STAGED"
    if counts["staged_assigned_pending_count"] > 0:
        return "ASSIGNED"
    if counts["in_progress_opening_count"] > 0:
        return "IN_PROGRESS"
    if counts["completed_opening_count"] > counts["shipped_opening_count"]:
        return "COMPLETED"
    return "SHIPPED"


def _pull_rows_by_request_number(session: Session, request_numbers: list[str]) -> dict[str, list[PullRequestModel]]:
    """Every pull ever minted for these request numbers, live and cancelled, oldest first.

    One statement for the whole page. A cancelled pull keeps its number (#343 replaced the global
    unique constraint with one that excludes CANCELLED), so a request that has been through a
    cancel/re-accept cycle legitimately has several - and the cancelled ones are exactly the history
    the pipeline exists to surface.
    """
    if not request_numbers:
        return {}
    rows = session.scalars(
        select(PullRequestModel)
        .where(
            PullRequestModel.request_number.in_(request_numbers),
            PullRequestModel.source == PullRequestSource.SHOP_ASSEMBLY,
            PullRequestModel.deleted_at.is_(None),
        )
        .order_by(PullRequestModel.created_at.asc())
    ).all()
    grouped: dict[str, list[PullRequestModel]] = {}
    for pr in rows:
        grouped.setdefault(pr.request_number, []).append(pr)
    return grouped


def _opening_stage_counts(session: Session, request_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict]:
    """Per-request opening counts, in ONE grouped aggregate over every request given.

    `count(*) FILTER (...)` rather than four queries, and rather than a Python pass over loaded rows:
    these are the fields the All-Projects list renders on every row.
    """
    if not request_ids:
        return {}
    in_progress = ShopAssemblyOpening.assembly_status == AssemblyStatus.IN_PROGRESS
    completed = ShopAssemblyOpening.assembly_status == AssemblyStatus.COMPLETED
    staged = ShopAssemblyOpening.pull_status == PullStatus.PULLED
    held = ShopAssemblyOpening.assigned_to_user_id.is_not(None)
    # Staged-and-untouched, split by whether anybody is holding it: the STAGED and ASSIGNED rungs.
    # They cannot be reconstructed from the other four counts, because `remove_opening_from_user`
    # (#340) allows unassigning an IN_PROGRESS leaf, so "assigned" and "started" are independent.
    untouched = and_(staged, ShopAssemblyOpening.assembly_status == AssemblyStatus.PENDING)
    rows = session.execute(
        select(
            ShopAssemblyOpening.shop_assembly_request_id.label("request_id"),
            func.count(1).label("total"),
            func.count(1).filter(staged).label("staged"),
            func.count(1).filter(held).label("assigned"),
            func.count(1).filter(in_progress).label("in_progress"),
            func.count(1).filter(completed).label("completed"),
            func.count(1).filter(and_(untouched, held)).label("staged_assigned_pending"),
            func.count(1)
            .filter(and_(untouched, ShopAssemblyOpening.assigned_to_user_id.is_(None)))
            .label("staged_unassigned_pending"),
        )
        .where(ShopAssemblyOpening.shop_assembly_request_id.in_(request_ids))
        .group_by(ShopAssemblyOpening.shop_assembly_request_id)
    ).all()
    return {
        row.request_id: {
            "opening_count": int(row.total),
            "staged_opening_count": int(row.staged),
            "assigned_opening_count": int(row.assigned),
            "in_progress_opening_count": int(row.in_progress),
            "completed_opening_count": int(row.completed),
            "staged_assigned_pending_count": int(row.staged_assigned_pending),
            "staged_unassigned_pending_count": int(row.staged_unassigned_pending),
        }
        for row in rows
    }


def _unit_counts(session: Session, request_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict]:
    """Per-request unit rollups, in ONE statement: the progress counters summed, plus how many
    openings have something outstanding.

    The "how many openings" part is why this is a two-level aggregate rather than a flat one -
    "openings with anything owed" counts groups that satisfy a predicate on their own sum, so the
    per-opening sums are computed in a subquery and rolled up in the outer select. Still one
    round-trip, still no rows loaded.
    """
    if not request_ids:
        return {}
    per_opening = (
        select(
            ShopAssemblyOpening.shop_assembly_request_id.label("request_id"),
            ShopAssemblyOpening.id.label("opening_id"),
            func.coalesce(func.sum(ShopAssemblyOpeningItem.quantity), 0).label("planned"),
            func.coalesce(func.sum(ShopAssemblyOpeningItem.allocated_quantity), 0).label("allocated"),
            func.coalesce(func.sum(ShopAssemblyOpeningItem.installed_quantity), 0).label("installed"),
            func.coalesce(func.sum(ShopAssemblyOpeningItem.deficient_quantity), 0).label("deficient"),
            func.coalesce(func.sum(ShopAssemblyOpeningItem.replacement_pending_quantity), 0).label("pending"),
        )
        .join(
            ShopAssemblyOpeningItem,
            ShopAssemblyOpeningItem.shop_assembly_opening_id == ShopAssemblyOpening.id,
        )
        .where(ShopAssemblyOpening.shop_assembly_request_id.in_(request_ids))
        .group_by(ShopAssemblyOpening.shop_assembly_request_id, ShopAssemblyOpening.id)
        .subquery()
    )
    outstanding = per_opening.c.deficient + per_opening.c.pending
    short = per_opening.c.planned - per_opening.c.allocated
    rows = session.execute(
        select(
            per_opening.c.request_id,
            func.coalesce(func.sum(per_opening.c.planned), 0).label("planned"),
            func.coalesce(func.sum(per_opening.c.allocated), 0).label("allocated"),
            func.coalesce(func.sum(per_opening.c.installed), 0).label("installed"),
            func.coalesce(func.sum(per_opening.c.deficient), 0).label("deficient"),
            func.coalesce(func.sum(per_opening.c.pending), 0).label("pending"),
            func.count(1).filter(outstanding > 0).label("awaiting_openings"),
            func.count(1).filter(short > 0).label("short_openings"),
        ).group_by(per_opening.c.request_id)
    ).all()
    return {
        row.request_id: {
            "planned_unit_count": int(row.planned),
            "allocated_unit_count": int(row.allocated),
            "short_unit_count": int(row.planned) - int(row.allocated),
            "installed_unit_count": int(row.installed),
            "deficient_unit_count": int(row.deficient),
            "replacement_pending_unit_count": int(row.pending),
            "awaiting_replacement_opening_count": int(row.awaiting_openings),
            "short_opening_count": int(row.short_openings),
        }
        for row in rows
    }


def _shipped_counts(session: Session, request_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict]:
    """Per-request shipped-leaf counts, in ONE statement.

    There is no FK from a ShopAssemblyOpening to the leaf it produced, so this joins the way
    `find_assembled_leaf` keys it - (project, opening_id, leaf), a legacy null leaf matching only a
    null leaf - and scopes the join to the request's own project, because `opening_id` is a
    historical stamp that a re-upload can reissue.

    `count(DISTINCT opening)` because the item join fans the rows out, and because a leaf that
    shipped and was then re-assembled by a correction has more than one OpeningItem. Counting an
    opening as shipped when *any* of its rows shipped is the conservative reading for a rollup; the
    per-leaf detail view resolves that ambiguity properly, live row winning, exactly as
    `find_assembled_leaf` does.

    **Only COMPLETED openings can be shipped.** (opening_id, leaf) is not scoped to a request, so a
    leaf that shipped under an earlier request and was then re-requested matches the *new* request's
    opening too - and without this filter the new request read as already SHIPPED before anybody had
    picked its cart, taking its pipeline stage, its shipped count and its after-ship count with it.
    An opening that has not been assembled cannot have produced the leaf that shipped, so requiring
    COMPLETED is both the fix and the honest statement of the join.
    """
    if not request_ids:
        return {}
    shipped = OpeningItemModel.state == OpeningItemState.SHIPPED_OUT
    rows = session.execute(
        select(
            ShopAssemblyOpening.shop_assembly_request_id.label("request_id"),
            func.count(func.distinct(ShopAssemblyOpening.id)).filter(shipped).label("shipped"),
            func.count(func.distinct(ShopAssemblyOpening.id))
            .filter(and_(shipped, ShopAssemblyOpeningItem.replacement_pending_quantity > 0))
            .label("after_ship"),
        )
        .select_from(ShopAssemblyOpening)
        .join(ShopAssemblyRequest, ShopAssemblyRequest.id == ShopAssemblyOpening.shop_assembly_request_id)
        .join(
            OpeningItemModel,
            and_(
                OpeningItemModel.opening_id == ShopAssemblyOpening.opening_id,
                OpeningItemModel.leaf.is_not_distinct_from(ShopAssemblyOpening.leaf),
                OpeningItemModel.project_id == ShopAssemblyRequest.project_id,
                ShopAssemblyOpening.assembly_status == AssemblyStatus.COMPLETED,
            ),
        )
        .outerjoin(
            ShopAssemblyOpeningItem,
            ShopAssemblyOpeningItem.shop_assembly_opening_id == ShopAssemblyOpening.id,
        )
        .where(ShopAssemblyOpening.shop_assembly_request_id.in_(request_ids))
        .group_by(ShopAssemblyOpening.shop_assembly_request_id)
    ).all()
    return {
        row.request_id: {
            "shipped_opening_count": int(row.shipped),
            "replacement_after_ship_opening_count": int(row.after_ship),
        }
        for row in rows
    }


_EMPTY_OPENING_COUNTS = {
    "opening_count": 0,
    "staged_opening_count": 0,
    "assigned_opening_count": 0,
    "in_progress_opening_count": 0,
    "completed_opening_count": 0,
    "staged_assigned_pending_count": 0,
    "staged_unassigned_pending_count": 0,
}
_EMPTY_UNIT_COUNTS = {
    "planned_unit_count": 0,
    "allocated_unit_count": 0,
    "short_unit_count": 0,
    "installed_unit_count": 0,
    "deficient_unit_count": 0,
    "replacement_pending_unit_count": 0,
    "awaiting_replacement_opening_count": 0,
    "short_opening_count": 0,
}
_EMPTY_SHIPPED_COUNTS = {"shipped_opening_count": 0, "replacement_after_ship_opening_count": 0}


def get_assembly_pipeline_summaries(
    session: Session,
    project_id: uuid.UUID | None = None,
    status: ShopAssemblyRequestStatus | None = None,
    request_ids: list[uuid.UUID] | None = None,
) -> list[AssemblyPipelineSummary]:
    """Every shop-assembly request's journey, in counts (#344). FIVE statements, always.

    The statement count does not depend on how many requests come back or how many openings they
    have, which is the requirement: with `project_id` omitted this is the All-Projects view, and a
    per-request follow-up query here would be the pattern CLAUDE.md's perf rules exist to prevent.
    The five are: the requests (with their project name), every pull ever minted for them, and the
    three grouped aggregates - opening stages, unit progress, shipped leaves.

    Legacy #222 openings that hang straight off a PullRequest with no ShopAssemblyRequest are not
    covered, because there is no request for them to be a pipeline *of*. They remain visible in the
    Assemble List and the pull queue, which is where they always were.
    """
    # Local, matching the rest of this module: `warehouse.pull_requests` imports back into here at
    # call time for the replacement-arrival path, so the two packages stay uncoupled at import time.
    from app.repositories.warehouse import StagingSummary as warehouse_staging_summary

    stmt = (
        select(ShopAssemblyRequest, Project.project_id, Project.description)
        .outerjoin(Project, Project.id == ShopAssemblyRequest.project_id)
        .order_by(ShopAssemblyRequest.created_at.desc())
    )
    if project_id is not None:
        stmt = stmt.where(ShopAssemblyRequest.project_id == project_id)
    if status is not None:
        stmt = stmt.where(ShopAssemblyRequest.status == status)
    if request_ids is not None:
        if not request_ids:
            return []
        stmt = stmt.where(ShopAssemblyRequest.id.in_(request_ids))
    rows = session.execute(stmt).all()
    if not rows:
        return []

    ids = [sar.id for sar, _code, _name in rows]
    pulls_by_number = _pull_rows_by_request_number(session, [sar.request_number for sar, _c, _n in rows])
    opening_counts = _opening_stage_counts(session, ids)
    unit_counts = _unit_counts(session, ids)
    shipped_counts = _shipped_counts(session, ids)

    summaries: list[AssemblyPipelineSummary] = []
    for sar, project_code, project_name in rows:
        pulls = pulls_by_number.get(sar.request_number, [])
        cancelled = [p for p in pulls if p.status == PullRequestStatus.CANCELLED]
        live = next((p for p in reversed(pulls) if p.status != PullRequestStatus.CANCELLED), None)
        counts = {
            **_EMPTY_OPENING_COUNTS,
            **opening_counts.get(sar.id, {}),
            **_EMPTY_UNIT_COUNTS,
            **unit_counts.get(sar.id, {}),
            **_EMPTY_SHIPPED_COUNTS,
            **shipped_counts.get(sar.id, {}),
        }
        # What an un-staged opening of this request reads as. A property of the pull, not of any one
        # opening, so it is computed once here with a placeholder opening.
        unstaged_stage = _opening_stage(
            request_status=sar.status,
            pull_request_id=live.id if live is not None else None,
            pull_status=PullStatus.NOT_PULLED,
            assembly_status=AssemblyStatus.PENDING,
            assigned_to_user_id=None,
            opening_item_state=None,
            live_pull_status=live.status if live is not None else None,
            had_cancelled_pull=bool(cancelled),
        )
        staging_status = None
        if counts["opening_count"] > 0:
            # Reuse #343's derivation rather than restate it: PARTIAL is the aggregate reading over a
            # set of openings, and there must be exactly one place that decides what it means.
            staging_status = warehouse_staging_summary(
                staged_opening_count=counts["staged_opening_count"],
                total_opening_count=counts["opening_count"],
            ).status
        summaries.append(
            AssemblyPipelineSummary(
                request_id=sar.id,
                request_number=sar.request_number,
                project_id=sar.project_id,
                project_code=project_code,
                project_name=project_name,
                request_status=sar.status,
                created_by=sar.created_by,
                created_at=sar.created_at,
                accepted_by=sar.approved_by,
                accepted_at=sar.approved_at,
                rejected_by=sar.rejected_by,
                rejected_at=sar.rejected_at,
                integrity_note=sar.integrity_note,
                pull_request_id=live.id if live is not None else None,
                pull_request_status=live.status if live is not None else None,
                pull_approved_at=live.approved_at if live is not None else None,
                pull_completed_at=live.completed_at if live is not None else None,
                staging_status=staging_status,
                cancelled_pull_count=len(cancelled),
                last_cancelled_at=cancelled[-1].cancelled_at if cancelled else None,
                last_cancelled_by=cancelled[-1].cancelled_by if cancelled else None,
                last_cancellation_reason=cancelled[-1].cancellation_reason if cancelled else None,
                opening_count=counts["opening_count"],
                staged_opening_count=counts["staged_opening_count"],
                assigned_opening_count=counts["assigned_opening_count"],
                in_progress_opening_count=counts["in_progress_opening_count"],
                completed_opening_count=counts["completed_opening_count"],
                shipped_opening_count=counts["shipped_opening_count"],
                planned_unit_count=counts["planned_unit_count"],
                allocated_unit_count=counts["allocated_unit_count"],
                short_unit_count=counts["short_unit_count"],
                installed_unit_count=counts["installed_unit_count"],
                deficient_unit_count=counts["deficient_unit_count"],
                replacement_pending_unit_count=counts["replacement_pending_unit_count"],
                awaiting_replacement_opening_count=counts["awaiting_replacement_opening_count"],
                replacement_after_ship_opening_count=counts["replacement_after_ship_opening_count"],
                short_opening_count=counts["short_opening_count"],
                stage=_request_stage(counts, unstaged_stage, sar.status),
            )
        )
    return summaries


def get_assembly_pipeline(session: Session, request_id: uuid.UUID) -> AssemblyPipeline:
    """One request's pipeline: the summary, plus a row per door leaf (#344). EIGHT statements,
    however many openings the request has.

    The summary comes from `get_assembly_pipeline_summaries` rather than from the opening rows loaded
    below, and that is worth three extra aggregate queries on a single request: it means the header
    numbers on this screen are *by construction* the same numbers as the row for this request in the
    list, and it keeps the aggregate rule honest rather than "honest except on the detail page".

    The three statements this adds are the opening rows themselves, one grouped aggregate of their
    hardware lines, and one fetch of the assembled leaves. That is flat in the number of openings,
    which is what `test_pipeline_detail_query_count_is_flat_as_openings_grow` pins down.
    """
    summaries = get_assembly_pipeline_summaries(session, request_ids=[request_id])
    if not summaries:
        raise NotFoundError(f"Shop-assembly request {request_id} not found")
    summary = summaries[0]

    openings = list(
        session.scalars(
            select(ShopAssemblyOpening)
            .where(ShopAssemblyOpening.shop_assembly_request_id == request_id)
            .order_by(ShopAssemblyOpening.opening_number.asc(), ShopAssemblyOpening.leaf.asc())
        ).all()
    )
    if not openings:
        return AssemblyPipeline(summary=summary, openings=[])

    opening_ids = [o.id for o in openings]
    # One grouped aggregate for every opening's hardware lines - not a selectinload plus a Python
    # sum, because the four counters are all this view wants and summing them in the database is
    # both the rule and the cheaper read.
    sums_by_opening = {
        row.opening_id: row
        for row in session.execute(
            select(
                ShopAssemblyOpeningItem.shop_assembly_opening_id.label("opening_id"),
                func.coalesce(func.sum(ShopAssemblyOpeningItem.quantity), 0).label("planned"),
                func.coalesce(func.sum(ShopAssemblyOpeningItem.allocated_quantity), 0).label("allocated"),
                func.coalesce(func.sum(ShopAssemblyOpeningItem.installed_quantity), 0).label("installed"),
                func.coalesce(func.sum(ShopAssemblyOpeningItem.deficient_quantity), 0).label("deficient"),
                func.coalesce(func.sum(ShopAssemblyOpeningItem.replacement_pending_quantity), 0).label("pending"),
            )
            .where(ShopAssemblyOpeningItem.shop_assembly_opening_id.in_(opening_ids))
            .group_by(ShopAssemblyOpeningItem.shop_assembly_opening_id)
        ).all()
    }

    # The assembled leaves, in one fetch for the whole request rather than a find_assembled_leaf call
    # per opening. The live-wins-over-shipped and latest-wins tie-breaks are applied here in exactly
    # the order that function documents, so a leaf that shipped and was re-assembled resolves the
    # same way in both places. The match is only *used* for an opening this request actually finished
    # (see below): (opening_id, leaf) carries no request lineage, so a re-requested leaf would
    # otherwise read the previous request's shipped unit as its own.
    leaves: dict[tuple[uuid.UUID, int | None], OpeningItemModel] = {}
    for oi in session.scalars(
        select(OpeningItemModel).where(
            OpeningItemModel.project_id == summary.project_id,
            OpeningItemModel.opening_id.in_({o.opening_id for o in openings}),
        )
    ).all():
        key = (oi.opening_id, oi.leaf)
        incumbent = leaves.get(key)
        if incumbent is None or _leaf_wins(oi, incumbent):
            leaves[key] = oi

    rows: list[PipelineOpening] = []
    for opening in openings:
        sums = sums_by_opening.get(opening.id)
        # An opening that has not been completed has not produced a leaf, whatever else in the
        # project happens to carry the same (opening_id, leaf).
        leaf_row = (
            leaves.get((opening.opening_id, opening.leaf))
            if opening.assembly_status == AssemblyStatus.COMPLETED
            else None
        )
        rows.append(
            PipelineOpening(
                shop_assembly_opening_id=opening.id,
                opening_number=opening.opening_number,
                leaf=opening.leaf,
                building=opening.building,
                floor=opening.floor,
                location=opening.location,
                stage=_opening_stage(
                    request_status=summary.request_status,
                    pull_request_id=opening.pull_request_id,
                    pull_status=opening.pull_status,
                    assembly_status=opening.assembly_status,
                    assigned_to_user_id=opening.assigned_to_user_id,
                    opening_item_state=leaf_row.state if leaf_row is not None else None,
                    live_pull_status=summary.pull_request_status,
                    had_cancelled_pull=summary.cancelled_pull_count > 0,
                ),
                pull_status=opening.pull_status,
                staged_at=opening.staged_at,
                staged_by=opening.staged_by,
                assigned_to_user_id=opening.assigned_to_user_id,
                assigned_to=opening.assigned_to,
                assembly_status=opening.assembly_status,
                completed_at=opening.completed_at,
                planned_unit_count=int(sums.planned) if sums is not None else 0,
                allocated_unit_count=int(sums.allocated) if sums is not None else 0,
                installed_unit_count=int(sums.installed) if sums is not None else 0,
                deficient_unit_count=int(sums.deficient) if sums is not None else 0,
                replacement_pending_unit_count=int(sums.pending) if sums is not None else 0,
                opening_item_id=leaf_row.id if leaf_row is not None else None,
                opening_item_state=leaf_row.state if leaf_row is not None else None,
                assembled_location=_format_location(leaf_row) if leaf_row is not None else None,
            )
        )
    return AssemblyPipeline(summary=summary, openings=rows)


def _leaf_wins(candidate: OpeningItemModel, incumbent: OpeningItemModel) -> bool:
    """`find_assembled_leaf`'s tie-break, applied to a batch: a live row beats a shipped one, and
    among equals the most recently assembled wins."""
    candidate_live = candidate.state != OpeningItemState.SHIPPED_OUT
    incumbent_live = incumbent.state != OpeningItemState.SHIPPED_OUT
    if candidate_live != incumbent_live:
        return candidate_live
    return candidate.assembly_completed_at > incumbent.assembly_completed_at


def _format_location(oi: OpeningItemModel) -> str | None:
    """The assembled leaf's warehouse address, or None when it has not been put away. Joined here
    rather than on the client so the pipeline and the warehouse views read the same."""
    parts = [p for p in (oi.aisle, oi.row, oi.bay) if p]
    return "-".join(parts) if parts else None


def get_pending_review_openings(session: Session, project_id: uuid.UUID | None = None) -> list[dict]:
    """Every door leaf awaiting shop-assembly review, across all projects (#495).

    A pooled, project-agnostic queue. Review used to be request-level, which meant one contentious
    leaf held up every other leaf on the same request; and the reviewer works a queue, not one
    request at a time, so the project is a column here rather than a filter you have to pick first.

    One query with the items selectinloaded - the row summary counts them, and a per-row lazy load
    over a queue is exactly the N+1 this codebase keeps paying for.
    """
    from app.models.project import Project as ProjectModel

    stmt = (
        select(ShopAssemblyOpening, ShopAssemblyRequest, ProjectModel)
        .join(ShopAssemblyRequest, ShopAssemblyRequest.id == ShopAssemblyOpening.shop_assembly_request_id)
        .join(ProjectModel, ProjectModel.id == ShopAssemblyRequest.project_id)
        .options(selectinload(ShopAssemblyOpening.items))
        .where(ShopAssemblyOpening.review_status == OpeningReviewStatus.PENDING)
    )
    if project_id is not None:
        stmt = stmt.where(ShopAssemblyRequest.project_id == project_id)
    stmt = stmt.order_by(
        ShopAssemblyRequest.created_at,
        ShopAssemblyOpening.opening_number,
        ShopAssemblyOpening.leaf,
    )

    rows = []
    for opening, request, project in session.execute(stmt).unique().all():
        items = list(opening.items or [])
        rows.append(
            {
                "opening": opening,
                "request_number": request.request_number,
                "requested_by": request.requested_by,
                "requested_at": request.created_at,
                "project_id": project.id,
                "project_number": project.project_id,
                "project_name": project.description or project.project_id,
                "item_count": len(items),
                # What the allocator could not cover. Purchasing already knows; the reviewer needs
                # it because a leaf that is short is a different decision from one that is whole.
                "short_quantity": sum(max(0, i.quantity - (i.allocated_quantity or 0)) for i in items),
            }
        )
    return rows


def get_deferred_review_openings(session: Session, project_id: uuid.UUID | None = None) -> list[dict]:
    """Leaves a reviewer set aside (#495). Same shape as the pending queue, different bucket."""
    from app.models.project import Project as ProjectModel

    stmt = (
        select(ShopAssemblyOpening, ShopAssemblyRequest, ProjectModel)
        .join(ShopAssemblyRequest, ShopAssemblyRequest.id == ShopAssemblyOpening.shop_assembly_request_id)
        .join(ProjectModel, ProjectModel.id == ShopAssemblyRequest.project_id)
        .options(selectinload(ShopAssemblyOpening.items))
        .where(ShopAssemblyOpening.review_status == OpeningReviewStatus.DEFERRED)
    )
    if project_id is not None:
        stmt = stmt.where(ShopAssemblyRequest.project_id == project_id)
    stmt = stmt.order_by(ShopAssemblyOpening.reviewed_at.desc())

    rows = []
    for opening, request, project in session.execute(stmt).unique().all():
        items = list(opening.items or [])
        rows.append(
            {
                "opening": opening,
                "request_number": request.request_number,
                "requested_by": request.requested_by,
                "requested_at": request.created_at,
                "project_id": project.id,
                "project_number": project.project_id,
                "project_name": project.description or project.project_id,
                "item_count": len(items),
                "short_quantity": sum(max(0, i.quantity - (i.allocated_quantity or 0)) for i in items),
            }
        )
    return rows
