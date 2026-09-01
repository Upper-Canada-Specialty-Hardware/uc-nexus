"""Raising, batching and unwinding shop-assembly requests (#646, #643, #644).

A shop-assembly request is a FLAG, not a claim. The PM picks the openings the shop needs assembled
and the request records what each was still owed at that moment - no allocation, no availability
gate, no reservation, no pull. It then waits, indefinitely if the hardware never arrives, because
"the shop needs these doors built" is true whether or not there is stock on the shelf today.

The Shop Assembly Manager works it in BATCHES. One batch is a chosen subset of the still-pending
openings with a per-line allocated quantity (partial allowed), and creating it is what does
everything the old accept did: gate on availability for exactly those allocations, write the
reservations, mint the warehouse PullRequest. Batching an opening CONSUMES it - the batch is the
decision for that opening and any unallocated remainder is forfeited, rather than becoming a
silent backlog row nobody works. Unbatched openings stay pending for a later batch, an opening with
nothing allocatable simply cannot be batched, and the manager can DISMISS whatever is left over to
finish a request off.

What this replaced: a single accept that minted one pull for the whole request, and the
creation-time availability gate that forced the PM to compose against stock months before the shop
needed it. Both were the same mistake - one decision point holding two decisions that belong to
different people at different times.
"""

import uuid
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from app.errors import InvalidStateTransitionError, NotFoundError, ValidationError
from app.models.enums import (
    PullRequestSource,
    PullRequestStatus,
    ReservationSource,
    ShopAssemblyBatchStatus,
    ShopAssemblyOpeningStatus,
    ShopAssemblyRequestStatus,
)
from app.models.pull_request import PullRequest as PullRequestModel
from app.models.pull_request import PullRequestItem as PullRequestItemModel
from app.models.shop_assembly import (
    ShopAssemblyBatch,
    ShopAssemblyBatchItem,
    ShopAssemblyRequest,
    ShopAssemblyRequestItem,
    ShopAssemblyRequestOpening,
)

# Where one request sits on the ladder the requests list draws as columns. Derived from the request's
# own status and the state of the pulls its batches minted - never stored, because a stored copy is
# one more thing that can disagree with the facts it is derived from.
STAGE_REQUESTED = "REQUESTED"
STAGE_ACCEPTED = "ACCEPTED"
STAGE_PULLING = "PULLING"
STAGE_DONE = "DONE"
STAGE_REJECTED = "REJECTED"

MAX_DISMISSAL_REASON_LENGTH = 500


# ---------------------------------------------------------------------------
# Creation (the PM's flag)
# ---------------------------------------------------------------------------


def create_shop_assembly_request(
    session: Session,
    project_id: uuid.UUID,
    items: list[dict],
    *,
    created_by: str,
) -> ShopAssemblyRequest:
    """Raise a PENDING shop-assembly request over the given openings' owed lines (#646).

    Reserves nothing, gates on nothing, mints nothing. The whole content of this call is "the shop
    needs these openings assembled, and here is what they were owed when I said so" - a statement
    about demand, which is true regardless of what is on the shelf. Allocation happens at batching,
    where the manager is standing in front of real numbers.

    Every line must carry an opening number. The request IS a list of openings, and a line hanging
    off none of them could never be batched, so accepting one would write hardware nobody can ever
    dispatch.
    """
    from app.repositories.request_numbers import mint_request_number

    if not items:
        raise ValidationError(
            "A shop-assembly request must include at least one line.",
            field="items",
        )

    lines = [_validated_line(item) for item in items]

    # #493: minted from the project's counter, shared with shipping-out requests so one chronological
    # sequence covers every pull on the job.
    request_number = mint_request_number(session, project_id)

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
                requested_quantity=line["requested_quantity"],
            )
        )

    for opening_number in sorted({line["opening_number"] for line in lines}):
        session.add(
            ShopAssemblyRequestOpening(
                id=uuid.uuid4(),
                shop_assembly_request_id=request.id,
                opening_number=opening_number,
                status=ShopAssemblyOpeningStatus.PENDING,
            )
        )

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

    opening_number = (item.get("opening_number") or "").strip()
    if not opening_number:
        raise ValidationError(
            f"{category} {code}: a shop-assembly line must name the opening it is owed to.",
            field="opening_number",
        )

    # `quantity` is still accepted so a browser tab loaded before #646 keeps working - it sent the
    # composer's suggestion under that name, which is exactly what this field means now.
    quantity = item.get("requested_quantity")
    if quantity is None:
        quantity = item.get("quantity")
    if quantity is None or quantity < 1:
        raise ValidationError(
            f"{category} {code}: a line must be owed at least one unit.",
            field="requested_quantity",
        )

    return {
        "opening_number": opening_number,
        "hardware_category": category,
        "product_code": code,
        "requested_quantity": quantity,
    }


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
#
# Both readers below run with `populate_existing=True`, and it is load-bearing rather than defensive.
#
# A request is worked in several steps within ONE transaction - batch it, then dismiss what is left;
# batch it, then re-read it to build the mutation's response - and every step re-reads the request
# through these functions. Without `populate_existing` the second read returns the identity-mapped
# instance from the first with its eagerly-loaded collections UNTOUCHED: SQLAlchemy will not
# overwrite loaded attributes on an object it already has. So a batch added and flushed a line
# earlier is simply absent from `request.batches`, and every reading derived from that collection is
# wrong in the same direction - `reject_shop_assembly_request` lets a batched request through,
# `_stage_for` sees no live batches and answers DONE, and the mutation's own response carries an
# empty `batches` list back to the client.
#
# `populate_existing` re-populates those collections from the row the query just read. Autoflush
# writes any pending state before the SELECT, so nothing in flight is lost by the refresh.


def get_shop_assembly_requests(
    session: Session,
    project_id: uuid.UUID | None = None,
    status: ShopAssemblyRequestStatus | None = None,
    reopenable_only: bool = False,
    *,
    company: str | None = None,
) -> list[ShopAssemblyRequest]:
    """List shop-assembly requests for the requests page. Defaults to PENDING.

    reopenable_only: keep only requests carrying at least one ACTIVE batch whose pull is still
    PENDING - the ones a discard can still act on. It is the Accepted view's filter, unchanged in
    meaning from #325 and only moved to batch granularity.
    """
    effective_status = status if status is not None else ShopAssemblyRequestStatus.PENDING
    stmt = (
        select(ShopAssemblyRequest)
        .options(
            selectinload(ShopAssemblyRequest.items),
            selectinload(ShopAssemblyRequest.openings),
            selectinload(ShopAssemblyRequest.batches).selectinload(ShopAssemblyBatch.items),
        )
        .where(ShopAssemblyRequest.status == effective_status)
        .order_by(ShopAssemblyRequest.created_at.asc())
        .execution_options(populate_existing=True)
    )
    if project_id is not None:
        stmt = stmt.where(ShopAssemblyRequest.project_id == project_id)
    if company is not None:
        from app.repositories import tenancy

        stmt = stmt.where(ShopAssemblyRequest.project_id.in_(tenancy.project_ids_for(company)))
    if reopenable_only:
        discardable = (
            select(ShopAssemblyBatch.id)
            .join(PullRequestModel, ShopAssemblyBatch.pull_request_id == PullRequestModel.id)
            .where(
                ShopAssemblyBatch.shop_assembly_request_id == ShopAssemblyRequest.id,
                ShopAssemblyBatch.status == ShopAssemblyBatchStatus.ACTIVE,
                PullRequestModel.status == PullRequestStatus.PENDING,
            )
        )
        stmt = stmt.where(discardable.exists())
    return list(session.scalars(stmt).unique().all())


def get_shop_assembly_request(session: Session, request_id: uuid.UUID) -> ShopAssemblyRequest:
    """One request with its lines, openings and batches loaded. Raises if it does not exist."""
    request = (
        session.scalars(
            select(ShopAssemblyRequest)
            .options(
                selectinload(ShopAssemblyRequest.items),
                selectinload(ShopAssemblyRequest.openings),
                selectinload(ShopAssemblyRequest.batches).selectinload(ShopAssemblyBatch.items),
            )
            .where(ShopAssemblyRequest.id == request_id)
            .execution_options(populate_existing=True)
        )
        .unique()
        .first()
    )
    if request is None:
        raise NotFoundError(f"Shop-assembly request {request_id} not found")
    return request


def get_pull_statuses(session: Session, requests: list[ShopAssemblyRequest]) -> dict[uuid.UUID, PullRequestStatus]:
    """Status of every pull minted by these requests' batches, keyed by pull id, in ONE query for the
    whole list (CLAUDE.md perf rules). Every derived reading below is a fold over this map."""
    pull_ids = [b.pull_request_id for r in requests for b in r.batches if b.pull_request_id is not None]
    if not pull_ids:
        return {}
    return {
        pull_id: status
        for pull_id, status in session.execute(
            select(PullRequestModel.id, PullRequestModel.status).where(PullRequestModel.id.in_(pull_ids))
        ).all()
    }


def get_request_stages(session: Session, requests: list[ShopAssemblyRequest]) -> dict[uuid.UUID, str]:
    """Where each request sits on the ladder, in ONE query for the whole list.

    A PENDING request reads REQUESTED however many batches it already has out. That is the honest
    reading of the amber "somebody has to act on this" rung: openings on it are still waiting for
    the manager, and what the warehouse is doing with an earlier batch does not change that.
    """
    if not requests:
        return {}
    pull_status_by_id = get_pull_statuses(session, requests)
    return {request.id: _stage_for(request, pull_status_by_id) for request in requests}


def _stage_for(request: ShopAssemblyRequest, pull_status_by_id: dict[uuid.UUID, PullRequestStatus]) -> str:
    if request.status == ShopAssemblyRequestStatus.REJECTED:
        return STAGE_REJECTED
    if request.status == ShopAssemblyRequestStatus.PENDING:
        return STAGE_REQUESTED

    # Worked to conclusion. The rung is the LEAST advanced of its live batches - what is holding the
    # request up, not its best news. A request finished entirely by dismissal has no batches and
    # nothing left to wait for, so it is done.
    statuses = [
        pull_status_by_id.get(batch.pull_request_id)
        for batch in request.batches
        if batch.status == ShopAssemblyBatchStatus.ACTIVE
    ]
    if not statuses:
        return STAGE_DONE
    if any(s == PullRequestStatus.PENDING or s is None for s in statuses):
        return STAGE_ACCEPTED
    if any(s == PullRequestStatus.IN_PROGRESS for s in statuses):
        return STAGE_PULLING
    return STAGE_DONE


def get_return_notes(session: Session, requests: list[ShopAssemblyRequest]) -> dict[uuid.UUID, str | None]:
    """The "returned to Pending" note a cancelled batch leaves on its request, one query for the list.

    The shipping-out twin (`app.repositories.request_return_notes`) reads the request's own
    `pull_request_id`; a shop-assembly request has none, so the same question is answered off its
    CANCELLED batches instead. Purely derived, so a fresh batch over the same openings clears it for
    free. Only PENDING requests carry it - the note explains a reappearance on the manager's board.
    """
    notes: dict[uuid.UUID, str | None] = {r.id: None for r in requests}
    pending = [r for r in requests if r.status == ShopAssemblyRequestStatus.PENDING]
    cancelled_pull_ids = [
        b.pull_request_id
        for r in pending
        for b in r.batches
        if b.status == ShopAssemblyBatchStatus.CANCELLED and b.pull_request_id is not None
    ]
    if not cancelled_pull_ids:
        return notes

    pulls = {
        pull_id: (number, cancelled_by, cancelled_at, reason)
        for pull_id, number, cancelled_by, cancelled_at, reason in session.execute(
            select(
                PullRequestModel.id,
                PullRequestModel.request_number,
                PullRequestModel.cancelled_by,
                PullRequestModel.cancelled_at,
                PullRequestModel.cancellation_reason,
            ).where(PullRequestModel.id.in_(cancelled_pull_ids))
        ).all()
    }

    for request in pending:
        cancelled = [
            b for b in request.batches if b.status == ShopAssemblyBatchStatus.CANCELLED and b.pull_request_id in pulls
        ]
        if not cancelled:
            continue
        # The most recent cancellation is the one that explains why the request is on the board now.
        latest = max(cancelled, key=lambda b: b.sequence)
        notes[request.id] = _format_return_note(*pulls[latest.pull_request_id])
    return notes


def _format_return_note(batch_number: str, cancelled_by: str | None, cancelled_at, reason: str | None) -> str:
    who = cancelled_by or "someone"
    when = cancelled_at.date().isoformat() if cancelled_at is not None else "an earlier date"
    head = f"Returned to Pending: batch {batch_number} was cancelled by {who} on {when}"
    return f"{head}: {reason}" if reason else f"{head}."


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


def get_allocation_review(session: Session, request_id: uuid.UUID) -> dict:
    """What the manager needs to build a batch: the request's still-pending openings, each opening's
    owed lines, and the reservation-aware free stock for every product across them.

    Availability is per COMBO and project-wide - the same `on-hand - deficient - every active
    reservation` figure the batch gate applies - so the screen and the server cannot disagree about
    what is free. It is deliberately not divided up per opening: two openings wanting the same hinge
    are competing for one pool, and the review has to show that competition rather than hide it
    behind a pre-split number. Whoever composes the batch spends the pool down as they walk.

    Three statements regardless of how many openings the request holds: the request (with its
    relationships), then the availability aggregate's own two.
    """
    from app.repositories import warehouse as warehouse_repository

    request = get_shop_assembly_request(session, request_id)
    pending = sorted(
        (o for o in request.openings if o.status == ShopAssemblyOpeningStatus.PENDING),
        key=lambda o: o.opening_number,
    )
    pending_numbers = {o.opening_number for o in pending}

    lines_by_opening: dict[str, list[ShopAssemblyRequestItem]] = {n: [] for n in pending_numbers}
    for item in request.items:
        if item.opening_number in pending_numbers:
            lines_by_opening[item.opening_number].append(item)

    combos = {(i.hardware_category, i.product_code) for lines in lines_by_opening.values() for i in lines}
    available = warehouse_repository.get_available_quantities(session, request.project_id, combos)

    return {
        "request": request,
        "openings": [
            {
                "opening_number": opening.opening_number,
                "lines": [
                    {
                        "opening_number": item.opening_number,
                        "hardware_category": item.hardware_category,
                        "product_code": item.product_code,
                        "requested_quantity": item.requested_quantity,
                        "available_quantity": available.get((item.hardware_category, item.product_code), 0),
                    }
                    for item in sorted(
                        lines_by_opening[opening.opening_number],
                        key=lambda i: (i.hardware_category, i.product_code),
                    )
                ],
            }
            for opening in pending
        ],
    }


# ---------------------------------------------------------------------------
# Batching (the manager's decision)
# ---------------------------------------------------------------------------


def create_shop_assembly_batch(
    session: Session,
    request_id: uuid.UUID,
    lines: list[dict],
    *,
    created_by: str,
) -> ShopAssemblyBatch:
    """Dispatch a subset of a request's pending openings, at the quantities the manager allocated.

    Everything the old accept did, done here where the numbers exist: gate on available inventory
    for exactly these allocations, write the reservations under the batch's own id, mint the
    warehouse PullRequest, and mark the batch's openings BATCHED.

    The batch's opening set is whatever the lines name. An opening with nothing allocatable
    therefore cannot be batched at all - it has no lines to name it - which is the behaviour the
    business wanted for an opening whose hardware simply has not arrived: it stays pending and comes
    back on the next batch, rather than being dispatched as an empty cart.

    The request closes itself off when this leaves nothing pending on it.
    """
    from app.repositories import warehouse as warehouse_repository

    request = get_shop_assembly_request(session, request_id)
    if request.status != ShopAssemblyRequestStatus.PENDING:
        raise InvalidStateTransitionError(f"Shop-assembly request must be Pending to batch, got {request.status.value}")
    if not lines:
        raise ValidationError("A batch must allocate at least one line.", field="lines")

    pending_openings = {o.opening_number: o for o in request.openings if o.status == ShopAssemblyOpeningStatus.PENDING}
    owed = {(i.opening_number, i.hardware_category, i.product_code): i.requested_quantity for i in request.items}

    allocations: dict[tuple[str, str, str], int] = {}
    for line in lines:
        key, quantity = _validated_allocation(line, pending_openings, owed)
        # Two rows for the same line are the same decision stated twice; summing them is what would
        # let a client quietly allocate past what the opening is owed.
        if key in allocations:
            raise ValidationError(
                f"{key[0]} {key[1]} {key[2]}: this line appears on the batch twice.",
                field="lines",
            )
        allocations[key] = quantity

    batch_openings = sorted({key[0] for key in allocations})

    needs_by_combo: dict[tuple[str, str], int] = {}
    for (_, category, code), quantity in allocations.items():
        needs_by_combo[(category, code)] = needs_by_combo.get((category, code), 0) + quantity

    sequence = (
        session.scalar(
            select(func.coalesce(func.max(ShopAssemblyBatch.sequence), 0)).where(
                ShopAssemblyBatch.shop_assembly_request_id == request.id
            )
        )
        or 0
    ) + 1
    batch_number = f"{request.request_number}-B{sequence}"

    warehouse_repository.gate_on_available_inventory(
        session,
        request.project_id,
        [(category, code, quantity) for (category, code), quantity in sorted(needs_by_combo.items())],
        label="shop-assembly batch",
        request_number=batch_number,
    )

    batch = ShopAssemblyBatch(
        id=uuid.uuid4(),
        shop_assembly_request_id=request.id,
        sequence=sequence,
        batch_number=batch_number,
        status=ShopAssemblyBatchStatus.ACTIVE,
        created_by=created_by,
    )
    session.add(batch)
    session.flush()

    pull = PullRequestModel(
        id=uuid.uuid4(),
        # The pull carries the batch's number, so the pick sheet reads as the dispatch it is. Unique
        # among live pulls, which a re-mint after a discard relies on.
        request_number=batch_number,
        project_id=request.project_id,
        source=PullRequestSource.SHOP_ASSEMBLY,
        status=PullRequestStatus.PENDING,
        requested_by=created_by,
    )
    session.add(pull)
    session.flush()

    for (opening_number, category, code), quantity in sorted(allocations.items()):
        session.add(
            ShopAssemblyBatchItem(
                id=uuid.uuid4(),
                shop_assembly_batch_id=batch.id,
                opening_number=opening_number,
                hardware_category=category,
                product_code=code,
                allocated_quantity=quantity,
            )
        )
        session.add(
            PullRequestItemModel(
                id=uuid.uuid4(),
                pull_request_id=pull.id,
                opening_number=opening_number,
                hardware_category=category,
                product_code=code,
                requested_quantity=quantity,
            )
        )

    batch.pull_request_id = pull.id

    # One reservation row per combo across the whole batch, over the allocated quantities, so the
    # pull asks for exactly what is reserved and the pick stays all-or-nothing per combo.
    warehouse_repository.create_reservations(
        session,
        request.project_id,
        ReservationSource.SHOP_ASSEMBLY_BATCH,
        batch.id,
        [(category, code, quantity) for (category, code), quantity in sorted(needs_by_combo.items())],
    )

    for opening_number in batch_openings:
        opening = pending_openings[opening_number]
        opening.status = ShopAssemblyOpeningStatus.BATCHED
        opening.batch_id = batch.id

    _close_if_nothing_pending(session, request, closed_by=created_by)
    session.flush()
    return batch


def _validated_allocation(
    line: dict,
    pending_openings: dict[str, ShopAssemblyRequestOpening],
    owed: dict[tuple[str, str, str], int],
) -> tuple[tuple[str, str, str], int]:
    """One allocation, checked against the opening it names and what that opening is owed."""
    opening_number = (line.get("opening_number") or "").strip()
    category = line.get("hardware_category")
    code = line.get("product_code")
    if not opening_number or not category or not code:
        raise ValidationError(
            "A batch line must name an opening, a hardware category and a product code.",
            field="lines",
        )
    if opening_number not in pending_openings:
        raise ValidationError(
            f"Opening {opening_number} is not waiting on this request - it has already been batched or dismissed.",
            field="opening_number",
        )

    key = (opening_number, category, code)
    if key not in owed:
        raise NotFoundError(f"{category} {code} is not owed to opening {opening_number} on this request")

    quantity = line.get("allocated_quantity")
    if quantity is None or quantity < 1:
        raise ValidationError(
            f"{opening_number} {category} {code}: allocate at least one unit, or leave the line off the batch.",
            field="allocated_quantity",
        )
    if quantity > owed[key]:
        raise ValidationError(
            f"{opening_number} {category} {code}: cannot allocate {quantity} - the opening is owed {owed[key]}.",
            field="allocated_quantity",
        )
    return key, quantity


def dismiss_shop_assembly_openings(
    session: Session,
    request_id: uuid.UUID,
    opening_numbers: list[str] | None,
    *,
    dismissed_by: str,
    reason: str | None,
) -> ShopAssemblyRequest:
    """Write off pending openings the manager is not going to batch (#646).

    `opening_numbers=None` means every opening still pending, which is the "finish this request off"
    action. Dismissing releases nothing, because a pending opening has never held anything: it is a
    statement that the shop is not getting this hardware through this request.
    """
    request = get_shop_assembly_request(session, request_id)
    if request.status != ShopAssemblyRequestStatus.PENDING:
        raise InvalidStateTransitionError(
            f"Shop-assembly request must be Pending to dismiss openings, got {request.status.value}"
        )

    reason = (reason or "").strip() or None
    if reason is not None and len(reason) > MAX_DISMISSAL_REASON_LENGTH:
        raise ValidationError(
            f"Dismissal reason must be {MAX_DISMISSAL_REASON_LENGTH} characters or fewer",
            field="reason",
        )

    pending = {o.opening_number: o for o in request.openings if o.status == ShopAssemblyOpeningStatus.PENDING}
    if opening_numbers is None:
        targets = list(pending.values())
    else:
        wanted = list(dict.fromkeys(opening_numbers))
        missing = [n for n in wanted if n not in pending]
        if missing:
            raise ValidationError(
                f"Opening(s) {', '.join(sorted(missing))} are not waiting on this request.",
                field="opening_numbers",
            )
        targets = [pending[n] for n in wanted]

    if not targets:
        raise ValidationError("There is nothing left to dismiss on this request.", field="opening_numbers")

    now = datetime.utcnow()
    for opening in targets:
        opening.status = ShopAssemblyOpeningStatus.DISMISSED
        opening.dismissed_by = dismissed_by
        opening.dismissed_at = now
        opening.dismissal_reason = reason

    _close_if_nothing_pending(session, request, closed_by=dismissed_by)
    session.flush()
    return request


def reject_shop_assembly_request(
    session: Session,
    request_id: uuid.UUID,
    rejected_by: str,
    reason: str | None,
) -> ShopAssemblyRequest:
    """Turn a whole shop-assembly request down. Only possible while it has no batches (#646).

    Releases nothing: a request with no batches has never held a claim on inventory. Once one batch
    exists the request has partly happened - hardware is reserved and a pull is on the floor - and
    the honest ways to end it are cancelling that pull and dismissing what is left, both of which
    say what actually became of each opening.
    """
    request = get_shop_assembly_request(session, request_id)
    if request.status != ShopAssemblyRequestStatus.PENDING:
        raise InvalidStateTransitionError(
            f"Shop-assembly request must be Pending to reject, got {request.status.value}"
        )
    if request.batches:
        raise InvalidStateTransitionError(
            "This request has already been batched, so it cannot be rejected whole. Cancel the "
            "batch's pull to undo it, and dismiss whatever is left."
        )

    request.status = ShopAssemblyRequestStatus.REJECTED
    request.rejected_by = rejected_by
    request.rejection_reason = (reason or "").strip() or None
    request.rejected_at = datetime.utcnow()
    session.flush()
    return request


def discard_shop_assembly_batch(session: Session, batch_id: uuid.UUID) -> ShopAssemblyRequest:
    """Undo a batch the warehouse has not started: the #325 reopen, moved to batch granularity.

    Hard-deletes the PullRequest the batch minted (and its items) and the batch itself, releases the
    claim the batch was holding, and hands its openings back to PENDING so they can be batched
    differently or dismissed. Refused once the warehouse has started that pull - by then inventory is
    moving, and the way out is cancelling the pull, not pretending the batch never happened.

    A hard delete rather than a status flip, for the same reason the reopen used one: `batch_number`
    is unique, so a later batch has to be free to take the next sequence without the discarded row
    lingering with a live pull attached.
    """
    from app.repositories import warehouse as warehouse_repository

    batch = session.get(ShopAssemblyBatch, batch_id)
    if batch is None:
        raise NotFoundError(f"Shop-assembly batch {batch_id} not found")
    if batch.status != ShopAssemblyBatchStatus.ACTIVE:
        raise InvalidStateTransitionError("This batch's pull was already cancelled; there is nothing to discard.")

    request = get_shop_assembly_request(session, batch.shop_assembly_request_id)
    pull_id = batch.pull_request_id

    # Release before the delete: the reservation rows cascade off the batch, and dropping them
    # silently through the FK would leave no record here of the claim having been given up.
    warehouse_repository.release_reservations(session, ReservationSource.SHOP_ASSEMBLY_BATCH, batch.id)

    for opening in request.openings:
        if opening.batch_id == batch.id:
            opening.status = ShopAssemblyOpeningStatus.PENDING
            opening.batch_id = None
    _reopen_to_pending(request)

    # Detach before discarding, so deleting the pull does not trip THIS row's foreign key - the same
    # ordering the #325 reopen used for the request's own pointer. Flushed on its own, because the
    # DELETE below runs as SQL and cannot see a pending attribute change.
    batch.pull_request_id = None
    session.flush()

    # Guards that the pull is unworked and rolls the whole transaction back if it is not, so the
    # release, the detach and the opening flips above are all undone with it.
    warehouse_repository.discard_pending_pull_request(session, pull_id)

    session.execute(delete(ShopAssemblyBatchItem).where(ShopAssemblyBatchItem.shop_assembly_batch_id == batch.id))
    session.delete(batch)
    session.flush()
    session.refresh(request, attribute_names=["batches", "openings"])
    return request


def return_batch_to_pending(session: Session, batch: ShopAssemblyBatch) -> bool:
    """Hand a cancelled batch's openings back to its request, for the pull-cancel path (#343/#646).

    Cancelling a pull says the *dispatch* was wrong, not that the shop no longer needs the doors, so
    the openings go back on the manager's board rather than being written off. The batch keeps its
    row - CANCELLED, still pointing at the cancelled pull - because that pointer is what the request
    list reads to explain why these openings reappeared.

    **Nothing is re-reserved.** A pending opening holds no claim by design (#646); the units the
    cancel just restocked go back to the free pool, and the next batch competes for them like
    anybody else. That is the whole difference from the shipping-out path, which does re-reserve
    because a returned shipping request is still a live claim.
    """
    if batch.status != ShopAssemblyBatchStatus.ACTIVE:
        return False

    batch.status = ShopAssemblyBatchStatus.CANCELLED
    openings = session.scalars(
        select(ShopAssemblyRequestOpening).where(ShopAssemblyRequestOpening.batch_id == batch.id)
    ).all()
    for opening in openings:
        opening.status = ShopAssemblyOpeningStatus.PENDING
        opening.batch_id = None

    request = session.get(ShopAssemblyRequest, batch.shop_assembly_request_id)
    if request is not None:
        _reopen_to_pending(request)
    session.flush()
    return True


# ---------------------------------------------------------------------------
# Request-level status, derived from its openings
# ---------------------------------------------------------------------------


def _close_if_nothing_pending(session: Session, request: ShopAssemblyRequest, *, closed_by: str) -> None:
    """Flip a request to APPROVED once every opening on it is batched or dismissed.

    APPROVED is "the manager is done with this request", not "one accept happened" - there is no
    single accept any more. Kept as the same enum value so the column, the Accepted view and the
    reopenable filter all keep working.
    """
    if any(o.status == ShopAssemblyOpeningStatus.PENDING for o in request.openings):
        return
    request.status = ShopAssemblyRequestStatus.APPROVED
    request.approved_by = closed_by
    request.approved_at = datetime.utcnow()


def _reopen_to_pending(request: ShopAssemblyRequest) -> None:
    """Put a closed-out request back on the manager's board, clearing the close-out stamps."""
    if request.status != ShopAssemblyRequestStatus.APPROVED:
        return
    request.status = ShopAssemblyRequestStatus.PENDING
    request.approved_by = None
    request.approved_at = None


def pending_openings_exist(session: Session, request_id: uuid.UUID) -> bool:
    """Whether a request still has an opening waiting on the manager. One scalar read."""
    return bool(
        session.scalar(
            select(func.count())
            .select_from(ShopAssemblyRequestOpening)
            .where(
                ShopAssemblyRequestOpening.shop_assembly_request_id == request_id,
                ShopAssemblyRequestOpening.status == ShopAssemblyOpeningStatus.PENDING,
            )
        )
    )


def opening_status_counts(
    session: Session, request_ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict[ShopAssemblyOpeningStatus, int]]:
    """Openings per status per request, as one grouped aggregate for a whole list."""
    if not request_ids:
        return {}
    counts: dict[uuid.UUID, dict[ShopAssemblyOpeningStatus, int]] = {}
    for request_id, status, total in session.execute(
        select(
            ShopAssemblyRequestOpening.shop_assembly_request_id,
            ShopAssemblyRequestOpening.status,
            func.count(),
        )
        .where(ShopAssemblyRequestOpening.shop_assembly_request_id.in_(request_ids))
        .group_by(
            ShopAssemblyRequestOpening.shop_assembly_request_id,
            ShopAssemblyRequestOpening.status,
        )
    ).all():
        counts.setdefault(request_id, {})[status] = int(total or 0)
    return counts


def batch_for_pull(session: Session, pull_request_id: uuid.UUID) -> ShopAssemblyBatch | None:
    """The batch a shop-assembly pull was minted by, or None for one nothing here minted.

    Deliberately not filtered on ACTIVE: the mapping is 1:1 for the life of the pull (a re-batch
    mints a fresh pull under the next batch number), and a caller asking "whose claim is this" about
    an already-cancelled pull deserves the true answer rather than a silent None.
    """
    return session.scalar(select(ShopAssemblyBatch).where(ShopAssemblyBatch.pull_request_id == pull_request_id))
