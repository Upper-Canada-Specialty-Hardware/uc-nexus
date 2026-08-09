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

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.errors import InvalidStateTransitionError, NotFoundError, ValidationError
from app.models.enums import ReservationSource, ShippingOutRequestStatus
from app.models.shipping_out_request import ShippingOutRequest, ShippingOutRequestItem


def create_shipping_out_requests(
    session: Session,
    project_id: uuid.UUID,
    drafts: list[dict],
    *,
    created_by: str,
) -> list[ShippingOutRequest]:
    """Mint PENDING shipping-out requests and the reservations that back their lines.

    Every draft in one call competes for the same stock and is gated together, because they are
    created in one transaction: gating them one at a time would let the second draft pass on stock
    the first had already spoken for.

    No PullRequest is minted here. A signed-in user accepts the request later, and that accept is
    what mints the warehouse pull (#293).
    """
    if not drafts:
        return []

    for draft in drafts:
        if not draft.get("items"):
            raise ValidationError(
                "A shipping-out request has no items - select at least one line.",
                field="items",
            )

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


def replace_shipping_out_request_items(
    session: Session,
    request_id: uuid.UUID,
    items: list[dict],
) -> ShippingOutRequest:
    """Rewrite a PENDING request's lines to exactly `items`, re-gating and re-reserving (#451).

    PENDING only. Once the request is accepted its lines have been copied onto a warehouse pull that
    the floor may already be picking, and editing behind that is how a picker ends up holding a sheet
    for hardware nobody asked for any more. Reopen it first (#325), then edit.

    The order here is load-bearing. The old reservations are released *before* the gate runs, so the
    request is measured against stock that includes what it was already holding - otherwise trimming
    a line from 4 to 3 would be gated as if it wanted 3 *more*. Anything the gate refuses raises, and
    the whole transaction rolls back with the original claim intact.
    """
    req = (
        session.scalars(
            select(ShippingOutRequest)
            .options(selectinload(ShippingOutRequest.items))
            .where(ShippingOutRequest.id == request_id)
        )
        .unique()
        .first()
    )
    if req is None:
        raise NotFoundError(f"Shipping-out request {request_id} not found")
    if req.status != ShippingOutRequestStatus.PENDING:
        raise InvalidStateTransitionError(
            f"Shipping-out request must be Pending to edit, got {req.status.value}. "
            "Reopen it first if the warehouse has not started the pull."
        )
    if not items:
        raise ValidationError(
            "A shipping-out request needs at least one line. Reject it instead of emptying it.",
            field="items",
        )

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
    session.flush()
    # The rows were written by id rather than by appending to the collection, so `req.items` still
    # holds the set that was just deleted. Expiring it makes the returned object tell the truth about
    # what the request now contains, rather than relying on the caller's commit to expire it.
    session.expire(req, ["items"])
    return req


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
