"""Project inventory + opening item reads and admin quantity corrections."""

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import NotFoundError, ValidationError
from app.models.enums import AuditAction, AuditEntityType, Classification
from app.models.hardware import HardwareItem as HardwareItemModel
from app.models.inventory import InventoryLocation as InventoryLocationModel
from app.models.project import Project as ProjectModel
from app.models.purchase_order import POLineItem as POLineItemModel
from app.models.purchase_order import PurchaseOrder as POModel

from .audit import _log_audit_event
from .locations import _normalize_and_validate_location_fields, clone_origin_fields, location_detail


def get_unlocated_inventory(
    session: Session, project_id: uuid.UUID | None = None, warehouse_id: uuid.UUID | None = None
) -> list[dict]:
    """
    Query InventoryLocation rows where aisle, row, and bay are all NULL and quantity > 0.
    Joins to POLineItem for unit_cost/classification and PurchaseOrder for po_number.
    Optionally scoped to one warehouse so put-away can work one building at a time.
    """
    stmt = (
        select(InventoryLocationModel, POLineItemModel.classification, POModel.po_number, POLineItemModel.unit_cost)
        .outerjoin(POLineItemModel, InventoryLocationModel.po_line_item_id == POLineItemModel.id)
        .outerjoin(POModel, POLineItemModel.po_id == POModel.id)
        .where(
            InventoryLocationModel.aisle.is_(None),
            InventoryLocationModel.row.is_(None),
            InventoryLocationModel.bay.is_(None),
            InventoryLocationModel.quantity > 0,
        )
    )
    if project_id is not None:
        stmt = stmt.where(InventoryLocationModel.project_id == project_id)
    if warehouse_id is not None:
        stmt = stmt.where(InventoryLocationModel.warehouse_id == warehouse_id)
    stmt = stmt.order_by(
        InventoryLocationModel.hardware_category,
        InventoryLocationModel.product_code,
        InventoryLocationModel.received_at.desc(),
    )
    rows = session.execute(stmt).all()

    # A stock-origin migrated row has no PO line, so its classification and cost are null on the join.
    # Fall back the classification to the schedule's dominant value for (category, code) - the same
    # read the extras-lane chip uses - and the cost to the row's own off-PO unit_cost, so put-away
    # shows a Site/Shop chip and a value for migrated stock instead of a blank. One BATCHED schedule
    # read across every project that needs it (this backs the put-away tab and is refetched after
    # each assign, so a per-project aggregate here is exactly the N+1 the perf rules ban); null
    # classification is not migration-only - returns and unclassified PO lines join null too.
    fallback_pids = {il.project_id for il, po_classification, _, _ in rows if po_classification is None}
    scheduled = get_scheduled_classifications_for_projects(session, sorted(fallback_pids, key=str))

    result = []
    for il, po_classification, po_number, po_unit_cost in rows:
        classification = po_classification
        if classification is None:
            classification = scheduled.get(il.project_id, {}).get((il.hardware_category, il.product_code))
        cost = float(po_unit_cost) if po_unit_cost is not None else float(il.unit_cost or 0)
        result.append(
            {
                "inventory_location": il,
                "classification": classification,
                "po_number": po_number,
                "unit_cost": cost,
            }
        )
    return result


def adjust_inventory_quantity(
    session: Session, inv_id: uuid.UUID, adjustment: int, reason: str, *, performed_by: str, spot_check: bool = False
) -> InventoryLocationModel:
    """Adjust the quantity of an InventoryLocation by a positive or negative amount.

    `performed_by` is keyword-only and required (#427). This function used to take no actor at all
    and hardcode "Admin/Manager" on its audit row, so every quantity adjustment in the system was
    filed under an admin no matter who made it - and, worse, the resolver had no way to pass the
    truth through even once somebody noticed. Requiring it means a new caller has to answer the
    question rather than inherit a wrong answer.

    `spot_check` marks a physical-count reconciliation: the audit row's action is SPOT_CHECK rather
    than ADJUSTMENT and its detail carries systemQuantity/physicalQuantity, so the history render can
    show what was counted against what the system held. The SPOT_CHECK enum value existed unused
    until this - the spot-check UI wrote a plain ADJUSTMENT before."""
    il = session.get(InventoryLocationModel, inv_id)
    if il is None:
        raise NotFoundError(f"Inventory location {inv_id} not found")

    if not reason or len(reason) > 500:
        raise ValidationError("reason must be 1-500 characters", field="reason")

    new_quantity = il.quantity + adjustment
    if new_quantity < 0:
        raise ValidationError("Adjustment would result in negative quantity", field="adjustment")
    if new_quantity < il.deficient_quantity:
        # The deficient claim stays on the row; dropping below it would trip the
        # deficient<=quantity CHECK with a raw 500. override_inventory_quantity guards the same way.
        raise ValidationError(
            "Cannot set quantity below this row's deficient quantity",
            field="adjustment",
        )

    old_quantity = il.quantity
    il.quantity = new_quantity

    detail = {
        "oldQuantity": old_quantity,
        "newQuantity": new_quantity,
        "adjustment": adjustment,
        "reason": reason,
    }
    if spot_check:
        # The counted-vs-system pair the SPOT_CHECK history render reads.
        detail["systemQuantity"] = old_quantity
        detail["physicalQuantity"] = new_quantity

    _log_audit_event(
        session,
        project_id=il.project_id,
        entity_type=AuditEntityType.INVENTORY_LOCATION,
        entity_id=il.id,
        action=AuditAction.SPOT_CHECK if spot_check else AuditAction.ADJUSTMENT,
        performed_by=performed_by,
        detail=detail,
    )

    return il


def override_inventory_quantity(
    session: Session,
    *,
    inv_id: uuid.UUID,
    new_quantity: int,
    reason: str,
    destinations: list[dict],
    performed_by: str,
) -> InventoryLocationModel:
    """Set an InventoryLocation row to an absolute new_quantity. Reason always required, audit-logged.

    Decrease: the row shrinks to new_quantity (lost units written off with the reason); it cannot drop
    below the row's own deficient_quantity.

    Increase: the added (new_quantity - current) units must be placed via `destinations`, whose
    quantities sum to the delta. A destination at the row's own aisle/row/bay bumps this row; any other
    destination becomes a new InventoryLocation that inherits this row's origin, so the has-origin CHECK
    holds and valuations keep the same unit_cost.
    """
    il = session.get(InventoryLocationModel, inv_id)
    if il is None:
        raise NotFoundError(f"Inventory location {inv_id} not found")
    if not reason or len(reason) > 500:
        raise ValidationError("reason_text must be 1-500 characters", field="reason_text")
    if new_quantity < 0:
        raise ValidationError("new_quantity must be >= 0", field="new_quantity")

    old_quantity = il.quantity
    delta = new_quantity - old_quantity
    if delta == 0:
        raise ValidationError("new_quantity must differ from the current quantity", field="new_quantity")

    created: list[InventoryLocationModel] = []
    audit_destinations: list[dict] = []

    if delta < 0:
        if new_quantity < il.deficient_quantity:
            raise ValidationError(
                "Cannot set quantity below this row's deficient quantity",
                field="new_quantity",
            )
        il.quantity = new_quantity
    else:
        if not destinations:
            raise ValidationError(
                "destination location(s) are required when increasing quantity",
                field="destinations",
            )
        normalized: list[dict] = []
        for dest in destinations:
            qty = dest["quantity"]
            if qty < 1:
                raise ValidationError("destination quantity must be >= 1", field="destinations")
            a, b, c = _normalize_and_validate_location_fields(dest["aisle"], dest["row"], dest["bay"])
            normalized.append({"aisle": a, "row": b, "bay": c, "quantity": qty})
        if sum(d["quantity"] for d in normalized) != delta:
            raise ValidationError(
                "destination quantities must sum to the added quantity",
                field="destinations",
            )

        now = datetime.utcnow()
        for dest in normalized:
            audit_destinations.append(dest)
            if (dest["aisle"], dest["row"], dest["bay"]) == (il.aisle, il.row, il.bay):
                il.quantity += dest["quantity"]
            else:
                new_il = InventoryLocationModel(
                    project_id=il.project_id,
                    **clone_origin_fields(il),
                    warehouse_id=il.warehouse_id,
                    hardware_category=il.hardware_category,
                    product_code=il.product_code,
                    quantity=dest["quantity"],
                    deficient_quantity=0,
                    aisle=dest["aisle"],
                    row=dest["row"],
                    bay=dest["bay"],
                    received_at=now,
                )
                session.add(new_il)
                created.append(new_il)

    _log_audit_event(
        session,
        project_id=il.project_id,
        entity_type=AuditEntityType.INVENTORY_LOCATION,
        entity_id=il.id,
        action=AuditAction.ADJUSTMENT,
        performed_by=performed_by,
        detail={
            "oldQuantity": old_quantity,
            "newQuantity": new_quantity,
            "delta": delta,
            "reason": reason,
            "override": True,
            "destinations": audit_destinations,
        },
    )

    session.flush()
    for new_il in created:
        _log_audit_event(
            session,
            project_id=new_il.project_id,
            entity_type=AuditEntityType.INVENTORY_LOCATION,
            entity_id=new_il.id,
            action=AuditAction.ADJUSTMENT,
            performed_by=performed_by,
            detail={
                "createdByOverrideOf": str(il.id),
                "quantity": new_il.quantity,
                "location": location_detail(new_il.aisle, new_il.row, new_il.bay, new_il.warehouse_id),
                "reason": reason,
            },
        )

    return il


def get_scheduled_pairs(session: Session, project_id: uuid.UUID) -> set[tuple[str, str]]:
    """Every (hardware_category, product_code) the project's imported schedule knows about.

    One grouped query, no relationship walking - this is called once per flat-inventory request and
    its result is checked in Python against rows already in memory, so it never becomes an N+1 (see
    the GraphQL/SQLAlchemy performance rules in CLAUDE.md).
    """
    rows = session.execute(
        select(HardwareItemModel.hardware_category, HardwareItemModel.product_code)
        .where(HardwareItemModel.project_id == project_id)
        .distinct()
    ).all()
    return {(cat, code) for cat, code in rows}


def get_scheduled_classifications(
    session: Session, project_id: uuid.UUID
) -> dict[tuple[str, str], Classification | None]:
    """The dominant SITE/SHOP classification of each product on the project's schedule, project-wide.

    The same rule `request_composer._dominant_classification` applies per (opening, product), lifted
    to the whole project so a loose extras line - which carries no opening - can still show the chip
    and framing the opening-tagged catalog rows carry. Whichever classification covers the most units
    of a product wins; a tie breaks on the enum name so the answer never depends on row order, and an
    unclassified majority answers None rather than guessing site or shop on the user's behalf.

    One grouped query down to (category, product, classification); the winner is picked in Python
    against the handful of rows a single product has. Only products the schedule names appear - a
    stock combo the schedule never mentions is absent from the map, and the caller reads that as None.
    """
    return get_scheduled_classifications_for_projects(session, [project_id]).get(project_id, {})


def get_scheduled_classifications_for_projects(
    session: Session, project_ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict[tuple[str, str], Classification | None]]:
    """`get_scheduled_classifications` across many projects in ONE grouped query.

    Same dominance rule per (project, category, code); a project with no schedule is simply absent.
    Exists so multi-project readers (put-away's classification fallback) stay one query at any queue
    size instead of one aggregate per project.
    """
    if not project_ids:
        return {}

    rows = session.execute(
        select(
            HardwareItemModel.project_id,
            HardwareItemModel.hardware_category,
            HardwareItemModel.product_code,
            HardwareItemModel.classification,
            func.sum(HardwareItemModel.item_quantity),
        )
        .where(HardwareItemModel.project_id.in_(project_ids))
        .group_by(
            HardwareItemModel.project_id,
            HardwareItemModel.hardware_category,
            HardwareItemModel.product_code,
            HardwareItemModel.classification,
        )
    ).all()

    by_product: dict[tuple[uuid.UUID, str, str], dict[Classification | None, int]] = {}
    for project_id, category, code, classification, quantity in rows:
        tally = by_product.setdefault((project_id, category, code), {})
        tally[classification] = tally.get(classification, 0) + int(quantity or 0)

    out: dict[uuid.UUID, dict[tuple[str, str], Classification | None]] = {}
    for (project_id, category, code), tally in by_product.items():
        winner = sorted(tally.items(), key=lambda item: (-item[1], item[0].value if item[0] else ""))[0][0]
        out.setdefault(project_id, {})[(category, code)] = winner
    return out


def get_project_schedule_products(session: Session, project_ids: list[uuid.UUID]) -> list[dict]:
    """Per project, EVERY schedule (hardware_category, product_code) pair, with its required units.

    Feeds the SharePoint migration wizard's category snap and classification step. A migrated row is
    made claimable only by an exact (hardware_category, product_code) match against the schedule, but
    SharePoint's part category is free text that rarely matches the schedule's wording, so the wizard
    snaps a matched row to the schedule's category - and this is where it reads it from.

    One row per (project, category, code) pair - NOT collapsed to a dominant category per code. A code
    split across two categories (the same product scheduled as Hinge on one opening and Lock on
    another) is two pairs, and the wizard splits the migrated quantity across them by
    `required_quantity`; collapsing here left the minority pair's rows unmarked and unclassified with
    nothing on screen saying so. `classification` is the dominant value within the pair (most units
    wins, ties on the enum name), or null where the schedule never classified it - the step presents
    that inherited or asks for a pick. One grouped query; winners picked in Python.
    """
    if not project_ids:
        return []

    rows = session.execute(
        select(
            HardwareItemModel.project_id,
            HardwareItemModel.hardware_category,
            HardwareItemModel.product_code,
            HardwareItemModel.classification,
            func.sum(HardwareItemModel.item_quantity),
        )
        .where(HardwareItemModel.project_id.in_(project_ids))
        .group_by(
            HardwareItemModel.project_id,
            HardwareItemModel.hardware_category,
            HardwareItemModel.product_code,
            HardwareItemModel.classification,
        )
    ).all()

    # (project, category, code) -> {classification: units}
    grouped: dict[tuple[uuid.UUID, str, str], dict[Classification | None, int]] = {}
    for project_id, category, code, classification, quantity in rows:
        tally = grouped.setdefault((project_id, category, code), {})
        tally[classification] = tally.get(classification, 0) + int(quantity or 0)

    out: list[dict] = []
    for (project_id, category, code), tally in grouped.items():
        required = sum(tally.values())
        dominant_class = sorted(tally.items(), key=lambda item: (-item[1], item[0].value if item[0] else ""))[0][0]
        out.append(
            {
                "project_id": project_id,
                "hardware_category": category,
                "product_code": code,
                "classification": dominant_class,
                "required_quantity": required,
            }
        )
    # Largest pair first within a code, so the wizard's split order is already the read order.
    out.sort(key=lambda r: (str(r["project_id"]), r["product_code"], -r["required_quantity"], r["hardware_category"]))
    return out


def resolve_project_combo_cost(session: Session, project_id: uuid.UUID, hardware_category: str, product_code: str):
    """The best-known per-unit cost of one (category, code) in a project, or None.

    For write paths that re-materialize inventory with no PO line to hang a cost on - a shipment
    return, a pull-cancel restock after the original row was deleted. Newest project row's effective
    cost first (PO line cost, else the row's own off-PO cost - the same coalesce every value view
    applies), then the schedule's dominant unit_cost for the combo. None when nothing knows a price;
    inventing 0 here would just be the silent-zero valuation bug with extra steps.
    """
    row_cost = session.execute(
        select(func.coalesce(POLineItemModel.unit_cost, InventoryLocationModel.unit_cost))
        .select_from(InventoryLocationModel)
        .outerjoin(POLineItemModel, InventoryLocationModel.po_line_item_id == POLineItemModel.id)
        .where(
            InventoryLocationModel.project_id == project_id,
            InventoryLocationModel.hardware_category == hardware_category,
            InventoryLocationModel.product_code == product_code,
            func.coalesce(POLineItemModel.unit_cost, InventoryLocationModel.unit_cost).is_not(None),
        )
        .order_by(InventoryLocationModel.received_at.desc())
        .limit(1)
    ).scalar()
    if row_cost is not None:
        return row_cost

    # Schedule fallback: the cost covering the most units wins, ties on the higher cost so the
    # answer never depends on row order.
    schedule_rows = session.execute(
        select(HardwareItemModel.unit_cost, func.sum(HardwareItemModel.item_quantity))
        .where(
            HardwareItemModel.project_id == project_id,
            HardwareItemModel.hardware_category == hardware_category,
            HardwareItemModel.product_code == product_code,
            HardwareItemModel.unit_cost.is_not(None),
        )
        .group_by(HardwareItemModel.unit_cost)
    ).all()
    if not schedule_rows:
        return None
    return sorted(schedule_rows, key=lambda r: (-int(r[1] or 0), -r[0]))[0][0]


def get_inventory_rows(
    session: Session, project_id: uuid.UUID | None = None, warehouse_id: uuid.UUID | None = None
) -> list[dict]:
    """Every stocked InventoryLocation as a flat row (#506).

    The Hardware Items view was a category -> product -> location accordion, which answered
    "what does this project hold" but not "what is on which shelf" without three clicks per line.
    This is the same data one row per inventory line, so the warehouse can sort, filter and export
    it like the spreadsheet it replaces; a product-level rollup is one sort away.

    One query, no N+1: the vendor name and PO number come off the originating PO line by outer join,
    and a stock-origin row (no po_line_item_id) simply carries nulls.
    """
    from app.models.warehouse import Warehouse as WarehouseModel

    stmt = (
        select(
            InventoryLocationModel,
            POLineItemModel.unit_cost,
            POModel.po_number,
            POModel.vendor_name_snapshot,
            WarehouseModel.code,
            WarehouseModel.name,
            ProjectModel.project_id,
            ProjectModel.description,
        )
        .outerjoin(POLineItemModel, InventoryLocationModel.po_line_item_id == POLineItemModel.id)
        .outerjoin(POModel, POLineItemModel.po_id == POModel.id)
        .join(WarehouseModel, InventoryLocationModel.warehouse_id == WarehouseModel.id)
        .join(ProjectModel, InventoryLocationModel.project_id == ProjectModel.id)
        # Rows emptied by destock or allocation are kept for FK integrity but hold nothing.
        .where(InventoryLocationModel.quantity > 0)
    )
    if project_id is not None:
        stmt = stmt.where(InventoryLocationModel.project_id == project_id)
    if warehouse_id is not None:
        stmt = stmt.where(InventoryLocationModel.warehouse_id == warehouse_id)
    stmt = stmt.order_by(
        InventoryLocationModel.hardware_category,
        InventoryLocationModel.product_code,
        InventoryLocationModel.aisle,
        InventoryLocationModel.row,
        InventoryLocationModel.bay,
    )

    rows = []
    for il, unit_cost, po_number, vendor_name, wh_code, wh_name, proj_number, proj_desc in session.execute(stmt).all():
        # PO line cost first, then the row's own off-PO cost (the SharePoint migration), then 0.
        cost = float(unit_cost if unit_cost is not None else (il.unit_cost or 0))
        rows.append(
            {
                "inventory_location": il,
                "unit_cost": cost,
                "line_value": cost * il.quantity,
                "po_number": po_number,
                "vendor_name": vendor_name,
                "warehouse_code": wh_code,
                "warehouse_name": wh_name,
                "project_number": proj_number,
                "project_name": proj_desc or proj_number,
            }
        )
    return rows
