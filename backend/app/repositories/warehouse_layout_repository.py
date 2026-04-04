"""Repository for warehouse layout CRUD and utilization queries."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.errors import NotFoundError, ValidationError
from app.models.inventory import InventoryLocation as InventoryLocationModel
from app.models.warehouse_layout import WarehouseAisle, WarehouseBay, WarehouseBin

# ---------------------------------------------------------------------------
# Aisle CRUD
# ---------------------------------------------------------------------------


def get_aisles(session: Session, active_only: bool = True) -> list[WarehouseAisle]:
    stmt = select(WarehouseAisle).options(selectinload(WarehouseAisle.bays).selectinload(WarehouseBay.bins))
    if active_only:
        stmt = stmt.where(WarehouseAisle.is_active.is_(True))
    stmt = stmt.order_by(WarehouseAisle.x_position, WarehouseAisle.name)
    return list(session.scalars(stmt).unique().all())


def create_aisle(session: Session, name: str, label: str | None, x: int, y: int, w: int, h: int) -> WarehouseAisle:
    if not name or len(name) > 20:
        raise ValidationError("Aisle name must be 1-20 characters", field="name")
    aisle = WarehouseAisle(name=name, label=label, x_position=x, y_position=y, width=w, height=h)
    session.add(aisle)
    session.flush()
    return aisle


def update_aisle(
    session: Session,
    aisle_id: uuid.UUID,
    name: str | None,
    label: str | None,
    x: int | None,
    y: int | None,
    w: int | None,
    h: int | None,
    is_active: bool | None,
) -> WarehouseAisle:
    aisle = session.get(WarehouseAisle, aisle_id)
    if aisle is None:
        raise NotFoundError(f"Aisle {aisle_id} not found")
    if name is not None:
        aisle.name = name
    if label is not None:
        aisle.label = label
    if x is not None:
        aisle.x_position = x
    if y is not None:
        aisle.y_position = y
    if w is not None:
        aisle.width = w
    if h is not None:
        aisle.height = h
    if is_active is not None:
        aisle.is_active = is_active
    return aisle


# ---------------------------------------------------------------------------
# Bay CRUD
# ---------------------------------------------------------------------------


def get_bays(session: Session, aisle_id: uuid.UUID) -> list[WarehouseBay]:
    stmt = (
        select(WarehouseBay)
        .options(selectinload(WarehouseBay.bins))
        .where(WarehouseBay.aisle_id == aisle_id, WarehouseBay.is_active.is_(True))
        .order_by(WarehouseBay.row_position, WarehouseBay.col_position, WarehouseBay.name)
    )
    return list(session.scalars(stmt).unique().all())


def create_bay(
    session: Session,
    aisle_id: uuid.UUID,
    name: str,
    row_pos: int,
    col_pos: int,
) -> WarehouseBay:
    if not name or len(name) > 20:
        raise ValidationError("Bay name must be 1-20 characters", field="name")
    bay = WarehouseBay(aisle_id=aisle_id, name=name, row_position=row_pos, col_position=col_pos)
    session.add(bay)
    session.flush()
    return bay


def update_bay(
    session: Session,
    bay_id: uuid.UUID,
    name: str | None,
    row_pos: int | None,
    col_pos: int | None,
    is_active: bool | None,
) -> WarehouseBay:
    bay = session.get(WarehouseBay, bay_id)
    if bay is None:
        raise NotFoundError(f"Bay {bay_id} not found")
    if name is not None:
        bay.name = name
    if row_pos is not None:
        bay.row_position = row_pos
    if col_pos is not None:
        bay.col_position = col_pos
    if is_active is not None:
        bay.is_active = is_active
    return bay


# ---------------------------------------------------------------------------
# Bin CRUD
# ---------------------------------------------------------------------------


def get_bins(session: Session, bay_id: uuid.UUID) -> list[WarehouseBin]:
    stmt = (
        select(WarehouseBin)
        .where(WarehouseBin.bay_id == bay_id, WarehouseBin.is_active.is_(True))
        .order_by(WarehouseBin.row_position, WarehouseBin.col_position, WarehouseBin.name)
    )
    return list(session.scalars(stmt).all())


def create_bin(
    session: Session,
    bay_id: uuid.UUID,
    name: str,
    row_pos: int,
    col_pos: int,
    capacity: int | None,
) -> WarehouseBin:
    if not name or len(name) > 20:
        raise ValidationError("Bin name must be 1-20 characters", field="name")
    wbin = WarehouseBin(bay_id=bay_id, name=name, row_position=row_pos, col_position=col_pos, capacity=capacity)
    session.add(wbin)
    session.flush()
    return wbin


def update_bin(
    session: Session,
    bin_id: uuid.UUID,
    name: str | None,
    row_pos: int | None,
    col_pos: int | None,
    capacity: int | None,
    is_active: bool | None,
) -> WarehouseBin:
    wbin = session.get(WarehouseBin, bin_id)
    if wbin is None:
        raise NotFoundError(f"Bin {bin_id} not found")
    if name is not None:
        wbin.name = name
    if row_pos is not None:
        wbin.row_position = row_pos
    if col_pos is not None:
        wbin.col_position = col_pos
    if capacity is not None:
        wbin.capacity = capacity
    if is_active is not None:
        wbin.is_active = is_active
    return wbin


# ---------------------------------------------------------------------------
# Utilization queries (for viewer)
# ---------------------------------------------------------------------------


def get_aisle_utilization(session: Session) -> list[dict]:
    """Get aisles with aggregated inventory stats."""
    aisles = get_aisles(session, active_only=True)
    result = []
    for aisle in aisles:
        # Sum inventory at this aisle
        inv_stats = session.execute(
            select(
                func.coalesce(func.sum(InventoryLocationModel.quantity), 0),
                func.count(),
            ).where(InventoryLocationModel.aisle == aisle.name, InventoryLocationModel.quantity > 0)
        ).one()
        total_capacity = 0
        for bay in aisle.bays:
            for wbin in bay.bins:
                if wbin.capacity and wbin.is_active:
                    total_capacity += wbin.capacity
        result.append(
            {
                "aisle": aisle,
                "total_quantity": int(inv_stats[0]),
                "item_count": int(inv_stats[1]),
                "total_capacity": total_capacity,
            }
        )
    return result


def suggest_put_away(
    session: Session,
    product_code: str,
    hardware_category: str,
    quantity: int,
) -> list[dict]:
    """Suggest bins for put-away based on co-location and capacity."""
    suggestions = []

    # 1. Find bins that already have the same product code
    colocated = session.execute(
        select(
            InventoryLocationModel.aisle,
            InventoryLocationModel.bay,
            InventoryLocationModel.bin,
            func.sum(InventoryLocationModel.quantity).label("current_qty"),
        )
        .where(
            InventoryLocationModel.product_code == product_code,
            InventoryLocationModel.aisle.is_not(None),
            InventoryLocationModel.quantity > 0,
        )
        .group_by(InventoryLocationModel.aisle, InventoryLocationModel.bay, InventoryLocationModel.bin)
        .order_by(func.sum(InventoryLocationModel.quantity).desc())
        .limit(3)
    ).all()

    for row in colocated:
        # Look up bin capacity
        bin_capacity = session.scalar(
            select(WarehouseBin.capacity)
            .join(WarehouseBay, WarehouseBin.bay_id == WarehouseBay.id)
            .join(WarehouseAisle, WarehouseBay.aisle_id == WarehouseAisle.id)
            .where(
                WarehouseAisle.name == row[0],
                WarehouseBay.name == row[1],
                WarehouseBin.name == row[2],
                WarehouseBin.is_active.is_(True),
            )
        )
        suggestions.append(
            {
                "aisle": row[0],
                "bay": row[1],
                "bin": row[2],
                "reason": "co-located",
                "current_quantity": int(row[3]),
                "capacity": bin_capacity,
            }
        )

    if len(suggestions) >= 3:
        return suggestions[:3]

    # 2. Find bins with remaining capacity
    bins_with_capacity = session.execute(
        select(WarehouseAisle.name, WarehouseBay.name, WarehouseBin.name, WarehouseBin.capacity)
        .join(WarehouseBay, WarehouseBin.bay_id == WarehouseBay.id)
        .join(WarehouseAisle, WarehouseBay.aisle_id == WarehouseAisle.id)
        .where(
            WarehouseBin.is_active.is_(True),
            WarehouseBin.capacity.is_not(None),
            WarehouseBin.capacity > 0,
        )
        .order_by(WarehouseBin.capacity.desc())
        .limit(10)
    ).all()

    existing_locations = {(s["aisle"], s["bay"], s["bin"]) for s in suggestions}
    for row in bins_with_capacity:
        if len(suggestions) >= 3:
            break
        loc = (row[0], row[1], row[2])
        if loc in existing_locations:
            continue
        # Check current occupancy
        current = (
            session.scalar(
                select(func.coalesce(func.sum(InventoryLocationModel.quantity), 0)).where(
                    InventoryLocationModel.aisle == row[0],
                    InventoryLocationModel.bay == row[1],
                    InventoryLocationModel.bin == row[2],
                )
            )
            or 0
        )
        remaining = row[3] - current
        if remaining >= quantity:
            suggestions.append(
                {
                    "aisle": row[0],
                    "bay": row[1],
                    "bin": row[2],
                    "reason": "capacity-available",
                    "current_quantity": int(current),
                    "capacity": row[3],
                }
            )

    return suggestions[:3]
