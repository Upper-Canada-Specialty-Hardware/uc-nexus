"""Stock item reads + in-pool corrections (adjust, move, locate, reclassify)."""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import NotFoundError, ValidationError
from app.models.enums import AuditAction, AuditEntityType, PoolKind
from app.models.stock_item import StockItem
from app.repositories.warehouse import ensure_registered_location, location_detail, normalize_location_value
from app.repositories.warehouse.inventory import check_expected_quantity

from .common import (
    _find_or_create_stock_row,
    _find_stock_row,
    _log_audit_event,
    _stock_row_is_referenced,
    _validate_location_fields,
    fold_into_same_key_row,
    lock_for_shelf_move,
    lock_pool_source,
)


def get_stock_items(
    session: Session,
    product_code_contains: str | None = None,
    hardware_category: str | None = None,
    aisle: str | None = None,
    only_deficient: bool = False,
    warehouse_id: uuid.UUID | None = None,
    only_unlocated: bool = False,
    *,
    company: str | None = None,
    kind: PoolKind | None = None,
) -> list[StockItem]:
    """List stock_items optionally filtered by product code, category, aisle, deficient-only, or
    unlocated-only (no aisle - the rows the Put Away stock section works through).

    Hides fully-emptied rows (quantity = 0 AND deficient_quantity = 0). These rows are kept in the
    DB so they can remain the origin of any inventory_locations row that was allocated out of them
    (the FK SET NULL would otherwise blank out the only origin link).
    """
    stmt = (
        select(StockItem)
        .where(StockItem.quantity + StockItem.deficient_quantity > 0)
        .order_by(
            StockItem.hardware_category.asc(),
            StockItem.product_code.asc(),
            StockItem.received_at.asc(),
        )
    )
    # #1508: both come from the pool's filter boxes, typed or pasted, so a stray space must not empty
    # the pool, and the category matches part of the value in any case, like every other search box.
    product_code_contains = (product_code_contains or "").strip()
    hardware_category = (hardware_category or "").strip()
    if product_code_contains:
        # Escaped (#1270): product codes carry `_`, which LIKE reads as "any character".
        stmt = stmt.where(StockItem.product_code.ilike(f"%{_escape_like(product_code_contains)}%", escape="\\"))
    if hardware_category:
        stmt = stmt.where(StockItem.hardware_category.ilike(f"%{_escape_like(hardware_category)}%", escape="\\"))
    if aisle:
        stmt = stmt.where(StockItem.aisle == aisle)
    if only_deficient:
        stmt = stmt.where(StockItem.deficient_quantity > 0)
    if warehouse_id is not None:
        stmt = stmt.where(StockItem.warehouse_id == warehouse_id)
    if only_unlocated:
        stmt = stmt.where(StockItem.aisle.is_(None))
    if kind is not None:
        stmt = stmt.where(StockItem.kind == kind)
    if company is not None:
        from app.repositories import tenancy

        # Stock is jobless, so it scopes through its warehouse rather than a project (#637).
        stmt = stmt.where(StockItem.warehouse_id.in_(tenancy.warehouse_ids_for(company)))
    return list(session.scalars(stmt).all())


def _escape_like(raw: str) -> str:
    r"""Escape LIKE metacharacters so a filter for "50%" means "50%" and not "anything after 50"."""
    return raw.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def get_stock_item(session: Session, stock_item_id: uuid.UUID) -> StockItem:
    si = session.get(StockItem, stock_item_id)
    if si is None:
        raise NotFoundError(f"Stock item {stock_item_id} not found")
    return si


def lock_stock_item(session: Session, stock_item_id: uuid.UUID) -> StockItem:
    """Row-lock one pool row and return it fresh (#1156).

    For writers that read a pool row's count and then write it back: without the lock two allocations
    off the same row both pass the availability check, and a recount overwrites a concurrent move.
    `populate_existing` matters for the same reason as `lock_inventory_combo`: the row is usually already
    in the session from the tenancy check, and a plain FOR UPDATE would hand back that stale copy.
    """
    si = session.scalars(
        select(StockItem)
        .where(StockItem.id == stock_item_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).first()
    if si is None:
        raise NotFoundError(f"Stock item {stock_item_id} not found")
    return si


def adjust_stock_quantity(
    session: Session,
    *,
    stock_item_id: uuid.UUID,
    new_quantity: int,
    reason_text: str,
    performed_by: str,
    expected_quantity: int | None = None,
) -> StockItem:
    """Set stock_item.quantity to an absolute value (recount / write-off). reason required.

    The pool row is locked and read fresh, and `expected_quantity` (the count the dialog showed and
    built `new_quantity` from) must still hold, or the write is refused (#1316): an allocation landing
    in between would otherwise be undone and its units brought back."""
    if not reason_text or len(reason_text) > 500:
        raise ValidationError("reason_text must be 1-500 characters", field="reason_text")
    if new_quantity < 0:
        raise ValidationError("new_quantity must be >= 0", field="new_quantity")

    si = lock_stock_item(session, stock_item_id)
    # Must follow the lock directly: the count compared is the locked, fresh one.
    check_expected_quantity(si.quantity, expected_quantity)

    # The deficient units stay on the row, so the count cannot go below them (#1517: same words as inventory).
    if new_quantity < si.deficient_quantity:
        raise ValidationError(
            "Cannot set quantity below this row's deficient quantity",
            field="new_quantity",
        )

    old_quantity = si.quantity
    si.quantity = new_quantity

    _log_audit_event(
        session,
        project_id=None,
        entity_type=AuditEntityType.STOCK_ITEM,
        entity_id=si.id,
        action=AuditAction.ADJUSTMENT,
        performed_by=performed_by,
        detail={
            "oldQuantity": old_quantity,
            "newQuantity": new_quantity,
            "adjustment": new_quantity - old_quantity,
            "reasonText": reason_text,
        },
    )
    return si


def move_stock_location(
    session: Session,
    *,
    stock_item_id: uuid.UUID,
    new_aisle: str,
    new_row: str,
    new_bay: str,
    performed_by: str,
) -> StockItem:
    if new_aisle is None or new_row is None or new_bay is None:
        raise ValidationError("new aisle/row/bay are required", field="location")
    new_aisle = normalize_location_value(new_aisle) or ""
    new_row = normalize_location_value(new_row) or ""
    new_bay = normalize_location_value(new_bay) or ""
    _validate_location_fields(new_aisle, new_row, new_bay)

    # The moving row and the same-key row on the target shelf are locked together, in id order (#1401).
    si = lock_for_shelf_move(session, stock_item_id, aisle=new_aisle, row=new_row, bay=new_bay)
    ensure_registered_location(session, si.warehouse_id, new_aisle, new_row, new_bay)
    old = location_detail(si.aisle, si.row, si.bay, si.warehouse_id)
    detail = {"fromLocation": old, "toLocation": location_detail(new_aisle, new_row, new_bay, si.warehouse_id)}
    # A same-key row already on the target shelf takes this one's units (#1377), so the shelf never
    # holds two rows of one product at one price.
    target = fold_into_same_key_row(session, si, aisle=new_aisle, row=new_row, bay=new_bay)
    if target is None:
        si.aisle = new_aisle
        si.row = new_row
        si.bay = new_bay
    else:
        detail["foldedIntoStockItemId"] = str(target.id)

    _log_audit_event(
        session,
        project_id=None,
        entity_type=AuditEntityType.STOCK_ITEM,
        entity_id=si.id,
        action=AuditAction.MOVE,
        performed_by=performed_by,
        detail=detail,
    )
    return target or si


def mark_stock_item_unlocated(session: Session, *, stock_item_id: uuid.UUID, performed_by: str) -> StockItem:
    """Clear the aisle/row/bay on a StockItem."""
    if not performed_by:
        raise ValidationError("performed_by is required", field="performed_by")
    si = get_stock_item(session, stock_item_id)
    old = location_detail(si.aisle, si.row, si.bay, si.warehouse_id)
    si.aisle = None
    si.row = None
    si.bay = None
    _log_audit_event(
        session,
        project_id=None,
        entity_type=AuditEntityType.STOCK_ITEM,
        entity_id=si.id,
        action=AuditAction.UNLOCATE,
        performed_by=performed_by,
        detail={"fromLocation": old},
    )
    return si


def assign_stock_item_location(
    session: Session,
    *,
    stock_item_id: uuid.UUID,
    aisle: str,
    row: str,
    bay: str,
    performed_by: str,
) -> StockItem:
    """Assign aisle/row/bay to a StockItem (initial put-away or re-locate after unlocate)."""
    if not performed_by:
        raise ValidationError("performed_by is required", field="performed_by")
    aisle = normalize_location_value(aisle) or ""
    row = normalize_location_value(row) or ""
    bay = normalize_location_value(bay) or ""
    _validate_location_fields(aisle, row, bay)
    # Locked with the same-key row on the target shelf, in id order (#1401).
    si = lock_for_shelf_move(session, stock_item_id, aisle=aisle, row=row, bay=bay)
    ensure_registered_location(session, si.warehouse_id, aisle, row, bay)
    detail = {"toLocation": location_detail(aisle, row, bay, si.warehouse_id)}
    # Put away onto a shelf that already holds this row's key: fold into it (#1377).
    target = fold_into_same_key_row(session, si, aisle=aisle, row=row, bay=bay)
    if target is None:
        si.aisle = aisle
        si.row = row
        si.bay = bay
    else:
        detail["foldedIntoStockItemId"] = str(target.id)
    _log_audit_event(
        session,
        project_id=None,
        entity_type=AuditEntityType.STOCK_ITEM,
        entity_id=si.id,
        action=AuditAction.PUT_AWAY,
        performed_by=performed_by,
        detail=detail,
    )
    return target or si


def reclassify_stock_item(
    session: Session,
    *,
    stock_item_id: uuid.UUID,
    new_hardware_category: str,
    new_product_code: str,
    quantity: int,
    reason_text: str | None,
    performed_by: str,
) -> tuple[StockItem, StockItem | None]:
    """Change (category, code) on `quantity` units. If quantity < total, original keeps remainder.

    Returns (reclassified_row, original_row_or_none).
    """
    if quantity < 1:
        raise ValidationError("quantity must be >= 1", field="quantity")
    if not new_hardware_category:
        raise ValidationError("new_hardware_category is required", field="new_hardware_category")
    if not new_product_code:
        raise ValidationError("new_product_code is required", field="new_product_code")

    # #1422: a split writes two pool rows - this one and the row of the new key on the same shelf - so
    # both are locked together in id order, the way a shelf move locks them (#1401). Locking this row
    # first and the other inside the find-or-create below let two opposite reclassifies on one shelf
    # deadlock. The other row is found unlocked here; the find-or-create re-finds it, already held.
    found = session.get(StockItem, stock_item_id)
    if found is None:
        raise NotFoundError(f"Stock item {stock_item_id} not found")
    other = _find_stock_row(
        session,
        warehouse_id=found.warehouse_id,
        hardware_category=new_hardware_category,
        product_code=new_product_code,
        aisle=found.aisle,
        row=found.row,
        bay=found.bay,
        kind=found.kind,
        unit_cost=found.unit_cost,
        lock=False,
    )
    si = lock_pool_source(session, stock_item_id, other.id if other is not None else None)
    if quantity > si.quantity:
        raise ValidationError("Reclassify quantity exceeds stock quantity", field="quantity")

    # Disallow reclassifying deficient units — those must be resolved first
    available = si.quantity - (si.deficient_quantity or 0)
    if quantity > available:
        raise ValidationError(
            "Cannot reclassify deficient units; resolve deficiency first",
            field="quantity",
        )

    now = datetime.utcnow()

    if quantity == si.quantity:
        # #1509: the shelf may already hold the new key - a typo'd code put beside the right one at
        # receive. Rewriting this row in place then left two rows of one product at one price (#1164,
        # #1377), so the units fold into that row instead, the way a whole-row kind flip and a shelf
        # move fold. Re-found here locked; lock_pool_source already holds it.
        target = _find_stock_row(
            session,
            warehouse_id=si.warehouse_id,
            hardware_category=new_hardware_category,
            product_code=new_product_code,
            aisle=si.aisle,
            row=si.row,
            bay=si.bay,
            kind=si.kind,
            unit_cost=si.unit_cost,
        )
        if target is not None and target.id != si.id:
            return _fold_reclassified_row(
                session,
                si,
                target,
                new_hardware_category=new_hardware_category,
                new_product_code=new_product_code,
                reason_text=reason_text,
                performed_by=performed_by,
            )

        # Full reclassify in place
        old_cat = si.hardware_category
        old_code = si.product_code
        si.hardware_category = new_hardware_category
        si.product_code = new_product_code
        _log_audit_event(
            session,
            project_id=None,
            entity_type=AuditEntityType.STOCK_ITEM,
            entity_id=si.id,
            action=AuditAction.RECLASSIFY,
            performed_by=performed_by,
            detail={
                "from": {"hardwareCategory": old_cat, "productCode": old_code},
                "to": {
                    "hardwareCategory": new_hardware_category,
                    "productCode": new_product_code,
                },
                "quantity": quantity,
                "reasonText": reason_text,
            },
        )
        return (si, None)

    # Split: original keeps (qty - split), new row gets `quantity` at the new (cat, code)
    si.quantity -= quantity
    new_row = _find_or_create_stock_row(
        session,
        warehouse_id=si.warehouse_id,
        hardware_category=new_hardware_category,
        product_code=new_product_code,
        aisle=si.aisle,
        row=si.row,
        bay=si.bay,
        received_at=now,
        # A reclassify changes what the units are, not which half of the pool they sit in (#832),
        # nor what they cost (#942) - the same as a full in-place reclassify keeps the row's price.
        kind=si.kind,
        unit_cost=si.unit_cost,
    )
    new_row.quantity += quantity

    session.flush()

    detail = {
        "originalStockItemId": str(si.id),
        "newStockItemId": str(new_row.id),
        "from": {"hardwareCategory": si.hardware_category, "productCode": si.product_code},
        "to": {"hardwareCategory": new_hardware_category, "productCode": new_product_code},
        "quantity": quantity,
        "reasonText": reason_text,
    }
    _log_audit_event(
        session,
        project_id=None,
        entity_type=AuditEntityType.STOCK_ITEM,
        entity_id=si.id,
        action=AuditAction.RECLASSIFY,
        performed_by=performed_by,
        detail=detail,
    )
    _log_audit_event(
        session,
        project_id=None,
        entity_type=AuditEntityType.STOCK_ITEM,
        entity_id=new_row.id,
        action=AuditAction.RECLASSIFY,
        performed_by=performed_by,
        detail=detail,
    )
    return (new_row, si)


def _fold_reclassified_row(
    session: Session,
    si: StockItem,
    target: StockItem,
    *,
    new_hardware_category: str,
    new_product_code: str,
    reason_text: str | None,
    performed_by: str,
) -> tuple[StockItem, StockItem | None]:
    """Move every unit of `si` into `target`, the row already holding the new key on this shelf (#1509).

    Only sound units reach here (a whole-row reclassify needs no deficient units), so only the quantity
    moves. The emptied row is deleted when nothing points at it, as `fold_into_same_key_row` does; a
    referenced one stays, empty and hidden from the browse view, and comes back as the original.
    """
    detail = {
        "originalStockItemId": str(si.id),
        "newStockItemId": str(target.id),
        "from": {"hardwareCategory": si.hardware_category, "productCode": si.product_code},
        "to": {"hardwareCategory": new_hardware_category, "productCode": new_product_code},
        "quantity": si.quantity,
        "reasonText": reason_text,
        "foldedIntoStockItemId": str(target.id),
    }
    target.quantity += si.quantity
    si.quantity = 0
    session.flush()
    for entity_id in (si.id, target.id):
        _log_audit_event(
            session,
            project_id=None,
            entity_type=AuditEntityType.STOCK_ITEM,
            entity_id=entity_id,
            action=AuditAction.RECLASSIFY,
            performed_by=performed_by,
            detail=detail,
        )
    if _stock_row_is_referenced(session, si.id):
        return (target, si)
    session.delete(si)
    session.flush()
    return (target, None)


def set_stock_item_kind(
    session: Session,
    *,
    stock_item_id: uuid.UUID,
    kind: PoolKind,
    quantity: int,
    performed_by: str,
) -> tuple[StockItem, StockItem | None]:
    """Re-flag `quantity` units of a pool row as Stock or Overhead (#832).

    The units move to the row of the other kind on the same shelf and at the same price (#942), which
    is created or merged into.
    When every unit of the row moves and there is no such row yet, the row's own flag flips in place
    instead, so it keeps its id.

    Only sound units move (1..available), the same rule reclassify applies: deficient units are
    condemned and stay on their row, under the kind they were condemned under, until the deficiency is
    resolved. That keeps a deficiency review pointing at the row it was raised against.

    Returns (row_now_holding_the_units, source_row_or_none) - the second is None on an in-place flip.
    """
    if quantity < 1:
        raise ValidationError("quantity must be >= 1", field="quantity")
    if not performed_by:
        raise ValidationError("performed_by is required", field="performed_by")

    # #1422: the units move to the row of the other kind on this shelf, so both rows are locked
    # together in id order (#1401) - locking this one first and that one in the find below let a Stock
    # -> Overhead flip and an Overhead -> Stock flip of the same product deadlock. Found unlocked here,
    # re-found below, already held.
    found = session.get(StockItem, stock_item_id)
    if found is None:
        raise NotFoundError(f"Stock item {stock_item_id} not found")
    other = _find_stock_row(
        session,
        warehouse_id=found.warehouse_id,
        hardware_category=found.hardware_category,
        product_code=found.product_code,
        aisle=found.aisle,
        row=found.row,
        bay=found.bay,
        kind=kind,
        unit_cost=found.unit_cost,
        lock=False,
    )
    si = lock_pool_source(session, stock_item_id, other.id if other is not None else None)
    if si.kind == kind:
        raise ValidationError(f"This row is already {kind.value.lower()}", field="kind")
    available = si.quantity - (si.deficient_quantity or 0)
    if quantity > available:
        raise ValidationError(
            "Quantity exceeds the row's available units; deficient units must be resolved first",
            field="quantity",
        )

    from_kind = si.kind
    target = _find_stock_row(
        session,
        warehouse_id=si.warehouse_id,
        hardware_category=si.hardware_category,
        product_code=si.product_code,
        aisle=si.aisle,
        row=si.row,
        bay=si.bay,
        kind=kind,
        unit_cost=si.unit_cost,
    )

    if target is None and quantity == si.quantity:
        si.kind = kind
        session.flush()
        _log_audit_event(
            session,
            project_id=None,
            entity_type=AuditEntityType.STOCK_ITEM,
            entity_id=si.id,
            action=AuditAction.POOL_KIND_CHANGE,
            performed_by=performed_by,
            detail={
                "fromKind": from_kind.value,
                "toKind": kind.value,
                "quantity": quantity,
                "hardwareCategory": si.hardware_category,
                "productCode": si.product_code,
                "location": location_detail(si.aisle, si.row, si.bay, si.warehouse_id),
            },
        )
        return (si, None)

    if target is None:
        target = _find_or_create_stock_row(
            session,
            warehouse_id=si.warehouse_id,
            hardware_category=si.hardware_category,
            product_code=si.product_code,
            aisle=si.aisle,
            row=si.row,
            bay=si.bay,
            received_at=si.received_at,
            kind=kind,
            unit_cost=si.unit_cost,
        )
    si.quantity -= quantity
    target.quantity += quantity
    session.flush()

    detail = {
        "fromKind": from_kind.value,
        "toKind": kind.value,
        "quantity": quantity,
        "hardwareCategory": si.hardware_category,
        "productCode": si.product_code,
        "location": location_detail(si.aisle, si.row, si.bay, si.warehouse_id),
        "originalStockItemId": str(si.id),
        "newStockItemId": str(target.id),
    }
    for entity_id in (si.id, target.id):
        _log_audit_event(
            session,
            project_id=None,
            entity_type=AuditEntityType.STOCK_ITEM,
            entity_id=entity_id,
            action=AuditAction.POOL_KIND_CHANGE,
            performed_by=performed_by,
            detail=detail,
        )
    return (target, si)
