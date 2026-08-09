"""What each opening still has coming, for whichever request is being composed.

Shop assembly and shipping out both ask the same question at composition time, so they get the same
answer from here:

    *I have picked these openings. What does the schedule still owe them, what has already left,
    what is somebody else already holding, and what is still at the vendor?*

    suggested = max(owed - sent - claimed, 0)

**Owed** is the CURRENT schedule (`HardwareItem`), summed per (opening, category, product). The leaf
is summed away: `HardwareItem.leaf` survives as parsed demand data but stops propagating downstream,
because nothing past this point carries a door.

**Sent** is hardware that has left the building. There are exactly two exits and a completed pull is
the moment of both:

  - shop assembly - a completed SHOP_ASSEMBLY pull is terminal. The bench work that follows is
    untracked in v1, so the pull is the last thing the system sees.
  - shipping out - a completed SHIPPING_OUT pull, and then the packing slip cut from it.
    `max(pull, slip)` per key folds those two into one exit rather than adding them: the slip
    consumes what the pull fulfilled, so summing would charge the opening twice for one shipment,
    and taking only the slip would re-offer everything sitting picked and waiting for a truck.

**Claimed** is hardware spoken for but not yet gone: lines on PENDING requests, plus lines on pulls
that are live (approved or being picked) but not completed. Read off the *pull* rather than the
accepted request behind it, because accept copies the request's lines onto the pull - counting both
would double the claim. A completed pull leaves this term and enters `sent` in the same instant, so
it is counted once and only once. Cancelled pulls and rejected requests appear in neither: they put
the hardware back.

Two consequences worth being explicit about, because they are the point rather than accidents:

  - A re-upload that lowers `owed` below what has already been sent reads zero, never negative and
    never a return. The system does not auto-unwind a shipment because a schedule changed; a human
    decides what to do about hardware already at site.
  - Nothing here is availability. `projectInventoryAvailability` answers "what may I claim" (#342)
    and the creation gate is applied against that number. A second availability figure computed here
    at a slightly different instant is exactly the drift that would let the panel say 3 and the
    shortfall alert say 2. The caller joins the two by combo key.

Query budget is fixed at EIGHT regardless of how many openings are selected (CLAUDE.md perf rules):
the openings, the grouped schedule read, two behind `sent` (completed pulls, packing slips), three
behind `claimed` (live pulls, pending shop-assembly requests, pending shipping-out requests), and
the on-order aggregate.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enums import (
    Classification,
    POStatus,
    PullRequestSource,
    PullRequestStatus,
    ShippingOutRequestStatus,
    ShopAssemblyRequestStatus,
)
from app.models.hardware import HardwareItem as HardwareItemModel
from app.models.project import Opening as OpeningModel
from app.models.pull_request import PullRequest as PullRequestModel
from app.models.pull_request import PullRequestItem as PullRequestItemModel
from app.models.purchase_order import POLineItem as POLineItemModel
from app.models.purchase_order import PurchaseOrder as PurchaseOrderModel
from app.models.shipping import PackingSlip, PackingSlipItem
from app.models.shipping_out_request import ShippingOutRequest, ShippingOutRequestItem
from app.models.shop_assembly import ShopAssemblyRequest, ShopAssemblyRequestItem

# A PO counts as "on the way" once it has been placed with the vendor and until it is closed out.
# DRAFT is excluded on purpose: nobody has ordered it, so promising it to a requester would be a lie.
ON_ORDER_PO_STATUSES = (
    POStatus.GP_REGISTERED,
    POStatus.VENDOR_CONFIRMED,
    POStatus.PARTIALLY_RECEIVED,
)

# A pull holds its claim from the moment it is minted until it completes or is cancelled.
_LIVE_PULL_STATUSES = (PullRequestStatus.PENDING, PullRequestStatus.IN_PROGRESS)

_ComboKey = tuple[str, str]
_OpeningComboKey = tuple[str, str, str]


def get_request_coverage(
    session: Session,
    project_id: uuid.UUID,
    opening_numbers: list[str],
) -> list[dict]:
    """One row per (opening, category, product) the given openings are owed or have been sent.

    A product the schedule no longer lists but that has already gone out still gets a row, reading
    `owed 0 / sent n / suggested 0`. Dropping it would make a lowered schedule look like nothing ever
    happened, which is the one case where a silent zero is worse than a visible one.
    """
    if not opening_numbers:
        return []

    wanted = list(dict.fromkeys(opening_numbers))

    openings = session.execute(
        select(OpeningModel.id, OpeningModel.opening_number).where(
            OpeningModel.project_id == project_id,
            OpeningModel.opening_number.in_(wanted),
        )
    ).all()
    opening_number_by_id = {oid: number for oid, number in openings}
    # An opening the schedule has since dropped can still have been sent hardware, so the reads below
    # work off the numbers that were asked for, not only the ones the schedule still resolves.
    known = sorted(set(wanted))

    owed = _owed_quantities(session, project_id, opening_number_by_id)
    sent = _sent_quantities(session, project_id, known)
    claimed = _claimed_quantities(session, project_id, known)
    on_order = _on_order_quantities(session, project_id)

    rows: list[dict] = []
    for opening_number in known:
        keys = sorted(
            {key for key in owed.get(opening_number, {})}
            | {key for key in sent.get(opening_number, {})}
            | {key for key in claimed.get(opening_number, {})}
        )
        for key in keys:
            owed_line = owed.get(opening_number, {}).get(key)
            owed_quantity = owed_line["owed_quantity"] if owed_line else 0
            sent_quantity = sent.get(opening_number, {}).get(key, 0)
            claimed_quantity = claimed.get(opening_number, {}).get(key, 0)
            rows.append(
                {
                    "opening_number": opening_number,
                    "hardware_category": key[0],
                    "product_code": key[1],
                    "classification": _dominant_classification(owed_line),
                    "owed_quantity": owed_quantity,
                    "sent_quantity": sent_quantity,
                    "claimed_quantity": claimed_quantity,
                    # Floored at 0. An opening that has been sent more than the current schedule asks
                    # for is over-supplied, not owed a negative quantity.
                    "suggested_quantity": max(0, owed_quantity - sent_quantity - claimed_quantity),
                    "on_order_quantity": on_order.get(key, 0),
                }
            )
    return rows


def _owed_quantities(
    session: Session,
    project_id: uuid.UUID,
    opening_number_by_id: dict[uuid.UUID, str],
) -> dict[str, dict[_ComboKey, dict]]:
    """What the current schedule says each opening takes, as {opening: {(cat, code): line}}.

    Grouped in SQL down to (opening, category, product, classification). Classification is part of
    the key because it is a column on the item rows and two rows for the same product on the same
    opening are free to disagree; the disagreement is resolved when the line is emitted, by unit
    count, so the display never depends on row order.
    """
    opening_ids = list(opening_number_by_id)
    if not opening_ids:
        return {}

    rows = session.execute(
        select(
            HardwareItemModel.opening_id,
            HardwareItemModel.hardware_category,
            HardwareItemModel.product_code,
            HardwareItemModel.classification,
            func.sum(HardwareItemModel.item_quantity),
        )
        .where(
            HardwareItemModel.project_id == project_id,
            HardwareItemModel.opening_id.in_(opening_ids),
        )
        .group_by(
            HardwareItemModel.opening_id,
            HardwareItemModel.hardware_category,
            HardwareItemModel.product_code,
            HardwareItemModel.classification,
        )
    ).all()

    out: dict[str, dict[_ComboKey, dict]] = {}
    for opening_id, category, code, classification, quantity in rows:
        opening_number = opening_number_by_id.get(opening_id)
        if opening_number is None:
            continue
        line = out.setdefault(opening_number, {}).setdefault(
            (category, code),
            {"owed_quantity": 0, "by_classification": {}},
        )
        line["owed_quantity"] += int(quantity or 0)
        key = classification.value if classification is not None else None
        line["by_classification"][key] = line["by_classification"].get(key, 0) + int(quantity or 0)
    return out


def _sent_quantities(
    session: Session,
    project_id: uuid.UUID,
    opening_numbers: list[str],
) -> dict[str, dict[_ComboKey, int]]:
    """Units that have left the building, per {opening: {(cat, code): quantity}}.

    Shop assembly and shipping out are added together - they are different exits, and hardware that
    went to the bench is not hardware that went on a truck. Within shipping out, the completed pull
    and the slip cut from it are folded with `max`, because they are two records of one departure.
    """
    if not opening_numbers:
        return {}

    completed_by_source: dict[PullRequestSource, dict[_OpeningComboKey, int]] = {
        PullRequestSource.SHOP_ASSEMBLY: {},
        PullRequestSource.SHIPPING_OUT: {},
    }
    for opening_number, category, code, source, quantity in session.execute(
        select(
            PullRequestItemModel.opening_number,
            PullRequestItemModel.hardware_category,
            PullRequestItemModel.product_code,
            PullRequestModel.source,
            func.sum(PullRequestItemModel.requested_quantity),
        )
        .join(PullRequestModel, PullRequestItemModel.pull_request_id == PullRequestModel.id)
        .where(
            PullRequestModel.project_id == project_id,
            PullRequestModel.status == PullRequestStatus.COMPLETED,
            PullRequestModel.deleted_at.is_(None),
            PullRequestItemModel.opening_number.in_(opening_numbers),
        )
        .group_by(
            PullRequestItemModel.opening_number,
            PullRequestItemModel.hardware_category,
            PullRequestItemModel.product_code,
            PullRequestModel.source,
        )
    ).all():
        key = (opening_number, category, code)
        bucket = completed_by_source[source]
        bucket[key] = bucket.get(key, 0) + int(quantity or 0)

    shipped: dict[_OpeningComboKey, int] = {}
    for opening_number, category, code, quantity in session.execute(
        select(
            PackingSlipItem.opening_number,
            PackingSlipItem.hardware_category,
            PackingSlipItem.product_code,
            func.sum(PackingSlipItem.quantity),
        )
        .join(PackingSlip, PackingSlipItem.packing_slip_id == PackingSlip.id)
        .where(
            PackingSlip.project_id == project_id,
            PackingSlipItem.opening_number.in_(opening_numbers),
        )
        .group_by(
            PackingSlipItem.opening_number,
            PackingSlipItem.hardware_category,
            PackingSlipItem.product_code,
        )
    ).all():
        key = (opening_number, category, code)
        shipped[key] = shipped.get(key, 0) + int(quantity or 0)

    assembled = completed_by_source[PullRequestSource.SHOP_ASSEMBLY]
    shipped_out = completed_by_source[PullRequestSource.SHIPPING_OUT]

    out: dict[str, dict[_ComboKey, int]] = {}
    for key in set(assembled) | set(shipped_out) | set(shipped):
        opening_number, category, code = key
        total = assembled.get(key, 0) + max(shipped_out.get(key, 0), shipped.get(key, 0))
        if total > 0:
            out.setdefault(opening_number, {})[(category, code)] = total
    return out


def _claimed_quantities(
    session: Session,
    project_id: uuid.UUID,
    opening_numbers: list[str],
) -> dict[str, dict[_ComboKey, int]]:
    """Units somebody else is already holding, per {opening: {(cat, code): quantity}}.

    Two reads, arranged so an accepted request is never counted alongside the pull it minted: live
    pulls (the accepted half), and PENDING requests of both kinds (the half that has no pull yet).
    """
    if not opening_numbers:
        return {}

    claimed: dict[_OpeningComboKey, int] = {}

    def add(opening_number: str, category: str, code: str, quantity: int | None) -> None:
        key = (opening_number, category, code)
        claimed[key] = claimed.get(key, 0) + int(quantity or 0)

    for opening_number, category, code, quantity in session.execute(
        select(
            PullRequestItemModel.opening_number,
            PullRequestItemModel.hardware_category,
            PullRequestItemModel.product_code,
            func.sum(PullRequestItemModel.requested_quantity),
        )
        .join(PullRequestModel, PullRequestItemModel.pull_request_id == PullRequestModel.id)
        .where(
            PullRequestModel.project_id == project_id,
            PullRequestModel.status.in_(_LIVE_PULL_STATUSES),
            PullRequestModel.deleted_at.is_(None),
            PullRequestItemModel.opening_number.in_(opening_numbers),
        )
        .group_by(
            PullRequestItemModel.opening_number,
            PullRequestItemModel.hardware_category,
            PullRequestItemModel.product_code,
        )
    ).all():
        add(opening_number, category, code, quantity)

    for opening_number, category, code, quantity in session.execute(
        select(
            ShopAssemblyRequestItem.opening_number,
            ShopAssemblyRequestItem.hardware_category,
            ShopAssemblyRequestItem.product_code,
            func.sum(ShopAssemblyRequestItem.allocated_quantity),
        )
        .join(ShopAssemblyRequest, ShopAssemblyRequestItem.shop_assembly_request_id == ShopAssemblyRequest.id)
        .where(
            ShopAssemblyRequest.project_id == project_id,
            ShopAssemblyRequest.status == ShopAssemblyRequestStatus.PENDING,
            ShopAssemblyRequestItem.opening_number.in_(opening_numbers),
        )
        .group_by(
            ShopAssemblyRequestItem.opening_number,
            ShopAssemblyRequestItem.hardware_category,
            ShopAssemblyRequestItem.product_code,
        )
    ).all():
        add(opening_number, category, code, quantity)

    for opening_number, category, code, quantity in session.execute(
        select(
            ShippingOutRequestItem.opening_number,
            ShippingOutRequestItem.hardware_category,
            ShippingOutRequestItem.product_code,
            func.sum(ShippingOutRequestItem.requested_quantity),
        )
        .join(ShippingOutRequest, ShippingOutRequestItem.shipping_out_request_id == ShippingOutRequest.id)
        .where(
            ShippingOutRequest.project_id == project_id,
            ShippingOutRequest.status == ShippingOutRequestStatus.PENDING,
            ShippingOutRequestItem.opening_number.in_(opening_numbers),
        )
        .group_by(
            ShippingOutRequestItem.opening_number,
            ShippingOutRequestItem.hardware_category,
            ShippingOutRequestItem.product_code,
        )
    ).all():
        add(opening_number, category, code, quantity)

    out: dict[str, dict[_ComboKey, int]] = {}
    for (opening_number, category, code), total in claimed.items():
        if total > 0:
            out.setdefault(opening_number, {})[(category, code)] = total
    return out


def _on_order_quantities(session: Session, project_id: uuid.UUID) -> dict[_ComboKey, int]:
    """Placed-but-not-received units per (category, product) across the project's live POs.

    `greatest(ordered - received, 0)` per line before summing: an over-receive is a real thing and
    it must not silently cancel out another line's genuine backorder.
    """
    rows = session.execute(
        select(
            POLineItemModel.hardware_category,
            POLineItemModel.product_code,
            func.sum(func.greatest(POLineItemModel.ordered_quantity - POLineItemModel.received_quantity, 0)),
        )
        .join(PurchaseOrderModel, POLineItemModel.po_id == PurchaseOrderModel.id)
        .where(
            PurchaseOrderModel.project_id == project_id,
            PurchaseOrderModel.deleted_at.is_(None),
            PurchaseOrderModel.status.in_(ON_ORDER_PO_STATUSES),
        )
        .group_by(POLineItemModel.hardware_category, POLineItemModel.product_code)
    ).all()
    return {(category, code): int(total or 0) for category, code, total in rows if total}


def _dominant_classification(owed_line: dict | None) -> Classification | None:
    """The classification of one product on one opening: whichever covers the most units.

    Rows for the same product on the same opening can disagree (they are separate schedule entries
    and each carries its own column), so this has to be decided rather than picked off the first row.
    Unit count first, then enum name, so the answer never depends on query order. An unclassified
    majority answers None, which the composer groups under "unclassified" rather than guessing site
    or shop on the user's behalf.
    """
    if not owed_line:
        return None
    ranked = sorted(
        owed_line["by_classification"].items(),
        key=lambda item: (-item[1], item[0] or ""),
    )
    winner = ranked[0][0]
    return Classification(winner) if winner is not None else None
