"""Repository for stock_items (non-stock, UCSH-owned shelf hardware)."""

import uuid
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.errors import NotFoundError, ValidationError
from app.models.audit_log import InventoryAuditLog
from app.models.enums import (
    AuditAction,
    AuditEntityType,
    DeficiencyResolution,
    DeficientItemSource,
    DestockSource,
)
from app.models.inventory import InventoryLocation as InventoryLocationModel
from app.models.stock_item import StockItem
from app.repositories.warehouse_repository import normalize_location_value


def _log_audit_event(
    session: Session,
    *,
    project_id: uuid.UUID | None,
    entity_type: AuditEntityType,
    entity_id: uuid.UUID,
    action: AuditAction,
    performed_by: str,
    detail: dict | None = None,
) -> None:
    """Insert a row into inventory_audit_log. Project_id is null for pure stock-pool events."""
    session.add(
        InventoryAuditLog(
            project_id=project_id,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            detail=detail,
            performed_by=performed_by,
        )
    )


def _validate_location_fields(aisle: str | None, bay: str | None, bin: str | None) -> None:
    """Validate aisle, bay, bin lengths when provided."""
    for field_name, value in [("aisle", aisle), ("bay", bay), ("bin", bin)]:
        if value is not None and (len(value) < 1 or len(value) > 20):
            raise ValidationError(f"{field_name} must be 1-20 characters", field=field_name)


def _normalize_optional_location_fields(
    aisle: str | None, bay: str | None, bin: str | None
) -> tuple[str | None, str | None, str | None]:
    """Normalize each optional field then re-validate. Returns canonical triple (nullable)."""
    a = normalize_location_value(aisle)
    b = normalize_location_value(bay)
    c = normalize_location_value(bin)
    _validate_location_fields(a, b, c)
    return (a, b, c)


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------


def get_stock_items(
    session: Session,
    product_code_contains: str | None = None,
    hardware_category: str | None = None,
    aisle: str | None = None,
    only_deficient: bool = False,
    warehouse_id: uuid.UUID | None = None,
) -> list[StockItem]:
    """List stock_items optionally filtered by product code, category, aisle, or deficient-only.

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
    if product_code_contains:
        stmt = stmt.where(StockItem.product_code.ilike(f"%{product_code_contains}%"))
    if hardware_category:
        stmt = stmt.where(StockItem.hardware_category == hardware_category)
    if aisle:
        stmt = stmt.where(StockItem.aisle == aisle)
    if only_deficient:
        stmt = stmt.where(StockItem.deficient_quantity > 0)
    if warehouse_id is not None:
        stmt = stmt.where(StockItem.warehouse_id == warehouse_id)
    return list(session.scalars(stmt).all())


def get_stock_item(session: Session, stock_item_id: uuid.UUID) -> StockItem:
    si = session.get(StockItem, stock_item_id)
    if si is None:
        raise NotFoundError(f"Stock item {stock_item_id} not found")
    return si


def get_stock_matches_for_opening(
    session: Session,
    opening_item_id: uuid.UUID,
) -> list[StockItem]:
    """Return stock_items whose hardware_category matches the opening item's category.

    Match is intentionally loose: same hardware_category, ranking exact product_code match first.
    """
    from app.models.opening_item import OpeningItem, OpeningItemHardware

    oi = session.get(OpeningItem, opening_item_id)
    if oi is None:
        raise NotFoundError(f"Opening item {opening_item_id} not found")

    # Pull installed hardware to know what categories/codes we are looking for
    ih_stmt = select(OpeningItemHardware).where(OpeningItemHardware.opening_item_id == opening_item_id)
    installed = list(session.scalars(ih_stmt).all())
    if not installed:
        return []

    categories = {h.hardware_category for h in installed}
    codes = {h.product_code for h in installed}

    stmt = (
        select(StockItem)
        .where(StockItem.hardware_category.in_(categories))
        .where(StockItem.quantity > 0)
        .order_by(StockItem.product_code.asc(), StockItem.received_at.asc())
    )
    rows = list(session.scalars(stmt).all())
    # Promote exact product_code matches to the front
    rows.sort(key=lambda r: (r.product_code not in codes, r.hardware_category, r.product_code))
    return rows


# ---------------------------------------------------------------------------
# Helpers shared by destock / allocate / receive-to-stock
# ---------------------------------------------------------------------------


def _find_or_create_stock_row(
    session: Session,
    *,
    warehouse_id: uuid.UUID,
    hardware_category: str,
    product_code: str,
    aisle: str | None,
    bay: str | None,
    bin: str | None,
    received_at: datetime,
) -> StockItem:
    """Find an existing stock row matching (warehouse, category, code, aisle, bay, bin) or create one with qty=0.

    Caller is responsible for incrementing quantity and writing audit events. Location fields are
    normalized here so writes from any entry path (destock, allocate, receive) match canonical form.
    """
    aisle = normalize_location_value(aisle)
    bay = normalize_location_value(bay)
    bin = normalize_location_value(bin)

    stmt = select(StockItem).where(
        StockItem.warehouse_id == warehouse_id,
        StockItem.hardware_category == hardware_category,
        StockItem.product_code == product_code,
    )
    if aisle is None:
        stmt = stmt.where(StockItem.aisle.is_(None))
    else:
        stmt = stmt.where(StockItem.aisle == aisle)
    if bay is None:
        stmt = stmt.where(StockItem.bay.is_(None))
    else:
        stmt = stmt.where(StockItem.bay == bay)
    if bin is None:
        stmt = stmt.where(StockItem.bin.is_(None))
    else:
        stmt = stmt.where(StockItem.bin == bin)

    existing = session.scalars(stmt).first()
    if existing is not None:
        return existing

    new_row = StockItem(
        warehouse_id=warehouse_id,
        hardware_category=hardware_category,
        product_code=product_code,
        quantity=0,
        deficient_quantity=0,
        aisle=aisle,
        bay=bay,
        bin=bin,
        received_at=received_at,
    )
    session.add(new_row)
    session.flush()
    return new_row


# ---------------------------------------------------------------------------
# Event 1: destock — InventoryLocation → StockItem
# ---------------------------------------------------------------------------


def destock_inventory(
    session: Session,
    *,
    inventory_location_id: uuid.UUID,
    quantity: int,
    source: DestockSource,
    reason_text: str | None,
    target_aisle: str | None,
    target_bay: str | None,
    target_bin: str | None,
    performed_by: str,
) -> StockItem:
    """Move quantity units from a project's InventoryLocation row into the stock pool."""
    if quantity < 1:
        raise ValidationError("quantity must be >= 1", field="quantity")
    if not performed_by:
        raise ValidationError("performed_by is required", field="performed_by")
    _validate_location_fields(target_aisle, target_bay, target_bin)

    il = session.get(InventoryLocationModel, inventory_location_id)
    if il is None:
        raise NotFoundError(f"Inventory location {inventory_location_id} not found")
    if quantity > il.quantity:
        raise ValidationError("Destock quantity exceeds available quantity", field="quantity")

    # If DEFICIENT_SWAP, the units being destocked are the deficient ones: tighten that flag too
    is_deficient_swap = source == DestockSource.DEFICIENT_SWAP
    if is_deficient_swap:
        if quantity > (il.deficient_quantity or 0):
            raise ValidationError(
                "DEFICIENT_SWAP destock quantity exceeds deficient_quantity on source row",
                field="quantity",
            )

    # Pick target bin: explicit override or fall back to source bin
    final_aisle = target_aisle if target_aisle is not None else il.aisle
    final_bay = target_bay if target_bay is not None else il.bay
    final_bin = target_bin if target_bin is not None else il.bin

    now = datetime.utcnow()
    stock_row = _find_or_create_stock_row(
        session,
        warehouse_id=il.warehouse_id,
        hardware_category=il.hardware_category,
        product_code=il.product_code,
        aisle=final_aisle,
        bay=final_bay,
        bin=final_bin,
        received_at=now,
    )

    # Apply the move
    il.quantity -= quantity
    if is_deficient_swap:
        il.deficient_quantity = max(0, (il.deficient_quantity or 0) - quantity)
    stock_row.quantity += quantity

    session.flush()

    detail = {
        "fromInventoryLocationId": str(il.id),
        "projectId": str(il.project_id),
        "hardwareCategory": il.hardware_category,
        "productCode": il.product_code,
        "quantity": quantity,
        "source": source.value,
        "reasonText": reason_text,
        "targetLocation": {"aisle": final_aisle, "bay": final_bay, "bin": final_bin},
        "stockItemId": str(stock_row.id),
    }
    _log_audit_event(
        session,
        project_id=il.project_id,
        entity_type=AuditEntityType.INVENTORY_LOCATION,
        entity_id=il.id,
        action=AuditAction.DESTOCK,
        performed_by=performed_by,
        detail=detail,
    )
    _log_audit_event(
        session,
        project_id=None,
        entity_type=AuditEntityType.STOCK_ITEM,
        entity_id=stock_row.id,
        action=AuditAction.DESTOCK,
        performed_by=performed_by,
        detail=detail,
    )
    return stock_row


# ---------------------------------------------------------------------------
# Event 4: adjust + move stock-pool internally
# ---------------------------------------------------------------------------


def adjust_stock_quantity(
    session: Session,
    *,
    stock_item_id: uuid.UUID,
    new_quantity: int,
    reason_text: str,
    performed_by: str,
) -> StockItem:
    """Set stock_item.quantity to an absolute value (recount / write-off). reason required."""
    if not reason_text or len(reason_text) > 500:
        raise ValidationError("reason_text must be 1-500 characters", field="reason_text")
    if new_quantity < 0:
        raise ValidationError("new_quantity must be >= 0", field="new_quantity")

    si = get_stock_item(session, stock_item_id)

    # Honor the deficient_quantity <= quantity invariant by clamping if needed
    if new_quantity < si.deficient_quantity:
        raise ValidationError(
            "Cannot set quantity below current deficient_quantity",
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
    new_bay: str,
    new_bin: str,
    performed_by: str,
) -> StockItem:
    if new_aisle is None or new_bay is None or new_bin is None:
        raise ValidationError("new aisle/bay/bin are required", field="location")
    new_aisle = normalize_location_value(new_aisle) or ""
    new_bay = normalize_location_value(new_bay) or ""
    new_bin = normalize_location_value(new_bin) or ""
    _validate_location_fields(new_aisle, new_bay, new_bin)

    si = get_stock_item(session, stock_item_id)
    old = {"aisle": si.aisle, "bay": si.bay, "bin": si.bin}
    si.aisle = new_aisle
    si.bay = new_bay
    si.bin = new_bin

    _log_audit_event(
        session,
        project_id=None,
        entity_type=AuditEntityType.STOCK_ITEM,
        entity_id=si.id,
        action=AuditAction.MOVE,
        performed_by=performed_by,
        detail={"fromLocation": old, "toLocation": {"aisle": new_aisle, "bay": new_bay, "bin": new_bin}},
    )
    return si


def mark_stock_item_unlocated(session: Session, *, stock_item_id: uuid.UUID, performed_by: str) -> StockItem:
    """Clear the aisle/bay/bin on a StockItem."""
    if not performed_by:
        raise ValidationError("performed_by is required", field="performed_by")
    si = get_stock_item(session, stock_item_id)
    old = {"aisle": si.aisle, "bay": si.bay, "bin": si.bin}
    si.aisle = None
    si.bay = None
    si.bin = None
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
    bay: str,
    bin: str,
    performed_by: str,
) -> StockItem:
    """Assign aisle/bay/bin to a StockItem (initial put-away or re-locate after unlocate)."""
    if not performed_by:
        raise ValidationError("performed_by is required", field="performed_by")
    aisle = normalize_location_value(aisle) or ""
    bay = normalize_location_value(bay) or ""
    bin = normalize_location_value(bin) or ""
    _validate_location_fields(aisle, bay, bin)
    si = get_stock_item(session, stock_item_id)
    si.aisle = aisle
    si.bay = bay
    si.bin = bin
    _log_audit_event(
        session,
        project_id=None,
        entity_type=AuditEntityType.STOCK_ITEM,
        entity_id=si.id,
        action=AuditAction.PUT_AWAY,
        performed_by=performed_by,
        detail={"toLocation": {"aisle": aisle, "bay": bay, "bin": bin}},
    )
    return si


# ---------------------------------------------------------------------------
# Event 5: reclassify (split-capable)
# ---------------------------------------------------------------------------


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

    si = get_stock_item(session, stock_item_id)
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
        hardware_category=new_hardware_category,
        product_code=new_product_code,
        aisle=si.aisle,
        bay=si.bay,
        bin=si.bin,
        received_at=now,
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


# ---------------------------------------------------------------------------
# Event 3: allocate stock → project inventory
# ---------------------------------------------------------------------------


def allocate_stock_to_project(
    session: Session,
    *,
    stock_item_id: uuid.UUID,
    project_id: uuid.UUID,
    target_hardware_category: str,
    target_product_code: str,
    quantity: int,
    target_aisle: str | None,
    target_bay: str | None,
    target_bin: str | None,
    performed_by: str,
) -> InventoryLocationModel:
    """Transfer `quantity` units from a stock row into a project's inventory.

    Creates an InventoryLocation whose origin is the stock_items row (stock_item_id set,
    po_line_item_id / receive_line_item_id NULL). The CHECK constraint ck_inventory_locations_has_origin
    enforces that every row has either a PO origin or a stock origin.
    """
    from app.models.project import Project as ProjectModel

    if quantity < 1:
        raise ValidationError("quantity must be >= 1", field="quantity")
    if not target_hardware_category:
        raise ValidationError("target_hardware_category is required", field="target_hardware_category")
    if not target_product_code:
        raise ValidationError("target_product_code is required", field="target_product_code")
    _validate_location_fields(target_aisle, target_bay, target_bin)

    si = get_stock_item(session, stock_item_id)
    available = si.quantity - (si.deficient_quantity or 0)
    if quantity > available:
        raise ValidationError("Allocate quantity exceeds available stock", field="quantity")

    project = session.get(ProjectModel, project_id)
    if project is None:
        raise NotFoundError(f"Project {project_id} not found")

    now = datetime.utcnow()

    new_il = InventoryLocationModel(
        project_id=project_id,
        po_line_item_id=None,
        receive_line_item_id=None,
        stock_item_id=stock_item_id,
        warehouse_id=si.warehouse_id,
        hardware_category=target_hardware_category,
        product_code=target_product_code,
        quantity=quantity,
        deficient_quantity=0,
        aisle=target_aisle,
        bay=target_bay,
        bin=target_bin,
        received_at=now,
    )
    session.add(new_il)

    si.quantity -= quantity
    session.flush()

    detail = {
        "sourceStockItemId": str(stock_item_id),
        "projectId": str(project_id),
        "targetHardwareCategory": target_hardware_category,
        "targetProductCode": target_product_code,
        "quantity": quantity,
        "targetLocation": {"aisle": target_aisle, "bay": target_bay, "bin": target_bin},
        "newInventoryLocationId": str(new_il.id),
    }
    _log_audit_event(
        session,
        project_id=None,
        entity_type=AuditEntityType.STOCK_ITEM,
        entity_id=si.id,
        action=AuditAction.ALLOCATE_FROM_STOCK,
        performed_by=performed_by,
        detail=detail,
    )
    _log_audit_event(
        session,
        project_id=project_id,
        entity_type=AuditEntityType.INVENTORY_LOCATION,
        entity_id=new_il.id,
        action=AuditAction.ALLOCATE_FROM_STOCK,
        performed_by=performed_by,
        detail=detail,
    )

    # Keep empty stock rows so they can remain the origin of inventory_locations rows that were
    # allocated out of them (the ON DELETE SET NULL on stock_item_id would otherwise blank out the
    # only origin link and violate ck_inventory_locations_has_origin). get_stock_items filters
    # rows where quantity + deficient_quantity == 0 so they don't clutter the browse view.

    return new_il


# ---------------------------------------------------------------------------
# Events 6 + 7: deficiency report + resolve
# ---------------------------------------------------------------------------


def report_inventory_deficiency(
    session: Session,
    *,
    inventory_location_id: uuid.UUID,
    quantity: int,
    reason_text: str | None,
    performed_by: str,
) -> InventoryLocationModel:
    if quantity < 1:
        raise ValidationError("quantity must be >= 1", field="quantity")

    il = session.get(InventoryLocationModel, inventory_location_id)
    if il is None:
        raise NotFoundError(f"Inventory location {inventory_location_id} not found")

    new_deficient = (il.deficient_quantity or 0) + quantity
    if new_deficient > il.quantity:
        raise ValidationError(
            "Reported deficient quantity exceeds total quantity on row",
            field="quantity",
        )
    il.deficient_quantity = new_deficient

    _log_audit_event(
        session,
        project_id=il.project_id,
        entity_type=AuditEntityType.INVENTORY_LOCATION,
        entity_id=il.id,
        action=AuditAction.REPORT_DEFICIENT,
        performed_by=performed_by,
        detail={
            "quantity": quantity,
            "newDeficientQuantity": new_deficient,
            "reasonText": reason_text,
            "hardwareCategory": il.hardware_category,
            "productCode": il.product_code,
        },
    )
    return il


def report_stock_deficiency(
    session: Session,
    *,
    stock_item_id: uuid.UUID,
    quantity: int,
    reason_text: str | None,
    performed_by: str,
) -> StockItem:
    if quantity < 1:
        raise ValidationError("quantity must be >= 1", field="quantity")

    si = get_stock_item(session, stock_item_id)
    new_deficient = (si.deficient_quantity or 0) + quantity
    if new_deficient > si.quantity:
        raise ValidationError(
            "Reported deficient quantity exceeds total quantity on row",
            field="quantity",
        )
    si.deficient_quantity = new_deficient

    _log_audit_event(
        session,
        project_id=None,
        entity_type=AuditEntityType.STOCK_ITEM,
        entity_id=si.id,
        action=AuditAction.REPORT_DEFICIENT,
        performed_by=performed_by,
        detail={
            "quantity": quantity,
            "newDeficientQuantity": new_deficient,
            "reasonText": reason_text,
            "hardwareCategory": si.hardware_category,
            "productCode": si.product_code,
        },
    )
    return si


def report_deficiency_at_assembly(
    session: Session,
    *,
    sa_opening_item_id: uuid.UUID,
    source_inventory_location_id: uuid.UUID,
    quantity: int,
    reason_text: str | None,
    performed_by: str,
):
    """During SA, bump source InventoryLocation deficient_quantity AND auto-create a replacement
    pull request item against the same SAR opening.

    Returns (inventory_location, replacement_pull_request_item).
    """
    from app.models.enums import PullRequestItemType, PullRequestSource, PullRequestStatus
    from app.models.pull_request import PullRequest as PullRequestModel
    from app.models.pull_request import PullRequestItem as PullRequestItemModel
    from app.models.shop_assembly import ShopAssemblyOpening as SAOpeningModel
    from app.models.shop_assembly import ShopAssemblyOpeningItem as SAOpeningItemModel

    sa_oi = session.get(SAOpeningItemModel, sa_opening_item_id)
    if sa_oi is None:
        raise NotFoundError(f"Shop assembly opening item {sa_opening_item_id} not found")

    il = report_inventory_deficiency(
        session,
        inventory_location_id=source_inventory_location_id,
        quantity=quantity,
        reason_text=reason_text,
        performed_by=performed_by,
    )

    # Pull the parent SAR opening to learn opening_number for the replacement PR item
    sa_opening = session.get(SAOpeningModel, sa_oi.shop_assembly_opening_id)
    if sa_opening is None:
        raise NotFoundError(f"Shop assembly opening {sa_oi.shop_assembly_opening_id} not found")

    sar = sa_opening.shop_assembly_request

    # Find or create an open replacement pull request for this SAR
    replacement_request_number = f"PR-REPL-{sar.request_number}"
    existing_pr_stmt = select(PullRequestModel).where(
        PullRequestModel.request_number == replacement_request_number,
        PullRequestModel.deleted_at.is_(None),
        PullRequestModel.status.in_([PullRequestStatus.PENDING, PullRequestStatus.IN_PROGRESS]),
    )
    existing_pr = session.scalars(existing_pr_stmt).first()
    if existing_pr is None:
        replacement_pr = PullRequestModel(
            request_number=replacement_request_number,
            project_id=il.project_id,
            source=PullRequestSource.SHOP_ASSEMBLY,
            status=PullRequestStatus.PENDING,
            requested_by=performed_by,
        )
        session.add(replacement_pr)
        session.flush()
    else:
        replacement_pr = existing_pr

    opening_number = sa_opening.opening_number or "REPLACEMENT"

    pri = PullRequestItemModel(
        pull_request_id=replacement_pr.id,
        item_type=PullRequestItemType.LOOSE,
        opening_number=opening_number,
        hardware_category=il.hardware_category,
        product_code=il.product_code,
        requested_quantity=quantity,
    )
    session.add(pri)
    session.flush()

    return (il, pri)


def resolve_deficiency(
    session: Session,
    *,
    inventory_location_id: uuid.UUID | None,
    stock_item_id: uuid.UUID | None,
    resolution: DeficiencyResolution,
    quantity: int,
    reason_text: str | None,
    rma_reference: str | None,
    destock_source: DestockSource | None,
    reviewed_by: str,
):
    """Resolve a deficient batch. Exactly one of inventory_location_id / stock_item_id is set."""
    from app.models.deficiency_review import DeficiencyReview

    if (inventory_location_id is None) == (stock_item_id is None):
        raise ValidationError(
            "Exactly one of inventory_location_id / stock_item_id must be provided",
            field="source",
        )
    if quantity < 1:
        raise ValidationError("quantity must be >= 1", field="quantity")
    if not reviewed_by:
        raise ValidationError("reviewed_by is required", field="reviewed_by")
    if resolution == DeficiencyResolution.RETURN_TO_VENDOR and not rma_reference:
        raise ValidationError(
            "rma_reference is required when resolution is RETURN_TO_VENDOR",
            field="rma_reference",
        )
    if resolution == DeficiencyResolution.SEND_TO_STOCK and destock_source is None:
        # default to DEFICIENT_SWAP for project sources if not specified
        destock_source = DestockSource.DEFICIENT_SWAP

    resulting_stock_item_id: uuid.UUID | None = None
    project_for_audit: uuid.UUID | None = None
    hardware_category: str
    product_code: str

    if inventory_location_id is not None:
        il = session.get(InventoryLocationModel, inventory_location_id)
        if il is None:
            raise NotFoundError(f"Inventory location {inventory_location_id} not found")
        if quantity > (il.deficient_quantity or 0):
            raise ValidationError(
                "Resolved quantity exceeds current deficient_quantity",
                field="quantity",
            )
        project_for_audit = il.project_id
        hardware_category = il.hardware_category
        product_code = il.product_code

        if resolution == DeficiencyResolution.SEND_TO_STOCK:
            il.quantity -= quantity
            il.deficient_quantity -= quantity
            stock_row = _find_or_create_stock_row(
                session,
                hardware_category=il.hardware_category,
                product_code=il.product_code,
                aisle=il.aisle,
                bay=il.bay,
                bin=il.bin,
                received_at=datetime.utcnow(),
            )
            stock_row.quantity += quantity
            stock_row.deficient_quantity += quantity
            resulting_stock_item_id = stock_row.id
        elif resolution == DeficiencyResolution.SCRAP:
            il.quantity -= quantity
            il.deficient_quantity -= quantity
        elif resolution == DeficiencyResolution.REPAIR:
            il.deficient_quantity -= quantity
        elif resolution == DeficiencyResolution.RETURN_TO_VENDOR:
            il.quantity -= quantity
            il.deficient_quantity -= quantity
        elif resolution == DeficiencyResolution.LEAVE_AS_DEFICIENT:
            pass

    else:
        si = get_stock_item(session, stock_item_id)
        if quantity > (si.deficient_quantity or 0):
            raise ValidationError(
                "Resolved quantity exceeds current deficient_quantity",
                field="quantity",
            )
        hardware_category = si.hardware_category
        product_code = si.product_code

        if resolution == DeficiencyResolution.SEND_TO_STOCK:
            # Already on stock — for parity record a re-routing into a (possibly new) row.
            # Practically, leave on the same row but clear the deficient flag
            si.deficient_quantity -= quantity
            resulting_stock_item_id = si.id
        elif resolution == DeficiencyResolution.SCRAP:
            si.quantity -= quantity
            si.deficient_quantity -= quantity
        elif resolution == DeficiencyResolution.REPAIR:
            si.deficient_quantity -= quantity
        elif resolution == DeficiencyResolution.RETURN_TO_VENDOR:
            si.quantity -= quantity
            si.deficient_quantity -= quantity
        elif resolution == DeficiencyResolution.LEAVE_AS_DEFICIENT:
            pass

        # Keep empty stock rows for the same reason allocate does — see comment there.

    review = DeficiencyReview(
        inventory_location_id=inventory_location_id,
        stock_item_id=stock_item_id,
        resolution=resolution,
        quantity=quantity,
        reason_text=reason_text,
        rma_reference=rma_reference,
        reviewed_by=reviewed_by,
        resulting_stock_item_id=resulting_stock_item_id,
    )
    session.add(review)
    session.flush()

    detail = {
        "resolution": resolution.value,
        "quantity": quantity,
        "reasonText": reason_text,
        "rmaReference": rma_reference,
        "destockSource": destock_source.value if destock_source else None,
        "resultingStockItemId": str(resulting_stock_item_id) if resulting_stock_item_id else None,
        "hardwareCategory": hardware_category,
        "productCode": product_code,
    }
    if inventory_location_id is not None:
        _log_audit_event(
            session,
            project_id=project_for_audit,
            entity_type=AuditEntityType.INVENTORY_LOCATION,
            entity_id=inventory_location_id,
            action=AuditAction.RESOLVE_DEFICIENT,
            performed_by=reviewed_by,
            detail=detail,
        )
    if stock_item_id is not None:
        _log_audit_event(
            session,
            project_id=None,
            entity_type=AuditEntityType.STOCK_ITEM,
            entity_id=stock_item_id,
            action=AuditAction.RESOLVE_DEFICIENT,
            performed_by=reviewed_by,
            detail=detail,
        )

    return review


# ---------------------------------------------------------------------------
# Deficient items review queue (union of project + stock sources)
# ---------------------------------------------------------------------------


def get_deficient_items(
    session: Session,
    project_id: uuid.UUID | None = None,
    source: DeficientItemSource | None = None,
) -> list[dict]:
    rows: list[dict] = []

    if source is None or source == DeficientItemSource.PROJECT_INVENTORY:
        il_stmt = select(InventoryLocationModel).where(InventoryLocationModel.deficient_quantity > 0)
        if project_id is not None:
            il_stmt = il_stmt.where(InventoryLocationModel.project_id == project_id)
        il_stmt = il_stmt.order_by(
            InventoryLocationModel.project_id,
            InventoryLocationModel.hardware_category,
            InventoryLocationModel.product_code,
        )
        for il in session.scalars(il_stmt).all():
            rows.append(
                {
                    "source": DeficientItemSource.PROJECT_INVENTORY,
                    "inventory_location_id": il.id,
                    "stock_item_id": None,
                    "project_id": il.project_id,
                    "hardware_category": il.hardware_category,
                    "product_code": il.product_code,
                    "deficient_quantity": il.deficient_quantity,
                    "aisle": il.aisle,
                    "bay": il.bay,
                    "bin": il.bin,
                }
            )

    if (source is None or source == DeficientItemSource.STOCK_POOL) and project_id is None:
        si_stmt = (
            select(StockItem)
            .where(StockItem.deficient_quantity > 0)
            .order_by(StockItem.hardware_category, StockItem.product_code)
        )
        for si in session.scalars(si_stmt).all():
            rows.append(
                {
                    "source": DeficientItemSource.STOCK_POOL,
                    "inventory_location_id": None,
                    "stock_item_id": si.id,
                    "project_id": None,
                    "hardware_category": si.hardware_category,
                    "product_code": si.product_code,
                    "deficient_quantity": si.deficient_quantity,
                    "aisle": si.aisle,
                    "bay": si.bay,
                    "bin": si.bin,
                }
            )
    return rows


def get_deficiency_reviews(
    session: Session,
    inventory_location_id: uuid.UUID | None = None,
    stock_item_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
) -> list:
    from app.models.deficiency_review import DeficiencyReview

    stmt = select(DeficiencyReview).order_by(DeficiencyReview.reviewed_at.desc())
    if inventory_location_id is not None:
        stmt = stmt.where(DeficiencyReview.inventory_location_id == inventory_location_id)
    if stock_item_id is not None:
        stmt = stmt.where(DeficiencyReview.stock_item_id == stock_item_id)
    if project_id is not None:
        # Project-scoped reviews join through inventory_locations
        il_ids = select(InventoryLocationModel.id).where(InventoryLocationModel.project_id == project_id)
        stmt = stmt.where(
            or_(
                DeficiencyReview.inventory_location_id.in_(il_ids),
                # also include any review whose resulting stock item came from a project row
                # (covered by inventory_location_id above; pure stock-side reviews don't have a project)
            )
        )
    return list(session.scalars(stmt).all())


# ---------------------------------------------------------------------------
# Receive-to-stock helper used by receive flow when PO has no project_id
# ---------------------------------------------------------------------------


def receive_into_stock(
    session: Session,
    *,
    warehouse_id: uuid.UUID | None = None,
    hardware_category: str,
    product_code: str,
    quantity: int,
    deficient_quantity: int,
    aisle: str | None,
    bay: str | None,
    bin: str | None,
    received_at: datetime,
    received_by: str,
    po_number: str | None,
) -> StockItem:
    """Receive vendor PO directly into the stock pool. Used when PO has no project_id."""
    if quantity < 1:
        raise ValidationError("quantity must be >= 1", field="quantity")
    if deficient_quantity < 0 or deficient_quantity > quantity:
        raise ValidationError(
            "deficient_quantity must be 0 <= deficient_quantity <= quantity",
            field="deficient_quantity",
        )

    if warehouse_id is None:
        from app.repositories import warehouse_admin_repository

        warehouse_id = warehouse_admin_repository.get_primary_warehouse_id(session)

    stock_row = _find_or_create_stock_row(
        session,
        warehouse_id=warehouse_id,
        hardware_category=hardware_category,
        product_code=product_code,
        aisle=aisle,
        bay=bay,
        bin=bin,
        received_at=received_at,
    )
    stock_row.quantity += quantity
    stock_row.deficient_quantity += deficient_quantity

    _log_audit_event(
        session,
        project_id=None,
        entity_type=AuditEntityType.STOCK_ITEM,
        entity_id=stock_row.id,
        action=AuditAction.RECEIVE,
        performed_by=received_by,
        detail={
            "quantity": quantity,
            "deficientQuantity": deficient_quantity,
            "hardwareCategory": hardware_category,
            "productCode": product_code,
            "poNumber": po_number,
            "location": {"aisle": aisle, "bay": bay, "bin": bin},
        },
    )
    return stock_row
