"""Repository for warehouse inventory and opening item data access."""

import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.inventory import InventoryLocation as InventoryLocationModel
from app.models.opening_item import OpeningItem as OpeningItemModel
from app.models.purchase_order import PurchaseOrder as POModel, POLineItem as POLineItemModel
from app.errors import NotFoundError


def get_inventory_hierarchy(session: Session, project_id: uuid.UUID) -> list[dict]:
    """
    Query all InventoryLocation rows WHERE project_id.
    Group by hardware_category, then product_code.
    At each level, sum quantities.
    Sort categories and product codes alphabetically.

    Return structure: list of dicts, each with:
    {
        "hardware_category": str,
        "product_codes": [
            {
                "product_code": str,
                "items": [InventoryLocationModel, ...],
                "total_quantity": int
            },
            ...
        ],
        "total_quantity": int
    }
    """
    stmt = (
        select(InventoryLocationModel)
        .where(InventoryLocationModel.project_id == project_id)
        .order_by(
            InventoryLocationModel.hardware_category,
            InventoryLocationModel.product_code,
        )
    )
    rows = list(session.scalars(stmt).all())

    # Group by hardware_category -> product_code
    cat_map: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for il in rows:
        cat_map[il.hardware_category][il.product_code].append(il)

    result = []
    for category in sorted(cat_map.keys()):
        product_codes_map = cat_map[category]
        product_code_nodes = []
        category_total = 0

        for pc in sorted(product_codes_map.keys()):
            items = product_codes_map[pc]
            pc_total = sum(item.quantity for item in items)
            category_total += pc_total
            product_code_nodes.append({
                "product_code": pc,
                "items": items,
                "total_quantity": pc_total,
            })

        result.append({
            "hardware_category": category,
            "product_codes": product_code_nodes,
            "total_quantity": category_total,
        })

    return result


def get_inventory_items(
    session: Session,
    project_id: uuid.UUID,
    category: str,
    product_code: str,
) -> list[dict]:
    """
    Query InventoryLocation rows matching (project_id, category, product_code).
    JOIN to POLineItem (via po_line_item_id) then PurchaseOrder (via po_id) to get po_number and classification.

    Return list of dicts with keys: inventory_location, po_number, classification
    """
    stmt = (
        select(InventoryLocationModel, POLineItemModel.classification, POModel.po_number)
        .join(POLineItemModel, InventoryLocationModel.po_line_item_id == POLineItemModel.id)
        .join(POModel, POLineItemModel.po_id == POModel.id)
        .where(
            InventoryLocationModel.project_id == project_id,
            InventoryLocationModel.hardware_category == category,
            InventoryLocationModel.product_code == product_code,
        )
    )
    rows = session.execute(stmt).all()

    return [
        {
            "inventory_location": row[0],
            "classification": row[1],
            "po_number": row[2],
        }
        for row in rows
    ]


def get_opening_items(session: Session, project_id: uuid.UUID) -> list[OpeningItemModel]:
    """
    Query all OpeningItem rows for project_id.
    Eagerly load installed_hardware relationship (OpeningItemHardware).
    Sort by opening_number ASC.
    """
    stmt = (
        select(OpeningItemModel)
        .options(selectinload(OpeningItemModel.installed_hardware))
        .where(OpeningItemModel.project_id == project_id)
        .order_by(OpeningItemModel.opening_number.asc())
    )
    return list(session.scalars(stmt).unique().all())


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
