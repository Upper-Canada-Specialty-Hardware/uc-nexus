"""Creating, accepting and unwinding shop-assembly requests.

A shop-assembly request is now the same shape as a shipping-out one: a flat list of lines, each
tagged with an opening number, gated on availability at creation and holding a reservation until the
pull that spends it. The difference is only which exit the completed pull is - the bench rather than
a truck - and v1 does not follow the hardware past that point.

What used to live here and does not any more: per-leaf review, assignment, bench progress,
completion into an assembled unit, and the replacement loop. All five hung off
`ShopAssemblyOpening`/`ShopAssemblyOpeningItem`, and all five went with the door.
"""

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.errors import InvalidStateTransitionError, NotFoundError, ValidationError
from app.models.enums import (
    PullRequestSource,
    PullRequestStatus,
    ReservationSource,
    ShopAssemblyRequestStatus,
)
from app.models.pull_request import PullRequest as PullRequestModel
from app.models.pull_request import PullRequestItem as PullRequestItemModel
from app.models.shop_assembly import ShopAssemblyRequest, ShopAssemblyRequestItem
from app.repositories import request_return_notes

# Where one request sits on the ladder the requests list draws as columns. Derived from the request's
# own status and the state of the pull it minted - never stored, because a stored copy is a fifth
# thing that can disagree with the four facts it is derived from.
STAGE_REQUESTED = "REQUESTED"
STAGE_ACCEPTED = "ACCEPTED"
STAGE_PULLING = "PULLING"
STAGE_DONE = "DONE"
STAGE_REJECTED = "REJECTED"


def create_shop_assembly_request(
    session: Session,
    project_id: uuid.UUID,
    items: list[dict],
    *,
    created_by: str,
) -> ShopAssemblyRequest:
    """Mint a PENDING shop-assembly request and the reservation that backs it.

    No PullRequest is minted here. A reviewer accepts the request later, and that accept is what
    mints the warehouse pull (#293).

    The gate is over the ALLOCATED quantity, not the owed one. The composer already decided what to
    claim and what to leave short, so what is gated is exactly what will be reserved and pulled. The
    gate is therefore a **race** gate rather than a shortfall gate: the composer built its numbers
    from a snapshot of availability, and if that went stale between load and send, reserving anyway
    would write a claim on hardware that is not there.
    """
    from app.repositories import warehouse as warehouse_repository
    from app.repositories.request_numbers import mint_request_number

    if not items:
        raise ValidationError(
            "A shop-assembly request must include at least one line.",
            field="items",
        )

    lines = [_validated_line(item) for item in items]
    needs = [
        (line["hardware_category"], line["product_code"], line["allocated_quantity"])
        for line in lines
        if line["allocated_quantity"] > 0
    ]
    if not needs:
        raise ValidationError(
            "Nothing on this request could be allocated, so there is nothing to pull for it. "
            "Trim it, or wait for stock.",
            field="allocated_quantity",
        )

    # #493: minted from the project's counter, shared with shipping-out requests so one chronological
    # sequence covers every pull on the job.
    request_number = mint_request_number(session, project_id)
    warehouse_repository.gate_on_available_inventory(
        session,
        project_id,
        needs,
        label="shop-assembly request",
        request_number=request_number,
    )

    request = ShopAssemblyRequest(
        id=uuid.uuid4(),
        request_number=request_number,
        project_id=project_id,
        status=ShopAssemblyRequestStatus.PENDING,
        created_by=created_by,
    )
    session.add(request)
    session.flush()

    for line in lines:
        session.add(
            ShopAssemblyRequestItem(
                id=uuid.uuid4(),
                shop_assembly_request_id=request.id,
                opening_number=line["opening_number"],
                hardware_category=line["hardware_category"],
                product_code=line["product_code"],
                quantity=line["quantity"],
                allocated_quantity=line["allocated_quantity"],
            )
        )

    # The request holds its claim from here until the pick that spends it (#342/#367). One row per
    # combo across the whole request, over the allocated quantities, so the pull the accept mints
    # asks for exactly what is reserved and `approve_pull_request` stays all-or-nothing.
    warehouse_repository.create_reservations(
        session,
        project_id,
        ReservationSource.SHOP_ASSEMBLY_REQUEST,
        request.id,
        needs,
    )

    _notify_shortfall(session, project_id, request_number, lines)
    session.flush()
    return request


def _validated_line(item: dict) -> dict:
    """One request line, checked against the invariants the check constraints also hold."""
    category = item.get("hardware_category")
    code = item.get("product_code")
    if not category or not code:
        raise ValidationError(
            "A shop-assembly line must name a hardware category and product code.",
            field="product_code",
        )

    quantity = item.get("quantity")
    if quantity is None or quantity < 1:
        raise ValidationError(
            f"{category} {code}: a line must be owed at least one unit.",
            field="quantity",
        )

    allocated = item.get("allocated_quantity")
    if allocated is None:
        raise ValidationError(
            f"{category} {code}: a line must say how much of what it is owed was allocated.",
            field="allocated_quantity",
        )
    if allocated < 0 or allocated > quantity:
        raise ValidationError(
            f"{category} {code}: allocated quantity {allocated} must be between 0 and the {quantity} unit(s) owed.",
            field="allocated_quantity",
        )

    return {
        # Null on a line raised straight off inventory: a hinge on a shelf carries no opening, and
        # inventing one would be a claim the schedule never made.
        "opening_number": item.get("opening_number") or None,
        "hardware_category": category,
        "product_code": code,
        "quantity": quantity,
        "allocated_quantity": allocated,
    }


def _notify_shortfall(
    session: Session,
    project_id: uuid.UUID,
    request_number: str,
    lines: list[dict],
) -> None:
    """Tell purchasing what the schedule owed that this request could not claim.

    Totals are accumulated over EVERY line of a combo, not only the short ones. Purchasing acts on
    the combo, so the number it needs is what this request wanted of that product against what it
    got; counting only the short lines would report a request that took 4 hinges on one opening and
    missed 3 on another as "need 4, 1 available", which is true of neither.
    """
    totals: dict[tuple[str, str], list[int]] = {}
    for line in lines:
        key = (line["hardware_category"], line["product_code"])
        entry = totals.setdefault(key, [0, 0])
        entry[0] += line["quantity"]
        entry[1] += line["allocated_quantity"]

    short = {key: (owed, allocated) for key, (owed, allocated) in totals.items() if owed > allocated}
    if not short:
        return

    from app.repositories import warehouse as warehouse_repository
    from app.services import notification_service

    notification_service.notify_po_shortfall(
        session,
        project_id=project_id,
        request_number=request_number,
        shortfalls=[
            warehouse_repository.Shortfall(
                hardware_category=category,
                product_code=code,
                requested=owed,
                available=allocated,
                short=owed - allocated,
                reserved=0,
            )
            for (category, code), (owed, allocated) in sorted(short.items())
        ],
        # The request exists and nothing is blocked - this is "here is what the project is missing",
        # not "a request failed".
        sent_short=True,
    )


def get_shop_assembly_requests(
    session: Session,
    project_id: uuid.UUID | None = None,
    status: ShopAssemblyRequestStatus | None = None,
    reopenable_only: bool = False,
) -> list[ShopAssemblyRequest]:
    """List shop-assembly requests for the requests page (#293). Defaults to PENDING.

    reopenable_only (#325): keep only requests still in the reopen window - the pull they minted is
    still PENDING, so the warehouse has not started on it.
    """
    effective_status = status if status is not None else ShopAssemblyRequestStatus.PENDING
    stmt = (
        select(ShopAssemblyRequest)
        .options(selectinload(ShopAssemblyRequest.items))
        .where(ShopAssemblyRequest.status == effective_status)
        .order_by(ShopAssemblyRequest.created_at.asc())
    )
    if project_id is not None:
        stmt = stmt.where(ShopAssemblyRequest.project_id == project_id)
    if reopenable_only:
        stmt = stmt.join(PullRequestModel, ShopAssemblyRequest.pull_request_id == PullRequestModel.id).where(
            PullRequestModel.status == PullRequestStatus.PENDING
        )
    return list(session.scalars(stmt).unique().all())


def get_shop_assembly_request(session: Session, request_id: uuid.UUID) -> ShopAssemblyRequest:
    """One request with its lines loaded. Raises if it does not exist."""
    request = (
        session.scalars(
            select(ShopAssemblyRequest)
            .options(selectinload(ShopAssemblyRequest.items))
            .where(ShopAssemblyRequest.id == request_id)
        )
        .unique()
        .first()
    )
    if request is None:
        raise NotFoundError(f"Shop-assembly request {request_id} not found")
    return request


def get_request_stages(session: Session, requests: list[ShopAssemblyRequest]) -> dict[uuid.UUID, str]:
    """Where each request sits on the ladder, in ONE query for the whole list (CLAUDE.md perf rules).

    A cancelled pull reads as REQUESTED rather than as a stage of its own: cancellation puts the
    hardware back and sends the request to PENDING for re-acceptance (#343), so the honest reading is
    that it is waiting to be accepted again.
    """
    if not requests:
        return {}

    pull_ids = [r.pull_request_id for r in requests if r.pull_request_id is not None]
    pull_status_by_id: dict[uuid.UUID, PullRequestStatus] = {}
    if pull_ids:
        pull_status_by_id = {
            pull_id: status
            for pull_id, status in session.execute(
                select(PullRequestModel.id, PullRequestModel.status).where(PullRequestModel.id.in_(pull_ids))
            ).all()
        }

    stages: dict[uuid.UUID, str] = {}
    for request in requests:
        stages[request.id] = _stage_for(request, pull_status_by_id.get(request.pull_request_id))
    return stages


def _stage_for(request: ShopAssemblyRequest, pull_status: PullRequestStatus | None) -> str:
    if request.status == ShopAssemblyRequestStatus.REJECTED:
        return STAGE_REJECTED
    if request.status == ShopAssemblyRequestStatus.PENDING:
        return STAGE_REQUESTED
    if pull_status == PullRequestStatus.COMPLETED:
        return STAGE_DONE
    if pull_status == PullRequestStatus.IN_PROGRESS:
        return STAGE_PULLING
    if pull_status == PullRequestStatus.CANCELLED or pull_status is None:
        return STAGE_REQUESTED
    return STAGE_ACCEPTED


def get_return_notes(session: Session, requests: list[ShopAssemblyRequest]) -> dict[uuid.UUID, str | None]:
    """The "returned to Pending" note per request (#613), one query for the whole list. A PENDING
    request still pointing at a CANCELLED pull was put back on the accept board by that cancel. See
    `app.repositories.request_return_notes`."""
    pending = [r for r in requests if r.status == ShopAssemblyRequestStatus.PENDING]
    derived = request_return_notes.return_notes_for(session, pending)
    return {r.id: derived.get(r.id) for r in requests}


def get_request_line_counts(session: Session, request_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    """Line count per request, as one grouped read rather than a `len()` over a loaded collection."""
    if not request_ids:
        return {}
    return {
        request_id: int(total or 0)
        for request_id, total in session.execute(
            select(ShopAssemblyRequestItem.shop_assembly_request_id, func.count())
            .where(ShopAssemblyRequestItem.shop_assembly_request_id.in_(request_ids))
            .group_by(ShopAssemblyRequestItem.shop_assembly_request_id)
        ).all()
    }


def accept_shop_assembly_request(
    session: Session,
    request_id: uuid.UUID,
    accepted_by: str,
) -> ShopAssemblyRequest:
    """Accept a PENDING shop-assembly request (#293): flip it to APPROVED and mint the warehouse
    PullRequest (SHOP_ASSEMBLY, PENDING) it will be pulled under.

    A **pure human approval gate**. The hardware was reserved when the request was created, so it is
    already this request's; re-checking availability here could only ever fail for stock that was
    never free, and it would make accept a second place a shortfall surfaces with no action the
    acceptor could take about it. The check happens once at creation, and the claim is spent at pick
    confirmation. Accepting touches no reservations.

    The pull asks for the **allocated** quantity, and a line with nothing allocated mints no pull
    line at all. That keeps the pull equal to the reservation. Sending the owed quantity instead
    would ask the warehouse for stock nobody claimed, and the pull would sit unpickable.
    """
    request = (
        session.scalars(
            select(ShopAssemblyRequest)
            .options(selectinload(ShopAssemblyRequest.items))
            .where(ShopAssemblyRequest.id == request_id)
        )
        .unique()
        .first()
    )
    if request is None:
        raise NotFoundError(f"Shop-assembly request {request_id} not found")
    if request.status != ShopAssemblyRequestStatus.PENDING:
        raise InvalidStateTransitionError(
            f"Shop-assembly request must be Pending to accept, got {request.status.value}"
        )

    pull = PullRequestModel(
        id=uuid.uuid4(),
        # The pull carries the request's own number, so the pick sheet reads as the request the shop
        # raised. Unique among live pulls, which a re-accept after a cancellation relies on (#343).
        request_number=request.request_number,
        project_id=request.project_id,
        source=PullRequestSource.SHOP_ASSEMBLY,
        status=PullRequestStatus.PENDING,
        requested_by=accepted_by,
    )
    session.add(pull)
    session.flush()

    for item in request.items:
        if item.allocated_quantity <= 0:
            # Fully short line: nothing was reserved for it and nothing is coming. A zero-quantity
            # pull line would put a pick on the sheet the warehouse cannot fill.
            continue
        session.add(
            PullRequestItemModel(
                id=uuid.uuid4(),
                pull_request_id=pull.id,
                opening_number=item.opening_number,
                hardware_category=item.hardware_category,
                product_code=item.product_code,
                requested_quantity=item.allocated_quantity,
            )
        )

    request.status = ShopAssemblyRequestStatus.APPROVED
    request.approved_by = accepted_by
    request.approved_at = datetime.utcnow()
    request.pull_request_id = pull.id
    session.flush()
    return request


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
    holding its claim, and rejecting it from there runs exactly this code.
    """
    from app.repositories import warehouse as warehouse_repository

    request = session.get(ShopAssemblyRequest, request_id)
    if request is None:
        raise NotFoundError(f"Shop-assembly request {request_id} not found")
    if request.status != ShopAssemblyRequestStatus.PENDING:
        raise InvalidStateTransitionError(
            f"Shop-assembly request must be Pending to reject, got {request.status.value}"
        )

    request.status = ShopAssemblyRequestStatus.REJECTED
    request.rejected_by = rejected_by
    request.rejection_reason = (reason or "").strip() or None
    request.rejected_at = datetime.utcnow()
    warehouse_repository.release_reservations(session, ReservationSource.SHOP_ASSEMBLY_REQUEST, request.id)
    return request


def reopen_shop_assembly_request(
    session: Session,
    request_id: uuid.UUID,
) -> ShopAssemblyRequest:
    """Reopen an APPROVED shop-assembly request back to PENDING (#325).

    Undoes an erroneous accept by hard-deleting the PullRequest the accept minted (and its items) and
    flipping the request back so it can be re-accepted or rejected. Only allowed while that pull is
    still PENDING - once the warehouse has started on it, inventory is moving and the reopen is
    refused. The request keeps its reservations throughout; it never stopped holding them.
    """
    from app.repositories import warehouse as warehouse_repository

    request = session.get(ShopAssemblyRequest, request_id)
    if request is None:
        raise NotFoundError(f"Shop-assembly request {request_id} not found")
    if request.status != ShopAssemblyRequestStatus.APPROVED:
        raise InvalidStateTransitionError(
            f"Shop-assembly request must be Approved to reopen, got {request.status.value}"
        )

    pull_id = request.pull_request_id
    # Detach before discarding, so deleting the pull does not trip the request's foreign key.
    # discard_pending_pull_request still guards that the pull is unworked and rolls the whole
    # transaction back if it is not.
    request.pull_request_id = None
    request.status = ShopAssemblyRequestStatus.PENDING
    request.approved_by = None
    request.approved_at = None
    session.flush()

    warehouse_repository.discard_pending_pull_request(session, pull_id)
    return request
