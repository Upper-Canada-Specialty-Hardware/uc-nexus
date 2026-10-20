"""Creating and editing shipping-out requests, from either of the two places they are raised (#451).

Start a Request raises one off the hardware schedule; the Shipping module raises one straight off
project inventory, for the loose stock a schedule line never accounted for. Both land here, because
every guard below is a property of the request itself and not of the screen that composed it: an
empty request has nothing to accept, and every line has to fit inside what is genuinely free (#342).

Editing is full-replace over the item list rather than a diff. The client sends the request it
wants, not the steps to get there: a diff has to be applied in an order that never transiently
over-claims, and every caller would be reconstructing the same final list anyway. Replace releases
the request's own claim first, so a line whose quantity is being *reduced* is not gated against
stock it already holds.

Every line is loose hardware. The assembled-leaf line type went with the door - shipping out claims
fungible stock and re-attaches the opening as a tag, the same as every other pull in the system.
"""

import hashlib
import uuid

from sqlalchemy import func, literal, select
from sqlalchemy.orm import Session

from app.errors import ConflictError, InvalidStateTransitionError, ValidationError
from app.models.enums import ReservationSource, ShippingOutRequestStatus
from app.models.shipping_out_request import ShippingOutRequest, ShippingOutRequestItem
from app.status_labels import status_label


def create_shipping_out_requests(
    session: Session,
    project_id: uuid.UUID,
    drafts: list[dict],
    *,
    created_by: str,
    created_by_user_id: str | None = None,
    idempotency_key: str | None = None,
) -> list[ShippingOutRequest]:
    """Mint PENDING shipping-out requests and the reservations that back their lines.

    Every draft in one call competes for the same stock and is gated together, because they are
    created in one transaction: gating them one at a time would let the second draft pass on stock
    the first had already spoken for.

    No PullRequest is minted here. A signed-in user accepts the request later, and that accept is
    what mints the warehouse pull (#293).

    `idempotency_key` (#1552) is the Shipping module's, minted when its dialog opened, for a call of
    one draft: a resend after a lost reply gets back the request its first attempt wrote rather than a
    second request reserving the same stock again.
    """
    if not drafts:
        return []
    if idempotency_key:
        if len(drafts) != 1:
            raise ValueError("an idempotency key names one request, so it is for a call of one draft")
        existing = _request_for_create_key(session, project_id, idempotency_key)
        if existing is not None:
            return [existing]

    for draft in drafts:
        if not draft.get("items"):
            raise ValidationError(
                "A shipping-out request has no items - select at least one line.",
                field="items",
            )

    # #1258: a line tagged to an opening must name one the project has. Checked once for every draft.
    _check_openings(session, project_id, [item for draft in drafts for item in draft.get("items", [])])

    needs_by_draft = {index: _needs(draft.get("items", [])) for index, draft in enumerate(drafts)}
    all_needs = [need for needs in needs_by_draft.values() for need in needs]
    if all_needs:
        from app.repositories import warehouse as warehouse_repository

        warehouse_repository.gate_on_available_inventory(
            session,
            project_id,
            all_needs,
            label="shipping-out request",
            # #493: the gate's label only names the request in its error text, and the number does
            # not exist yet - it is minted per draft below.
            request_number=None,
        )

    created: list[ShippingOutRequest] = []
    from app.repositories.request_numbers import mint_request_number

    for index, draft in enumerate(drafts):
        # #493: minted from the project's counter, shared with shop-assembly requests so one
        # chronological sequence covers every pull on the job. The draft's request_number is
        # deprecated and ignored.
        request_number = mint_request_number(session, project_id)

        req = ShippingOutRequest(
            id=uuid.uuid4(),
            request_number=request_number,
            project_id=project_id,
            status=ShippingOutRequestStatus.PENDING,
            created_by=created_by,
            created_by_user_id=created_by_user_id,
            create_idempotency_key=idempotency_key or None,
        )
        session.add(req)
        session.flush()

        for item_input in draft.get("items", []):
            session.add(_build_item(req, item_input, request_number))

        # The request now holds its claim on stock until the pick that spends it (#342/#367).
        from app.repositories import warehouse as warehouse_repository

        warehouse_repository.create_reservations(
            session,
            project_id,
            ReservationSource.SHIPPING_OUT_REQUEST,
            req.id,
            needs_by_draft[index],
        )
        created.append(req)

    return created


# Namespace for the transaction-scoped advisory lock a keyed create takes on its key (#1552). The
# two-int form keeps it apart from every single-key advisory lock elsewhere.
_CREATE_KEY_LOCK_NAMESPACE = 1552


def _request_for_create_key(session: Session, project_id: uuid.UUID, key: str) -> ShippingOutRequest | None:
    """The request a create with this key already wrote, if any (#1552).

    A resend that overlaps its own first attempt would pass an unlocked look and write a second request,
    so the look is made under an advisory lock on the key: only attempts carrying the same key ever wait
    on it, so it orders against no other lock. The second waits for the first to commit, then finds it.
    """
    if len(key) > 100:
        raise ValidationError("idempotency_key must be at most 100 characters", field="idempotency_key")
    session.execute(select(func.pg_advisory_xact_lock(literal(_CREATE_KEY_LOCK_NAMESPACE), func.hashtext(key))))
    existing = session.scalars(
        select(ShippingOutRequest)
        .where(ShippingOutRequest.create_idempotency_key == key)
        .execution_options(populate_existing=True)
    ).first()
    if existing is not None and existing.project_id != project_id:
        raise ValidationError("This request key was already used on another project.", field="idempotency_key")
    return existing


def replace_shipping_out_request_items(
    session: Session,
    request_id: uuid.UUID,
    items: list[dict],
    *,
    expected_lines_version: str | None = None,
) -> ShippingOutRequest:
    """Rewrite a PENDING request's lines to exactly `items`, re-gating and re-reserving (#451).

    PENDING only. Once the request is accepted its lines have been copied onto a warehouse pull that
    the floor may already be picking, and editing behind that is how a picker ends up holding a sheet
    for hardware nobody asked for any more. Reopen it first (#325), then edit.

    The order here is load-bearing. The old reservations are released *before* the gate runs, so the
    request is measured against stock that includes what it was already holding - otherwise trimming
    a line from 4 to 3 would be gated as if it wanted 3 *more*. Anything the gate refuses raises, and
    the whole transaction rolls back with the original claim intact.

    `expected_lines_version` (#1260) is the `lines_version` the editor loaded. When it no longer
    matches, someone else saved the request in between, and replacing would silently undo their
    change, so the edit is refused and the editor reloads. Omitted, no check is made.
    """
    from app.repositories.shipping_repository import lock_shipping_out_request

    # Locked (#1107): an edit racing an accept could otherwise rewrite lines the accept had just
    # copied onto a warehouse pull.
    req = lock_shipping_out_request(session, request_id)
    if req.status != ShippingOutRequestStatus.PENDING:
        raise InvalidStateTransitionError(
            f"Shipping-out request must be Pending to edit; it is {status_label(req.status)}. "
            "Reopen it first if the warehouse has not started the pull."
        )
    if not items:
        raise ValidationError(
            "A shipping-out request needs at least one line. Reject it instead of emptying it.",
            field="items",
        )
    if expected_lines_version is not None and expected_lines_version != lines_version(req.items):
        raise ConflictError(
            f"Shipping-out request {req.request_number} was changed by someone else since you opened it. "
            "Reload it to see the current lines, then make your change again.",
            field="items",
        )
    _check_openings(session, req.project_id, items, request_number=req.request_number)

    from app.repositories import warehouse as warehouse_repository

    for existing in list(req.items):
        session.delete(existing)
    session.flush()
    warehouse_repository.release_reservations(session, ReservationSource.SHIPPING_OUT_REQUEST, req.id)

    needs = _needs(items)
    if needs:
        warehouse_repository.gate_on_available_inventory(
            session,
            req.project_id,
            needs,
            label="shipping-out request",
            request_number=req.request_number,
        )

    for item_input in items:
        session.add(_build_item(req, item_input, req.request_number))
    warehouse_repository.create_reservations(
        session,
        req.project_id,
        ReservationSource.SHIPPING_OUT_REQUEST,
        req.id,
        needs,
    )
    # #1174: the edit has just gated and reserved every line against today's stock and schedule, so a
    # note saying the request holds no claim (a cancelled pull it could not re-reserve) or that the
    # schedule moved under it is no longer true. Accept leaves the note alone: without an edit first,
    # the claim really is still missing.
    req.integrity_note = None
    session.flush()
    # The rows were written by id rather than by appending to the collection, so `req.items` still
    # holds the set that was just deleted. Expiring it makes the returned object tell the truth about
    # what the request now contains, rather than relying on the caller's commit to expire it.
    session.expire(req, ["items"])
    return req


def lines_version(items) -> str:
    """A fingerprint of a request's lines (#1260), so an edit can tell the lines it was composed
    against from what is stored now. Order-independent: the same lines in another order are the same
    request."""
    rows = sorted(
        (i.opening_number or "", i.hardware_category, i.product_code, int(i.requested_quantity)) for i in items
    )
    return hashlib.sha1(repr(rows).encode("utf-8")).hexdigest()[:16]


def get_reserved_by_product(session: Session, request_id: uuid.UUID) -> list[tuple[str, str, int]]:
    """What this request actually holds on stock, per product (#1262).

    Usually the request's line totals, but not always: a request sent back to Pending by a cancelled
    pull that could not be re-reserved holds nothing. The edit composer adds this back as headroom,
    so it must be the real claim rather than the lines.
    """
    from app.models.inventory_reservation import InventoryReservation

    rows = session.execute(
        select(
            InventoryReservation.hardware_category,
            InventoryReservation.product_code,
            func.sum(InventoryReservation.quantity),
        )
        .where(
            InventoryReservation.source == ReservationSource.SHIPPING_OUT_REQUEST,
            InventoryReservation.shipping_out_request_id == request_id,
        )
        .group_by(InventoryReservation.hardware_category, InventoryReservation.product_code)
    ).all()
    return [(cat, code, int(qty or 0)) for cat, code, qty in rows]


def _check_openings(
    session: Session,
    project_id: uuid.UUID,
    items: list[dict],
    *,
    request_number: str | None = None,
) -> None:
    """Refuse a line tagged to an opening the project does not have (#1258).

    A line raised off loose inventory carries no opening and is not checked. A schedule line keeps
    the opening it came off, and the pick sheet and the `sent` term both read that tag - so a tag on
    a door a re-upload has since dropped (a draft saved before the re-upload, or an API call) would
    reserve stock and misattribute what ships.
    """
    wanted = {item.get("opening_number") for item in items if item.get("opening_number")}
    if not wanted:
        return
    from app.models.project import Opening

    known = set(
        session.scalars(
            select(Opening.opening_number).where(
                Opening.project_id == project_id,
                Opening.opening_number.in_(wanted),
            )
        )
    )
    missing = sorted(wanted - known)
    if missing:
        label = f"Shipping-out request {request_number}: " if request_number else ""
        raise ValidationError(
            f"{label}opening {', '.join(missing)} is not on this project's schedule. "
            "Remove the line or re-add it from the current schedule.",
            field="opening_number",
        )


def _needs(items: list[dict]) -> list[tuple[str, str, int]]:
    """What one request's lines claim, as the reservation and gate helpers want it."""
    return [
        (item["hardware_category"], item["product_code"], item.get("requested_quantity", 1))
        for item in items
        if item.get("hardware_category") and item.get("product_code")
    ]


def _build_item(
    req: ShippingOutRequest,
    item_input: dict,
    request_number: str,
) -> ShippingOutRequestItem:
    """One request line."""
    if not item_input.get("hardware_category") or not item_input.get("product_code"):
        raise ValidationError(
            f"Shipping-out request {request_number}: a line must name a hardware category and product code",
            field="product_code",
        )

    quantity = item_input.get("requested_quantity", 1)
    if quantity is None or quantity < 1:
        raise ValidationError(
            f"Shipping-out request {request_number}: a line must ask for at least one unit",
            field="requested_quantity",
        )

    return ShippingOutRequestItem(
        id=uuid.uuid4(),
        shipping_out_request_id=req.id,
        # Null on a line raised straight off inventory (#451): a hinge on a shelf carries no opening,
        # and inventing one would be a claim the schedule never made. Schedule-driven lines keep
        # their attribution.
        opening_number=item_input.get("opening_number") or None,
        hardware_category=item_input["hardware_category"],
        product_code=item_input["product_code"],
        requested_quantity=quantity,
    )
