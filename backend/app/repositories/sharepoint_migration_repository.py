"""One-time import of the legacy SharePoint inventory list into Nexus inventory.

Every entry the wizard sends has already been resolved by a human: its warehouse and aisle/row/bay
came out of the location-mapping step, its project out of the project-mapping step, its purchase
order out of the Reconcile GP PO link step, and rows nobody could place were excluded client-side. So
this module validates and writes; it does not guess.

An entry that names no purchase order goes through the stock pool, because that is the only origin an
`InventoryLocation` can have that is not a purchase order. `ck_inventory_locations_has_origin`
requires either (po_line_item_id AND receive_line_item_id) or stock_item_id or
shipment_return_item_id. Routing through `receive_into_stock` -> `allocate_stock_to_project` reuses
the same path the warehouse already uses to move shelf stock onto a project, which means the audit
trail and the drained-stock-row bookkeeping come for free.

An entry that DOES name a GP PO LINE ITEM takes the other branch of that constraint. UBC's FIRST TIME
GP COMPANY NEXUS INITIALIZATION copied its whole PO history, so the order those units arrived on is
in Nexus, and the migrated quantity is written as a receipt against the line: a ReceiveRecord dated
the run, one ReceiveLineItem per entry, and the InventoryLocation carrying both origin columns. The
line's received quantity is NOT touched - GP has counted these units for years - and GP RECEIVE ENTRY
is never called. The line also takes the entry's hardware category and product code and becomes a
NEXUS REGISTERED LINE, so the OPEN-POS SYNC stops overwriting them with GP's item number and
description.
"""

import logging
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, selectinload

from app.errors import NotFoundError, ValidationError
from app.models.enums import AuditAction, AuditEntityType, Classification, HardwareItemState, POOrigin
from app.models.hardware import HardwareItem
from app.models.inventory import InventoryLocation
from app.models.inventory_item_type import CustomInventoryItem
from app.models.project import Opening
from app.models.project import Project as ProjectModel
from app.models.purchase_order import POLineItem
from app.models.receiving import ReceiveLineItem, ReceiveRecord
from app.models.sharepoint_migration_run import SharepointMigrationMark, SharepointMigrationRun
from app.models.warehouse import Warehouse
from app.repositories import custom_items_repository
from app.repositories import stock as stock_repository
from app.repositories.warehouse import (
    _log_audit_event,
    ensure_registered_location,
    location_detail,
    normalize_location_value,
)

logger = logging.getLogger(__name__)

DESTINATION_PROJECT = "PROJECT"
DESTINATION_STOCK = "STOCK"

# What a migrated receipt is called wherever a receive record's notes are shown. Nexus-only text; it
# never reaches GP, because no GP RECEIVE ENTRY is made for these units.
MIGRATION_RECEIPT_NOTE = "SharePoint migration"


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


def migrate_inventory(
    session: Session, entries: list[dict], performed_by: str, classifications: list[dict] | None = None
) -> dict:
    """Write every resolved entry, in one transaction, and make the units behave like PO'd hardware.

    Each entry: destination, warehouse_id, hardware_category, product_code, quantity, optional
    unit_cost, optional aisle/row/bay, optional po_line_item_id, and project_id when destination is
    PROJECT.

    Beyond writing inventory the migration also (a) carries the SharePoint unit cost onto the rows
    that have no PO line to hang it on; (b) writes the wizard's Site/Shop decisions onto the matching
    schedule rows that are still unclassified; and (c) flips the covered schedule rows to IN_PO so
    every lifecycle rollup counts the units as bought - see `_mark_purchased`. All of it is one
    transaction with the inventory writes.

    All-or-nothing on purpose. A partial migration is worse than none: the wizard has no resume
    state, so re-running after a half-failure would double the rows that did land.
    """
    if not entries:
        raise ValidationError("No inventory entries to migrate", field="entries")

    # Validate the whole batch before writing anything, so a bad row 2000 does not leave the caller
    # guessing which of the first 1999 went in.
    _validate_entries(session, entries)
    linked_lines = _validate_po_links(session, entries)

    now = datetime.utcnow()
    # Stock rows, not stock ENTRIES: receive_into_stock merges into an existing row for the same
    # (warehouse, category, code, aisle, row, bay), so two SharePoint rows for one part on one shelf
    # are one StockItem. Counting entries would report a number the warehouse view cannot reproduce.
    stock_row_ids: set[uuid.UUID] = set()
    project_locations = 0
    total_units = 0
    linked_entries = 0
    # One ReceiveRecord per purchase order per run: every migrated unit of a given PO arrived as one
    # historical delivery as far as Nexus is concerned, and a record per entry would litter the PO's
    # receiving history with dozens of same-dated receipts.
    receipts: dict[uuid.UUID, ReceiveRecord] = {}
    # Project inventory landed per (project, category, code, po line) - the N the purchased marking
    # spends against the schedule. Only PROJECT-destination units; company stock covers no project's
    # need. The line is part of the key so the marking ties its rows to the line it came from.
    project_qty: dict[tuple[uuid.UUID, str, str, uuid.UUID | None], int] = {}

    for index, entry in enumerate(entries):
        # Written stripped, not just validated stripped: a trailing space makes a distinct identity
        # that can never match a schedule pair, and this is a public admin mutation rather than
        # something only the wizard calls.
        category = entry["hardware_category"].strip()
        code = entry["product_code"].strip()
        quantity = entry["quantity"]
        warehouse_id = entry["warehouse_id"]
        unit_cost = _clean_unit_cost(entry.get("unit_cost"))
        aisle = _clean_location(entry.get("aisle"))
        row = _clean_location(entry.get("row"))
        bay = _clean_location(entry.get("bay"))
        line = linked_lines.get(entry.get("po_line_item_id")) if entry.get("po_line_item_id") else None

        try:
            if line is not None:
                # The identity is what makes it a NEXUS REGISTERED LINE, and it is written on both
                # destinations: a stock-destination row proves just as much about what the line was
                # really for as a project one does.
                line.hardware_category = category
                line.product_code = code
                line.nexus_registered = True
                linked_entries += 1

            if line is not None and entry["destination"] == DESTINATION_PROJECT:
                _receive_against_line(
                    session,
                    receipts=receipts,
                    line=line,
                    project_id=entry["project_id"],
                    warehouse_id=warehouse_id,
                    hardware_category=category,
                    product_code=code,
                    quantity=quantity,
                    aisle=aisle,
                    row=row,
                    bay=bay,
                    received_at=now,
                    received_by=performed_by,
                )
                project_locations += 1
                key = (entry["project_id"], category, code, line.id)
                project_qty[key] = project_qty.get(key, 0) + quantity
                total_units += quantity
                continue

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
                # A stock-destination row's PO reaches the audit detail and nothing else: the stock
                # pool is fungible by design and a StockItem has no purchase order of its own.
                po_number=line.purchase_order.po_number if line is not None else None,
                unit_cost=unit_cost,
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
                    # The ENTRY's own cost, not the pool row's. receive_into_stock merges same-shelf
                    # entries into one row and keeps the first cost it saw, so reading the pool back
                    # here would price this project's units at whichever entry happened to land first.
                    unit_cost_override=unit_cost,
                )
                project_locations += 1
                key = (entry["project_id"], category, code, None)
                project_qty[key] = project_qty.get(key, 0) + quantity
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

    classified = _apply_classifications(session, classifications or [])

    # The run marker is created before the marking so each mark can carry its run id - the marks are
    # what lets finalize re-apply the coverage after a schedule replace wipes the marked rows.
    run = SharepointMigrationRun(
        run_at=now,
        performed_by=performed_by,
        entry_count=len(entries),
        unit_count=total_units,
    )
    session.add(run)
    session.flush()
    marked = _mark_purchased(session, project_qty, run_id=run.id)
    session.flush()

    logger.info(
        "SharePoint migration by %s: %d stock rows, %d project locations, %d units, "
        "%d entries linked to a GP PO line, %d schedule rows classified, %d schedule rows marked IN_PO",
        performed_by,
        len(stock_row_ids),
        project_locations,
        total_units,
        linked_entries,
        classified,
        marked,
    )
    return {
        "stock_items": len(stock_row_ids),
        "project_locations": project_locations,
        "total_units": total_units,
        "linked_entries": linked_entries,
    }


def _receive_against_line(
    session: Session,
    *,
    receipts: dict[uuid.UUID, ReceiveRecord],
    line: POLineItem,
    project_id: uuid.UUID,
    warehouse_id: uuid.UUID,
    hardware_category: str,
    product_code: str,
    quantity: int,
    aisle: str | None,
    row: str | None,
    bay: str | None,
    received_at: datetime,
    received_by: str,
) -> InventoryLocation:
    """Land one entry's units as a receipt against the GP PO LINE ITEM they were bought on.

    The line's `received_quantity` is deliberately left alone: GP counted these units when they were
    received years ago, and adding them again here would double the PO's received figure the next
    OPEN-POS SYNC compares against. What this writes is the Nexus-side history that was missing - a
    receive record, a receive line and an inventory row whose origin is the PO line - so the units
    behave like any other PO'd hardware from here on.

    `unit_cost` is left null on purpose: valuation reads coalesce(po_line.unit_cost, row.unit_cost, 0)
    and the line carries GP's own cost, which is a better number than the SharePoint one.
    """
    # The same rule allocate_stock_to_project applies to a migrated project row, so a row behaves the
    # same whether or not it turned out to have a purchase order: a partial triple is refused, and a
    # complete one has to name a location the warehouse has actually defined (#632).
    aisle = normalize_location_value(aisle)
    row = normalize_location_value(row)
    bay = normalize_location_value(bay)
    provided = [v for v in (aisle, row, bay) if v is not None]
    if provided and len(provided) != 3:
        raise ValidationError("target aisle, row, and bay must all be provided together", field="target_location")
    if provided:
        ensure_registered_location(session, warehouse_id, aisle, row, bay)

    receipt = receipts.get(line.po_id)
    if receipt is None:
        receipt = ReceiveRecord(
            po_id=line.po_id,
            received_at=received_at,
            received_by=received_by,
            # No GP receipt exists for these units, so there is no RCT###### and no batch to record.
            receipt_number=None,
            batch_number=None,
            notes=MIGRATION_RECEIPT_NOTE,
        )
        session.add(receipt)
        session.flush()
        receipts[line.po_id] = receipt

    receive_line = ReceiveLineItem(
        receive_record_id=receipt.id,
        po_line_item_id=line.id,
        hardware_category=hardware_category,
        product_code=product_code,
        quantity_received=quantity,
    )
    session.add(receive_line)
    session.flush()

    inventory_row = InventoryLocation(
        project_id=project_id,
        po_line_item_id=line.id,
        receive_line_item_id=receive_line.id,
        warehouse_id=warehouse_id,
        hardware_category=hardware_category,
        product_code=product_code,
        quantity=quantity,
        deficient_quantity=0,
        aisle=aisle,
        row=row,
        bay=bay,
        unit_cost=None,
        received_at=received_at,
    )
    session.add(inventory_row)
    session.flush()

    _log_audit_event(
        session,
        project_id=project_id,
        entity_type=AuditEntityType.INVENTORY_LOCATION,
        entity_id=inventory_row.id,
        action=AuditAction.RECEIVE,
        performed_by=received_by,
        detail={
            "quantity": quantity,
            "hardwareCategory": hardware_category,
            "productCode": product_code,
            "poNumber": line.purchase_order.po_number,
            "location": location_detail(aisle, row, bay, warehouse_id),
            "source": MIGRATION_RECEIPT_NOTE,
        },
    )
    return inventory_row


def _apply_classifications(session: Session, classifications: list[dict]) -> int:
    """Write the wizard's Site/Shop decisions onto matching schedule rows that are still unclassified.

    Each decision: project_id, hardware_category, product_code, classification. Inherit means never
    overwrite - a row the schedule already classified keeps its value, so only rows where
    classification IS NULL are touched. Categories are the schedule's own (the wizard snaps a matched
    row's category to the schedule before it gets here), so the (project, category, code) match lands
    on exactly the rows the extras-lane chip and the marking below read.
    """
    total = 0
    for decision in classifications:
        classification = decision.get("classification")
        if classification is None:
            continue
        result = session.execute(
            update(HardwareItem)
            .where(
                HardwareItem.project_id == decision["project_id"],
                HardwareItem.hardware_category == decision["hardware_category"].strip(),
                HardwareItem.product_code == decision["product_code"].strip(),
                HardwareItem.classification.is_(None),
            )
            .values(classification=Classification(classification))
        )
        total += result.rowcount or 0
    return total


def _validate_po_links(session: Session, entries: list[dict]) -> dict[uuid.UUID, POLineItem]:
    """Resolve every GP PO LINE ITEM the batch names, and refuse it if two entries disagree about one.

    Three checks, all of them before any write.

    The line has to exist and belong to a MIRRORED PO - one Nexus copied out of GP. A PO Nexus raised
    itself already carries the schedule's identity on every line, so there is nothing a shelf count
    could teach it, and pointing a migrated quantity at one would be pointing it at hardware that was
    ordered through Nexus in the first place.

    And a line may be given exactly one identity. Two rows resolving to the same line while
    disagreeing about what it is for means the wizard's matching was wrong; writing either would leave
    the line - and every unit received under it - describing hardware nobody has. Both offending rows
    are named, because the person fixing it needs to know which pair to choose between.
    """
    wanted = {entry["po_line_item_id"] for entry in entries if entry.get("po_line_item_id")}
    if not wanted:
        return {}

    lines = {
        line.id: line
        for line in session.scalars(
            select(POLineItem).options(selectinload(POLineItem.purchase_order)).where(POLineItem.id.in_(wanted))
        ).all()
    }
    missing = wanted - set(lines)
    if missing:
        raise ValidationError(
            f"Unknown purchase order line(s): {', '.join(str(m) for m in sorted(missing, key=str))}",
            field="po_line_item_id",
        )

    for line in lines.values():
        po = line.purchase_order
        if po is None or po.deleted_at is not None:
            raise ValidationError(
                f"Purchase order line {line.id} belongs to a deleted purchase order",
                field="po_line_item_id",
            )
        if po.origin != POOrigin.GP:
            raise ValidationError(
                f"Purchase order {po.po_number or po.id} was raised in Nexus - its lines already "
                "carry their schedule identity and migrated stock cannot be attached to them",
                field="po_line_item_id",
            )

    claimed: dict[uuid.UUID, tuple[int, str, str]] = {}
    for index, entry in enumerate(entries):
        line_id = entry.get("po_line_item_id")
        if not line_id:
            continue
        category = entry["hardware_category"].strip()
        code = entry["product_code"].strip()
        line = lines[line_id]

        if line.nexus_registered and (line.hardware_category, line.product_code) != (category, code):
            raise ValidationError(
                f"Entry {index + 1} ({category} / {code}) links to a purchase order line already "
                f"registered as {line.hardware_category} / {line.product_code}; its hardware category "
                "and product code cannot be changed",
                field="po_line_item_id",
            )

        previous = claimed.get(line_id)
        if previous is None:
            claimed[line_id] = (index, category, code)
        elif (previous[1], previous[2]) != (category, code):
            raise ValidationError(
                f"Entry {previous[0] + 1} ({previous[1]} / {previous[2]}) and Entry {index + 1} "
                f"({category} / {code}) are linked to the same purchase order line but disagree about "
                "what it is for. Resolve one of them differently before migrating.",
                field="po_line_item_id",
            )

    return lines


def _mark_purchased(
    session: Session,
    project_qty: dict[tuple[uuid.UUID, str, str, uuid.UUID | None], int],
    *,
    run_id: uuid.UUID,
) -> int:
    """Flip covered AVAILABLE schedule rows to IN_PO.

    A row whose units came off a GP PO LINE ITEM the wizard found is tied to that line, exactly as a
    Nexus-raised PO ties the hardware it covers. A row that named no purchase order is left
    null-linked: the real PO exists in GP under UBC - registered and received years ago - so the
    marking is still semantically true, these items ARE in POs, just not POs Nexus holds. Either way
    the rows drop out of not_purchased, survive re-imports (finalize preserves IN_PO and its dedup
    skips regenerating them), and are never re-bought by a later PO draft.

    Each combo's target N is also recorded as a `SharepointMigrationMark`, because the rows carrying
    the marking are wiped by a `replace_schedule` re-import - finalize reads the marks back and
    re-applies the coverage, and the line, against the new schedule's rows.
    """
    marked = 0
    for (project_id, category, code, po_line_item_id), n in project_qty.items():
        marked += mark_purchased_rows(session, project_id, category, code, n, po_line_item_id=po_line_item_id)
        session.add(
            SharepointMigrationMark(
                run_id=run_id,
                project_id=project_id,
                hardware_category=category,
                product_code=code,
                quantity=n,
                po_line_item_id=po_line_item_id,
            )
        )
    if marked:
        session.flush()
    return marked


def mark_purchased_rows(
    session: Session,
    project_id: uuid.UUID,
    category: str,
    code: str,
    n: int,
    *,
    po_line_item_id: uuid.UUID | None = None,
) -> int:
    """Greedy floor over one combo's AVAILABLE rows: mark every row that still fits within N.

    Deterministic (opening_number, id) order. A row that would overflow the remaining budget is
    SKIPPED, not a stopping point - a later smaller row that still fits is marked (quantities 3, 3, 1
    against N=4 mark the 3 and the 1). A partially-covered row stays AVAILABLE whole, because
    SharePoint only knows what remains on the shelf, not what was originally bought.

    `po_line_item_id` is the GP PO LINE ITEM the units came off, when the wizard found one; the marked
    rows are tied to it so the project's coverage reads through the PO rather than as an unattributed
    marking. Absent leaves them null-linked, which is the ordinary migrated marking.

    Shared with the finalize re-apply step (`import_repository`), so the migration and a schedule
    replace mark by exactly the same rule.
    """
    rows = (
        session.execute(
            select(HardwareItem)
            .join(Opening, HardwareItem.opening_id == Opening.id)
            .where(
                HardwareItem.project_id == project_id,
                HardwareItem.hardware_category == category,
                HardwareItem.product_code == code,
                HardwareItem.state == HardwareItemState.AVAILABLE,
            )
            .order_by(Opening.opening_number, HardwareItem.id)
        )
        .scalars()
        .all()
    )
    marked = 0
    remaining = n
    for hi in rows:
        if hi.item_quantity > remaining:
            continue
        hi.state = HardwareItemState.IN_PO
        if po_line_item_id is not None:
            hi.po_line_item_id = po_line_item_id
        remaining -= hi.item_quantity
        marked += 1
        if remaining <= 0:
            break
    return marked


def reapply_migration_marks(session: Session, project_id: uuid.UUID) -> int:
    """Re-mark a project's schedule rows from the recorded migration coverage, after a re-import.

    A `replace_schedule` finalize wipes every HardwareItem - the IN_PO marking included - and
    regenerates from the new input as AVAILABLE, so without this the project reads as never-purchased
    the moment its schedule is re-uploaded. For each recorded (category, code, PO line) target N,
    whatever IN_PO rows carrying that same line survived count first (a normal re-import preserves
    them), and the remainder is marked greedily by the same rule the migration used. A no-migration
    project has no marks and pays one indexed SELECT.

    The PO line is part of the key on both sides, so a mark that named a GP PO LINE ITEM re-ties its
    rows to that line and a mark that named none goes on covering null-linked rows. Marks that name a
    line are re-applied first: those rows have a home to go back to, and the unlinked marking is the
    one that can fall anywhere.
    """
    mark_rows = session.execute(
        select(
            SharepointMigrationMark.hardware_category,
            SharepointMigrationMark.product_code,
            SharepointMigrationMark.po_line_item_id,
            func.sum(SharepointMigrationMark.quantity),
        )
        .where(SharepointMigrationMark.project_id == project_id)
        .group_by(
            SharepointMigrationMark.hardware_category,
            SharepointMigrationMark.product_code,
            SharepointMigrationMark.po_line_item_id,
        )
    ).all()
    if not mark_rows:
        return 0

    # Units already covered by surviving IN_PO rows, per (combo, PO line), in one query.
    covered = {
        (category, code, line_id): int(total or 0)
        for category, code, line_id, total in session.execute(
            select(
                HardwareItem.hardware_category,
                HardwareItem.product_code,
                HardwareItem.po_line_item_id,
                func.sum(HardwareItem.item_quantity),
            )
            .where(
                HardwareItem.project_id == project_id,
                HardwareItem.state == HardwareItemState.IN_PO,
            )
            .group_by(
                HardwareItem.hardware_category,
                HardwareItem.product_code,
                HardwareItem.po_line_item_id,
            )
        ).all()
    }

    marked = 0
    for category, code, line_id, target in sorted(mark_rows, key=lambda r: (r[2] is None, r[0], r[1], str(r[2] or ""))):
        remaining = int(target or 0) - covered.get((category, code, line_id), 0)
        if remaining > 0:
            marked += mark_purchased_rows(session, project_id, category, code, remaining, po_line_item_id=line_id)
    if marked:
        session.flush()
    return marked


# The columns are Numeric(19, 5): fourteen integer digits. Anything past this dies at flush as an
# unnamed NumericValueOutOfRange, so _validate_entries refuses it with the entry named instead.
_MAX_UNIT_COST = Decimal("99999999999999.99999")


def _clean_unit_cost(value) -> Decimal | None:
    """A positive finite Decimal cost, or None. Blank / zero / negative / NaN / unparseable all read
    as None, so a row with no cost on the source list simply carries no cost rather than a spurious
    0.0000. (The <= comparison itself raises on NaN, so the finite check must come first.)"""
    if value is None:
        return None
    try:
        dec = Decimal(str(value))
    except (ArithmeticError, TypeError, ValueError):
        return None
    if not dec.is_finite() or dec <= 0:
        return None
    return dec


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

        # The cost columns are Numeric(19, 5); an over-large value would otherwise reach the flush
        # and die as a raw 500 naming no entry - the same trap the aisle-length check below guards.
        cost = _clean_unit_cost(entry.get("unit_cost"))
        if cost is not None and cost > _MAX_UNIT_COST:
            raise ValidationError(
                f"{label}: unit_cost must be {_MAX_UNIT_COST} or less",
                field="unit_cost",
            )

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


def has_migration_run(session: Session) -> bool:
    """Whether the SharePoint migration has already run, for the wizard's re-run warning.

    Definitive, unlike the old has-any-inventory check it replaces: that answered "is this database
    empty" and was true on any environment that had ever received a PO. This reads the run marker the
    migration writes, so it means what it says. A full data reset clears the table (it is not
    preserved), which is what lets the cutover run the migration again after resetting.
    """
    return session.scalar(select(SharepointMigrationRun.id).limit(1)) is not None
