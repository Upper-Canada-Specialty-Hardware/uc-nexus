"""Project inventory + opening item reads and admin quantity corrections."""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import NotFoundError, ValidationError
from app.models.enums import AuditAction, AuditEntityType
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

    return [
        {
            "inventory_location": row[0],
            "classification": row[1],
            "po_number": row[2],
            "unit_cost": float(row[3]) if row[3] is not None else 0.0,
        }
        for row in rows
    ]


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
        cost = float(unit_cost or 0)
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
