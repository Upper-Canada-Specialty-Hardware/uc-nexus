"""Admin-only queries and mutations for the one-time SharePoint inventory migration.

The snapshot query is a pure Graph read with no database access; all the interpretation of it -
which rows carry migratable quantity, how a location string maps to aisle/row/bay, which SharePoint
project is which Nexus project - happens in the wizard, because every one of those is a decision a
human makes once and the backend has no basis to make alone.
"""

import uuid

import strawberry

from app.auth import current_user, resolve_display_name
from app.database import SessionLocal
from app.repositories import sharepoint_migration_repository
from app.repositories import warehouse as warehouse_repository
from app.services import sharepoint_inventory

from .inputs import MigrateSharepointInventoryInput
from .types import (
    MigrationResult,
    ProjectScheduleProduct,
    SharepointInventoryItem,
    SharepointInventorySnapshot,
)


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
        """Each project's schedule products (category, code, dominant classification) for the wizard.

        Read once the projects are mapped so the wizard can snap a matched migrated row's category to
        the schedule and drive the classification step. One grouped query per call, no per-row work."""
        ids = [uuid.UUID(str(pid)) for pid in project_ids]
        with SessionLocal() as session:
            rows = warehouse_repository.get_project_schedule_products(session, ids)
        return [
            ProjectScheduleProduct(
                project_id=strawberry.ID(str(row["project_id"])),
                hardware_category=row["hardware_category"],
                product_code=row["product_code"],
                classification=row["classification"],
                required_quantity=row["required_quantity"],
            )
            for row in rows
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
                catalog_items_created=catalog["items_created"],
                catalog_items_skipped=catalog["items_skipped"],
                catalog_attributes_created=catalog["attributes_created"],
            )
