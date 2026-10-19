"""Where a project's hardware sits on the racks (#1730).

The outbound supervisor's ask: show the bin locations of what a request wants while it is being
raised and accepted, instead of looking each one up in a spreadsheet after the email arrives. The pick
sheet already lists rack rows for the picker; this is the same knowledge, earlier, per product.

Counted net of condemned units, and only rows that have been put away - a row with no aisle has no
place anybody can walk to yet.
"""

import uuid
from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.inventory import InventoryLocation
from app.models.warehouse import Warehouse


def project_rack_locations(session: Session, project_id: uuid.UUID) -> list[dict]:
    """Each of the project's products with the racks holding it, in one grouped read.

    Returns `[{hardware_category, product_code, locations: [{warehouse_code, aisle, row, bay, quantity}]}]`,
    products in category then product order and each one's racks in warehouse then rack order.
    """
    usable = func.sum(InventoryLocation.quantity - InventoryLocation.deficient_quantity)
    rows = session.execute(
        select(
            InventoryLocation.hardware_category,
            InventoryLocation.product_code,
            Warehouse.code,
            InventoryLocation.aisle,
            InventoryLocation.row,
            InventoryLocation.bay,
            usable.label("quantity"),
        )
        .join(Warehouse, Warehouse.id == InventoryLocation.warehouse_id)
        .where(InventoryLocation.project_id == project_id, InventoryLocation.aisle.is_not(None))
        .group_by(
            InventoryLocation.hardware_category,
            InventoryLocation.product_code,
            Warehouse.code,
            InventoryLocation.aisle,
            InventoryLocation.row,
            InventoryLocation.bay,
        )
        .having(usable > 0)
        .order_by(
            InventoryLocation.hardware_category,
            InventoryLocation.product_code,
            Warehouse.code,
            InventoryLocation.aisle,
            InventoryLocation.row,
            InventoryLocation.bay,
        )
    ).all()

    by_product: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        by_product[(r.hardware_category, r.product_code)].append(
            {"warehouse_code": r.code, "aisle": r.aisle, "row": r.row, "bay": r.bay, "quantity": int(r.quantity)}
        )
    return [
        {"hardware_category": category, "product_code": product, "locations": locations}
        for (category, product), locations in by_product.items()
    ]
