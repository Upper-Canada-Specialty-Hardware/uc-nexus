"""What each selected door leaf still owes the site, for the shipping-out builder (#451).

The shipping-out request is created off the hardware schedule, and the schedule is the only thing
that knows what a leaf is supposed to carry. This module answers, per leaf, the question the shipper
is actually asking at creation time:

    *I have picked these openings. What belongs with them, what is physically on the leaf already,
    what of the rest can I claim right now, and what is still at the vendor?*

The three answers come from three different places, which is why nothing upstream could produce
this list on its own:

  - **Owed** is the schedule (`HardwareItem`), per (leaf, category, product).
  - **Installed** is the assembled leaf (`OpeningItemHardware`). Shop hardware that was fitted at
    the bench left fungible inventory then and ships *on the leaf*, not beside it; shop hardware
    that was skipped (unavailable at assembly time) never did, so it still has to go loose.
  - **On order** is the purchase orders that have been placed but not fully received.

Site hardware is never installed at the bench at all - it goes to site loose by definition - so the
single formula `suggested = owed - installed` covers all three classifications and degrades
correctly for hardware that was never classified.

What this deliberately does NOT return is availability. `projectInventoryAvailability` already
answers "what may I claim" (#342) and the creation gate is applied against *that* number; a second
availability figure computed here at a slightly different instant is exactly the drift that would
let the panel say 3 and the shortfall alert say 2. The caller joins the two by combo key.

Query budget is fixed at six regardless of how many openings are selected (CLAUDE.md perf rules):
openings, schedule items (grouped), assembled units + their hardware (selectinload), live shipping
claims, and the on-order aggregate.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.enums import Classification, OpeningItemState, POStatus
from app.models.hardware import HardwareItem as HardwareItemModel
from app.models.opening_item import OpeningItem as OpeningItemModel
from app.models.project import Opening as OpeningModel
from app.models.purchase_order import POLineItem as POLineItemModel
from app.models.purchase_order import PurchaseOrder as PurchaseOrderModel

# A PO counts as "on the way" once it has been placed with the vendor and until it is closed out.
# DRAFT is excluded on purpose: nobody has ordered it, so promising it to a shipper would be a lie.
ON_ORDER_PO_STATUSES = (
    POStatus.GP_REGISTERED,
    POStatus.VENDOR_CONFIRMED,
    POStatus.PARTIALLY_RECEIVED,
)


def get_shipping_coverage(
    session: Session,
    project_id: uuid.UUID,
    opening_numbers: list[str],
) -> list[dict]:
    """One row per door leaf of the given openings, each listing what that leaf is owed.

    Leaves are enumerated from everything that knows about them - the opening's `leaf_count`, the
    leaves the schedule names, and the leaves that have actually been assembled - so a leaf can
    never be missing from the list merely because one of those three is silent. An opening none of
    them resolve (legacy, no leaf data anywhere) yields a single leaf-less row rather than nothing.
    """
    if not opening_numbers:
        return []

    wanted = list(dict.fromkeys(opening_numbers))

    openings = session.execute(
        select(OpeningModel.id, OpeningModel.opening_number, OpeningModel.leaf_count).where(
            OpeningModel.project_id == project_id,
            OpeningModel.opening_number.in_(wanted),
        )
    ).all()
    if not openings:
        return []

    opening_number_by_id = {oid: number for oid, number, _ in openings}
    leaf_count_by_number = {number: leaf_count for _, number, leaf_count in openings}

    schedule = _schedule_lines(session, project_id, opening_number_by_id)
    assembled = _assembled_units(session, project_id, list(leaf_count_by_number))
    on_order = _on_order_quantities(session, project_id)

    from app.repositories.shipping_repository import find_live_shipping_claims

    claims = find_live_shipping_claims(
        session,
        project_id,
        opening_item_ids=[oi.id for units in assembled.values() for oi in units],
    )["by_opening_item"]

    rows: list[dict] = []
    for opening_number in sorted(leaf_count_by_number):
        owed = schedule.get(opening_number, {})
        units = assembled.get(opening_number, [])
        leaves = _enumerate_leaves(leaf_count_by_number[opening_number], owed, units)
        owed = _fold_leafless_lines(owed, leaves)
        unit_by_leaf = _match_units_to_leaves(units, leaves)

        for leaf in leaves:
            unit = unit_by_leaf.get(leaf)
            installed = _installed_quantities(unit)
            rows.append(
                {
                    "opening_number": opening_number,
                    "leaf": leaf,
                    "status": _leaf_status(unit),
                    "opening_item_id": unit.id if unit is not None else None,
                    "claimed_by_request_number": claims.get(unit.id) if unit is not None else None,
                    "lines": _coverage_lines(owed.get(leaf, {}), installed, on_order),
                }
            )
    return rows


def _schedule_lines(
    session: Session,
    project_id: uuid.UUID,
    opening_number_by_id: dict[uuid.UUID, str],
) -> dict[str, dict[int | None, dict[tuple[str, str], dict]]]:
    """What the schedule says each leaf takes, as {opening: {leaf: {(cat, code): line}}}.

    Grouped in SQL down to (opening, leaf, category, product, classification). Classification is
    part of the key because it is a column on the item rows and two rows for the same product on the
    same leaf are free to disagree; the disagreement is resolved when the line is emitted, by unit
    count, so the display never depends on row order.
    """
    opening_ids = list(opening_number_by_id)
    if not opening_ids:
        return {}

    rows = session.execute(
        select(
            HardwareItemModel.opening_id,
            HardwareItemModel.leaf,
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
            HardwareItemModel.leaf,
            HardwareItemModel.hardware_category,
            HardwareItemModel.product_code,
            HardwareItemModel.classification,
        )
    ).all()

    out: dict[str, dict[int | None, dict[tuple[str, str], dict]]] = {}
    for opening_id, leaf, category, code, classification, quantity in rows:
        opening_number = opening_number_by_id.get(opening_id)
        if opening_number is None:
            continue
        line = (
            out.setdefault(opening_number, {})
            .setdefault(leaf, {})
            .setdefault(
                (category, code),
                {"hardware_category": category, "product_code": code, "owed_quantity": 0, "by_classification": {}},
            )
        )
        line["owed_quantity"] += int(quantity or 0)
        key = classification.value if classification is not None else None
        line["by_classification"][key] = line["by_classification"].get(key, 0) + int(quantity or 0)
    return out


def _assembled_units(
    session: Session,
    project_id: uuid.UUID,
    opening_numbers: list[str],
) -> dict[str, list[OpeningItemModel]]:
    """Assembled units per opening, with their installed hardware eagerly loaded."""
    units = (
        session.scalars(
            select(OpeningItemModel)
            .options(selectinload(OpeningItemModel.installed_hardware))
            .where(
                OpeningItemModel.project_id == project_id,
                OpeningItemModel.opening_number.in_(opening_numbers),
            )
        )
        .unique()
        .all()
    )

    out: dict[str, list[OpeningItemModel]] = {}
    for unit in units:
        out.setdefault(unit.opening_number, []).append(unit)
    return out


def _on_order_quantities(session: Session, project_id: uuid.UUID) -> dict[tuple[str, str], int]:
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


def _enumerate_leaves(
    leaf_count: int | None,
    owed: dict[int | None, dict],
    units: list[OpeningItemModel],
) -> list[int | None]:
    """Every leaf of one opening, from all three things that know about them.

    Returns `[None]` when none of them resolve a leaf - a legacy whole-opening row, which is a real
    shape the rest of the chain still carries and must not be dropped.
    """
    resolved: set[int] = set()
    if leaf_count and leaf_count >= 1:
        resolved.update(range(1, leaf_count + 1))
    resolved.update(leaf for leaf in owed if leaf is not None)
    resolved.update(unit.leaf for unit in units if unit.leaf is not None)
    return sorted(resolved) if resolved else [None]


def _fold_leafless_lines(
    owed: dict[int | None, dict[tuple[str, str], dict]],
    leaves: list[int | None],
) -> dict[int | None, dict[tuple[str, str], dict]]:
    """Attach leaf-less schedule lines to the opening's lowest leaf.

    A pair whose schedule carries a leaf-less row (a frame line, or an item TITAN did not attribute)
    would otherwise strand those units on a phantom third leaf nobody can select. The import wizard
    folds them the same way when it builds shop-assembly work units, so the two paths agree on where
    an unattributed unit belongs.
    """
    leafless = owed.get(None)
    if leafless is None or leaves == [None]:
        return owed

    folded = {leaf: dict(lines) for leaf, lines in owed.items() if leaf is not None}
    target = folded.setdefault(leaves[0], {})
    for key, line in leafless.items():
        existing = target.get(key)
        if existing is None:
            target[key] = line
            continue
        existing["owed_quantity"] += line["owed_quantity"]
        for classification, quantity in line["by_classification"].items():
            existing["by_classification"][classification] = (
                existing["by_classification"].get(classification, 0) + quantity
            )
    return folded


def _match_units_to_leaves(
    units: list[OpeningItemModel],
    leaves: list[int | None],
) -> dict[int | None, OpeningItemModel]:
    """The assembled unit that IS each leaf.

    Exact leaf match first. A live unit wins over a shipped one - `uq_opening_items_live_leaf`
    allows a leaf to be re-assembled after the first one shipped, and the leaf the shipper cares
    about is the one still in the building. Failing that, an opening with exactly one leaf and
    exactly one unit is matched regardless of leaf value, which is what keeps a legacy null-leaf
    unit from reading as NOT_ASSEMBLED under a leaf the schedule numbered 1.
    """

    def rank(unit: OpeningItemModel) -> tuple[int, object]:
        return (0 if unit.state != OpeningItemState.SHIPPED_OUT else 1, unit.assembly_completed_at)

    out: dict[int | None, OpeningItemModel] = {}
    for leaf in leaves:
        candidates = [unit for unit in units if unit.leaf == leaf]
        if candidates:
            out[leaf] = min(candidates, key=rank)

    if not out and len(leaves) == 1 and len(units) == 1:
        out[leaves[0]] = units[0]
    return out


def _leaf_status(unit: OpeningItemModel | None) -> str:
    """LeafStatus for one leaf: the assembled unit's own state, or NOT_ASSEMBLED if there is none."""
    return unit.state.value if unit is not None else "NOT_ASSEMBLED"


def _installed_quantities(unit: OpeningItemModel | None) -> dict[tuple[str, str], int]:
    """What is physically bolted onto one assembled leaf, per (category, product)."""
    if unit is None:
        return {}
    installed: dict[tuple[str, str], int] = {}
    for row in unit.installed_hardware:
        key = (row.hardware_category, row.product_code)
        installed[key] = installed.get(key, 0) + row.quantity
    return installed


def _coverage_lines(
    owed_lines: dict[tuple[str, str], dict],
    installed: dict[tuple[str, str], int],
    on_order: dict[tuple[str, str], int],
) -> list[dict]:
    """One row per product this leaf is owed, plus anything installed on it the schedule no longer
    lists - a leaf that was assembled off an older revision still has that hardware on it, and
    hiding the line would make the leaf look emptier than it is.
    """
    keys = sorted(set(owed_lines) | set(installed))
    lines = []
    for key in keys:
        owed_line = owed_lines.get(key)
        owed_quantity = owed_line["owed_quantity"] if owed_line else 0
        installed_quantity = installed.get(key, 0)
        lines.append(
            {
                "hardware_category": key[0],
                "product_code": key[1],
                "classification": _dominant_classification(owed_line),
                "owed_quantity": owed_quantity,
                "installed_quantity": installed_quantity,
                # Site hardware is never fitted at the bench, so `installed` is 0 for it and this is
                # its whole owed quantity. Shop hardware nets off what assembly actually fitted,
                # leaving exactly what was skipped. Floored at 0: a leaf carrying more than the
                # current schedule asks for is over-supplied, not owed a negative quantity.
                "suggested_quantity": max(0, owed_quantity - installed_quantity),
                "on_order_quantity": on_order.get(key, 0),
            }
        )
    return lines


def _dominant_classification(owed_line: dict | None) -> Classification | None:
    """The classification of one product on one leaf: whichever covers the most units.

    Rows for the same product on the same leaf can disagree (they are separate schedule entries
    and each carries its own column), so this has to be decided rather than picked off the first
    row. Unit count first, then enum name, so the answer never depends on query order. An
    unclassified majority answers None, which the builder groups under "unclassified" rather than
    guessing site or shop on the user's behalf.
    """
    if not owed_line:
        return None
    ranked = sorted(
        owed_line["by_classification"].items(),
        key=lambda item: (-item[1], item[0] or ""),
    )
    winner = ranked[0][0]
    return Classification(winner) if winner is not None else None
