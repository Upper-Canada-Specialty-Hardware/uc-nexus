"""Repository for shop assembly data access."""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, func, or_, select
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
    PullRequestItemType,
    PullRequestSource,
    PullRequestStatus,
    PullStatus,
    ReservationSource,
    ShopAssemblyRequestStatus,
)
from app.models.opening_item import OpeningItem as OpeningItemModel
from app.models.opening_item import OpeningItemHardware as OIHModel
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
# that never got off the ground (PENDING, nothing deducted) or was cancelled (hardware restocked;
# cancellation also detaches its openings, so this is belt-and-braces).
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
        if new_installed + new_deficient > item.quantity:
            raise ValidationError(
                f"{item.product_code}: {new_installed} installed + {new_deficient} deficient exceeds the "
                f"{item.quantity} unit(s) pulled for this leaf",
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
                "previousInstalledQuantity": previous_installed,
                "installedQuantity": new_installed,
                "flaggedDeficientQuantity": flagged,
                "deficientQuantity": new_deficient,
                "remainingQuantity": item.quantity - new_installed - new_deficient,
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
    aisle: str | None,
    row: str | None,
    bay: str | None,
    completed_by: str | None = None,
) -> OpeningItemModel:
    """Mark an opening's assembly as complete. Creates OpeningItem + OpeningItemHardware records.

    Completion takes no checklist any more (#340). It reads the per-item counters
    record_assembly_progress has been persisting, so what is snapshotted onto the assembled leaf is
    what the assembler actually recorded fitting, unit by unit - not a claim made in the same call.
    Deficiencies were already returned to inventory and replaced when they were flagged, so this
    function no longer writes any of that.
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

    # 4. Every unit must be accounted for (#340). Business decision: block, never auto-default. An
    #    unrecorded unit is an unanswered question - was it fitted, is it still on the cart, is it
    #    missing? - and silently treating it as installed is what would put hardware on a leaf that
    #    was never there, while silently treating it as deficient would mint replacement pulls nobody
    #    asked for. Name the lines so the assembler knows exactly which ones to go finish.
    undispositioned = [
        f"{item.product_code} ({item.quantity - item.installed_quantity - item.deficient_quantity} of "
        f"{item.quantity} unrecorded)"
        for item in sa_opening.items
        if item.installed_quantity + item.deficient_quantity != item.quantity
    ]
    if undispositioned:
        raise ValidationError(
            "Cannot complete assembly while hardware is unaccounted for. Record each unit as "
            "installed or flag it deficient first: " + ", ".join(undispositioned),
            field="items",
        )

    # 4b. Refuse an all-deficient completion (#339). If every unit was flagged deficient the
    #     OpeningItem would be minted with zero OpeningItemHardware rows - an "assembled" leaf that
    #     had nothing installed on it, which then reads as ship-ready inventory. The deficiencies
    #     themselves stand (they were recorded when they were found, #340); what is refused is calling
    #     the leaf assembled. It stays IN_PROGRESS until at least one unit is installed on it.
    if sa_opening.items and all(item.installed_quantity == 0 for item in sa_opening.items):
        raise ValidationError(
            "Cannot complete an opening with every unit flagged deficient - nothing would be "
            "assembled. Leave the opening open until replacement hardware is installed.",
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
        aisle=aisle,
        row=row,
        bay=bay,
    )
    session.add(opening_item)
    session.flush()  # Get opening_item.id for OpeningItemHardware FK

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
                    "installedQuantity": item.installed_quantity,
                    "deficientQuantity": item.deficient_quantity,
                }
                for item in sa_opening.items
            ],
            "aisle": aisle,
            "row": row,
            "bay": bay,
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


def get_awaiting_replacement_quantities(
    session: Session,
    opening_item_ids: Iterable[uuid.UUID],
) -> dict[uuid.UUID, int]:
    """Per assembled leaf, how many units of its hardware are still owed (#341): units condemned and
    not yet replaced, plus units whose replacement has arrived but is not fitted yet.

    This is the shipping deficiency flag. A leaf with a non-zero count is physically short of what
    its checklist says it carries, so shipping it is a decision, not an accident - the wizard flags
    it and the shipping-out creation path refuses it without an explicit acknowledgment.

    One grouped scalar aggregate over the whole id set, never a len() over loaded collections
    (CLAUDE.md perf rules): the shipping selection lists every assembled leaf in a project, and a
    per-leaf query here would be an N+1 on the heaviest list in the module. Only non-zero entries are
    returned, so callers can treat a missing key as "nothing outstanding".
    """
    ids = list(opening_item_ids)
    if not ids:
        return {}
    outstanding = func.sum(
        ShopAssemblyOpeningItem.deficient_quantity + ShopAssemblyOpeningItem.replacement_pending_quantity
    )
    stmt = (
        select(OpeningItemModel.id, outstanding.label("outstanding"))
        .select_from(OpeningItemModel)
        .join(
            ShopAssemblyOpening,
            and_(
                ShopAssemblyOpening.opening_id == OpeningItemModel.opening_id,
                ShopAssemblyOpening.leaf.is_not_distinct_from(OpeningItemModel.leaf),
                ShopAssemblyOpening.assembly_status == AssemblyStatus.COMPLETED,
            ),
        )
        .join(PullRequestModel, PullRequestModel.id == ShopAssemblyOpening.pull_request_id)
        .join(
            ShopAssemblyOpeningItem,
            ShopAssemblyOpeningItem.shop_assembly_opening_id == ShopAssemblyOpening.id,
        )
        .where(
            OpeningItemModel.id.in_(ids),
            # Scope the join to the leaf's own project: opening_id is a historical stamp, not an FK,
            # and a re-upload can reissue it.
            PullRequestModel.project_id == OpeningItemModel.project_id,
        )
        .group_by(OpeningItemModel.id)
        .having(outstanding > 0)
    )
    return {row.id: int(row.outstanding) for row in session.execute(stmt).all()}


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
    # but "small today" is how N+1s get written.
    leaf_by_key: dict[tuple[uuid.UUID, uuid.UUID, int | None], OpeningItemModel] = {}
    for _item, opening, proj_id in rows:
        key = (proj_id, opening.opening_id, opening.leaf)
        if key not in leaf_by_key:
            found = find_assembled_leaf(session, proj_id, opening.opening_id, opening.leaf)
            if found is not None:
                leaf_by_key[key] = found

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
                    requested_quantity=item.quantity,
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
