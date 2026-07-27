"""Warehouse queries + mutations: receiving, inventory, locations, pull requests, warehouse admin."""

import asyncio
import uuid

import strawberry

from app.auth import require_user, resolve_display_name
from app.database import SessionLocal
from app.repositories import warehouse as warehouse_repository
from app.repositories import warehouse_admin_repository
from app.services import gp_idempotency, gp_po
from app.services.relay_gateway import gateway as relay_gateway

from .converters import (
    inventory_location_to_type,
    notification_to_type,
    opening_item_hardware_to_type,
    opening_item_to_type,
    po_to_type,
    pull_request_to_type,
    receive_record_to_type,
    stock_item_to_type,
    warehouse_to_type,
)
from .enums import ApproveOutcome, AuditEntityType, LeafStatus, PullRequestSource, PullRequestStatus
from .inputs import CreateReceiveInput, CreateWarehouseInput, OverrideInventoryQuantityInput, UpdateWarehouseInput
from .types import (
    ApproveResult,
    AuditLogEntry,
    BackOrderedItem,
    InventoryHierarchyNode,
    InventoryItemDetail,
    InventoryLocation,
    InventoryShortfall,
    LocationContents,
    LocationDistinctValues,
    LocationDuplicateGroup,
    LocationMergeResult,
    LocationUtilizationEntry,
    LocationVariant,
    OpeningItem,
    OpeningItemDetail,
    OpeningLeafState,
    OpeningLeafStatus,
    ProductCodeNode,
    ProjectProgressByProduct,
    PullRequest,
    PurchaseOrder,
    ReceiveRecord,
    RecentReceiveRecord,
    VendorInventoryNode,
    Warehouse,
    WarehouseDashboard,
)


def _load_receive_type(receive_id: uuid.UUID) -> ReceiveRecord:
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.models.receiving import ReceiveRecord as ReceiveRecordModel

    with SessionLocal() as session:
        rec = (
            session.scalars(
                select(ReceiveRecordModel)
                .options(selectinload(ReceiveRecordModel.line_items))
                .where(ReceiveRecordModel.id == receive_id)
            )
            .unique()
            .first()
        )
        return receive_record_to_type(rec)


def _prepare_create_receive(*, po_id, received_by, line_items_data) -> tuple[str, dict]:
    """Read-only: validate the receive is eligible (before the GP receipt is posted) and build the relay
    create_receipt payload. Returns (gp_company, payload)."""
    with SessionLocal() as session:
        po_number, gp_company, receipt_line_items = warehouse_repository.validate_receive_eligibility(
            session, po_id, received_by, line_items_data
        )
    payload = gp_po.build_create_receipt_payload(
        po_number=po_number, received_by=received_by, line_items=receipt_line_items
    )
    return gp_company, payload


def _persist_create_receive(*, key, po_id, received_by, line_items_data, warehouse_id, relay_result) -> ReceiveRecord:
    with SessionLocal() as session:
        receive_record = warehouse_repository.create_receive(
            session, po_id, received_by, line_items_data, warehouse_id=warehouse_id
        )
        # Capture the id before commit: expire_on_commit would make receive_record.id raise
        # DetachedInstanceError once the session block closes.
        receive_id = receive_record.id
        gp_idempotency.stamp_result_id(session, key, "create_receive", relay_result, str(receive_id))
        session.commit()
    return _load_receive_type(receive_id)


@strawberry.type
class WarehouseQueries:
    @strawberry.field
    def po_receiving_details(self, po_id: strawberry.ID) -> PurchaseOrder:
        with SessionLocal() as session:
            po, receive_records = warehouse_repository.get_po_receiving_details(session, uuid.UUID(str(po_id)))
            return po_to_type(po, receive_records)

    @strawberry.field
    def inventory_hierarchy(
        self, project_id: strawberry.ID | None = None, warehouse_id: strawberry.ID | None = None
    ) -> list[InventoryHierarchyNode]:
        with SessionLocal() as session:
            hierarchy = warehouse_repository.get_inventory_hierarchy(
                session,
                uuid.UUID(str(project_id)) if project_id else None,
                uuid.UUID(str(warehouse_id)) if warehouse_id else None,
            )
            return [
                InventoryHierarchyNode(
                    hardware_category=cat_node["hardware_category"],
                    product_codes=[
                        ProductCodeNode(
                            product_code=pc_node["product_code"],
                            items=[inventory_location_to_type(il) for il in pc_node["items"]],
                            total_quantity=pc_node["total_quantity"],
                            total_available_quantity=pc_node["total_available_quantity"],
                            total_value=pc_node["total_value"],
                        )
                        for pc_node in cat_node["product_codes"]
                    ],
                    total_quantity=cat_node["total_quantity"],
                    total_available_quantity=cat_node["total_available_quantity"],
                    total_value=cat_node["total_value"],
                )
                for cat_node in hierarchy
            ]

    @strawberry.field
    def inventory_items(
        self, project_id: strawberry.ID | None = None, category: str = "", product_code: str = ""
    ) -> list[InventoryItemDetail]:
        with SessionLocal() as session:
            items = warehouse_repository.get_inventory_items(
                session, uuid.UUID(str(project_id)) if project_id else None, category, product_code
            )
            return [
                InventoryItemDetail(
                    inventory_location=inventory_location_to_type(item["inventory_location"]),
                    po_number=item["po_number"],
                    classification=item["classification"],
                    unit_cost=item["unit_cost"],
                )
                for item in items
            ]

    @strawberry.field
    def unlocated_inventory(self, project_id: strawberry.ID | None = None) -> list[InventoryItemDetail]:
        with SessionLocal() as session:
            items = warehouse_repository.get_unlocated_inventory(
                session, uuid.UUID(str(project_id)) if project_id else None
            )
            return [
                InventoryItemDetail(
                    inventory_location=inventory_location_to_type(item["inventory_location"]),
                    po_number=item["po_number"],
                    classification=item["classification"],
                    unit_cost=item["unit_cost"],
                )
                for item in items
            ]

    @strawberry.field
    def recent_receive_records(self, limit: int = 10) -> list[RecentReceiveRecord]:
        with SessionLocal() as session:
            rows = warehouse_repository.get_recent_receive_records(session, limit)
            return [
                RecentReceiveRecord(
                    receive_record=receive_record_to_type(rr),
                    po_number=po.po_number,
                    total_items_received=sum(rli.quantity_received for rli in rr.line_items),
                )
                for rr, po in rows
            ]

    @strawberry.field
    def opening_items(self, project_id: strawberry.ID | None = None) -> list[OpeningItem]:
        with SessionLocal() as session:
            pid = uuid.UUID(str(project_id)) if project_id else None
            ois = warehouse_repository.get_opening_items(session, pid)
            # leaf_count (#311) is the "N of M leaves shipped" denominator; one grouped query,
            # attached per item so consumers can roll up by opening without an N+1. Computed for the
            # global view too (pid=None) so leafCount isn't null everywhere when project_id is omitted.
            leaf_counts = warehouse_repository.get_opening_leaf_counts(session, pid)
            # Shipping deficiency flag (#341): one grouped scalar aggregate for the whole list, the
            # same shape as leaf_counts above - a per-row lookup here would be an N+1 over every
            # assembled leaf in the project.
            from app.repositories import shop_assembly_repository

            awaiting = shop_assembly_repository.get_awaiting_replacement_quantities(session, [oi.id for oi in ois])
            return [
                opening_item_to_type(
                    oi,
                    leaf_count=leaf_counts.get(oi.opening_number),
                    awaiting_replacement_quantity=awaiting.get(oi.id, 0),
                )
                for oi in ois
            ]

    @strawberry.field
    def opening_leaf_status(self, project_id: strawberry.ID | None = None) -> list[OpeningLeafStatus]:
        """Per-opening door-leaf rollup (#313). project_id scopes to one project (shipping view);
        omit it for the global shop-assembly view (rows carry project identity to group by)."""
        with SessionLocal() as session:
            pid = uuid.UUID(str(project_id)) if project_id else None
            rows = warehouse_repository.get_opening_leaf_status(session, pid)
            return [
                OpeningLeafStatus(
                    project_id=strawberry.ID(str(r["project_id"])),
                    project_name=r["project_name"],
                    opening_number=r["opening_number"],
                    leaf_count=r["leaf_count"],
                    leaves=[OpeningLeafState(leaf=s["leaf"], status=LeafStatus(s["status"])) for s in r["leaves"]],
                )
                for r in rows
            ]

    @strawberry.field
    def opening_item_details(self, id: strawberry.ID) -> OpeningItemDetail:
        with SessionLocal() as session:
            from app.repositories import shop_assembly_repository

            oi = warehouse_repository.get_opening_item_details(session, uuid.UUID(str(id)))
            awaiting = shop_assembly_repository.get_awaiting_replacement_quantities(session, [oi.id])
            opening_item = opening_item_to_type(oi, awaiting_replacement_quantity=awaiting.get(oi.id, 0))
            return OpeningItemDetail(
                opening_item=opening_item,
                installed_hardware=[opening_item_hardware_to_type(h) for h in oi.installed_hardware],
            )

    @strawberry.field
    def pull_requests(
        self,
        project_id: strawberry.ID | None = None,
        source: PullRequestSource | None = None,
        status: PullRequestStatus | None = None,
    ) -> list[PullRequest]:
        with SessionLocal() as session:
            prs = warehouse_repository.get_pull_requests(
                session, uuid.UUID(str(project_id)) if project_id else None, source, status
            )
            return [pull_request_to_type(pr) for pr in prs]

    @strawberry.field
    def pull_request_details(self, id: strawberry.ID) -> PullRequest:
        with SessionLocal() as session:
            pr = warehouse_repository.get_pull_request_details(session, uuid.UUID(str(id)))
            return pull_request_to_type(pr)

    @strawberry.field
    def expected_deliveries(self, project_id: strawberry.ID | None = None) -> list[PurchaseOrder]:
        with SessionLocal() as session:
            pos = warehouse_repository.get_expected_deliveries(
                session, uuid.UUID(str(project_id)) if project_id else None
            )
            return [po_to_type(po) for po in pos]

    @strawberry.field
    def back_ordered_items(self, project_id: strawberry.ID | None = None) -> list[BackOrderedItem]:
        with SessionLocal() as session:
            items = warehouse_repository.get_back_ordered_items(
                session, uuid.UUID(str(project_id)) if project_id else None
            )
            return [
                BackOrderedItem(
                    hardware_category=item["po_line_item"].hardware_category,
                    product_code=item["po_line_item"].product_code,
                    ordered_quantity=item["po_line_item"].ordered_quantity,
                    received_quantity=item["po_line_item"].received_quantity,
                    outstanding_quantity=item["outstanding_quantity"],
                    unit_cost=float(item["po_line_item"].unit_cost),
                    po_number=item["po_number"],
                    vendor_name=item["vendor_name"],
                    expected_delivery_date=item["expected_delivery_date"],
                )
                for item in items
            ]

    @strawberry.field
    def warehouse_dashboard(self) -> WarehouseDashboard:
        with SessionLocal() as session:
            d = warehouse_repository.get_warehouse_dashboard(session)
            return WarehouseDashboard(
                total_item_count=d["total_item_count"],
                total_value=d["total_value"],
                unlocated_count=d["unlocated_count"],
                pending_pull_shop=d["pending_pull_shop"],
                pending_pull_shipping=d["pending_pull_shipping"],
                received_last_7_days=d["received_last_7_days"],
                back_ordered_count=d["back_ordered_count"],
            )

    @strawberry.field
    def project_progress_by_product(self, project_id: strawberry.ID) -> list[ProjectProgressByProduct]:
        with SessionLocal() as session:
            rows = warehouse_repository.get_project_progress_by_product(session, uuid.UUID(str(project_id)))
            return [
                ProjectProgressByProduct(
                    hardware_category=row["hardware_category"],
                    product_code=row["product_code"],
                    required_quantity=row["required_quantity"],
                    po_drafted=row["po_drafted"],
                    ordered_quantity=row["ordered_quantity"],
                    received_quantity=row["received_quantity"],
                    back_ordered=row["back_ordered"],
                    shipped_out=row["shipped_out"],
                )
                for row in rows
            ]

    @strawberry.field
    def inventory_by_vendor(self, project_id: strawberry.ID | None = None) -> list[VendorInventoryNode]:
        with SessionLocal() as session:
            nodes = warehouse_repository.get_inventory_by_vendor(
                session, uuid.UUID(str(project_id)) if project_id else None
            )
            return [
                VendorInventoryNode(
                    vendor_name=node["vendor_name"],
                    product_codes=[
                        ProductCodeNode(
                            product_code=pc["product_code"],
                            items=[inventory_location_to_type(il) for il in pc["items"]],
                            total_quantity=pc["total_quantity"],
                            total_value=pc["total_value"],
                        )
                        for pc in node["product_codes"]
                    ],
                    total_quantity=node["total_quantity"],
                    total_value=node["total_value"],
                )
                for node in nodes
            ]

    @strawberry.field
    def location_contents(
        self,
        aisle: str,
        row: str | None = None,
        bay: str | None = None,
        warehouse_id: strawberry.ID | None = None,
    ) -> LocationContents:
        with SessionLocal() as session:
            data = warehouse_repository.get_location_contents(
                session, aisle, row, bay, uuid.UUID(str(warehouse_id)) if warehouse_id else None
            )
            return LocationContents(
                inventory_items=[
                    InventoryItemDetail(
                        inventory_location=inventory_location_to_type(item["inventory_location"]),
                        po_number=item["po_number"],
                        classification=None,
                        unit_cost=item["unit_cost"],
                    )
                    for item in data["inventory_items"]
                ],
                opening_items=[opening_item_to_type(oi) for oi in data["opening_items"]],
                stock_items=[stock_item_to_type(si) for si in data["stock_items"]],
            )

    @strawberry.field
    def location_audit_history(
        self,
        aisle: str,
        row: str | None = None,
        bay: str | None = None,
        limit: int = 10,
    ) -> list[AuditLogEntry]:
        with SessionLocal() as session:
            entries = warehouse_repository.get_location_audit_history(session, aisle, row, bay, limit=limit)
            return [
                AuditLogEntry(
                    id=strawberry.ID(str(e.id)),
                    project_id=strawberry.ID(str(e.project_id)) if e.project_id else None,
                    entity_type=e.entity_type,
                    entity_id=strawberry.ID(str(e.entity_id)),
                    action=e.action,
                    detail=e.detail,
                    performed_by=e.performed_by,
                    created_at=e.created_at,
                )
                for e in entries
            ]

    @strawberry.field
    def location_distinct_values(self) -> LocationDistinctValues:
        with SessionLocal() as session:
            values = warehouse_repository.get_distinct_location_values(session)
            return LocationDistinctValues(
                aisles=values["aisles"],
                rows=values["rows"],
                bays=values["bays"],
            )

    @strawberry.field
    def location_duplicates(self) -> list[LocationDuplicateGroup]:
        with SessionLocal() as session:
            groups = warehouse_repository.get_location_duplicates(session)
            return [
                LocationDuplicateGroup(
                    canonical_aisle=g["canonical_aisle"],
                    canonical_row=g["canonical_row"],
                    canonical_bay=g["canonical_bay"],
                    variants=[LocationVariant(aisle=v["aisle"], row=v["row"], bay=v["bay"]) for v in g["variants"]],
                )
                for g in groups
            ]

    @strawberry.field
    def location_utilization(self, warehouse_id: strawberry.ID | None = None) -> list[LocationUtilizationEntry]:
        with SessionLocal() as session:
            rows = warehouse_repository.get_location_utilization(
                session, uuid.UUID(str(warehouse_id)) if warehouse_id else None
            )
            return [
                LocationUtilizationEntry(
                    warehouse_id=strawberry.ID(str(r["warehouse_id"])) if r.get("warehouse_id") else None,
                    aisle=r["aisle"],
                    row=r["row"],
                    bay=r["bay"],
                    item_count=r["item_count"],
                    total_quantity=r["total_quantity"],
                )
                for r in rows
            ]

    @strawberry.field
    def audit_log(
        self,
        entity_id: strawberry.ID | None = None,
        entity_type: AuditEntityType | None = None,
        project_id: strawberry.ID | None = None,
        limit: int = 50,
    ) -> list[AuditLogEntry]:
        with SessionLocal() as session:
            entries = warehouse_repository.get_audit_log(
                session,
                entity_id=uuid.UUID(str(entity_id)) if entity_id else None,
                entity_type=entity_type.value if entity_type else None,
                project_id=uuid.UUID(str(project_id)) if project_id else None,
                limit=limit,
            )
            return [
                AuditLogEntry(
                    id=strawberry.ID(str(e.id)),
                    project_id=strawberry.ID(str(e.project_id)) if e.project_id else None,
                    entity_type=e.entity_type,
                    entity_id=strawberry.ID(str(e.entity_id)),
                    action=e.action,
                    detail=e.detail,
                    performed_by=e.performed_by,
                    created_at=e.created_at,
                )
                for e in entries
            ]

    @strawberry.field
    def warehouses(self, include_inactive: bool = True) -> list[Warehouse]:
        with SessionLocal() as session:
            return [
                warehouse_to_type(w)
                for w in warehouse_admin_repository.list_warehouses(session, include_inactive=include_inactive)
            ]

    @strawberry.field
    def warehouse(self, id: strawberry.ID) -> Warehouse | None:
        with SessionLocal() as session:
            w = warehouse_admin_repository.find_warehouse(session, uuid.UUID(str(id)))
            return warehouse_to_type(w) if w is not None else None


@strawberry.type
class WarehouseMutations:
    # Receiving
    @strawberry.mutation
    async def create_receive(self, info: strawberry.Info, input: CreateReceiveInput) -> ReceiveRecord:
        """Issue #199: GP-first, server-side. Posts the GP receipt via relay_call (create_receipt)
        BEFORE persisting the UC Nexus receive, and received_by is the acting UC Nexus user resolved
        from the Clerk token - not a client-supplied string, and not the relay's Windows account.

        Issue #202 #1/#3: idempotency_key makes a retry a no-op in GP (replacing the deleted client-side
        gpReceiptPostedRef guard); eligibility (over-receive, PO status, location sums) is validated
        before the GP receipt is posted; the DB and Clerk work is offloaded so no Postgres connection is
        held across the relay round-trip and the /relay-link read loop is never blocked on a sync call."""
        user = require_user(info)
        key = gp_idempotency.validate_key(input.idempotency_key)

        po_id = uuid.UUID(str(input.po_id))
        line_items_data = [
            {
                "po_line_item_id": uuid.UUID(str(li.po_line_item_id)),
                "quantity_received": li.quantity_received,
                "locations": [
                    {
                        "aisle": loc.aisle,
                        "row": loc.row,
                        "bay": loc.bay,
                        "quantity": loc.quantity,
                        "deficient_quantity": loc.deficient_quantity,
                    }
                    for loc in li.locations
                ],
            }
            for li in input.line_items
        ]
        warehouse_id = uuid.UUID(str(input.warehouse_id)) if input.warehouse_id else None

        state = await asyncio.to_thread(gp_idempotency.load, key)
        if state is not None and state.result_id is not None:
            return await asyncio.to_thread(_load_receive_type, uuid.UUID(state.result_id))

        received_by = await asyncio.to_thread(resolve_display_name, user["user_id"])
        gp_company, payload = await asyncio.to_thread(
            _prepare_create_receive, po_id=po_id, received_by=received_by, line_items_data=line_items_data
        )

        if state is not None and state.relay_result is not None:
            relay_result = state.relay_result
        else:
            relay_result = await relay_gateway.relay_call(gp_company, "create_receipt", payload)
            await asyncio.to_thread(gp_idempotency.record_relay_result, key, "create_receive", relay_result)

        return await asyncio.to_thread(
            _persist_create_receive,
            key=key,
            po_id=po_id,
            received_by=received_by,
            line_items_data=line_items_data,
            warehouse_id=warehouse_id,
            relay_result=relay_result,
        )

    # Pull Requests
    @strawberry.mutation
    def approve_pull_request(self, id: strawberry.ID, approved_by: str) -> ApproveResult:
        with SessionLocal() as session:
            pr, outcome, notification, shortfalls = warehouse_repository.approve_pull_request(
                session, uuid.UUID(str(id)), approved_by
            )
            session.commit()
            pr = warehouse_repository.get_pull_request_details(session, pr.id)

            return ApproveResult(
                pull_request=pull_request_to_type(pr),
                outcome=ApproveOutcome.APPROVED if outcome == "APPROVED" else ApproveOutcome.INSUFFICIENT,
                notification=notification_to_type(notification) if notification else None,
                shortfalls=[
                    InventoryShortfall(
                        hardware_category=s.hardware_category,
                        product_code=s.product_code,
                        requested=s.requested,
                        available=s.available,
                        short=s.short,
                    )
                    for s in shortfalls
                ],
            )

    @strawberry.mutation
    def complete_pull_request(self, id: strawberry.ID) -> PullRequest:
        with SessionLocal() as session:
            pr = warehouse_repository.complete_pull_request(session, uuid.UUID(str(id)))
            session.commit()
            pr = warehouse_repository.get_pull_request_details(session, pr.id)
            return pull_request_to_type(pr)

    # Admin Corrections
    @strawberry.mutation
    def adjust_inventory_quantity(
        self, inventory_location_id: strawberry.ID, adjustment: int, reason: str
    ) -> InventoryLocation:
        with SessionLocal() as session:
            result = warehouse_repository.adjust_inventory_quantity(
                session, uuid.UUID(str(inventory_location_id)), adjustment, reason
            )
            session.commit()
            session.refresh(result)
            return inventory_location_to_type(result)

    @strawberry.mutation
    def override_inventory_quantity(self, input: OverrideInventoryQuantityInput) -> InventoryLocation:
        with SessionLocal() as session:
            result = warehouse_repository.override_inventory_quantity(
                session,
                inv_id=uuid.UUID(str(input.inventory_location_id)),
                new_quantity=input.new_quantity,
                reason=input.reason_text,
                destinations=[
                    {"aisle": d.aisle, "row": d.row, "bay": d.bay, "quantity": d.quantity} for d in input.destinations
                ],
                performed_by=input.performed_by or "Warehouse",
            )
            session.commit()
            session.refresh(result)
            return inventory_location_to_type(result)

    @strawberry.mutation
    def move_inventory_location(
        self,
        inventory_location_id: strawberry.ID,
        new_aisle: str,
        new_row: str,
        new_bay: str,
    ) -> InventoryLocation:
        with SessionLocal() as session:
            result = warehouse_repository.move_inventory_location(
                session, uuid.UUID(str(inventory_location_id)), new_aisle, new_row, new_bay
            )
            session.commit()
            session.refresh(result)
            return inventory_location_to_type(result)

    @strawberry.mutation
    def mark_inventory_unlocated(self, inventory_location_id: strawberry.ID) -> InventoryLocation:
        with SessionLocal() as session:
            result = warehouse_repository.mark_inventory_unlocated(session, uuid.UUID(str(inventory_location_id)))
            session.commit()
            session.refresh(result)
            return inventory_location_to_type(result)

    @strawberry.mutation
    def assign_inventory_location(
        self,
        inventory_location_id: strawberry.ID,
        aisle: str,
        row: str,
        bay: str,
    ) -> InventoryLocation:
        with SessionLocal() as session:
            result = warehouse_repository.assign_inventory_location(
                session, uuid.UUID(str(inventory_location_id)), aisle, row, bay
            )
            session.commit()
            session.refresh(result)
            return inventory_location_to_type(result)

    @strawberry.mutation
    def move_opening_item_location(
        self,
        opening_item_id: strawberry.ID,
        aisle: str,
        row: str,
        bay: str,
        warehouse_id: strawberry.ID | None = None,
    ) -> OpeningItem:
        with SessionLocal() as session:
            result = warehouse_repository.move_opening_item_location(
                session,
                uuid.UUID(str(opening_item_id)),
                aisle,
                row,
                bay,
                warehouse_id=uuid.UUID(str(warehouse_id)) if warehouse_id else None,
            )
            session.commit()
            session.refresh(result)
            return opening_item_to_type(result)

    @strawberry.mutation
    def mark_opening_item_unlocated(self, opening_item_id: strawberry.ID) -> OpeningItem:
        with SessionLocal() as session:
            result = warehouse_repository.mark_opening_item_unlocated(session, uuid.UUID(str(opening_item_id)))
            session.commit()
            session.refresh(result)
            return opening_item_to_type(result)

    @strawberry.mutation
    def assign_opening_item_location(
        self,
        opening_item_id: strawberry.ID,
        aisle: str,
        row: str,
        bay: str,
    ) -> OpeningItem:
        with SessionLocal() as session:
            result = warehouse_repository.assign_opening_item_location(
                session, uuid.UUID(str(opening_item_id)), aisle, row, bay
            )
            session.commit()
            session.refresh(result)
            return opening_item_to_type(result)

    @strawberry.mutation
    def merge_locations(
        self,
        from_aisle: str,
        from_row: str,
        from_bay: str,
        to_aisle: str,
        to_row: str,
        to_bay: str,
    ) -> LocationMergeResult:
        with SessionLocal() as session:
            counts = warehouse_repository.merge_locations(
                session,
                from_aisle=from_aisle,
                from_row=from_row,
                from_bay=from_bay,
                to_aisle=to_aisle,
                to_row=to_row,
                to_bay=to_bay,
                performed_by="Admin/Manager",
            )
            session.commit()
            return LocationMergeResult(
                inventory_locations=counts["inventory_locations"],
                opening_items=counts["opening_items"],
                stock_items=counts["stock_items"],
            )

    # Warehouses (admin)
    @strawberry.mutation
    def create_warehouse(self, input: CreateWarehouseInput) -> Warehouse:
        with SessionLocal() as session:
            wh = warehouse_admin_repository.create_warehouse(
                session,
                name=input.name,
                code=input.code,
                address=input.address,
                city=input.city,
                province=input.province,
                postal_code=input.postal_code,
                is_primary=input.is_primary,
                is_active=input.is_active,
            )
            session.commit()
            session.refresh(wh)
            return warehouse_to_type(wh)

    @strawberry.mutation
    def update_warehouse(self, id: strawberry.ID, input: UpdateWarehouseInput) -> Warehouse:
        with SessionLocal() as session:
            wh = warehouse_admin_repository.update_warehouse(
                session,
                uuid.UUID(str(id)),
                name=input.name,
                code=input.code,
                address=input.address,
                city=input.city,
                province=input.province,
                postal_code=input.postal_code,
                is_primary=input.is_primary,
                is_active=input.is_active,
            )
            session.commit()
            session.refresh(wh)
            return warehouse_to_type(wh)

    @strawberry.mutation
    def delete_warehouse(self, id: strawberry.ID) -> bool:
        with SessionLocal() as session:
            warehouse_admin_repository.delete_warehouse(session, uuid.UUID(str(id)))
            session.commit()
            return True
