"""Creating and editing shipping-out requests, from either of the two places they are raised (#451).

Start a Request raises one off the hardware schedule; the Shipping module raises one straight off
project inventory, for the loose stock a schedule line never accounted for. Both land here, because
every guard below is a property of the request itself and not of the screen that composed it: one
physical leaf ships once, a leaf still on the bench cannot leave the building, an empty request has
nothing to accept, and a LOOSE line has to fit inside what is genuinely free (#342).

Editing is full-replace over the item list rather than a diff. The client sends the request it
wants, not the steps to get there: a diff has to be applied in an order that never transiently
over-claims, and every caller would be reconstructing the same final list anyway. Replace releases
the request's own claim first, so a line whose quantity is being *reduced* is not gated against
stock it already holds.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.errors import ConflictError, InvalidStateTransitionError, NotFoundError, ValidationError
from app.models.enums import (
    OpeningItemState,
    PullRequestItemType,
    ReservationSource,
    ShippingOutRequestStatus,
)
from app.models.opening_item import OpeningItem as OpeningItemModel
from app.models.shipping_out_request import ShippingOutRequest, ShippingOutRequestItem


def create_shipping_out_requests(
    session: Session,
    project_id: uuid.UUID,
    drafts: list[dict],
    *,
    created_by: str,
    acknowledge_incomplete_leaves: bool = False,
) -> list[ShippingOutRequest]:
    """Mint PENDING shipping-out requests and the reservations that back their loose lines.

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
                f"Shipping-out request {draft['request_number']} has no items - "
                "select at least one assembled leaf or loose line.",
                field="items",
            )

    opening_items_by_id = _load_referenced_leaves(session, drafts)
    _guard_unique_leaves(drafts, opening_items_by_id)
    _guard_leaves(
        session,
        project_id,
        opening_items_by_id,
        acknowledge_incomplete_leaves=acknowledge_incomplete_leaves,
    )

    loose_needs_by_draft = {index: _loose_needs(draft.get("items", [])) for index, draft in enumerate(drafts)}
    all_needs = [need for needs in loose_needs_by_draft.values() for need in needs]
    if all_needs:
        from app.repositories import warehouse as warehouse_repository

        warehouse_repository.gate_on_available_inventory(
            session,
            project_id,
            all_needs,
            label="shipping-out request",
            request_number=drafts[0]["request_number"],
        )

    created: list[ShippingOutRequest] = []
    for index, draft in enumerate(drafts):
        request_number = (draft["request_number"] or "").strip()
        if not request_number:
            raise ValidationError("A shipping-out request needs a request number.", field="request_number")
        existing = session.scalars(
            select(ShippingOutRequest).where(ShippingOutRequest.request_number == request_number)
        ).first()
        if existing is not None:
            raise ConflictError(
                f"Shipping-out request {request_number} already exists",
                field="request_number",
            )

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
            session.add(_build_item(req, project_id, item_input, opening_items_by_id, request_number))

        # The request now holds its claim on loose stock until the pick that spends it (#342/#367).
        # Nothing for the OPENING_ITEM lines: an assembled leaf left fungible inventory when it was
        # built and ships as itself (docs/HARDWARE_IDENTITY_LIFECYCLE.md).
        from app.repositories import warehouse as warehouse_repository

        warehouse_repository.create_reservations(
            session,
            project_id,
            ReservationSource.SHIPPING_OUT_REQUEST,
            req.id,
            loose_needs_by_draft[index],
        )
        created.append(req)

    return created


def replace_shipping_out_request_items(
    session: Session,
    request_id: uuid.UUID,
    items: list[dict],
    *,
    acknowledge_incomplete_leaves: bool = False,
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

    opening_items_by_id = _load_referenced_leaves(session, [{"items": items}])
    _guard_unique_leaves([{"items": items}], opening_items_by_id)
    # Leaves already on THIS request are not a conflict with themselves, so they are excluded from
    # the duplicate guard - an edit that keeps a leaf and changes a loose line must not be refused
    # for holding what it already holds.
    _guard_leaves(
        session,
        req.project_id,
        opening_items_by_id,
        acknowledge_incomplete_leaves=acknowledge_incomplete_leaves,
        ignore_request_number=req.request_number,
    )

    for existing in list(req.items):
        session.delete(existing)
    session.flush()
    warehouse_repository.release_reservations(session, ReservationSource.SHIPPING_OUT_REQUEST, req.id)

    needs = _loose_needs(items)
    if needs:
        warehouse_repository.gate_on_available_inventory(
            session,
            req.project_id,
            needs,
            label="shipping-out request",
            request_number=req.request_number,
        )

    for item_input in items:
        session.add(_build_item(req, req.project_id, item_input, opening_items_by_id, req.request_number))
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


# ---------------------------------------------------------------------------------------------
# internals shared by both entry points
# ---------------------------------------------------------------------------------------------


def leaf_label(oi: OpeningItemModel) -> str:
    """ "Opening 0019-EX Leaf 2", or just the opening number for a legacy whole-opening unit."""
    return f"Opening {oi.opening_number} Leaf {oi.leaf}" if oi.leaf is not None else f"Opening {oi.opening_number}"


def _loose_needs(items: list[dict]) -> list[tuple[str, str, int]]:
    """What the LOOSE lines of one request claim, as the reservation and gate helpers want it."""
    return [
        (item["hardware_category"], item["product_code"], item.get("requested_quantity", 1))
        for item in items
        if PullRequestItemType(item["item_type"]) == PullRequestItemType.LOOSE
        and item.get("hardware_category")
        and item.get("product_code")
    ]


def _load_referenced_leaves(session: Session, drafts: list[dict]) -> dict[uuid.UUID, OpeningItemModel]:
    """Every OpeningItem an OPENING_ITEM line points at, read once for the whole call.

    Read rather than trusted: each line is then checked against the real row, so an id that is
    missing, foreign or already shipped cannot mint a line that moves someone else's leaf.
    """
    ids = {
        uuid.UUID(str(item["opening_item_id"]))
        for draft in drafts
        for item in draft.get("items", [])
        if item.get("opening_item_id")
    }
    if not ids:
        return {}
    return {oi.id: oi for oi in session.scalars(select(OpeningItemModel).where(OpeningItemModel.id.in_(ids))).all()}


# The input a caller has to set to get past the incomplete-leaf refusal below. It is named as the
# error's `field` so the browser can tell that one refusal apart from the two beneath it, which name
# `opening_item_id` and are not answerable by confirming anything.
ACKNOWLEDGE_FIELD = "acknowledge_incomplete_leaves"


def _guard_unique_leaves(
    drafts: list[dict],
    opening_items_by_id: dict[uuid.UUID, OpeningItemModel],
) -> None:
    """One physical leaf, named once, across everything this call is about to write.

    The guards below only see claims that were already committed, and `_load_referenced_leaves`
    collapses the ids into a set - so on its own, nothing here notices a leaf named twice inside a
    single call. Two OPENING_ITEM lines on one request would mint two lines that both move it; two
    drafts in one finalize would mint two live requests holding it, which is precisely what the
    already-on-a-live-request guard exists to prevent.
    """
    seen: set[uuid.UUID] = set()
    repeated: set[uuid.UUID] = set()
    for draft in drafts:
        for item in draft.get("items", []):
            raw = item.get("opening_item_id")
            if not raw:
                continue
            oi_id = uuid.UUID(str(raw))
            if oi_id in seen:
                repeated.add(oi_id)
            seen.add(oi_id)

    if repeated:
        detail = ", ".join(
            sorted(
                leaf_label(opening_items_by_id[oi_id]) if oi_id in opening_items_by_id else str(oi_id)
                for oi_id in repeated
            )
        )
        raise ValidationError(
            f"These assembled leaves are named more than once: {detail}. One physical leaf ships on "
            "one line of one request.",
            field="opening_item_id",
        )


def _guard_leaves(
    session: Session,
    project_id: uuid.UUID,
    opening_items_by_id: dict[uuid.UUID, OpeningItemModel],
    *,
    acknowledge_incomplete_leaves: bool,
    ignore_request_number: str | None = None,
) -> None:
    """The three things that can be wrong with the assembled leaves a request names.

    Incomplete (#341): the leaf is physically short of the hardware list it would ship under, for
    two unrelated reasons the shipper has to be able to tell apart - a unit awaiting a replacement
    (a pull exists, waiting is a real option) and a unit that was never pulled (waiting does
    nothing; purchasing and reallocation close that gap). Warn + confirm, never silent and never a
    hard block: deliberate short-shipping is a real workflow, it just has to be a decision someone
    made.

    Already claimed: one physical leaf sits on exactly one live request. The UI hides claimed
    leaves, but a stale tab or a non-UI caller must not be able to send the same leaf twice.

    Still in assembly: the same leaf cannot be on its way out the door and inside a live
    shop-assembly work unit.
    """
    if not opening_items_by_id:
        return

    referenced = list(opening_items_by_id)

    if not acknowledge_incomplete_leaves:
        from app.repositories import shop_assembly_repository

        shortfalls = shop_assembly_repository.get_leaf_shortfalls(session, referenced)
        if shortfalls:
            # Name every flagged leaf, not just the first: the user is being asked to make a
            # decision, and can only make it once if they can see the whole list.
            labels = []
            for oi_id, shortfall in shortfalls.items():
                oi = opening_items_by_id.get(oi_id)
                if oi is None:
                    continue
                parts = []
                if shortfall.awaiting_replacement:
                    parts.append(f"{shortfall.awaiting_replacement} unit(s) awaiting replacement")
                if shortfall.never_pulled:
                    parts.append(f"{shortfall.never_pulled} unit(s) never pulled")
                labels.append(f"{leaf_label(oi)} ({', '.join(parts)})")
            if labels:
                raise ValidationError(
                    "These assembled leaves are incomplete - hardware they should carry is either "
                    f"awaiting a replacement or was never pulled: {', '.join(sorted(labels))}. "
                    "Confirm you want to ship them short, or wait for the hardware.",
                    field=ACKNOWLEDGE_FIELD,
                )

    from app.repositories import shipping_repository
    from app.repositories import shop_assembly_repository as sa_repository

    claims = shipping_repository.find_live_shipping_claims(session, project_id, opening_item_ids=referenced)[
        "by_opening_item"
    ]
    conflicting = {
        oi_id: request_number
        for oi_id, request_number in claims.items()
        if oi_id in opening_items_by_id and request_number != ignore_request_number
    }
    if conflicting:
        detail = ", ".join(
            sorted(f"{leaf_label(opening_items_by_id[oi_id])} (on {number})" for oi_id, number in conflicting.items())
        )
        raise ValidationError(
            f"These assembled leaves are already on a live shipping-out request: {detail}. "
            "Reject or complete that request first.",
            field="opening_item_id",
        )

    leaf_specs = [
        (oi.opening_number, oi.opening_id, oi.leaf)
        for oi in opening_items_by_id.values()
        if oi.project_id == project_id
    ]
    in_assembly = sa_repository.find_in_flight_assembly_leaves(session, leaf_specs)
    if in_assembly:
        detail = ", ".join(
            sorted(
                f"Opening {num}"
                + (f" Leaf {leaf}" if leaf is not None else "")
                + (f" (on shop-assembly request {number})" if number else "")
                for num, leaf, number in in_assembly
            )
        )
        raise ValidationError(
            f"These leaves are still in shop assembly: {detail}. They cannot be shipped "
            "until that work unit is finished or its request is rejected.",
            field="opening_item_id",
        )


def _build_item(
    req: ShippingOutRequest,
    project_id: uuid.UUID,
    item_input: dict,
    opening_items_by_id: dict[uuid.UUID, OpeningItemModel],
    request_number: str,
) -> ShippingOutRequestItem:
    """One request line, with the OPENING_ITEM invariants enforced against the real leaf."""
    item_type = PullRequestItemType(item_input["item_type"])
    opening_item_id = item_input.get("opening_item_id")
    opening_number = item_input.get("opening_number")

    if item_type == PullRequestItemType.OPENING_ITEM:
        label = f"Shipping-out request {request_number}, opening {opening_number}"
        if not opening_item_id:
            raise ValidationError(
                f"{label}: an assembled-opening line must reference an opening item",
                field="opening_item_id",
            )
        oi = opening_items_by_id.get(uuid.UUID(str(opening_item_id)))
        if oi is None or oi.project_id != project_id:
            raise ValidationError(
                f"{label}: opening item {opening_item_id} does not belong to this project",
                field="opening_item_id",
            )
        if oi.state != OpeningItemState.IN_INVENTORY:
            raise ValidationError(
                f"{label}: {leaf_label(oi)} is {oi.state.value}, not in inventory, so it "
                f"cannot be requested for shipping",
                field="opening_item_id",
            )
        # The leaf IS an opening and IS a leaf, so both come off the row rather than off the client.
        # A composer that names neither still produces a line a pair reads as two distinct entries.
        opening_number = opening_number or oi.opening_number
        if item_input.get("leaf") is None:
            item_input = {**item_input, "leaf": oi.leaf}
    elif not item_input.get("hardware_category") or not item_input.get("product_code"):
        raise ValidationError(
            f"Shipping-out request {request_number}: a loose line must name a hardware category and product code",
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
        item_type=item_type,
        # Null on a line raised straight off inventory (#451): a hinge on a shelf carries no opening,
        # and inventing one would be a claim the schedule never made. Schedule-driven lines keep
        # their attribution.
        opening_number=opening_number,
        opening_item_id=(uuid.UUID(str(opening_item_id)) if opening_item_id else None),
        leaf=item_input.get("leaf"),
        hardware_category=item_input.get("hardware_category"),
        product_code=item_input.get("product_code"),
        requested_quantity=quantity,
    )
