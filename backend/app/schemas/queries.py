import uuid
from typing import Optional

import strawberry
from sqlalchemy import select

from app.database import SessionLocal
from app.models.project import Project as ProjectModel
from app.models.enums import POStatus as DBPOStatus
from app.repositories import po_repository, warehouse_repository, shop_assembly_repository
from .enums import (
    POStatus,
    Classification,
    PullRequestSource,
    PullRequestStatus,
    ShopAssemblyRequestStatus,
)
from .inputs import ReconciliationItemInput
from .types import (
    Project,
    Opening,
    PurchaseOrder,
    POLineItem,
    ReceiveRecord,
    ReceiveLineItem,
    POStatistics,
    InventoryHierarchyNode,
    ProductCodeNode,
    InventoryLocation as InventoryLocationType,
    InventoryItemDetail,
    OpeningItem,
    OpeningItemDetail,
    OpeningItemHardware as OpeningItemHardwareType,
    PullRequest,
    PullRequestItem,
    ShipReadyItems,
    Notification,
    ShopAssemblyRequest,
    ShopAssemblyOpening,
    ShopAssemblyOpeningItem,
    ReconciliationResult,
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


def _po_to_type(po, receive_records=None) -> PurchaseOrder:
    return PurchaseOrder(
        id=strawberry.ID(str(po.id)),
        po_number=po.po_number,
        project_id=strawberry.ID(str(po.project_id)),
        status=po.status,
        vendor_name=po.vendor_name,
        vendor_contact=po.vendor_contact,
        expected_delivery_date=po.expected_delivery_date,
        ordered_at=po.ordered_at,
        created_at=po.created_at,
        updated_at=po.updated_at,
        line_items=[_po_line_item_to_type(li) for li in po.line_items],
        receive_records=[
            _receive_record_to_type(rr) for rr in (receive_records or [])
        ],
    )


def _project_to_type(p: ProjectModel) -> Project:
    return Project(
        id=strawberry.ID(str(p.id)),
        project_id=p.project_id,
        description=p.description,
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
        shelf=il.shelf,
        column=il.column,
        row=il.row,
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
        shelf=oi.shelf,
        column=oi.column,
        row=oi.row,
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


def _shop_assembly_opening_to_type(opening) -> ShopAssemblyOpening:
    return ShopAssemblyOpening(
        id=strawberry.ID(str(opening.id)),
        shop_assembly_request_id=strawberry.ID(str(opening.shop_assembly_request_id)),
        opening_id=strawberry.ID(str(opening.opening_id)),
        pull_status=opening.pull_status,
        assigned_to=opening.assigned_to,
        assembly_status=opening.assembly_status,
        completed_at=opening.completed_at,
        items=[_shop_assembly_opening_item_to_type(i) for i in opening.items],
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


@strawberry.type
class Query:
    @strawberry.field
    def projects(self) -> list[Project]:
        with SessionLocal() as session:
            stmt = select(ProjectModel).order_by(ProjectModel.created_at.desc())
            results = session.scalars(stmt).unique().all()
            return [_project_to_type(p) for p in results]

    @strawberry.field
    def project_by_schedule_id(self, project_id: str) -> Optional[Project]:
        with SessionLocal() as session:
            stmt = select(ProjectModel).where(
                ProjectModel.project_id == project_id
            )
            p = session.scalars(stmt).unique().first()
            if p is None:
                return None
            return _project_to_type(p)

    @strawberry.field
    def reconcile_schedule(
        self, project_id: strawberry.ID, items: list[ReconciliationItemInput]
    ) -> list[ReconciliationResult]:
        raise NotImplementedError("reconcileSchedule not yet implemented")

    @strawberry.field
    def purchase_orders(
        self, project_id: strawberry.ID, status: Optional[POStatus] = None
    ) -> list[PurchaseOrder]:
        with SessionLocal() as session:
            pos = po_repository.get_purchase_orders(
                session, uuid.UUID(str(project_id)), status
            )
            return [_po_to_type(po) for po in pos]

    @strawberry.field
    def purchase_order(self, id: strawberry.ID) -> Optional[PurchaseOrder]:
        with SessionLocal() as session:
            po = po_repository.get_purchase_order(session, uuid.UUID(str(id)))
            if po is None:
                return None
            receive_records = po_repository.get_receive_records_for_po(
                session, po.id
            )
            return _po_to_type(po, receive_records)

    @strawberry.field
    def po_statistics(self, project_id: strawberry.ID) -> POStatistics:
        with SessionLocal() as session:
            stats = po_repository.get_po_statistics(
                session, uuid.UUID(str(project_id))
            )
            return POStatistics(
                total=stats["total"],
                draft=stats["draft"],
                ordered=stats["ordered"],
                partially_received=stats["partially_received"],
                closed=stats["closed"],
                cancelled=stats["cancelled"],
            )

    @strawberry.field
    def open_p_os(self, project_id: strawberry.ID) -> list[PurchaseOrder]:
        from sqlalchemy.orm import selectinload
        from app.models.purchase_order import PurchaseOrder as POModel

        with SessionLocal() as session:
            stmt = (
                select(POModel)
                .options(selectinload(POModel.line_items))
                .where(
                    POModel.project_id == uuid.UUID(str(project_id)),
                    POModel.deleted_at.is_(None),
                    POModel.status.in_([
                        DBPOStatus.ORDERED,
                        DBPOStatus.PARTIALLY_RECEIVED,
                    ]),
                )
                .order_by(POModel.ordered_at.asc())
            )
            pos = session.scalars(stmt).unique().all()
            return [_po_to_type(po) for po in pos]

    @strawberry.field
    def po_receiving_details(self, po_id: strawberry.ID) -> PurchaseOrder:
        with SessionLocal() as session:
            po, receive_records = warehouse_repository.get_po_receiving_details(
                session, uuid.UUID(str(po_id))
            )
            return _po_to_type(po, receive_records)

    @strawberry.field
    def inventory_hierarchy(
        self, project_id: strawberry.ID
    ) -> list[InventoryHierarchyNode]:
        with SessionLocal() as session:
            hierarchy = warehouse_repository.get_inventory_hierarchy(
                session, uuid.UUID(str(project_id))
            )
            return [
                InventoryHierarchyNode(
                    hardware_category=cat_node["hardware_category"],
                    product_codes=[
                        ProductCodeNode(
                            product_code=pc_node["product_code"],
                            items=[_inventory_location_to_type(il) for il in pc_node["items"]],
                            total_quantity=pc_node["total_quantity"],
                        )
                        for pc_node in cat_node["product_codes"]
                    ],
                    total_quantity=cat_node["total_quantity"],
                )
                for cat_node in hierarchy
            ]

    @strawberry.field
    def inventory_items(
        self, project_id: strawberry.ID, category: str, product_code: str
    ) -> list[InventoryItemDetail]:
        with SessionLocal() as session:
            items = warehouse_repository.get_inventory_items(
                session, uuid.UUID(str(project_id)), category, product_code
            )
            return [
                InventoryItemDetail(
                    inventory_location=_inventory_location_to_type(item["inventory_location"]),
                    po_number=item["po_number"],
                    classification=item["classification"],
                )
                for item in items
            ]

    @strawberry.field
    def opening_items(self, project_id: strawberry.ID) -> list[OpeningItem]:
        with SessionLocal() as session:
            ois = warehouse_repository.get_opening_items(
                session, uuid.UUID(str(project_id))
            )
            return [_opening_item_to_type(oi) for oi in ois]

    @strawberry.field
    def opening_item_details(self, id: strawberry.ID) -> OpeningItemDetail:
        with SessionLocal() as session:
            oi = warehouse_repository.get_opening_item_details(
                session, uuid.UUID(str(id))
            )
            opening_item = _opening_item_to_type(oi)
            return OpeningItemDetail(
                opening_item=opening_item,
                installed_hardware=[_opening_item_hardware_to_type(h) for h in oi.installed_hardware],
            )

    @strawberry.field
    def pull_requests(
        self,
        project_id: strawberry.ID,
        source: Optional[PullRequestSource] = None,
        status: Optional[PullRequestStatus] = None,
    ) -> list[PullRequest]:
        with SessionLocal() as session:
            prs = warehouse_repository.get_pull_requests(
                session, uuid.UUID(str(project_id)), source, status
            )
            return [_pull_request_to_type(pr) for pr in prs]

    @strawberry.field
    def pull_request_details(self, id: strawberry.ID) -> PullRequest:
        with SessionLocal() as session:
            pr = warehouse_repository.get_pull_request_details(
                session, uuid.UUID(str(id))
            )
            return _pull_request_to_type(pr)

    @strawberry.field
    def ship_ready_items(self, project_id: strawberry.ID) -> ShipReadyItems:
        raise NotImplementedError("shipReadyItems not yet implemented")

    @strawberry.field
    def notifications(
        self,
        project_id: strawberry.ID,
        recipient_role: str,
        unread_only: Optional[bool] = None,
        limit: int = 5,
    ) -> list[Notification]:
        raise NotImplementedError("notifications not yet implemented")

    @strawberry.field
    def shop_assembly_requests(
        self,
        project_id: strawberry.ID,
        status: Optional[ShopAssemblyRequestStatus] = None,
    ) -> list[ShopAssemblyRequest]:
        with SessionLocal() as session:
            sars = shop_assembly_repository.get_shop_assembly_requests(
                session, uuid.UUID(str(project_id)), status
            )
            return [_shop_assembly_request_to_type(sar) for sar in sars]

    @strawberry.field
    def assemble_list(
        self, project_id: strawberry.ID
    ) -> list[ShopAssemblyOpening]:
        with SessionLocal() as session:
            openings = shop_assembly_repository.get_assemble_list(
                session, uuid.UUID(str(project_id))
            )
            return [_shop_assembly_opening_to_type(o) for o in openings]

    @strawberry.field
    def my_work(self, assigned_to: str) -> list[ShopAssemblyOpening]:
        raise NotImplementedError("myWork not yet implemented")
