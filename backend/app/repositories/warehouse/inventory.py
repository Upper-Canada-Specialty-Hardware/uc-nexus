"""Project inventory + opening item reads and admin quantity corrections."""

import uuid
from collections import defaultdict
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.errors import NotFoundError, ValidationError
from app.models.enums import AuditAction, AuditEntityType
from app.models.hardware import HardwareItem as HardwareItemModel
from app.models.inventory import InventoryLocation as InventoryLocationModel
from app.models.opening_item import OpeningItem as OpeningItemModel
from app.models.project import Opening as OpeningModel
from app.models.project import Project as ProjectModel
from app.models.purchase_order import POLineItem as POLineItemModel
from app.models.purchase_order import PurchaseOrder as POModel
from app.models.vendor import Vendor as VendorModel

from .audit import _log_audit_event
from .locations import _normalize_and_validate_location_fields


def get_inventory_hierarchy(
    session: Session, project_id: uuid.UUID | None = None, warehouse_id: uuid.UUID | None = None
) -> list[dict]:
    """
    Query all InventoryLocation rows joined with POLineItem for unit_cost,
    optionally filtered by project_id.
    Group by hardware_category, then product_code.
    At each level, sum quantities and compute total_value (unit_cost * quantity).
    Sort categories and product codes alphabetically.

    Return structure: list of dicts, each with:
    {
        "hardware_category": str,
        "product_codes": [
            {
                "product_code": str,
                "items": [InventoryLocationModel, ...],
                "total_quantity": int,
                "total_value": float
            },
            ...
        ],
        "total_quantity": int,
        "total_value": float
    }
    """
    stmt = select(InventoryLocationModel, POLineItemModel.unit_cost).outerjoin(
        POLineItemModel, InventoryLocationModel.po_line_item_id == POLineItemModel.id
    )
    # Hide rows fully emptied by destock/allocation (quantity = 0). They are kept in the DB
    # for FK integrity (origin of stock allocations) but should not clutter the inventory view.
    stmt = stmt.where(InventoryLocationModel.quantity > 0)
    if project_id is not None:
        stmt = stmt.where(InventoryLocationModel.project_id == project_id)
    if warehouse_id is not None:
        stmt = stmt.where(InventoryLocationModel.warehouse_id == warehouse_id)
    stmt = stmt.order_by(
        InventoryLocationModel.hardware_category,
        InventoryLocationModel.product_code,
    )
    rows = list(session.execute(stmt).all())

    # Group by hardware_category -> product_code, storing (il, unit_cost) pairs
    cat_map: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for il, unit_cost in rows:
        cat_map[il.hardware_category][il.product_code].append((il, unit_cost or 0))

    result = []
    for category in sorted(cat_map.keys()):
        product_codes_map = cat_map[category]
        product_code_nodes = []
        category_total = 0
        category_total_value = 0.0

        category_available = 0
        for pc in sorted(product_codes_map.keys()):
            items_with_cost = product_codes_map[pc]
            pc_total = sum(il.quantity for il, _ in items_with_cost)
            # Issue #229: net available = quantity - deficient_quantity, the same basis the
            # approve gate (check_inventory_sufficiency) uses - so pre-checks can agree with it.
            pc_available = sum(il.quantity - il.deficient_quantity for il, _ in items_with_cost)
            pc_total_value = sum(float(uc) * il.quantity for il, uc in items_with_cost)
            category_total += pc_total
            category_available += pc_available
            category_total_value += pc_total_value
            product_code_nodes.append(
                {
                    "product_code": pc,
                    "items": [il for il, _ in items_with_cost],
                    "total_quantity": pc_total,
                    "total_available_quantity": pc_available,
                    "total_value": pc_total_value,
                }
            )

        result.append(
            {
                "hardware_category": category,
                "product_codes": product_code_nodes,
                "total_quantity": category_total,
                "total_available_quantity": category_available,
                "total_value": category_total_value,
            }
        )

    return result


def get_inventory_items(
    session: Session,
    project_id: uuid.UUID | None,
    category: str,
    product_code: str,
) -> list[dict]:
    """
    Query InventoryLocation rows matching (optional project_id, category, product_code).
    JOIN to POLineItem (via po_line_item_id) then PurchaseOrder (via po_id) to get po_number and classification.

    Return list of dicts with keys: inventory_location, po_number, classification
    """
    stmt = (
        select(InventoryLocationModel, POLineItemModel.classification, POModel.po_number, POLineItemModel.unit_cost)
        .outerjoin(POLineItemModel, InventoryLocationModel.po_line_item_id == POLineItemModel.id)
        .outerjoin(POModel, POLineItemModel.po_id == POModel.id)
        .where(
            InventoryLocationModel.hardware_category == category,
            InventoryLocationModel.product_code == product_code,
            # Hide rows fully emptied by destock/allocation (kept in DB for FK integrity).
            InventoryLocationModel.quantity > 0,
        )
    )
    if project_id is not None:
        stmt = stmt.where(InventoryLocationModel.project_id == project_id)
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


def get_unlocated_inventory(session: Session, project_id: uuid.UUID | None = None) -> list[dict]:
    """
    Query InventoryLocation rows where aisle, row, and bay are all NULL and quantity > 0.
    Joins to POLineItem for unit_cost/classification and PurchaseOrder for po_number.
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


def get_inventory_by_vendor(session: Session, project_id: uuid.UUID | None = None) -> list[dict]:
    """Group inventory by vendor name (via PO.vendor_id → Vendor), then product_code."""
    stmt = (
        select(InventoryLocationModel, POLineItemModel.unit_cost, VendorModel.name)
        .outerjoin(POLineItemModel, InventoryLocationModel.po_line_item_id == POLineItemModel.id)
        .outerjoin(POModel, POLineItemModel.po_id == POModel.id)
        .outerjoin(VendorModel, POModel.vendor_id == VendorModel.id)
        # Hide rows fully emptied by destock/allocation (kept in DB for FK integrity).
        .where(InventoryLocationModel.quantity > 0)
    )
    if project_id is not None:
        stmt = stmt.where(InventoryLocationModel.project_id == project_id)
    stmt = stmt.order_by(VendorModel.name, InventoryLocationModel.product_code)
    rows = list(session.execute(stmt).all())

    vendor_map: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for il, unit_cost, vendor_name in rows:
        vname = vendor_name or "No Vendor"
        # Stock-allocated rows (stock_item origin) have no PO unit_cost; coerce to 0 like the
        # category hierarchy does, otherwise the float() in the value sum below blows up.
        vendor_map[vname][il.product_code].append((il, unit_cost or 0))

    result = []
    for vendor in sorted(vendor_map.keys()):
        pc_map = vendor_map[vendor]
        pc_nodes = []
        vendor_total = 0
        vendor_value = 0.0
        for pc in sorted(pc_map.keys()):
            items_with_cost = pc_map[pc]
            pc_total = sum(il.quantity for il, _ in items_with_cost)
            pc_value = sum(float(uc) * il.quantity for il, uc in items_with_cost)
            vendor_total += pc_total
            vendor_value += pc_value
            pc_nodes.append(
                {
                    "product_code": pc,
                    "items": [il for il, _ in items_with_cost],
                    "total_quantity": pc_total,
                    "total_value": pc_value,
                }
            )
        result.append(
            {
                "vendor_name": vendor,
                "product_codes": pc_nodes,
                "total_quantity": vendor_total,
                "total_value": vendor_value,
            }
        )
    return result


def get_opening_items(session: Session, project_id: uuid.UUID | None = None) -> list[OpeningItemModel]:
    """
    Query all OpeningItem rows, optionally filtered by project_id.
    Eagerly load installed_hardware relationship (OpeningItemHardware).
    Sort by opening_number ASC.
    """
    stmt = (
        select(OpeningItemModel)
        .options(selectinload(OpeningItemModel.installed_hardware))
        .order_by(OpeningItemModel.opening_number.asc())
    )
    if project_id is not None:
        stmt = stmt.where(OpeningItemModel.project_id == project_id)
    return list(session.scalars(stmt).unique().all())


def get_opening_leaf_counts(session: Session, project_id: uuid.UUID | None = None) -> dict[str, int | None]:
    """Map opening_number -> Opening.leaf_count (#311). This is the "N of M leaves shipped" denominator
    M; a single query keeps the openingItems list resolver free of N+1s. project_id scopes to one
    project; omit it for the global openingItems view (opening_number then keys across projects, which
    is acceptable - the global view is not project-disambiguated)."""
    stmt = select(OpeningModel.opening_number, OpeningModel.leaf_count)
    if project_id is not None:
        stmt = stmt.where(OpeningModel.project_id == project_id)
    rows = session.execute(stmt).all()
    return {opening_number: leaf_count for opening_number, leaf_count in rows}


# Furthest-along ordering when a leaf has more than one OpeningItem (e.g. after a correction): the
# most-advanced state wins. NOT_ASSEMBLED is the floor - a leaf the schedule expects but that has no
# OpeningItem at all.
_LEAF_STATUS_RANK = {"NOT_ASSEMBLED": 0, "IN_INVENTORY": 1, "SHIP_READY": 2, "SHIPPED_OUT": 3}


def get_opening_leaf_status(session: Session, project_id: uuid.UUID | None = None) -> list[dict]:
    """Per-opening door-leaf rollup (#313). One row per PAIR opening (leaf_count >= 2 - a single leaf
    is just its own row, matching the phase-5 rollup convention); each row lists every leaf
    1..leaf_count with its status. Status comes from OpeningItems (one grouped query, no N+1); a leaf
    with no OpeningItem is NOT_ASSEMBLED. project_id scopes to one project (shipping); omitting it
    spans all projects (global shop-assembly), so each row carries project identity to disambiguate
    opening numbers that collide across projects."""
    # Pairs only. leaf_count is the denominator M; a NULL leaf_count (legacy) fails `>= 2` and drops.
    op_stmt = select(OpeningModel.project_id, OpeningModel.opening_number, OpeningModel.leaf_count).where(
        OpeningModel.leaf_count >= 2
    )
    if project_id is not None:
        op_stmt = op_stmt.where(OpeningModel.project_id == project_id)
    openings = session.execute(op_stmt).all()
    if not openings:
        return []

    # Furthest-along OpeningItem state per (project_id, opening_number, leaf). Scope to the pair
    # openings found above so the global path (project_id=None) never scans the whole opening_items
    # table - only rows for openings we actually roll up. `openings` is non-empty here (guarded above);
    # the (project_id, opening_number, leaf) key lookup below filters the cross-product precisely.
    pair_project_ids = {pid for pid, _, _ in openings}
    pair_opening_numbers = {opening_number for _, opening_number, _ in openings}
    oi_stmt = select(
        OpeningItemModel.project_id,
        OpeningItemModel.opening_number,
        OpeningItemModel.leaf,
        OpeningItemModel.state,
    ).where(
        OpeningItemModel.project_id.in_(pair_project_ids),
        OpeningItemModel.opening_number.in_(pair_opening_numbers),
    )
    leaf_state: dict[tuple[uuid.UUID, str, int], str] = {}
    for pid, opening_number, leaf, state in session.execute(oi_stmt).all():
        if leaf is None:
            continue
        state_value = state.value if hasattr(state, "value") else str(state)
        key = (pid, opening_number, leaf)
        current = leaf_state.get(key)
        if current is None or _LEAF_STATUS_RANK[state_value] > _LEAF_STATUS_RANK[current]:
            leaf_state[key] = state_value

    project_names = {
        pid: (description or code)
        for pid, description, code in session.execute(
            select(ProjectModel.id, ProjectModel.description, ProjectModel.project_id).where(
                ProjectModel.id.in_({pid for pid, _, _ in openings})
            )
        ).all()
    }

    rows = [
        {
            "project_id": pid,
            "project_name": project_names.get(pid, ""),
            "opening_number": opening_number,
            "leaf_count": leaf_count,
            "leaves": [
                {"leaf": n, "status": leaf_state.get((pid, opening_number, n), "NOT_ASSEMBLED")}
                for n in range(1, leaf_count + 1)
            ],
        }
        for pid, opening_number, leaf_count in openings
    ]
    rows.sort(key=lambda r: (r["project_name"], r["opening_number"]))
    return rows


def get_opening_item_details(session: Session, oi_id: uuid.UUID) -> OpeningItemModel:
    """
    Single OpeningItem by id, eagerly load installed_hardware.
    Raise NotFoundError if not found.
    """
    stmt = (
        select(OpeningItemModel)
        .options(selectinload(OpeningItemModel.installed_hardware))
        .where(OpeningItemModel.id == oi_id)
    )
    oi = session.scalars(stmt).unique().first()
    if oi is None:
        raise NotFoundError(f"Opening item {oi_id} not found")
    return oi


def adjust_inventory_quantity(
    session: Session, inv_id: uuid.UUID, adjustment: int, reason: str, *, performed_by: str
) -> InventoryLocationModel:
    """Adjust the quantity of an InventoryLocation by a positive or negative amount.

    `performed_by` is keyword-only and required (#427). This function used to take no actor at all
    and hardcode "Admin/Manager" on its audit row, so every quantity adjustment in the system was
    filed under an admin no matter who made it - and, worse, the resolver had no way to pass the
    truth through even once somebody noticed. Requiring it means a new caller has to answer the
    question rather than inherit a wrong answer."""
    il = session.get(InventoryLocationModel, inv_id)
    if il is None:
        raise NotFoundError(f"Inventory location {inv_id} not found")

    if not reason or len(reason) > 500:
        raise ValidationError("reason must be 1-500 characters", field="reason")

    new_quantity = il.quantity + adjustment
    if new_quantity < 0:
        raise ValidationError("Adjustment would result in negative quantity", field="adjustment")

    old_quantity = il.quantity
    il.quantity = new_quantity

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
            "adjustment": adjustment,
            "reason": reason,
        },
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
                    po_line_item_id=il.po_line_item_id,
                    receive_line_item_id=il.receive_line_item_id,
                    stock_item_id=il.stock_item_id,
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
                "location": {"aisle": new_il.aisle, "row": new_il.row, "bay": new_il.bay},
                "reason": reason,
            },
        )

    return il


def get_scheduled_pairs(session: Session, project_id: uuid.UUID) -> set[tuple[str, str]]:
    """Every (hardware_category, product_code) the project's imported schedule knows about.

    One grouped query, no relationship walking - this is called once per hierarchy request and its
    result is checked in Python against nodes already in memory, so it never becomes an N+1 (see the
    GraphQL/SQLAlchemy performance rules in CLAUDE.md).
    """
    rows = session.execute(
        select(HardwareItemModel.hardware_category, HardwareItemModel.product_code)
        .where(HardwareItemModel.project_id == project_id)
        .distinct()
    ).all()
    return {(cat, code) for cat, code in rows}
