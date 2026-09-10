"""Admin-only queries and mutations for the one-time SharePoint inventory migration.

The snapshot query is a pure Graph read with no database access; all the interpretation of it -
which rows carry migratable quantity, how a location string maps to aisle/row/bay, which SharePoint
project is which Nexus project - happens in the wizard, because every one of those is a decision a
human makes once and the backend has no basis to make alone.
"""

import uuid

import strawberry
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.auth import current_user, resolve_display_name, tenant_scope
from app.database import SessionLocal
from app.errors import ValidationError
from app.models.purchase_order import POLineItem, PurchaseOrder
from app.repositories import sharepoint_migration_repository, tenancy
from app.repositories import warehouse as warehouse_repository
from app.services import sharepoint_inventory

from .inputs import MigrateSharepointInventoryInput
from .types import (
    MigrationResult,
    MirroredPo,
    MirroredPoLine,
    ProjectScheduleProduct,
    SharepointInventoryItem,
    SharepointInventorySnapshot,
)

# The most PO numbers one call may ask about. The wizard chunks its distinct numbers to this; the cap
# exists so a hand-written query cannot turn a `WHERE po_number IN (...)` into a table scan.
_MAX_PO_NUMBERS = 200


def _to_int(value) -> int:
    """SharePoint number columns come back as floats. Every quantity in the list is whole."""
    if value is None:
        return 0
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _to_float(value) -> float:
    """SharePoint currency columns come back as floats or strings. Absent / unparseable reads as 0."""
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _to_str(value) -> str:
    return str(value).strip() if value is not None else ""


def _line_order(line: POLineItem) -> tuple[int, int, str]:
    """GP's own line order where the mirror recorded it, creation order otherwise. A line with no
    `gp_line_ord` sorts last rather than first, so a Nexus-added line never displaces GP's."""
    return (1, 0, str(line.id)) if line.gp_line_ord is None else (0, line.gp_line_ord, "")


def _mirrored_line(line: POLineItem) -> MirroredPoLine:
    return MirroredPoLine(
        id=strawberry.ID(str(line.id)),
        gp_line_ord=line.gp_line_ord,
        product_code=line.product_code,
        hardware_category=line.hardware_category,
        ordered_quantity=line.ordered_quantity,
        received_quantity=line.received_quantity,
        nexus_registered=line.nexus_registered,
    )


@strawberry.type
class SharepointMigrationQueries:
    @strawberry.field
    async def sharepoint_inventory_snapshot(self, info: strawberry.Info) -> SharepointInventorySnapshot:
        # Async because graphql-core runs a sync resolver inline on the event loop - there is no
        # threadpool under it - so a multi-page Graph read in a `def` would freeze every other
        # request to the backend for its whole duration.
        rows = await sharepoint_inventory.fetch_inventory_items()
        items = [
            SharepointInventoryItem(
                sp_item_id=_to_str(r.get("sp_item_id")),
                part_number=_to_str(r.get("Title")),
                scheduled_part_number=_to_str(r.get("HWSPartNumberEquivalent")),
                part_category=_to_str(r.get("Part_x0020_Category_x0020_1")),
                inventory_type=_to_str(r.get("Inventory_x0020_Type")),
                locations=_to_str(r.get("Locations")),
                stock_qty=_to_int(r.get("Stock_x0020_Qty")),
                non_stock_qty=_to_int(r.get("Non_x0020_Stock_x0020_Qty")),
                project_inventory_qty=_to_int(r.get("Project_x0020_Inventory_x0020_Qt")),
                project_number=_to_str(r.get("Project_x0020_Number_x0020_Temp")),
                project_name=_to_str(r.get("Project_x0020_Name_x0020_Temp")),
                unit_cost=_to_float(r.get("UnitCost")),
                # The list has no Part Description column (see _FIELDS); always empty, and the
                # catalog description falls back to Part Category 1 downstream.
                part_description=_to_str(r.get("Part_x0020_Description")),
                finish=_to_str(r.get("Finish")),
                rating=_to_str(r.get("Rating")),
                mounting=_to_str(r.get("Mounting")),
                height_inches=_to_str(r.get("Height_x0020_in_x0020_inches")),
                width_inches=_to_str(r.get("Width_x0020_in_x0020_inches")),
                # The internal name really is truncated at "Numbe" - SharePoint cut it to 32
                # characters when the column was created.
                po_number=_to_str(r.get("Purchase_x0020_Order_x0020_Numbe")),
                supplier=_to_str(r.get("Supplier")),
                ordered_qty=_to_int(r.get("Ordered_x0020_Qty")),
                received_qty=_to_int(r.get("Received_x0020_Qty")),
            )
            for r in rows
        ]
        with SessionLocal() as session:
            already_migrated = sharepoint_migration_repository.has_migration_run(session)
        return SharepointInventorySnapshot(items=items, already_migrated=already_migrated)

    @strawberry.field
    def project_schedule_products(
        self, info: strawberry.Info, project_ids: list[strawberry.ID]
    ) -> list[ProjectScheduleProduct]:
        """Each project's schedule products (category, code, dominant classification, units required
        and units still available) for the migration wizard and for the Nexus Registration panel.

        Read once the projects are mapped so the wizard can snap a matched migrated row's category to
        the schedule and drive the classification step; the panel reads it to offer the products a
        GP-born PO's line could be for, and to cap the tie quantity. One grouped query per call, no
        per-row work."""
        ids = [uuid.UUID(str(pid)) for pid in project_ids]
        with SessionLocal() as session:
            scope = tenant_scope(info)
            for pid in ids:
                tenancy.require_project_in_scope(session, pid, scope)
            rows = warehouse_repository.get_project_schedule_products(session, ids)
        return [
            ProjectScheduleProduct(
                project_id=strawberry.ID(str(row["project_id"])),
                hardware_category=row["hardware_category"],
                product_code=row["product_code"],
                classification=row["classification"],
                required_quantity=row["required_quantity"],
                available_quantity=row["available_quantity"],
            )
            for row in rows
        ]

    @strawberry.field
    def mirrored_pos_by_number(self, info: strawberry.Info, po_numbers: list[str]) -> list[MirroredPo]:
        """The purchase orders behind the SharePoint list's PO Number column, with their lines.

        UBC's FIRST TIME GP COMPANY NEXUS INITIALIZATION is complete, so a number the source list
        carries should already be in Nexus as a mirrored PO. The Reconcile GP PO link step reads this
        once for the whole wizard and matches each migrated row against the returned lines.

        Matched on the number EXACTLY, not case-insensitively: the unique index the mirror converges
        on is (gp_company, po_number), and folding case here would trade it for a scan of every PO in
        the database. GP writes these numbers uppercase and the wizard uppercases the cell before
        asking. A number nobody holds simply does not come back, which is the step's first reason.

        One query, lines eagerly loaded - a lazy load per PO would be 200 round trips per chunk.
        """
        wanted = sorted({n.strip() for n in po_numbers if n and n.strip()})
        if len(wanted) > _MAX_PO_NUMBERS:
            raise ValidationError(
                f"At most {_MAX_PO_NUMBERS} purchase order numbers can be looked up at a time; "
                f"{len(wanted)} were asked for",
                field="poNumbers",
            )
        if not wanted:
            return []

        with SessionLocal() as session:
            scope = tenant_scope(info)
            stmt = (
                select(PurchaseOrder)
                .options(selectinload(PurchaseOrder.line_items))
                .where(
                    PurchaseOrder.po_number.in_(wanted),
                    PurchaseOrder.deleted_at.is_(None),
                )
                .order_by(PurchaseOrder.po_number, PurchaseOrder.created_at)
            )
            if scope is not None:
                stmt = stmt.where(PurchaseOrder.company == scope)
            pos = list(session.scalars(stmt).unique().all())
            return [
                MirroredPo(
                    id=strawberry.ID(str(po.id)),
                    po_number=po.po_number or "",
                    status=po.status,
                    origin=po.origin,
                    project_id=strawberry.ID(str(po.project_id)) if po.project_id else None,
                    lines=[_mirrored_line(line) for line in sorted(po.line_items, key=_line_order)],
                )
                for po in pos
            ]


@strawberry.type
class SharepointMigrationMutations:
    @strawberry.mutation
    def migrate_sharepoint_inventory(
        self, info: strawberry.Info, input: MigrateSharepointInventoryInput
    ) -> MigrationResult:
        auth = current_user(info)
        actor = resolve_display_name(auth["user_id"])
        entries = [
            {
                "destination": e.destination.value,
                "project_id": uuid.UUID(str(e.project_id)) if e.project_id else None,
                "warehouse_id": uuid.UUID(str(e.warehouse_id)),
                "hardware_category": e.hardware_category,
                "product_code": e.product_code,
                "quantity": e.quantity,
                "unit_cost": e.unit_cost,
                "aisle": e.aisle,
                "row": e.row,
                "bay": e.bay,
                "po_line_item_id": uuid.UUID(str(e.po_line_item_id)) if e.po_line_item_id else None,
            }
            for e in input.entries
        ]
        classifications = [
            {
                "project_id": uuid.UUID(str(c.project_id)),
                "hardware_category": c.hardware_category,
                "product_code": c.product_code,
                "classification": c.classification,
            }
            for c in (input.classifications or [])
        ]
        catalog_items = [
            {
                "type_id": uuid.UUID(str(c.type_id)),
                "product_code": c.product_code,
                "description": c.description,
                "values": [{"attribute_name": v.attribute_name, "value": v.value} for v in (c.values or [])],
            }
            for c in (input.catalog_items or [])
        ]
        with SessionLocal() as session:
            # Catalog first: it is the description of what the quantities below are, and doing it in
            # the same transaction means a failure either way leaves neither behind.
            catalog = sharepoint_migration_repository.migrate_catalog_items(session, catalog_items)
            result = sharepoint_migration_repository.migrate_inventory(session, entries, actor, classifications)
            session.commit()
            return MigrationResult(
                stock_items=result["stock_items"],
                project_locations=result["project_locations"],
                total_units=result["total_units"],
                linked_entries=result["linked_entries"],
                catalog_items_created=catalog["items_created"],
                catalog_items_skipped=catalog["items_skipped"],
                catalog_attributes_created=catalog["attributes_created"],
            )
