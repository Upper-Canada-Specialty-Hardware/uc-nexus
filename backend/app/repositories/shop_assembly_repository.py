"""Repository for shop assembly data access."""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.errors import (
    ConflictError,
    InvalidStateTransitionError,
    InventoryShortfallError,
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
    ShopAssemblyRequest,
)
from app.repositories.stock.common import _log_audit_event
from app.services.locking import lock_rows

MAX_DEFICIENT_REASON_LENGTH = 500

# Assembly statuses an opening can still be worked in (#340). COMPLETED is terminal.
_WORKABLE_ASSEMBLY_STATUSES = (AssemblyStatus.PENDING, AssemblyStatus.IN_PROGRESS)


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
    """Query ShopAssemblyOpenings whose shop-assembly PullRequest has been pulled (#222)."""
    stmt = (
        select(ShopAssemblyOpening)
        .join(
            PullRequestModel,
            ShopAssemblyOpening.pull_request_id == PullRequestModel.id,
        )
        .options(selectinload(ShopAssemblyOpening.items))
        .where(
            PullRequestModel.source == PullRequestSource.SHOP_ASSEMBLY,
            PullRequestModel.status == PullRequestStatus.COMPLETED,
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
    saved partial progress on has to stay in My Work or the work would be unreachable."""
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
            PullRequestModel.source == PullRequestSource.SHOP_ASSEMBLY,
            PullRequestModel.status == PullRequestStatus.COMPLETED,
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

    for opening in locked:
        if opening.pull_status != PullStatus.PULLED:
            raise InvalidStateTransitionError("Opening is not ready for assignment - hardware has not been pulled")
        if opening.assembly_status not in _WORKABLE_ASSEMBLY_STATUSES:
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
        PullRequestModel.status == PullRequestStatus.COMPLETED,
    )
    pr = session.scalars(pr_stmt).first()
    if pr is None:
        raise NotFoundError(f"Completed shop-assembly pull request for opening {opening_id} not found")

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
    """Accept a PENDING shop-assembly request (#293).

    Re-runs the shared inventory-sufficiency gate over the request's openings' items. If short,
    raises InventoryShortfallError WITHOUT minting anything - the resolver rolls back, notifies the
    PO in a fresh session, and re-raises so the shortfall reaches the caller inline. If covered,
    flips the request to APPROVED and mints the warehouse PullRequest (SHOP_ASSEMBLY, PENDING) with
    one LOOSE item per opening item, then repoints the request's ShopAssemblyOpenings at that PR
    (pull_request_id) so the unchanged warehouse pull/complete flow works exactly as before.
    """
    from app.repositories import warehouse as warehouse_repository
    from app.services import notification_service

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

    needs = [
        (item.hardware_category, item.product_code, item.quantity) for opening in sar.openings for item in opening.items
    ]
    sufficiency = warehouse_repository.check_inventory_sufficiency(session, sar.project_id, needs)
    if not sufficiency.sufficient:
        raise InventoryShortfallError(
            "Cannot accept shop-assembly request - insufficient inventory. "
            + notification_service.format_shortfall_lines(sufficiency.shortfalls),
            shortfalls=sufficiency.shortfalls,
            project_id=sar.project_id,
            request_number=sar.request_number,
        )

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
    """Reject a PENDING shop-assembly request (#293). Mints no PullRequest."""
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
    # the PR with request_number == sar.request_number, which is unique on pull_requests.
    pr = session.scalar(select(PullRequestModel).where(PullRequestModel.request_number == sar.request_number))

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
