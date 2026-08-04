"""Where every unit of an opening's hardware actually is, for the admin Opening Status page.

The page asks one question per opening: the schedule says this opening takes these products in these
quantities - where is each of those units right now? Answering it means walking the whole identity
lifecycle, because hardware changes hands several times between TITAN and the site.

**"Received" is not a state this module can report per opening, and that is a property of the domain
rather than a gap here.** `InventoryLocation` is keyed by (project, warehouse, category, product) and
carries no opening or leaf column - a hinge on the shelf belongs to the project, not to a door
(docs/HARDWARE_IDENTITY_LIFECYCLE.md). A receipt therefore cannot be attributed back to the opening
whose schedule caused the purchase. The PO line's received/ordered fill travels alongside the ORDERED
bucket as context ("these 2 hinges sit on a line that is 40 of 100 received"), never as this
opening's units having arrived.

Identity comes back at the pull, which is why everything downstream of it CAN be reported per
opening: a pull request line tags fungible stock onto a specific leaf of a specific opening.

Every unit of an owed line lands in exactly ONE bucket - furthest along wins - so the buckets account
for the line's whole owed quantity and no unit is counted twice:

    SHIPPED_ON_LEAF          OpeningItemHardware on a SHIPPED_OUT assembled unit
    STAGED                   OpeningItemHardware on a SHIP_READY assembled unit
    ASSEMBLED_IN_INVENTORY   OpeningItemHardware on an IN_INVENTORY assembled unit
    PULLED_FOR_ASSEMBLY      allocated on a live shop-assembly work unit (see below)
    ---- whatever no fulfilment bucket claimed is described by the schedule row's own PO linkage ----
    ORDERED                  on a placed PO (registered / confirmed / partially received / closed)
    PO_DRAFTED               on a DRAFT PO
    NOT_PURCHASED            no PO line at all, or its PO was cancelled or soft-deleted

PULLED_FOR_ASSEMBLY spans "a live request has claimed these units" through "they are on the bench".
It deliberately does not split at pick confirmation: the leaf chip already says whether the leaf is
assembled, and one bucket keeps the partition total honest. Cancelled pulls are excluded - cancelling
restocks the hardware, so the opening is owed it again.

Loose hardware is reported per OPENING and never per leaf, because that is the only identity it ever
regains: a LOOSE pull line carries `opening_number` and no leaf. Site hardware never goes near the
bench, so this is the whole of its story, and it gets its own two buckets:

    SHIPPED_LOOSE            PackingSlipItem LOOSE rows - units that have physically left
    PULLED_FOR_SHIPPING      staged-but-unshipped, plus in-flight shipping-out claims

The buckets SUM to the owed quantity in the ordinary case. They exceed it when a leaf physically
carries more of a product than the current schedule asks for - assembled off an older revision, or
over-assembled - because the fulfilment buckets report what is really there rather than clamping to
a number the hardware does not know about. What they never do is fall short: every owed unit is
accounted for by exactly one bucket.

The `max(shipped, fulfilled)` fold in `_loose_quantities` is lifted from
`shipping_coverage._spoken_for_quantities` and means the same thing there and here: a shipped unit
was fulfilled first, so the two overlap and adding them would double-count.

Query budget is a fixed EIGHT grouped statements - the same eight whether the caller wants a whole
project's rollup or one opening's detail - so cost grows with rows returned and never with the number
of openings (CLAUDE.md perf rules).
"""

import uuid
from dataclasses import dataclass, field

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.models.enums import (
    AssemblyStatus,
    OpeningItemState,
    POStatus,
    PullRequestItemType,
    PullRequestSource,
    PullRequestStatus,
    ShippingOutRequestStatus,
)
from app.models.hardware import HardwareItem as HardwareItemModel
from app.models.opening_item import OpeningItem as OpeningItemModel
from app.models.opening_item import OpeningItemHardware as OpeningItemHardwareModel
from app.models.project import Opening as OpeningModel
from app.models.pull_request import PullRequest as PullRequestModel
from app.models.pull_request import PullRequestItem as PullRequestItemModel
from app.models.purchase_order import POLineItem as POLineItemModel
from app.models.purchase_order import PurchaseOrder as PurchaseOrderModel
from app.models.shipping import PackingSlip, PackingSlipItem
from app.models.shipping_out_request import ShippingOutRequest, ShippingOutRequestItem
from app.models.shop_assembly import ShopAssemblyOpening, ShopAssemblyOpeningItem

# A PO that has been placed with a vendor. CLOSED belongs here too: the units were ordered, and
# whether they arrived is the line's received/ordered fill, not a different procurement state.
PLACED_PO_STATUSES = (
    POStatus.GP_REGISTERED,
    POStatus.VENDOR_CONFIRMED,
    POStatus.PARTIALLY_RECEIVED,
    POStatus.CLOSED,
)

# Furthest-along ordering when one leaf has several OpeningItems (e.g. a re-assembly after a
# correction). Mirrors `warehouse.inventory._LEAF_STATUS_RANK`, which the shipping and shop-assembly
# rollups already use, so all three screens agree on what a leaf's status is.
_LEAF_STATUS_RANK = {"NOT_ASSEMBLED": 0, "IN_INVENTORY": 1, "SHIP_READY": 2, "SHIPPED_OUT": 3}

_STATE_TO_BUCKET = {
    OpeningItemState.IN_INVENTORY: "assembled_in_inventory",
    OpeningItemState.SHIP_READY: "staged",
    OpeningItemState.SHIPPED_OUT: "shipped_on_leaf",
}


@dataclass(frozen=True)
class PoLineRef:
    """The PO line a schedule row is bound to, carried purely as context for the ORDERED bucket.

    `received_quantity` is the LINE's fill across the whole project, never this opening's units - see
    the module docstring on why receipts cannot be attributed to an opening.
    """

    po_number: str
    status: str
    ordered_quantity: int
    received_quantity: int


@dataclass(frozen=True)
class LeafLine:
    """One product one door leaf of one opening is owed, partitioned across the lifecycle.

    The eight quantities sum to `owed_quantity`. `shipped_loose` and `pulled_for_shipping` are this
    leaf's share of an OPENING-level budget: a loose line carries an opening and never a leaf, so the
    leaves of an opening consume that budget in order (see `_build_lines`).
    """

    leaf: int | None
    hardware_category: str
    product_code: str
    owed_quantity: int
    shipped_on_leaf: int
    shipped_loose: int
    staged: int
    pulled_for_shipping: int
    assembled_in_inventory: int
    pulled_for_assembly: int
    ordered: int
    po_drafted: int
    not_purchased: int
    po_lines: list[PoLineRef] = field(default_factory=list)


@dataclass(frozen=True)
class LooseLine:
    """Loose units of this opening that no leaf of it could account for.

    Normally empty. It fills when more of a product went out loose than the current schedule says the
    opening takes - an over-ship, or hardware sent against a schedule revision that has since changed.
    Surfaced rather than silently dropped, because units that left the building must appear somewhere.
    """

    hardware_category: str
    product_code: str
    pulled_for_shipping: int
    shipped_loose: int


@dataclass(frozen=True)
class LeafState:
    leaf: int
    status: str


@dataclass(frozen=True)
class OpeningDeepDive:
    opening_number: str
    building: str | None
    floor: str | None
    location: str | None
    leaf_count: int | None
    leaves: list[LeafState]
    leaf_claims: dict[int | None, str]
    lines: list[LeafLine]
    loose: list[LooseLine]


@dataclass(frozen=True)
class OpeningStatus:
    """One row of the project list: the partition rolled up to a single opening."""

    opening_number: str
    building: str | None
    floor: str | None
    location: str | None
    leaf_count: int | None
    stage: str
    owed_units: int
    shipped_units: int
    staged_units: int
    assembled_units: int
    pulled_units: int
    shipped_loose_units: int
    pulled_for_shipping_units: int
    ordered_units: int
    po_drafted_units: int
    not_purchased_units: int
    leaves: list[LeafState]


def get_project_opening_statuses(session: Session, project_id: uuid.UUID) -> list[OpeningStatus]:
    """Every opening in one project, each with its lifecycle partition rolled up to totals.

    Deliberately built on the SAME partition the deep dive returns rather than on a cheaper set of
    independent counts: the row's numbers are then the detail's numbers by construction, which is the
    property `get_assembly_pipeline` protects for the same reason. Rolling up in Python off eight
    grouped statements keeps that guarantee without a per-opening query.
    """
    dives = _partition(session, project_id, opening_numbers=None)
    return [_roll_up(dive) for dive in dives]


def get_opening_deep_dive(session: Session, project_id: uuid.UUID, opening_number: str) -> OpeningDeepDive | None:
    """One opening's full partition: every owed line per leaf, plus its loose shipping story."""
    dives = _partition(session, project_id, opening_numbers=[opening_number])
    return dives[0] if dives else None


def _partition(
    session: Session,
    project_id: uuid.UUID,
    opening_numbers: list[str] | None,
) -> list[OpeningDeepDive]:
    """The whole computation. `opening_numbers=None` means the entire project."""
    op_stmt = select(
        OpeningModel.id,
        OpeningModel.opening_number,
        OpeningModel.building,
        OpeningModel.floor,
        OpeningModel.location,
        OpeningModel.leaf_count,
    ).where(OpeningModel.project_id == project_id)
    if opening_numbers is not None:
        op_stmt = op_stmt.where(OpeningModel.opening_number.in_(opening_numbers))
    openings = session.execute(op_stmt.order_by(OpeningModel.opening_number)).all()
    if not openings:
        return []

    opening_ids = [row.id for row in openings]
    numbers = sorted({row.opening_number for row in openings})
    number_by_id = {row.id: row.opening_number for row in openings}

    schedule = _schedule_lines(session, project_id, opening_ids, number_by_id)
    installed = _installed_quantities(session, project_id, numbers)
    allocated = _allocated_for_assembly(session, project_id, numbers)
    leaf_states = _leaf_states(session, project_id, numbers)
    loose = _loose_quantities(session, project_id, numbers)
    claims = _leaf_claims(session, project_id, numbers)

    dives: list[OpeningDeepDive] = []
    for row in openings:
        number = row.opening_number
        owed = schedule.get(number, {})
        leaves = _enumerate_leaves(row.leaf_count, owed, leaf_states.get(number, {}))
        owed = _fold_leafless_lines(owed, leaves)
        lines, unattributed = _build_lines(
            owed,
            installed.get(number, {}),
            allocated.get(number, {}),
            loose.get(number, {}),
        )
        dives.append(
            OpeningDeepDive(
                opening_number=number,
                building=row.building,
                floor=row.floor,
                location=row.location,
                leaf_count=row.leaf_count,
                leaves=[
                    LeafState(leaf=leaf, status=leaf_states.get(number, {}).get(leaf, "NOT_ASSEMBLED"))
                    for leaf in leaves
                    if leaf is not None
                ],
                leaf_claims=claims.get(number, {}),
                lines=lines,
                loose=_build_loose(unattributed),
            )
        )
    return dives


def _schedule_lines(
    session: Session,
    project_id: uuid.UUID,
    opening_ids: list[uuid.UUID],
    number_by_id: dict[uuid.UUID, str],
) -> dict[str, dict[int | None, dict[tuple[str, str], dict]]]:
    """What the schedule owes, with each row's PO linkage, as {opening: {leaf: {(cat, code): line}}}.

    Grouped down to (opening, leaf, category, product, PO, PO line) so a product split across two POs
    keeps both references instead of one arbitrarily winning. The PO outer join is conditioned on
    `deleted_at IS NULL`, which is what turns a cancelled or soft-deleted PO's rows into NOT_PURCHASED
    without a second query: cancellation soft-deletes the PO, so the join simply yields no PO.
    """
    if not opening_ids:
        return {}

    rows = session.execute(
        select(
            HardwareItemModel.opening_id,
            HardwareItemModel.leaf,
            HardwareItemModel.hardware_category,
            HardwareItemModel.product_code,
            PurchaseOrderModel.status,
            PurchaseOrderModel.po_number,
            PurchaseOrderModel.request_number,
            POLineItemModel.ordered_quantity,
            POLineItemModel.received_quantity,
            func.sum(HardwareItemModel.item_quantity),
        )
        .outerjoin(POLineItemModel, HardwareItemModel.po_line_item_id == POLineItemModel.id)
        .outerjoin(
            PurchaseOrderModel,
            and_(
                POLineItemModel.po_id == PurchaseOrderModel.id,
                PurchaseOrderModel.deleted_at.is_(None),
            ),
        )
        .where(
            HardwareItemModel.project_id == project_id,
            HardwareItemModel.opening_id.in_(opening_ids),
        )
        .group_by(
            HardwareItemModel.opening_id,
            HardwareItemModel.leaf,
            HardwareItemModel.hardware_category,
            HardwareItemModel.product_code,
            PurchaseOrderModel.status,
            PurchaseOrderModel.po_number,
            PurchaseOrderModel.request_number,
            POLineItemModel.ordered_quantity,
            POLineItemModel.received_quantity,
        )
    ).all()

    out: dict[str, dict[int | None, dict[tuple[str, str], dict]]] = {}
    for (
        opening_id,
        leaf,
        category,
        code,
        po_status,
        po_number,
        request_number,
        line_ordered,
        line_received,
        quantity,
    ) in rows:
        number = number_by_id.get(opening_id)
        if number is None:
            continue
        line = (
            out.setdefault(number, {})
            .setdefault(leaf, {})
            .setdefault(
                (category, code),
                {"owed": 0, "ordered": 0, "po_drafted": 0, "not_purchased": 0, "po_lines": []},
            )
        )
        units = int(quantity or 0)
        line["owed"] += units
        if po_status in PLACED_PO_STATUSES:
            line["ordered"] += units
            line["po_lines"].append(
                PoLineRef(
                    po_number=po_number or request_number,
                    status=po_status.value,
                    ordered_quantity=int(line_ordered or 0),
                    received_quantity=int(line_received or 0),
                )
            )
        elif po_status == POStatus.DRAFT:
            line["po_drafted"] += units
            line["po_lines"].append(
                PoLineRef(
                    po_number=po_number or request_number,
                    status=po_status.value,
                    ordered_quantity=int(line_ordered or 0),
                    received_quantity=int(line_received or 0),
                )
            )
        else:
            line["not_purchased"] += units
    return out


def _installed_quantities(
    session: Session,
    project_id: uuid.UUID,
    numbers: list[str],
) -> dict[str, dict[int | None, dict[tuple[str, str], dict[str, int]]]]:
    """What is bolted onto assembled leaves, split by the unit's state.

    {opening: {leaf: {(cat, code): {bucket: quantity}}}} where bucket is one of the three
    OpeningItemState-derived names. Several units can share a leaf after a correction, so quantities
    accumulate per bucket rather than one unit winning.
    """
    if not numbers:
        return {}

    rows = session.execute(
        select(
            OpeningItemModel.opening_number,
            OpeningItemModel.leaf,
            OpeningItemModel.state,
            OpeningItemHardwareModel.hardware_category,
            OpeningItemHardwareModel.product_code,
            func.sum(OpeningItemHardwareModel.quantity),
        )
        .join(OpeningItemModel, OpeningItemHardwareModel.opening_item_id == OpeningItemModel.id)
        .where(
            OpeningItemModel.project_id == project_id,
            OpeningItemModel.opening_number.in_(numbers),
        )
        .group_by(
            OpeningItemModel.opening_number,
            OpeningItemModel.leaf,
            OpeningItemModel.state,
            OpeningItemHardwareModel.hardware_category,
            OpeningItemHardwareModel.product_code,
        )
    ).all()

    out: dict[str, dict[int | None, dict[tuple[str, str], dict[str, int]]]] = {}
    for number, leaf, state, category, code, quantity in rows:
        bucket = _STATE_TO_BUCKET.get(state)
        if bucket is None:
            continue
        per_key = out.setdefault(number, {}).setdefault(leaf, {}).setdefault((category, code), {})
        per_key[bucket] = per_key.get(bucket, 0) + int(quantity or 0)
    return out


def _allocated_for_assembly(
    session: Session,
    project_id: uuid.UUID,
    numbers: list[str],
) -> dict[str, dict[int | None, dict[tuple[str, str], int]]]:
    """Units a live shop-assembly work unit has claimed, as {opening: {leaf: {(cat, code): qty}}}.

    Live means the work unit is not COMPLETED (a completed one is an OpeningItem now, counted as
    installed) and its pull is not CANCELLED (cancelling restocks the hardware, so the opening is owed
    it again). `allocated_quantity` rather than `quantity`: what the request could actually claim is
    what will physically arrive, and the short remainder was never pulled.
    """
    if not numbers:
        return {}

    rows = session.execute(
        select(
            ShopAssemblyOpening.opening_number,
            ShopAssemblyOpening.leaf,
            ShopAssemblyOpeningItem.hardware_category,
            ShopAssemblyOpeningItem.product_code,
            func.sum(ShopAssemblyOpeningItem.allocated_quantity),
        )
        .join(
            ShopAssemblyOpening,
            ShopAssemblyOpeningItem.shop_assembly_opening_id == ShopAssemblyOpening.id,
        )
        .join(PullRequestModel, ShopAssemblyOpening.pull_request_id == PullRequestModel.id)
        .where(
            PullRequestModel.project_id == project_id,
            PullRequestModel.status != PullRequestStatus.CANCELLED,
            ShopAssemblyOpening.assembly_status != AssemblyStatus.COMPLETED,
            ShopAssemblyOpening.opening_number.in_(numbers),
        )
        .group_by(
            ShopAssemblyOpening.opening_number,
            ShopAssemblyOpening.leaf,
            ShopAssemblyOpeningItem.hardware_category,
            ShopAssemblyOpeningItem.product_code,
        )
    ).all()

    out: dict[str, dict[int | None, dict[tuple[str, str], int]]] = {}
    for number, leaf, category, code, quantity in rows:
        per_leaf = out.setdefault(number, {}).setdefault(leaf, {})
        key = (category, code)
        per_leaf[key] = per_leaf.get(key, 0) + int(quantity or 0)
    return out


def _leaf_states(session: Session, project_id: uuid.UUID, numbers: list[str]) -> dict[str, dict[int, str]]:
    """Furthest-along OpeningItem state per (opening, leaf)."""
    if not numbers:
        return {}

    rows = session.execute(
        select(
            OpeningItemModel.opening_number,
            OpeningItemModel.leaf,
            OpeningItemModel.state,
        ).where(
            OpeningItemModel.project_id == project_id,
            OpeningItemModel.opening_number.in_(numbers),
        )
    ).all()

    out: dict[str, dict[int, str]] = {}
    for number, leaf, state in rows:
        if leaf is None:
            continue
        value = state.value if hasattr(state, "value") else str(state)
        per_opening = out.setdefault(number, {})
        current = per_opening.get(leaf)
        if current is None or _LEAF_STATUS_RANK[value] > _LEAF_STATUS_RANK[current]:
            per_opening[leaf] = value
    return out


def _leaf_claims(session: Session, project_id: uuid.UUID, numbers: list[str]) -> dict[str, dict[int | None, str]]:
    """Request number of the live shipping-out request holding each leaf, if any."""
    if not numbers:
        return {}

    rows = session.execute(
        select(
            ShippingOutRequestItem.opening_number,
            ShippingOutRequestItem.leaf,
            ShippingOutRequest.request_number,
        )
        .join(ShippingOutRequest, ShippingOutRequestItem.shipping_out_request_id == ShippingOutRequest.id)
        .outerjoin(PullRequestModel, ShippingOutRequest.pull_request_id == PullRequestModel.id)
        .where(
            ShippingOutRequest.project_id == project_id,
            ShippingOutRequestItem.item_type == PullRequestItemType.OPENING_ITEM,
            ShippingOutRequestItem.opening_number.in_(numbers),
            # Live is defined by the pull, not the request: a shipping-out request stays APPROVED
            # forever once accepted. Same rule as `shipping_repository.find_live_shipping_claims`.
            (ShippingOutRequest.status == ShippingOutRequestStatus.PENDING)
            | (
                (ShippingOutRequest.status == ShippingOutRequestStatus.APPROVED)
                & (
                    PullRequestModel.id.is_(None)
                    | PullRequestModel.status.in_([PullRequestStatus.PENDING, PullRequestStatus.IN_PROGRESS])
                )
            ),
        )
    ).all()

    out: dict[str, dict[int | None, str]] = {}
    for number, leaf, request_number in rows:
        out.setdefault(number, {})[leaf] = request_number
    return out


def _loose_quantities(
    session: Session,
    project_id: uuid.UUID,
    numbers: list[str],
) -> dict[str, dict[tuple[str, str], dict[str, int]]]:
    """Loose units each opening has sent or claimed, as {opening: {(cat, code): {bucket: qty}}}.

    Three sources folded so nothing counts twice, exactly as
    `shipping_coverage._spoken_for_quantities` does it:

      - shipped: PackingSlipItem LOOSE rows, the units that physically left.
      - fulfilled: COMPLETED SHIPPING_OUT pulls no slip has consumed yet - the staged pool.
        `max(shipped, fulfilled)` folds the overlap, since a shipped unit was fulfilled first, and
        what remains above `shipped` is what is still staged.
      - in flight: lines on pulls still being picked, plus lines on PENDING requests that have not
        minted a pull yet. A request stops counting once accepted, because the accept copies its
        lines onto a pull the previous term already counts.
    """
    if not numbers:
        return {}

    shipped: dict[tuple[str, str, str], int] = {}
    for number, category, code, quantity in session.execute(
        select(
            PackingSlipItem.opening_number,
            PackingSlipItem.hardware_category,
            PackingSlipItem.product_code,
            func.sum(PackingSlipItem.quantity),
        )
        .join(PackingSlip, PackingSlipItem.packing_slip_id == PackingSlip.id)
        .where(
            PackingSlip.project_id == project_id,
            PackingSlipItem.item_type == PullRequestItemType.LOOSE,
            PackingSlipItem.opening_number.in_(numbers),
        )
        .group_by(
            PackingSlipItem.opening_number,
            PackingSlipItem.hardware_category,
            PackingSlipItem.product_code,
        )
    ).all():
        if category and code:
            shipped[(number, category, code)] = int(quantity or 0)

    fulfilled: dict[tuple[str, str, str], int] = {}
    in_flight: dict[tuple[str, str, str], int] = {}
    for number, category, code, status, quantity in session.execute(
        select(
            PullRequestItemModel.opening_number,
            PullRequestItemModel.hardware_category,
            PullRequestItemModel.product_code,
            PullRequestModel.status,
            func.sum(PullRequestItemModel.requested_quantity),
        )
        .join(PullRequestModel, PullRequestItemModel.pull_request_id == PullRequestModel.id)
        .where(
            PullRequestModel.project_id == project_id,
            PullRequestModel.source == PullRequestSource.SHIPPING_OUT,
            PullRequestModel.status != PullRequestStatus.CANCELLED,
            PullRequestItemModel.item_type == PullRequestItemType.LOOSE,
            PullRequestItemModel.opening_number.in_(numbers),
        )
        .group_by(
            PullRequestItemModel.opening_number,
            PullRequestItemModel.hardware_category,
            PullRequestItemModel.product_code,
            PullRequestModel.status,
        )
    ).all():
        if not category or not code:
            continue
        key = (number, category, code)
        bucket = fulfilled if status == PullRequestStatus.COMPLETED else in_flight
        bucket[key] = bucket.get(key, 0) + int(quantity or 0)

    for number, category, code, quantity in session.execute(
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
            ShippingOutRequestItem.item_type == PullRequestItemType.LOOSE,
            ShippingOutRequestItem.opening_number.in_(numbers),
        )
        .group_by(
            ShippingOutRequestItem.opening_number,
            ShippingOutRequestItem.hardware_category,
            ShippingOutRequestItem.product_code,
        )
    ).all():
        if not category or not code:
            continue
        key = (number, category, code)
        in_flight[key] = in_flight.get(key, 0) + int(quantity or 0)

    out: dict[str, dict[tuple[str, str], dict[str, int]]] = {}
    for key in set(shipped) | set(fulfilled) | set(in_flight):
        number, category, code = key
        shipped_units = shipped.get(key, 0)
        staged_units = max(fulfilled.get(key, 0) - shipped_units, 0)
        pulled = staged_units + in_flight.get(key, 0)
        if shipped_units or pulled:
            out.setdefault(number, {})[(category, code)] = {
                "shipped_loose": shipped_units,
                "pulled_for_shipping": pulled,
            }
    return out


def _enumerate_leaves(
    leaf_count: int | None,
    owed: dict[int | None, dict],
    leaf_states: dict[int, str],
) -> list[int | None]:
    """Every leaf of one opening, from all three things that know about them.

    Returns `[None]` when none of them resolve a leaf - a legacy whole-opening row, a real shape the
    rest of the chain still carries. Same rule as `shipping_coverage._enumerate_leaves`.
    """
    resolved: set[int] = set()
    if leaf_count and leaf_count >= 1:
        resolved.update(range(1, leaf_count + 1))
    resolved.update(leaf for leaf in owed if leaf is not None)
    resolved.update(leaf_states)
    return sorted(resolved) if resolved else [None]


def _fold_leafless_lines(
    owed: dict[int | None, dict[tuple[str, str], dict]],
    leaves: list[int | None],
) -> dict[int | None, dict[tuple[str, str], dict]]:
    """Attach leaf-less schedule lines to the opening's lowest leaf.

    A pair whose schedule carries a leaf-less row (a frame line, or an item TITAN did not attribute)
    would otherwise strand those units on a phantom third leaf nobody can reconcile. The import wizard
    folds them the same way when it builds shop-assembly work units, so the two paths agree.
    """
    leafless = owed.get(None)
    if leafless is None or leaves == [None]:
        return owed

    folded: dict[int | None, dict[tuple[str, str], dict]] = {
        leaf: {key: dict(line) for key, line in lines.items()} for leaf, lines in owed.items() if leaf is not None
    }
    target = folded.setdefault(leaves[0], {})
    for key, line in leafless.items():
        existing = target.get(key)
        if existing is None:
            target[key] = dict(line)
            continue
        for bucket in ("owed", "ordered", "po_drafted", "not_purchased"):
            existing[bucket] += line[bucket]
        existing["po_lines"] = existing["po_lines"] + line["po_lines"]
    return folded


def _build_lines(
    owed: dict[int | None, dict[tuple[str, str], dict]],
    installed: dict[int | None, dict[tuple[str, str], dict[str, int]]],
    allocated: dict[int | None, dict[tuple[str, str], int]],
    loose: dict[tuple[str, str], dict[str, int]],
) -> tuple[list[LeafLine], dict[tuple[str, str], dict[str, int]]]:
    """Partition every owed line across the lifecycle, furthest along first.

    Keys are the union of what the schedule owes, what is physically on the leaf, and what a live
    assembly request claimed - so hardware installed off an older schedule revision still shows (with
    `owed_quantity` 0) rather than vanishing and making the leaf look emptier than it is.

    `loose` is the OPENING's budget of shipped and in-flight loose units and is spent down here as the
    leaves are walked in order, the same way `shipping_coverage._coverage_lines` spends its
    spoken-for budget. This is what stops site hardware - which never touches a leaf - from reading as
    merely "ordered" for ever after it has physically shipped. Whatever the leaves cannot account for
    is returned for the caller to surface separately.
    """
    budget = {key: dict(buckets) for key, buckets in loose.items()}
    lines: list[LeafLine] = []

    for leaf in sorted(set(owed) | set(installed) | set(allocated), key=lambda x: (x is None, x)):
        owed_lines = owed.get(leaf, {})
        installed_lines = installed.get(leaf, {})
        allocated_lines = allocated.get(leaf, {})

        for key in sorted(set(owed_lines) | set(installed_lines) | set(allocated_lines)):
            line = owed_lines.get(key)
            owed_quantity = line["owed"] if line else 0
            per_state = installed_lines.get(key, {})
            per_loose = budget.get(key, {})

            # Facts first: what is physically on this leaf, and what a live work unit holds for it.
            # Reported as found and NEVER clamped to what the schedule owes - a leaf assembled off an
            # older revision really does carry that hardware, and clamping would report zero for it.
            # The four are disjoint by construction: a unit sits on exactly one OpeningItem, which has
            # exactly one state, and a work unit stops counting the moment it completes into one.
            shipped_on_leaf = per_state.get("shipped_on_leaf", 0)
            staged = per_state.get("staged", 0)
            assembled = per_state.get("assembled_in_inventory", 0)
            pulled = allocated_lines.get(key, 0)

            # Loose units carry an opening and no leaf, so they come out of an opening-level budget,
            # capped at the room this leaf has left. Without the cap the first leaf of a pair would
            # swallow the whole opening's shipment and the second would read as still owing it.
            room = max(owed_quantity - (shipped_on_leaf + staged + assembled + pulled), 0)
            shipped_loose, room = _take(room, per_loose.get("shipped_loose", 0))
            pulled_for_shipping, room = _take(room, per_loose.get("pulled_for_shipping", 0))
            if shipped_loose:
                per_loose["shipped_loose"] -= shipped_loose
            if pulled_for_shipping:
                per_loose["pulled_for_shipping"] -= pulled_for_shipping

            # `room` is now what no fulfilment bucket claimed, and the row's PO linkage describes it.
            # Spend the consumed units against ORDERED first: a unit that shipped or reached a leaf
            # was necessarily bought, so charging it to the unordered buckets would invent a backlog
            # that does not exist.
            consumed = owed_quantity - room
            ordered, consumed = _spend(line["ordered"] if line else 0, consumed)
            po_drafted, consumed = _spend(line["po_drafted"] if line else 0, consumed)
            not_purchased, _ = _spend(line["not_purchased"] if line else 0, consumed)

            lines.append(
                LeafLine(
                    leaf=leaf,
                    hardware_category=key[0],
                    product_code=key[1],
                    owed_quantity=owed_quantity,
                    shipped_on_leaf=shipped_on_leaf,
                    shipped_loose=shipped_loose,
                    staged=staged,
                    pulled_for_shipping=pulled_for_shipping,
                    assembled_in_inventory=assembled,
                    pulled_for_assembly=pulled,
                    ordered=ordered,
                    po_drafted=po_drafted,
                    not_purchased=not_purchased,
                    po_lines=list(line["po_lines"]) if line else [],
                )
            )

    unattributed = {
        key: buckets
        for key, buckets in budget.items()
        if buckets.get("shipped_loose", 0) > 0 or buckets.get("pulled_for_shipping", 0) > 0
    }
    return lines, unattributed


def _take(remaining: int, available: int) -> tuple[int, int]:
    """Claim up to `available` units out of `remaining`. Never negative, never over-claims."""
    taken = min(max(remaining, 0), max(available, 0))
    return taken, remaining - taken


def _spend(bucket: int, consumed: int) -> tuple[int, int]:
    """Draw `consumed` units down out of `bucket`, returning what is left of each."""
    spent = min(max(bucket, 0), max(consumed, 0))
    return bucket - spent, consumed - spent


def _build_loose(loose: dict[tuple[str, str], dict[str, int]]) -> list[LooseLine]:
    return [
        LooseLine(
            hardware_category=key[0],
            product_code=key[1],
            pulled_for_shipping=buckets.get("pulled_for_shipping", 0),
            shipped_loose=buckets.get("shipped_loose", 0),
        )
        for key, buckets in sorted(loose.items())
    ]


def _roll_up(dive: OpeningDeepDive) -> OpeningStatus:
    """Sum one opening's lines into the list row, and derive its headline stage."""
    owed = sum(line.owed_quantity for line in dive.lines)
    shipped = sum(line.shipped_on_leaf for line in dive.lines)
    staged = sum(line.staged for line in dive.lines)
    assembled = sum(line.assembled_in_inventory for line in dive.lines)
    pulled = sum(line.pulled_for_assembly for line in dive.lines)
    ordered = sum(line.ordered for line in dive.lines)
    po_drafted = sum(line.po_drafted for line in dive.lines)
    not_purchased = sum(line.not_purchased for line in dive.lines)
    # The unattributed remainder counts too: those units left the building, and an opening whose
    # over-shipment is its only shipping activity must not read as though nothing has gone out.
    shipped_loose = sum(line.shipped_loose for line in dive.lines) + sum(line.shipped_loose for line in dive.loose)
    pulled_for_shipping = sum(line.pulled_for_shipping for line in dive.lines) + sum(
        line.pulled_for_shipping for line in dive.loose
    )

    return OpeningStatus(
        opening_number=dive.opening_number,
        building=dive.building,
        floor=dive.floor,
        location=dive.location,
        leaf_count=dive.leaf_count,
        stage=_stage(
            owed=owed,
            not_purchased=not_purchased,
            po_drafted=po_drafted,
            ordered=ordered,
            pulled=pulled,
            assembled=assembled,
            staged=staged,
            shipped=shipped,
            shipped_loose=shipped_loose,
            pulled_for_shipping=pulled_for_shipping,
            leaves=dive.leaves,
        ),
        owed_units=owed,
        shipped_units=shipped,
        staged_units=staged,
        assembled_units=assembled,
        pulled_units=pulled,
        shipped_loose_units=shipped_loose,
        pulled_for_shipping_units=pulled_for_shipping,
        ordered_units=ordered,
        po_drafted_units=po_drafted,
        not_purchased_units=not_purchased,
        leaves=dive.leaves,
    )


def _stage(
    *,
    owed: int,
    not_purchased: int,
    po_drafted: int,
    ordered: int,
    pulled: int,
    assembled: int,
    staged: int,
    shipped: int,
    shipped_loose: int,
    pulled_for_shipping: int,
    leaves: list[LeafState],
) -> str:
    """The opening's headline stage: a scanning aid, with the per-bucket numbers as the truth.

    Deliberately the FURTHEST BEHIND thing still outstanding rather than the furthest along, because
    the question the page exists to answer is "what is holding this opening up". An opening whose
    leaf 1 has shipped while leaf 2 is unbought reads ORDERING, which is the useful answer.
    """
    if owed == 0 and shipped == 0 and shipped_loose == 0:
        return "NO_HARDWARE"
    if owed > 0 and not_purchased == owed:
        return "NOT_STARTED"
    if not_purchased > 0 or po_drafted > 0:
        return "ORDERING"
    if ordered > 0 or pulled > 0 or any(leaf.status == "NOT_ASSEMBLED" for leaf in leaves):
        return "ASSEMBLY"
    if assembled > 0 or staged > 0 or pulled_for_shipping > 0 or any(leaf.status != "SHIPPED_OUT" for leaf in leaves):
        return "SHIPPING"
    return "COMPLETE"
