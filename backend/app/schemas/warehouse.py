"""Warehouse queries + mutations: receiving, inventory, locations, pull requests, warehouse admin."""

import asyncio
import uuid

import strawberry

from app.auth import require_user, resolve_display_name
from app.database import SessionLocal
from app.errors import RelayUnavailableError
from app.repositories import warehouse as warehouse_repository
from app.repositories import warehouse_admin_repository
from app.services import gp_idempotency, gp_outbox_enqueue, gp_po
from app.services.relay_gateway import gateway as relay_gateway

from .converters import (
    inventory_location_to_type,
    notification_to_type,
    opening_item_hardware_to_type,
    opening_item_to_type,
    pick_sheet_to_type,
    po_to_type,
    pull_request_item_to_type,
    pull_request_to_type,
    receive_record_to_type,
    shop_assembly_opening_to_type,
    stock_item_to_type,
    warehouse_to_type,
)
from .enums import AuditEntityType, LeafStatus, PickOutcome, PullRequestSource, PullRequestStatus
from .inputs import (
    CancelPullRequestInput,
    CreateReceiveInput,
    CreateWarehouseInput,
    OverrideInventoryQuantityInput,
    PickLineInput,
    StagePullOpeningsInput,
    UpdateWarehouseInput,
)
from .types import (
    AuditLogEntry,
    BackOrderedItem,
    CancelPullRequestResult,
    ConfirmPickResult,
    CreateReceiveResult,
    InventoryAvailability,
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
    PickSheet,
    ProductCodeNode,
    ProjectProgressByProduct,
    PullRequest,
    PullRequestItem,
    PurchaseOrder,
    ReceiveRecord,
    RecentReceiveRecord,
    RestockedLine,
    ShopAssemblyOpening,
    StagePullOpeningsResult,
    VendorInventoryNode,
    Warehouse,
    WarehouseDashboard,
)


def _pick_lines_from_input(lines: list[PickLineInput]) -> list[warehouse_repository.PickLine]:
    """GraphQL input -> the repository's `PickLine`. The id parse is the only conversion."""
    return [
        warehouse_repository.PickLine(
            hardware_category=line.hardware_category,
            product_code=line.product_code,
            inventory_location_id=uuid.UUID(str(line.inventory_location_id)),
            quantity=line.quantity,
        )
        for line in lines
    ]


def _partially_picked(session, pr) -> bool | None:
    """Whether stock is off the shelf for an un-picked pull (#367), or None when the question does
    not apply. Every resolver that returns a PullRequest must pass this: the field is part of the
    shared client selection set, so a mutation result that omits it writes null over a cached true."""
    if pr.picked_at is not None:
        return None
    return pr.id in warehouse_repository.get_partially_picked_pull_ids(session, [pr.id])


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


def _receive_outbox_identity(po_id: uuid.UUID) -> tuple[uuid.UUID | None, str]:
    """(project_id, label) for a queued receive (#353 PR E). project_id routes a terminal failure to
    a notification (None when the PO has no project - the worker then relies on the queue UI rather
    than inventing a placeholder project); the label is the human line in that queue. One row."""
    from sqlalchemy import select

    from app.models.purchase_order import PurchaseOrder as POModel

    with SessionLocal() as session:
        row = session.execute(select(POModel.project_id, POModel.po_number).where(POModel.id == po_id)).first()
    project_id = row.project_id if row is not None else None
    number = row.po_number if row is not None else None
    return project_id, f"Receive against PO {number or po_id}"


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
    def project_inventory_availability(self, project_id: strawberry.ID) -> list[InventoryAvailability]:
        """What each product in a project can still be claimed for (#342):
        `available = on_hand - deficient - reserved`.

        This is the number the Start-a-Task creation gate applies, exposed so the wizard can block an
        over-selection with per-combo detail *before* submission rather than bouncing the whole
        finalize. Deliberately distinct from `inventoryHierarchy`'s availability, which is on-hand
        minus deficient: that answers "what is physically unspoken-for in the building", this
        answers "what may I claim". Two grouped scalar aggregates, no per-row work."""
        with SessionLocal() as session:
            rows = warehouse_repository.get_project_availability(session, uuid.UUID(str(project_id)))
            return [
                InventoryAvailability(
                    hardware_category=row["hardware_category"],
                    product_code=row["product_code"],
                    on_hand_quantity=row["on_hand_quantity"],
                    deficient_quantity=row["deficient_quantity"],
                    reserved_quantity=row["reserved_quantity"],
                    available_quantity=row["available_quantity"],
                )
                for row in rows
            ]

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

            shortfalls = shop_assembly_repository.get_leaf_shortfalls(session, [oi.id for oi in ois])
            return [
                opening_item_to_type(
                    oi,
                    leaf_count=leaf_counts.get(oi.opening_number),
                    awaiting_replacement_quantity=(
                        shortfalls[oi.id].awaiting_replacement if oi.id in shortfalls else 0
                    ),
                    never_pulled_quantity=(shortfalls[oi.id].never_pulled if oi.id in shortfalls else 0),
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
            shortfalls = shop_assembly_repository.get_leaf_shortfalls(session, [oi.id])
            shortfall = shortfalls.get(oi.id)
            opening_item = opening_item_to_type(
                oi,
                awaiting_replacement_quantity=shortfall.awaiting_replacement if shortfall else 0,
                never_pulled_quantity=shortfall.never_pulled if shortfall else 0,
            )
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
            # Two grouped aggregates for the whole page, never one query per row (#343, #367 /
            # CLAUDE.md perf rules): the queue renders a staging chip on every shop-assembly row and
            # a phase cell on every row. The partial-pick read is narrowed to un-picked pulls, which
            # are the only ones it means anything for.
            staging = warehouse_repository.get_pull_staging_summaries(session, [pr.id for pr in prs])
            partial = warehouse_repository.get_partially_picked_pull_ids(
                session, [pr.id for pr in prs if pr.picked_at is None]
            )
            return [
                pull_request_to_type(
                    pr,
                    staging.get(pr.id),
                    partially_picked=(pr.id in partial) if pr.picked_at is None else None,
                )
                for pr in prs
            ]

    @strawberry.field
    def pull_request_details(self, id: strawberry.ID) -> PullRequest:
        with SessionLocal() as session:
            pr = warehouse_repository.get_pull_request_details(session, uuid.UUID(str(id)))
            staging = warehouse_repository.get_pull_staging_summaries(session, [pr.id])
            partial = (
                pr.id in warehouse_repository.get_partially_picked_pull_ids(session, [pr.id])
                if pr.picked_at is None
                else None
            )
            return pull_request_to_type(pr, staging.get(pr.id), partially_picked=partial)

    @strawberry.field
    def pull_pick_sheet(self, info: strawberry.Info, pull_request_id: strawberry.ID) -> PickSheet:
        """Everything the pick screen and the printed sheet render from (#367).

        A query of its own rather than a field on `PullRequest`, for the same reason
        `pullRequestOpenings` is: a resolver field would run once per row of the pull-request queue,
        and the queue never needs it - only the pick page does.

        Open to any signed-in user. It exposes real per-location inventory for one project, which is
        the same shape of information the warehouse inventory views already carry."""
        require_user(info)
        with SessionLocal() as session:
            sheet = warehouse_repository.get_pick_sheet(session, uuid.UUID(str(pull_request_id)))
            pr = sheet.pull_request
            staging = warehouse_repository.get_pull_staging_summaries(session, [pr.id])
            partial = (
                pr.id in warehouse_repository.get_partially_picked_pull_ids(session, [pr.id])
                if pr.picked_at is None
                else None
            )
            return pick_sheet_to_type(sheet, staging.get(pr.id), partially_picked=partial)

    @strawberry.field
    def pull_request_openings(self, info: strawberry.Info, pull_request_id: strawberry.ID) -> list[ShopAssemblyOpening]:
        """The shop-assembly openings a pull covers, with their hardware lines, for the warehouse's
        per-opening staging checklist (#343).

        Deliberately a separate query rather than a field on `PullRequest`: a resolver field would
        run once per row of the pull-request queue, and the queue never needs it - only the detail
        view does. Returns an empty list for a shipping-out pull, a PR-REPL replacement pull, or a
        legacy pull, none of which have openings. Open to any signed-in user."""
        require_user(info)
        with SessionLocal() as session:
            openings = warehouse_repository.get_pull_request_openings(session, uuid.UUID(str(pull_request_id)))
            return [shop_assembly_opening_to_type(o) for o in openings]

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
                deficient_count=d["deficient_count"],
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
    async def create_receive(self, info: strawberry.Info, input: CreateReceiveInput) -> CreateReceiveResult:
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
            record = await asyncio.to_thread(_load_receive_type, uuid.UUID(state.result_id))
            return CreateReceiveResult(queued=False, outbox_entry_id=None, receive_record=record)

        received_by = await asyncio.to_thread(resolve_display_name, user["user_id"])
        gp_company, payload = await asyncio.to_thread(
            _prepare_create_receive, po_id=po_id, received_by=received_by, line_items_data=line_items_data
        )

        if state is not None and state.relay_result is not None:
            relay_result = state.relay_result
        else:
            try:
                relay_result = await relay_gateway.relay_call(gp_company, "create_receipt", payload)
            except RelayUnavailableError as e:
                # #353 PR E: the receipt never left the backend, so GP cannot have posted it - queue
                # it rather than failing a warehouse user who has already counted the hardware. A
                # DISPATCHED failure is re-raised: GP may hold the receipt, and a blind retry would
                # double-count inventory.
                if not gp_outbox_enqueue.may_enqueue(e):
                    raise
                project_id, label = await asyncio.to_thread(_receive_outbox_identity, po_id)
                entry_id = await asyncio.to_thread(
                    gp_outbox_enqueue.enqueue,
                    idempotency_key=key,
                    op="create_receive",
                    relay_op="create_receipt",
                    company=gp_company,
                    payload=payload,
                    persist_context={
                        "po_id": str(po_id),
                        "received_by": received_by,
                        "warehouse_id": str(warehouse_id) if warehouse_id else None,
                        "line_items_data": [
                            {
                                "po_line_item_id": str(li["po_line_item_id"]),
                                "quantity_received": li["quantity_received"],
                                "locations": li["locations"],
                            }
                            for li in line_items_data
                        ],
                    },
                    # Same entity_key as register_po_in_gp so a receipt can never be drained ahead of
                    # the registration of the PO it is against.
                    entity_key=f"po:{po_id}",
                    label=label,
                    project_id=project_id,
                    requested_by=user["user_id"],
                )
                # Nothing is in inventory yet - the persist is deferred with the GP write.
                return CreateReceiveResult(queued=True, outbox_entry_id=strawberry.ID(entry_id), receive_record=None)
            await asyncio.to_thread(gp_idempotency.record_relay_result, key, "create_receive", relay_result)

        record = await asyncio.to_thread(
            _persist_create_receive,
            key=key,
            po_id=po_id,
            received_by=received_by,
            line_items_data=line_items_data,
            warehouse_id=warehouse_id,
            relay_result=relay_result,
        )
        return CreateReceiveResult(queued=False, outbox_entry_id=None, receive_record=record)

    # Pull Requests - the pick (#367)
    @strawberry.mutation
    def start_pull_request_pick(self, info: strawberry.Info, id: strawberry.ID, started_by: str) -> PullRequest:
        """Claim a pending pull and open it for picking (#367). Nothing moves in inventory.

        This is what `approvePullRequest` used to be, minus everything that touched stock. The
        deduction, the sufficiency question and the consumption of the source request's claim all
        belong to `confirmPick` now, because until somebody has walked the racks nobody knows what
        was picked or from where.

        Open to any signed-in user - it assigns the pull to the caller, so it must not be reachable
        anonymously."""
        require_user(info)
        with SessionLocal() as session:
            pr = warehouse_repository.start_pull_request_pick(session, uuid.UUID(str(id)), started_by)
            session.commit()
            pr = warehouse_repository.get_pull_request_details(session, pr.id)
            staging = warehouse_repository.get_pull_staging_summaries(session, [pr.id])
            return pull_request_to_type(pr, staging.get(pr.id), partially_picked=False)

    @strawberry.mutation
    def save_pick_draft(
        self,
        info: strawberry.Info,
        pull_request_id: strawberry.ID,
        lines: list[PickLineInput],
        entered_by: str,
    ) -> PickSheet:
        """Save the half-keyed pick sheet without moving anything (#367).

        Replace-all rather than merge: the picker is transcribing a piece of paper, and a save says
        "this is the sheet now". Shape is validated; availability deliberately is not, because a
        draft is a note and blocking it while the numbers are mid-entry would make the button useless
        exactly when it is wanted.

        Open to any signed-in user - it attributes a user action, same rationale as
        `saveAssemblyProgress`."""
        require_user(info)
        with SessionLocal() as session:
            sheet = warehouse_repository.save_pick_draft(
                session,
                uuid.UUID(str(pull_request_id)),
                _pick_lines_from_input(lines),
                entered_by,
            )
            # `save_pick_draft` already returns the rebuilt sheet, so it is converted here rather
            # than read a second time: this is the picker's most frequent action, and re-running the
            # whole sheet read over Railway's network hop would double its cost for nothing. Built
            # before the commit, because expire_on_commit would leave the ORM objects detached.
            pr_id = sheet.pull_request.id
            staging = warehouse_repository.get_pull_staging_summaries(session, [pr_id])
            partial = pr_id in warehouse_repository.get_partially_picked_pull_ids(session, [pr_id])
            result = pick_sheet_to_type(sheet, staging.get(pr_id), partially_picked=partial)
            session.commit()
            return result

    @strawberry.mutation
    def confirm_pick(
        self,
        info: strawberry.Info,
        pull_request_id: strawberry.ID,
        lines: list[PickLineInput],
        picked_by: str,
    ) -> ConfirmPickResult:
        """Deduct exactly the rows the picker dictated, and consume the claim behind them (#367).

        The atomic swap that used to live in `approvePullRequest`, moved to the moment somebody has
        actually been to the racks: the source request's reservation is consumed for what is being
        picked and those units come off the exact rows named, in one transaction under the pull's
        lock and the locks of every named row.

        No row may give up more than its available units and no combo may exceed what the pull asked
        for - both hard, neither negotiable from the client. A confirmation that does not cover
        everything returns SHORT: what was entered is deducted, the pull stays In Progress and
        un-picked, purchasing is notified once, and a later confirmation enters the remainder.

        Open to any signed-in user - it writes inventory, so it must not be reachable anonymously."""
        require_user(info)
        with SessionLocal() as session:
            result = warehouse_repository.confirm_pick(
                session,
                uuid.UUID(str(pull_request_id)),
                _pick_lines_from_input(lines),
                picked_by,
            )
            notification = notification_to_type(result.notification) if result.notification else None
            shortfalls = [
                InventoryShortfall(
                    hardware_category=s.hardware_category,
                    product_code=s.product_code,
                    requested=s.requested,
                    available=s.available,
                    short=s.short,
                    reserved=s.reserved,
                )
                for s in result.shortfalls
            ]
            outcome = PickOutcome.PICKED if result.outcome == "PICKED" else PickOutcome.SHORT
            applied_quantity = result.applied_quantity
            session.commit()

            pr = warehouse_repository.get_pull_request_details(session, uuid.UUID(str(pull_request_id)))
            staging = warehouse_repository.get_pull_staging_summaries(session, [pr.id])
            partial = (
                pr.id in warehouse_repository.get_partially_picked_pull_ids(session, [pr.id])
                if pr.picked_at is None
                else None
            )
            return ConfirmPickResult(
                pull_request=pull_request_to_type(pr, staging.get(pr.id), partially_picked=partial),
                outcome=outcome,
                notification=notification,
                shortfalls=shortfalls,
                applied_quantity=applied_quantity,
            )

    @strawberry.mutation
    def set_pull_item_fetched(
        self,
        info: strawberry.Info,
        item_id: strawberry.ID,
        fetched: bool,
        fetched_by: str,
    ) -> PullRequestItem:
        """Tick (or untick) one assembled leaf off a shipping pull's fetch list (#367).

        Nothing moves in inventory - the leaf's hardware left it at assembly. The check-off is
        persisted so it survives a reload or a shift change, and unticking is supported because a
        picker who ticked the wrong leaf must be able to say so.

        Open to any signed-in user - it attributes a user action."""
        require_user(info)
        with SessionLocal() as session:
            item = warehouse_repository.set_pull_item_fetched(session, uuid.UUID(str(item_id)), fetched, fetched_by)
            session.commit()
            session.refresh(item)
            return pull_request_item_to_type(item)

    @strawberry.mutation
    def complete_pull_request(self, id: strawberry.ID, completed_by: str | None = None) -> PullRequest:
        """Close the whole pull in one go. Since #343 this reads as "stage everything still
        outstanding and finish": any opening not yet confirmed individually is flipped to PULLED and
        stamped here. `completedBy` is optional and additive - it only names the actor on those
        stamps, so existing callers are unaffected."""
        with SessionLocal() as session:
            pr = warehouse_repository.complete_pull_request(session, uuid.UUID(str(id)), completed_by=completed_by)
            session.commit()
            pr = warehouse_repository.get_pull_request_details(session, pr.id)
            staging = warehouse_repository.get_pull_staging_summaries(session, [pr.id])
            return pull_request_to_type(pr, staging.get(pr.id), _partially_picked(session, pr))

    @strawberry.mutation
    def stage_pull_openings(self, info: strawberry.Info, input: StagePullOpeningsInput) -> StagePullOpeningsResult:
        """Confirm that the carts for these openings of an approved shop-assembly pull are built (#343).

        Each confirmed opening flips to PULLED on its own and becomes assignable and workable
        immediately, so the assignment board fills as the warehouse picks rather than all at once at
        the end. Nothing moves in inventory: the FIFO deduction and the source request's reservation
        were both spent at approval, and staging is progress tracking. Staging the last opening
        completes the pull through the ordinary completion path, so its notification and any
        replacement-arrival application still happen exactly once.

        Open to any signed-in user - it makes hardware workable, so it must not be reachable
        anonymously."""
        require_user(info)
        with SessionLocal() as session:
            result = warehouse_repository.stage_pull_openings(
                session,
                uuid.UUID(str(input.pull_request_id)),
                [uuid.UUID(str(oid)) for oid in input.opening_ids],
                input.staged_by,
            )
            session.commit()
            pr = warehouse_repository.get_pull_request_details(session, result.pull_request.id)
            staging = warehouse_repository.get_pull_staging_summaries(session, [pr.id])
            openings = warehouse_repository.get_pull_request_openings(session, pr.id)
            return StagePullOpeningsResult(
                pull_request=pull_request_to_type(pr, staging.get(pr.id), _partially_picked(session, pr)),
                openings=[shop_assembly_opening_to_type(o) for o in openings],
                newly_staged_opening_ids=[strawberry.ID(str(oid)) for oid in result.newly_staged_ids],
                completed=result.completed,
            )

    @strawberry.mutation
    def cancel_pull_request(self, info: strawberry.Info, input: CancelPullRequestInput) -> CancelPullRequestResult:
        """Cancel an approved pull, return its hardware to inventory, and hand the source request
        back for re-acceptance (#343).

        All-or-nothing: any opening whose assembly has started or finished refuses the whole
        cancellation with a CONFLICT naming the blockers, because there is nowhere honest to park a
        half-cancelled pull. Everything short of that comes back, staged openings included - their
        hardware is on a cart in the shop, not on a leaf. The source request returns to PENDING and
        its claim is re-created from the returned quantities if availability still allows; if it does
        not, the request is left unreserved and flagged rather than half-claimed.

        Open to any signed-in user - it writes inventory, so it must not be reachable anonymously."""
        require_user(info)
        with SessionLocal() as session:
            result = warehouse_repository.cancel_pull_request(
                session,
                uuid.UUID(str(input.id)),
                input.cancelled_by,
                input.reason,
            )
            session.commit()
            pr = warehouse_repository.get_pull_request_details(session, result.pull_request.id)
            return CancelPullRequestResult(
                pull_request=pull_request_to_type(pr, partially_picked=_partially_picked(session, pr)),
                restocked=[
                    RestockedLine(
                        hardware_category=r.hardware_category,
                        product_code=r.product_code,
                        quantity=r.quantity,
                    )
                    for r in result.restocked
                ],
                released_opening_ids=[strawberry.ID(str(oid)) for oid in result.released_opening_ids],
                source_request_returned_to_pending=result.source_request_returned_to_pending,
                reservations_recreated=result.reservations_recreated,
                integrity_note=result.integrity_note,
            )

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
