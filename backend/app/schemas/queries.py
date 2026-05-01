import uuid

import strawberry
from sqlalchemy import select

from app.database import SessionLocal
from app.models.enums import POStatus as DBPOStatus
from app.models.project import Project as ProjectModel
from app.repositories import (
    admin_repository,
    notification_repository,
    po_repository,
    shipping_repository,
    shop_assembly_repository,
    user_repository,
    warehouse_layout_repository,
    warehouse_repository,
)

from .enums import (
    AuditEntityType,
    POStatus,
    PullRequestSource,
    PullRequestStatus,
    ShopAssemblyRequestStatus,
)
from .inputs import ReconciliationItemInput
from .types import (
    AuditLogEntry,
    BackOrderedItem,
    ClerkUser,
    HardwareSummaryRow,
    InventoryHierarchyNode,
    InventoryItemDetail,
    LocationContents,
    LocationUtilizationEntry,
    Notification,
    Opening,
    OpeningHardwareStatus,
    OpeningHardwareStatusItem,
    OpeningItem,
    OpeningItemDetail,
    PODocumentInfo,
    POLineItem,
    POStatistics,
    ProductCodeNode,
    Project,
    ProjectExcludedItem,
    PullRequest,
    PullRequestItem,
    PurchaseOrder,
    PutAwaySuggestion,
    ReceiveLineItem,
    ReceiveRecord,
    RecentReceiveRecord,
    ReconciliationResult,
    ShipReadyItems,
    ShipReadyLooseItem,
    ShopAssemblyOpening,
    ShopAssemblyOpeningItem,
    ShopAssemblyRequest,
    VendorInventoryNode,
    WarehouseAisleType,
    WarehouseBayType,
    WarehouseBinType,
    WarehouseDashboard,
    WarehouseRowType,
)
from .types import (
    InventoryLocation as InventoryLocationType,
)
from .types import (
    OpeningItemHardware as OpeningItemHardwareType,
)
from .types import (
    PackingSlip as PackingSlipType,
)
from .types import (
    PackingSlipItem as PackingSlipItemType,
)


def _po_line_item_to_type(li) -> POLineItem:
    return POLineItem(
        id=strawberry.ID(str(li.id)),
        po_id=strawberry.ID(str(li.po_id)),
        hardware_category=li.hardware_category,
        product_code=li.product_code,
        classification=li.classification,
        ordered_quantity=li.ordered_quantity,
        received_quantity=li.received_quantity,
        unit_cost=float(li.unit_cost),
        order_as=li.order_as,
        created_at=li.created_at,
        updated_at=li.updated_at,
    )


def _receive_line_item_to_type(rli) -> ReceiveLineItem:
    return ReceiveLineItem(
        id=strawberry.ID(str(rli.id)),
        receive_record_id=strawberry.ID(str(rli.receive_record_id)),
        po_line_item_id=strawberry.ID(str(rli.po_line_item_id)),
        hardware_category=rli.hardware_category,
        product_code=rli.product_code,
        quantity_received=rli.quantity_received,
        created_at=rli.created_at,
    )


def _receive_record_to_type(rr) -> ReceiveRecord:
    return ReceiveRecord(
        id=strawberry.ID(str(rr.id)),
        po_id=strawberry.ID(str(rr.po_id)),
        received_at=rr.received_at,
        received_by=rr.received_by,
        created_at=rr.created_at,
        line_items=[_receive_line_item_to_type(rli) for rli in rr.line_items],
    )


def _po_document_to_type(doc) -> PODocumentInfo:
    from app.services import storage

    return PODocumentInfo(
        id=strawberry.ID(str(doc.id)),
        po_id=strawberry.ID(str(doc.po_id)),
        file_name=doc.file_name,
        content_type=doc.content_type,
        file_size=doc.file_size,
        document_type=doc.document_type,
        uploaded_at=doc.uploaded_at,
        download_url=storage.generate_presigned_url(doc.s3_key),
    )


def _po_to_type(po, receive_records=None) -> PurchaseOrder:
    documents = getattr(po, "documents", None) or []
    return PurchaseOrder(
        id=strawberry.ID(str(po.id)),
        po_number=po.po_number,
        request_number=po.request_number,
        project_id=strawberry.ID(str(po.project_id)) if po.project_id else None,
        status=po.status,
        vendor_name=po.vendor_name,
        vendor_contact=po.vendor_contact,
        vendor_quote_number=po.vendor_quote_number,
        notes=po.notes,
        expected_delivery_date=po.expected_delivery_date,
        ordered_at=po.ordered_at,
        created_at=po.created_at,
        updated_at=po.updated_at,
        line_items=[_po_line_item_to_type(li) for li in po.line_items],
        receive_records=[_receive_record_to_type(rr) for rr in (receive_records or [])],
        documents=[_po_document_to_type(doc) for doc in documents],
    )


def _project_to_type(p: ProjectModel) -> Project:
    return Project(
        id=strawberry.ID(str(p.id)),
        project_id=p.project_id,
        description=p.description,
        client=p.client,
        job_site_name=p.job_site_name,
        address=p.address,
        city=p.city,
        state=p.state,
        zip=p.zip,
        contractor=p.contractor,
        project_manager=p.project_manager,
        application=p.application,
        submittal_job_no=p.submittal_job_no,
        submittal_assignment_count=p.submittal_assignment_count,
        estimator_code=p.estimator_code,
        titan_user_id=p.titan_user_id,
        created_at=p.created_at,
        updated_at=p.updated_at,
        openings=[
            Opening(
                id=strawberry.ID(str(o.id)),
                project_id=strawberry.ID(str(o.project_id)),
                opening_number=o.opening_number,
                building=o.building,
                floor=o.floor,
                location=o.location,
                location_to=o.location_to,
                location_from=o.location_from,
                hand=o.hand,
                width=o.width,
                length=o.length,
                door_thickness=o.door_thickness,
                jamb_thickness=o.jamb_thickness,
                door_type=o.door_type,
                frame_type=o.frame_type,
                interior_exterior=o.interior_exterior,
                keying=o.keying,
                heading_no=o.heading_no,
                single_pair=o.single_pair,
                assignment_multiplier=o.assignment_multiplier,
                created_at=o.created_at,
                updated_at=o.updated_at,
            )
            for o in p.openings
        ],
        purchase_orders=[],  # Loaded on demand in later tickets
    )


def _inventory_location_to_type(il) -> InventoryLocationType:
    return InventoryLocationType(
        id=strawberry.ID(str(il.id)),
        project_id=strawberry.ID(str(il.project_id)),
        po_line_item_id=strawberry.ID(str(il.po_line_item_id)),
        receive_line_item_id=strawberry.ID(str(il.receive_line_item_id)),
        hardware_category=il.hardware_category,
        product_code=il.product_code,
        quantity=il.quantity,
        aisle=il.aisle,
        row=il.row,
        bay=il.bay,
        bin=il.bin,
        received_at=il.received_at,
        created_at=il.created_at,
        updated_at=il.updated_at,
    )


def _opening_item_hardware_to_type(oih) -> OpeningItemHardwareType:
    return OpeningItemHardwareType(
        id=strawberry.ID(str(oih.id)),
        opening_item_id=strawberry.ID(str(oih.opening_item_id)),
        product_code=oih.product_code,
        hardware_category=oih.hardware_category,
        quantity=oih.quantity,
    )


def _opening_item_to_type(oi) -> OpeningItem:
    return OpeningItem(
        id=strawberry.ID(str(oi.id)),
        project_id=strawberry.ID(str(oi.project_id)),
        opening_id=strawberry.ID(str(oi.opening_id)),
        opening_number=oi.opening_number,
        building=oi.building,
        floor=oi.floor,
        location=oi.location,
        quantity=oi.quantity,
        assembly_completed_at=oi.assembly_completed_at,
        state=oi.state,
        aisle=oi.aisle,
        row=oi.row,
        bay=oi.bay,
        bin=oi.bin,
        created_at=oi.created_at,
        updated_at=oi.updated_at,
        installed_hardware=[_opening_item_hardware_to_type(h) for h in oi.installed_hardware],
    )


def _shop_assembly_opening_item_to_type(item) -> ShopAssemblyOpeningItem:
    return ShopAssemblyOpeningItem(
        id=strawberry.ID(str(item.id)),
        shop_assembly_opening_id=strawberry.ID(str(item.shop_assembly_opening_id)),
        hardware_category=item.hardware_category,
        product_code=item.product_code,
        quantity=item.quantity,
    )


def _shop_assembly_opening_to_type(opening, opening_model=None) -> ShopAssemblyOpening:
    return ShopAssemblyOpening(
        id=strawberry.ID(str(opening.id)),
        shop_assembly_request_id=strawberry.ID(str(opening.shop_assembly_request_id)),
        opening_id=strawberry.ID(str(opening.opening_id)),
        pull_status=opening.pull_status,
        assigned_to=opening.assigned_to,
        assembly_status=opening.assembly_status,
        completed_at=opening.completed_at,
        items=[_shop_assembly_opening_item_to_type(i) for i in opening.items],
        opening_number=opening_model.opening_number if opening_model else None,
        building=opening_model.building if opening_model else None,
        floor=opening_model.floor if opening_model else None,
    )


def _shop_assembly_request_to_type(sar) -> ShopAssemblyRequest:
    return ShopAssemblyRequest(
        id=strawberry.ID(str(sar.id)),
        request_number=sar.request_number,
        project_id=strawberry.ID(str(sar.project_id)),
        status=sar.status,
        created_by=sar.created_by,
        approved_by=sar.approved_by,
        rejected_by=sar.rejected_by,
        rejection_reason=sar.rejection_reason,
        created_at=sar.created_at,
        approved_at=sar.approved_at,
        rejected_at=sar.rejected_at,
        openings=[_shop_assembly_opening_to_type(o) for o in sar.openings],
    )


def _pull_request_item_to_type(item) -> PullRequestItem:
    return PullRequestItem(
        id=strawberry.ID(str(item.id)),
        pull_request_id=strawberry.ID(str(item.pull_request_id)),
        item_type=item.item_type,
        opening_number=item.opening_number,
        opening_item_id=strawberry.ID(str(item.opening_item_id)) if item.opening_item_id else None,
        hardware_category=item.hardware_category,
        product_code=item.product_code,
        requested_quantity=item.requested_quantity,
    )


def _pull_request_to_type(pr) -> PullRequest:
    return PullRequest(
        id=strawberry.ID(str(pr.id)),
        request_number=pr.request_number,
        project_id=strawberry.ID(str(pr.project_id)),
        source=pr.source,
        status=pr.status,
        requested_by=pr.requested_by,
        assigned_to=pr.assigned_to,
        created_at=pr.created_at,
        updated_at=pr.updated_at,
        approved_at=pr.approved_at,
        completed_at=pr.completed_at,
        cancelled_at=pr.cancelled_at,
        items=[_pull_request_item_to_type(i) for i in pr.items],
    )


def _notification_to_type(n) -> Notification:
    return Notification(
        id=strawberry.ID(str(n.id)),
        project_id=strawberry.ID(str(n.project_id)),
        recipient_role=n.recipient_role,
        type=n.type,
        message=n.message,
        is_read=n.is_read,
        created_at=n.created_at,
    )


def _packing_slip_item_to_type(psi) -> PackingSlipItemType:
    return PackingSlipItemType(
        id=strawberry.ID(str(psi.id)),
        packing_slip_id=strawberry.ID(str(psi.packing_slip_id)),
        item_type=psi.item_type,
        opening_item_id=strawberry.ID(str(psi.opening_item_id)) if psi.opening_item_id else None,
        opening_number=psi.opening_number,
        product_code=psi.product_code,
        hardware_category=psi.hardware_category,
        quantity=psi.quantity,
    )


def _packing_slip_to_type(ps) -> PackingSlipType:
    return PackingSlipType(
        id=strawberry.ID(str(ps.id)),
        packing_slip_number=ps.packing_slip_number,
        project_id=strawberry.ID(str(ps.project_id)),
        shipped_by=ps.shipped_by,
        shipped_at=ps.shipped_at,
        created_at=ps.created_at,
        items=[_packing_slip_item_to_type(i) for i in ps.items],
    )


def _bin_to_type(wbin) -> WarehouseBinType:
    return WarehouseBinType(
        id=strawberry.ID(str(wbin.id)),
        bay_id=strawberry.ID(str(wbin.bay_id)),
        row_id=strawberry.ID(str(wbin.row_id)) if wbin.row_id else None,
        name=wbin.name,
        row_position=wbin.row_position,
        col_position=wbin.col_position,
        capacity=wbin.capacity,
        is_active=wbin.is_active,
    )


def _row_to_type(row) -> WarehouseRowType:
    return WarehouseRowType(
        id=strawberry.ID(str(row.id)),
        aisle_id=strawberry.ID(str(row.aisle_id)),
        name=row.name,
        level=row.level,
        is_active=row.is_active,
    )


def _bay_to_type(bay) -> WarehouseBayType:
    return WarehouseBayType(
        id=strawberry.ID(str(bay.id)),
        aisle_id=strawberry.ID(str(bay.aisle_id)),
        name=bay.name,
        row_position=bay.row_position,
        col_position=bay.col_position,
        is_active=bay.is_active,
        bins=[_bin_to_type(b) for b in getattr(bay, "bins", [])],
    )


def _aisle_to_type(aisle, **kwargs) -> WarehouseAisleType:
    return WarehouseAisleType(
        id=strawberry.ID(str(aisle.id)),
        name=aisle.name,
        label=aisle.label,
        orientation=aisle.orientation,
        x_position=aisle.x_position,
        y_position=aisle.y_position,
        width=aisle.width,
        height=aisle.height,
        is_active=aisle.is_active,
        bays=[_bay_to_type(b) for b in getattr(aisle, "bays", [])],
        rows=[_row_to_type(r) for r in getattr(aisle, "rows", [])],
        **kwargs,
    )


@strawberry.type
class Query:
    @strawberry.field
    def projects(self) -> list[Project]:
        with SessionLocal() as session:
            stmt = select(ProjectModel).order_by(ProjectModel.created_at.desc())
            results = session.scalars(stmt).unique().all()
            return [_project_to_type(p) for p in results]

    @strawberry.field
    def project_by_schedule_id(self, project_id: str) -> Project | None:
        with SessionLocal() as session:
            stmt = select(ProjectModel).where(ProjectModel.project_id == project_id)
            p = session.scalars(stmt).unique().first()
            if p is None:
                return None
            return _project_to_type(p)

    @strawberry.field
    def reconcile_schedule(
        self, project_id: strawberry.ID, items: list[ReconciliationItemInput]
    ) -> list[ReconciliationResult]:
        from app.repositories import import_repository

        from .enums import ReconciliationStatus

        items_data = [
            {
                "opening_number": item.opening_number,
                "hardware_category": item.hardware_category,
                "product_code": item.product_code,
                "quantity_needed": item.quantity_needed,
            }
            for item in items
        ]
        with SessionLocal() as session:
            results = import_repository.reconcile_schedule(session, uuid.UUID(str(project_id)), items_data)
            return [
                ReconciliationResult(
                    opening_number=r["opening_number"],
                    hardware_category=r["hardware_category"],
                    product_code=r["product_code"],
                    quantity=r["quantity"],
                    status=ReconciliationStatus[r["status"]],
                )
                for r in results
            ]

    @strawberry.field
    def project_excluded_items(self, project_id: strawberry.ID) -> list[ProjectExcludedItem]:
        from app.models.project_excluded_item import ProjectExcludedItem as PEIModel

        with SessionLocal() as session:
            rows = session.scalars(select(PEIModel).where(PEIModel.project_id == uuid.UUID(str(project_id)))).all()
            return [
                ProjectExcludedItem(
                    hardware_category=row.hardware_category,
                    product_code=row.product_code,
                )
                for row in rows
            ]

    @strawberry.field
    def purchase_orders(
        self, project_id: strawberry.ID | None = None, status: POStatus | None = None
    ) -> list[PurchaseOrder]:
        with SessionLocal() as session:
            pid = uuid.UUID(str(project_id)) if project_id else None
            pos = po_repository.get_purchase_orders(session, pid, status)
            return [_po_to_type(po) for po in pos]

    @strawberry.field
    def po_document_download_url(self, document_id: strawberry.ID) -> str:
        from app.services import storage

        with SessionLocal() as session:
            doc = po_repository.get_po_document(session, uuid.UUID(str(document_id)))
            return storage.generate_presigned_url(doc.s3_key)

    @strawberry.field
    def purchase_order(self, id: strawberry.ID) -> PurchaseOrder | None:
        with SessionLocal() as session:
            po = po_repository.get_purchase_order(session, uuid.UUID(str(id)))
            if po is None:
                return None
            receive_records = po_repository.get_receive_records_for_po(session, po.id)
            return _po_to_type(po, receive_records)

    @strawberry.field
    def po_statistics(self, project_id: strawberry.ID | None = None) -> POStatistics:
        with SessionLocal() as session:
            stats = po_repository.get_po_statistics(session, uuid.UUID(str(project_id)) if project_id else None)
            return POStatistics(
                total=stats["total"],
                draft=stats["draft"],
                ordered=stats["ordered"],
                vendor_confirmed=stats["vendor_confirmed"],
                partially_received=stats["partially_received"],
                closed=stats["closed"],
                cancelled=stats["cancelled"],
            )

    @strawberry.field
    def open_p_os(self, project_id: strawberry.ID | None = None) -> list[PurchaseOrder]:
        from sqlalchemy.orm import selectinload

        from app.models.purchase_order import PurchaseOrder as POModel

        with SessionLocal() as session:
            stmt = (
                select(POModel)
                .options(selectinload(POModel.line_items), selectinload(POModel.documents))
                .where(
                    POModel.deleted_at.is_(None),
                    POModel.status.in_(
                        [
                            DBPOStatus.ORDERED,
                            DBPOStatus.VENDOR_CONFIRMED,
                            DBPOStatus.PARTIALLY_RECEIVED,
                        ]
                    ),
                )
                .order_by(POModel.ordered_at.asc())
            )
            if project_id:
                stmt = stmt.where(POModel.project_id == uuid.UUID(str(project_id)))
            pos = session.scalars(stmt).unique().all()
            return [_po_to_type(po) for po in pos]

    @strawberry.field
    def po_receiving_details(self, po_id: strawberry.ID) -> PurchaseOrder:
        with SessionLocal() as session:
            po, receive_records = warehouse_repository.get_po_receiving_details(session, uuid.UUID(str(po_id)))
            return _po_to_type(po, receive_records)

    @strawberry.field
    def inventory_hierarchy(self, project_id: strawberry.ID | None = None) -> list[InventoryHierarchyNode]:
        with SessionLocal() as session:
            hierarchy = warehouse_repository.get_inventory_hierarchy(
                session, uuid.UUID(str(project_id)) if project_id else None
            )
            return [
                InventoryHierarchyNode(
                    hardware_category=cat_node["hardware_category"],
                    product_codes=[
                        ProductCodeNode(
                            product_code=pc_node["product_code"],
                            items=[_inventory_location_to_type(il) for il in pc_node["items"]],
                            total_quantity=pc_node["total_quantity"],
                            total_value=pc_node["total_value"],
                        )
                        for pc_node in cat_node["product_codes"]
                    ],
                    total_quantity=cat_node["total_quantity"],
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
                    inventory_location=_inventory_location_to_type(item["inventory_location"]),
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
                    inventory_location=_inventory_location_to_type(item["inventory_location"]),
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
                    receive_record=_receive_record_to_type(rr),
                    po_number=po.po_number,
                    total_items_received=sum(rli.quantity_received for rli in rr.line_items),
                )
                for rr, po in rows
            ]

    @strawberry.field
    def opening_items(self, project_id: strawberry.ID | None = None) -> list[OpeningItem]:
        with SessionLocal() as session:
            ois = warehouse_repository.get_opening_items(session, uuid.UUID(str(project_id)) if project_id else None)
            return [_opening_item_to_type(oi) for oi in ois]

    @strawberry.field
    def opening_item_details(self, id: strawberry.ID) -> OpeningItemDetail:
        with SessionLocal() as session:
            oi = warehouse_repository.get_opening_item_details(session, uuid.UUID(str(id)))
            opening_item = _opening_item_to_type(oi)
            return OpeningItemDetail(
                opening_item=opening_item,
                installed_hardware=[_opening_item_hardware_to_type(h) for h in oi.installed_hardware],
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
            return [_pull_request_to_type(pr) for pr in prs]

    @strawberry.field
    def pull_request_details(self, id: strawberry.ID) -> PullRequest:
        with SessionLocal() as session:
            pr = warehouse_repository.get_pull_request_details(session, uuid.UUID(str(id)))
            return _pull_request_to_type(pr)

    @strawberry.field
    def ship_ready_items(self, project_id: strawberry.ID | None = None) -> ShipReadyItems:
        with SessionLocal() as session:
            data = shipping_repository.get_ship_ready_items(session, uuid.UUID(str(project_id)) if project_id else None)
            return ShipReadyItems(
                opening_items=[_opening_item_to_type(oi) for oi in data["opening_items"]],
                loose_items=[
                    ShipReadyLooseItem(
                        opening_number=li["opening_number"],
                        hardware_category=li["hardware_category"],
                        product_code=li["product_code"],
                        available_quantity=li["available_quantity"],
                    )
                    for li in data["loose_items"]
                ],
            )

    @strawberry.field
    def notifications(
        self,
        project_id: strawberry.ID | None = None,
        recipient_role: str = "",
        unread_only: bool | None = None,
        limit: int = 5,
    ) -> list[Notification]:
        with SessionLocal() as session:
            results = notification_repository.get_notifications(
                session,
                uuid.UUID(str(project_id)) if project_id else None,
                recipient_role,
                unread_only,
                limit,
            )
            return [_notification_to_type(n) for n in results]

    @strawberry.field
    def shop_assembly_requests(
        self,
        project_id: strawberry.ID | None = None,
        status: ShopAssemblyRequestStatus | None = None,
    ) -> list[ShopAssemblyRequest]:
        with SessionLocal() as session:
            sars = shop_assembly_repository.get_shop_assembly_requests(
                session, uuid.UUID(str(project_id)) if project_id else None, status
            )
            return [_shop_assembly_request_to_type(sar) for sar in sars]

    @strawberry.field
    def assemble_list(self, project_id: strawberry.ID | None = None) -> list[ShopAssemblyOpening]:
        with SessionLocal() as session:
            rows = shop_assembly_repository.get_assemble_list(
                session, uuid.UUID(str(project_id)) if project_id else None
            )
            return [_shop_assembly_opening_to_type(sao, opening_model=opening) for sao, opening in rows]

    @strawberry.field
    def my_work(self, assigned_to: str) -> list[ShopAssemblyOpening]:
        with SessionLocal() as session:
            rows = shop_assembly_repository.get_my_work(session, assigned_to)
            return [_shop_assembly_opening_to_type(sao, opening_model=opening) for sao, opening in rows]

    @strawberry.field
    def hardware_summary(self, project_id: strawberry.ID | None = None) -> list[HardwareSummaryRow]:
        with SessionLocal() as session:
            rows = admin_repository.get_hardware_summary(session, uuid.UUID(str(project_id)) if project_id else None)
            return [
                HardwareSummaryRow(
                    hardware_category=r["hardware_category"],
                    product_code=r["product_code"],
                    po_drafted=r["po_drafted"],
                    ordered=r["ordered"],
                    received=r["received"],
                    back_ordered=r["back_ordered"],
                    shipped_out=r["shipped_out"],
                )
                for r in rows
            ]

    @strawberry.field
    def opening_hardware_status(self, project_id: strawberry.ID | None = None) -> list[OpeningHardwareStatus]:
        with SessionLocal() as session:
            rows = admin_repository.get_opening_hardware_status(
                session, uuid.UUID(str(project_id)) if project_id else None
            )
            return [
                OpeningHardwareStatus(
                    opening_number=r["opening_number"],
                    building=r["building"],
                    floor=r["floor"],
                    location=r["location"],
                    items=[
                        OpeningHardwareStatusItem(
                            hardware_category=item["hardware_category"],
                            product_code=item["product_code"],
                            item_quantity=item["item_quantity"],
                            status=item["status"],
                        )
                        for item in r["items"]
                    ],
                )
                for r in rows
            ]

    @strawberry.field
    def users(self) -> list[ClerkUser]:
        results = user_repository.list_users()
        return [
            ClerkUser(
                id=u["id"],
                first_name=u["first_name"],
                last_name=u["last_name"],
                email=u["email"],
                roles=u["roles"],
                image_url=u["image_url"],
            )
            for u in results
        ]

    @strawberry.field
    def expected_deliveries(self, project_id: strawberry.ID | None = None) -> list[PurchaseOrder]:
        with SessionLocal() as session:
            pos = warehouse_repository.get_expected_deliveries(
                session, uuid.UUID(str(project_id)) if project_id else None
            )
            return [_po_to_type(po) for po in pos]

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
                            items=[_inventory_location_to_type(il) for il in pc["items"]],
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
    def location_contents(self, aisle: str, bay: str | None = None, bin: str | None = None) -> LocationContents:
        with SessionLocal() as session:
            data = warehouse_repository.get_location_contents(session, aisle, bay, bin)
            return LocationContents(
                inventory_items=[
                    InventoryItemDetail(
                        inventory_location=_inventory_location_to_type(item["inventory_location"]),
                        po_number=item["po_number"],
                        classification=None,
                        unit_cost=item["unit_cost"],
                    )
                    for item in data["inventory_items"]
                ],
                opening_items=[_opening_item_to_type(oi) for oi in data["opening_items"]],
            )

    @strawberry.field
    def location_utilization(self) -> list[LocationUtilizationEntry]:
        with SessionLocal() as session:
            rows = warehouse_repository.get_location_utilization(session)
            return [
                LocationUtilizationEntry(
                    aisle=r["aisle"],
                    row=r.get("row"),
                    bay=r["bay"],
                    bin=r["bin"],
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

    # --- Warehouse Layout queries ---

    @strawberry.field
    def warehouse_aisles(self, active_only: bool = True) -> list[WarehouseAisleType]:
        with SessionLocal() as session:
            aisles = warehouse_layout_repository.get_aisles(session, active_only)
            return [_aisle_to_type(a) for a in aisles]

    @strawberry.field
    def warehouse_bays(self, aisle_id: strawberry.ID) -> list[WarehouseBayType]:
        with SessionLocal() as session:
            bays = warehouse_layout_repository.get_bays(session, uuid.UUID(str(aisle_id)))
            return [_bay_to_type(b) for b in bays]

    @strawberry.field
    def warehouse_rows(self, aisle_id: strawberry.ID) -> list[WarehouseRowType]:
        with SessionLocal() as session:
            rows = warehouse_layout_repository.get_rows(session, uuid.UUID(str(aisle_id)))
            return [_row_to_type(r) for r in rows]

    @strawberry.field
    def warehouse_bins(self, bay_id: strawberry.ID, row_id: strawberry.ID | None = None) -> list[WarehouseBinType]:
        with SessionLocal() as session:
            bins = warehouse_layout_repository.get_bins(
                session,
                uuid.UUID(str(bay_id)),
                uuid.UUID(str(row_id)) if row_id else None,
            )
            return [_bin_to_type(b) for b in bins]

    @strawberry.field
    def warehouse_overview(self) -> list[WarehouseAisleType]:
        with SessionLocal() as session:
            rows = warehouse_layout_repository.get_aisle_utilization(session)
            return [
                _aisle_to_type(
                    r["aisle"],
                    total_quantity=r["total_quantity"],
                    item_count=r["item_count"],
                    total_capacity=r["total_capacity"],
                )
                for r in rows
            ]

    @strawberry.field
    def suggest_put_away(
        self,
        product_code: str,
        hardware_category: str,
        quantity: int = 1,
    ) -> list[PutAwaySuggestion]:
        with SessionLocal() as session:
            suggestions = warehouse_layout_repository.suggest_put_away(
                session,
                product_code,
                hardware_category,
                quantity,
            )
            return [
                PutAwaySuggestion(
                    aisle=s["aisle"],
                    bay=s["bay"],
                    bin=s["bin"],
                    reason=s["reason"],
                    current_quantity=s["current_quantity"],
                    capacity=s["capacity"],
                )
                for s in suggestions
            ]
