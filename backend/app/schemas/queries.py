from typing import Optional

import strawberry
from sqlalchemy import select

from app.database import SessionLocal
from app.models.project import Project as ProjectModel
from .enums import (
    POStatus,
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
    InventoryItemDetail,
    OpeningItem,
    OpeningItemDetail,
    PullRequest,
    ShipReadyItems,
    Notification,
    ShopAssemblyRequest,
    ShopAssemblyOpening,
    ReconciliationResult,
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
        raise NotImplementedError("purchaseOrders not yet implemented")

    @strawberry.field
    def purchase_order(self, id: strawberry.ID) -> Optional[PurchaseOrder]:
        raise NotImplementedError("purchaseOrder not yet implemented")

    @strawberry.field
    def po_statistics(self, project_id: strawberry.ID) -> POStatistics:
        raise NotImplementedError("poStatistics not yet implemented")

    @strawberry.field
    def open_p_os(self, project_id: strawberry.ID) -> list[PurchaseOrder]:
        raise NotImplementedError("openPOs not yet implemented")

    @strawberry.field
    def po_receiving_details(self, po_id: strawberry.ID) -> PurchaseOrder:
        raise NotImplementedError("poReceivingDetails not yet implemented")

    @strawberry.field
    def inventory_hierarchy(
        self, project_id: strawberry.ID
    ) -> list[InventoryHierarchyNode]:
        raise NotImplementedError("inventoryHierarchy not yet implemented")

    @strawberry.field
    def inventory_items(
        self, project_id: strawberry.ID, category: str, product_code: str
    ) -> list[InventoryItemDetail]:
        raise NotImplementedError("inventoryItems not yet implemented")

    @strawberry.field
    def opening_items(self, project_id: strawberry.ID) -> list[OpeningItem]:
        raise NotImplementedError("openingItems not yet implemented")

    @strawberry.field
    def opening_item_details(self, id: strawberry.ID) -> OpeningItemDetail:
        raise NotImplementedError("openingItemDetails not yet implemented")

    @strawberry.field
    def pull_requests(
        self,
        project_id: strawberry.ID,
        source: Optional[PullRequestSource] = None,
        status: Optional[PullRequestStatus] = None,
    ) -> list[PullRequest]:
        raise NotImplementedError("pullRequests not yet implemented")

    @strawberry.field
    def pull_request_details(self, id: strawberry.ID) -> PullRequest:
        raise NotImplementedError("pullRequestDetails not yet implemented")

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
        raise NotImplementedError("shopAssemblyRequests not yet implemented")

    @strawberry.field
    def assemble_list(
        self, project_id: strawberry.ID
    ) -> list[ShopAssemblyOpening]:
        raise NotImplementedError("assembleList not yet implemented")

    @strawberry.field
    def my_work(self, assigned_to: str) -> list[ShopAssemblyOpening]:
        raise NotImplementedError("myWork not yet implemented")
