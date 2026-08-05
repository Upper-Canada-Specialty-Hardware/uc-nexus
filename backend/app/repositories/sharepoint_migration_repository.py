"""One-time import of the legacy SharePoint inventory list into Nexus inventory.

Every entry the wizard sends has already been resolved by a human: its warehouse and aisle/row/bay
came out of the location-mapping step, its project out of the project-mapping step, and rows nobody
could place were excluded client-side. So this module validates and writes; it does not guess.

Both destinations go through the stock pool first, because that is the only origin an
`InventoryLocation` can have that is not a purchase order. `ck_inventory_locations_has_origin`
requires either (po_line_item_id AND receive_line_item_id) or stock_item_id or
shipment_return_item_id, and migrated hardware has no PO in Nexus - it was bought years ago in a
system being retired. Routing through `receive_into_stock` -> `allocate_stock_to_project` reuses the
same path the warehouse already uses to move shelf stock onto a project, which means the audit trail
and the drained-stock-row bookkeeping come for free.
"""

import logging
import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import NotFoundError, ValidationError
from app.models.inventory import InventoryLocation
from app.models.inventory_item_type import CustomInventoryItem
from app.models.project import Project as ProjectModel
from app.models.stock_item import StockItem
from app.models.warehouse import Warehouse
from app.repositories import custom_items_repository
from app.repositories import stock as stock_repository

logger = logging.getLogger(__name__)

DESTINATION_PROJECT = "PROJECT"
DESTINATION_STOCK = "STOCK"


def migrate_catalog_items(session: Session, catalog_items: list[dict]) -> dict:
    """Catalog the non-schedule products the migration is bringing across (#454).

    SharePoint's `Inventory Type` column is the same distinction `InventoryItemType` draws - Frame,
    Specialties, Consumable - and the descriptive columns beside it (Part Description, Finish,
    Rating, Mounting, sizes) are exactly what a type's attributes hold. Without this the quantities
    arrive and every word describing them is lost with the list.

    Each item: type_id, product_code, optional description, and values as [{attribute_name, value}].
    Attributes are addressed by NAME and created on the type if absent, because the seeded types
    start with none and the source's columns are not knowable in advance.

    Idempotent per product code: an item already catalogued under that type is left exactly as it
    is rather than raising, so re-running after a partial failure - or migrating a code the
    warehouse has already entered by hand - is not an error.
    """
    if not catalog_items:
        return {"items_created": 0, "items_skipped": 0, "attributes_created": 0}

    created = skipped = attributes_created = 0
    # attribute id by (type_id, lowercased name), filled lazily so each type is read once.
    attribute_ids: dict[tuple[uuid.UUID, str], uuid.UUID] = {}
    types_loaded: set[uuid.UUID] = set()

    for raw in catalog_items:
        type_id = raw["type_id"]
        product_code = (raw.get("product_code") or "").strip()
        if not product_code:
            continue

        if type_id not in types_loaded:
            item_type = custom_items_repository.get_item_type(session, type_id)
            for attribute in item_type.attributes:
                attribute_ids[(type_id, attribute.name.strip().lower())] = attribute.id
            types_loaded.add(type_id)

        if _catalog_item_exists(session, type_id, product_code):
            skipped += 1
            continue

        values = []
        for value in raw.get("values") or []:
            name = (value.get("attribute_name") or "").strip()
            text = (value.get("value") or "").strip()
            if not name or not text:
                continue
            key = (type_id, name.lower())
            if key not in attribute_ids:
                attribute = custom_items_repository.create_attribute(
                    session, type_id=type_id, name=name, sort_order=len(attribute_ids)
                )
                attribute_ids[key] = attribute.id
                attributes_created += 1
            values.append({"attribute_id": attribute_ids[key], "value": text})

        custom_items_repository.create_item(
            session,
            type_id=type_id,
            product_code=product_code,
            description=(raw.get("description") or "").strip() or None,
            values=values,
        )
        created += 1

    logger.info(
        "SharePoint migration catalogued %d items (%d already present, %d attributes created)",
        created,
        skipped,
        attributes_created,
    )
    return {"items_created": created, "items_skipped": skipped, "attributes_created": attributes_created}


def _catalog_item_exists(session: Session, type_id: uuid.UUID, product_code: str) -> bool:
    return (
        session.scalars(
            select(CustomInventoryItem.id).where(
                CustomInventoryItem.type_id == type_id,
                func.lower(CustomInventoryItem.product_code) == product_code.lower(),
            )
        ).first()
        is not None
    )


def migrate_inventory(session: Session, entries: list[dict], performed_by: str) -> dict:
    """Write every resolved entry, in one transaction.

    Each entry: destination, warehouse_id, hardware_category, product_code, quantity, optional
    aisle/row/bay, and project_id when destination is PROJECT.

    All-or-nothing on purpose. A partial migration is worse than none: the wizard has no resume
    state, so re-running after a half-failure would double the rows that did land.
    """
    if not entries:
        raise ValidationError("No inventory entries to migrate", field="entries")

    # Validate the whole batch before writing anything, so a bad row 2000 does not leave the caller
    # guessing which of the first 1999 went in.
    _validate_entries(session, entries)

    now = datetime.utcnow()
    # Stock rows, not stock ENTRIES: receive_into_stock merges into an existing row for the same
    # (warehouse, category, code, aisle, row, bay), so two SharePoint rows for one part on one shelf
    # are one StockItem. Counting entries would report a number the warehouse view cannot reproduce.
    stock_row_ids: set[uuid.UUID] = set()
    project_locations = 0
    total_units = 0

    for index, entry in enumerate(entries):
        # Written stripped, not just validated stripped: a trailing space makes a distinct identity
        # that can never match a schedule pair, and this is a public admin mutation rather than
        # something only the wizard calls.
        category = entry["hardware_category"].strip()
        code = entry["product_code"].strip()
        quantity = entry["quantity"]
        warehouse_id = entry["warehouse_id"]
        aisle = _clean_location(entry.get("aisle"))
        row = _clean_location(entry.get("row"))
        bay = _clean_location(entry.get("bay"))

        try:
            stock_row = stock_repository.receive_into_stock(
                session,
                warehouse_id=warehouse_id,
                hardware_category=category,
                product_code=code,
                quantity=quantity,
                deficient_quantity=0,
                aisle=aisle,
                row=row,
                bay=bay,
                received_at=now,
                received_by=performed_by,
                po_number=None,
            )

            if entry["destination"] == DESTINATION_PROJECT:
                stock_repository.allocate_stock_to_project(
                    session,
                    stock_item_id=stock_row.id,
                    project_id=entry["project_id"],
                    target_hardware_category=category,
                    target_product_code=code,
                    quantity=quantity,
                    target_aisle=aisle,
                    target_row=row,
                    target_bay=bay,
                    performed_by=performed_by,
                )
                project_locations += 1
            else:
                stock_row_ids.add(stock_row.id)

            total_units += quantity
        except (ValidationError, NotFoundError) as e:
            # Name the row. Without this the wizard shows "aisle must be 1-20 characters" against a
            # 2000-row batch and the user has nothing to act on.
            raise ValidationError(
                f"Entry {index + 1} ({category} / {code}): {e.message}",
                field=e.field,
            ) from e

    logger.info(
        "SharePoint migration by %s: %d stock rows, %d project locations, %d units",
        performed_by,
        len(stock_row_ids),
        project_locations,
        total_units,
    )
    return {
        "stock_items": len(stock_row_ids),
        "project_locations": project_locations,
        "total_units": total_units,
    }


# stock_items / inventory_locations store aisle, row and bay as String(20).
_MAX_LOCATION_PART = 20


def _clean_location(value: str | None) -> str | None:
    """Trim a location part, treating blank as absent."""
    cleaned = (value or "").strip()
    return cleaned or None


def _validate_entries(session: Session, entries: list[dict]) -> None:
    """Shape, quantity, and referential checks for the whole batch, before any write."""
    warehouse_ids: set[uuid.UUID] = set()
    project_ids: set[uuid.UUID] = set()

    for index, entry in enumerate(entries):
        label = f"Entry {index + 1}"
        destination = entry.get("destination")
        if destination not in (DESTINATION_PROJECT, DESTINATION_STOCK):
            raise ValidationError(f"{label}: destination must be PROJECT or STOCK", field="destination")

        if not (entry.get("hardware_category") or "").strip():
            raise ValidationError(f"{label}: hardware_category is required", field="hardware_category")
        if not (entry.get("product_code") or "").strip():
            raise ValidationError(f"{label}: product_code is required", field="product_code")

        quantity = entry.get("quantity")
        if not isinstance(quantity, int) or quantity < 1:
            raise ValidationError(f"{label}: quantity must be a positive integer", field="quantity")

        warehouse_id = entry.get("warehouse_id")
        if warehouse_id is None:
            raise ValidationError(f"{label}: warehouse_id is required", field="warehouse_id")
        warehouse_ids.add(warehouse_id)

        # receive_into_stock does not check these (allocate_stock_to_project does), and the columns
        # are String(20). Without this an over-long aisle reaches the flush and dies as a
        # StringDataRightTruncation - a raw 500 naming no entry, against a batch of thousands.
        for part in ("aisle", "row", "bay"):
            value = _clean_location(entry.get(part))
            if value is not None and len(value) > _MAX_LOCATION_PART:
                raise ValidationError(
                    f"{label}: {part} must be {_MAX_LOCATION_PART} characters or fewer",
                    field=part,
                )

        if destination == DESTINATION_PROJECT:
            project_id = entry.get("project_id")
            if project_id is None:
                raise ValidationError(f"{label}: project_id is required for a PROJECT entry", field="project_id")
            project_ids.add(project_id)

    # One query per referenced table rather than one per entry - a 2000-row batch typically names a
    # handful of warehouses and a few dozen projects.
    if warehouse_ids:
        found = set(session.scalars(select(Warehouse.id).where(Warehouse.id.in_(warehouse_ids))).all())
        missing = warehouse_ids - found
        if missing:
            raise ValidationError(
                f"Unknown warehouse(s): {', '.join(str(m) for m in sorted(missing, key=str))}",
                field="warehouse_id",
            )

    if project_ids:
        found = set(session.scalars(select(ProjectModel.id).where(ProjectModel.id.in_(project_ids))).all())
        missing = project_ids - found
        if missing:
            raise ValidationError(
                f"Unknown project(s): {', '.join(str(m) for m in sorted(missing, key=str))}",
                field="project_id",
            )


def has_any_inventory(session: Session) -> bool:
    """Whether Nexus already holds inventory, for the wizard's re-run warning.

    The migration has no idempotency marker, so running it twice doubles everything it wrote. This
    is what the first step warns on.

    Deliberately broad, and it will be true on any environment that has ever received a PO - this
    answers "is this database empty", not "has this migration run". It is a prompt to check, not a
    verdict; the honest version of the latter needs a persisted marker, which nothing writes yet.
    """
    has_locations = session.scalar(select(InventoryLocation.id).limit(1)) is not None
    if has_locations:
        return True
    return session.scalar(select(StockItem.id).where(StockItem.quantity > 0).limit(1)) is not None
