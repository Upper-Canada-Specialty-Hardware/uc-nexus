import uuid

import strawberry
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.auth import require_admin, require_user
from app.database import SessionLocal
from app.models.enums import POStatus as DBPOStatus
from app.models.project import Opening as OpeningModel
from app.models.project import Project as ProjectModel
from app.repositories import (
    admin_repository,
    dashboard_repository,
    notification_repository,
    po_repository,
    relay_repository,
    shipping_repository,
    shop_assembly_repository,
    stock_repository,
    user_repository,
    vendor_repository,
    warehouse_admin_repository,
    warehouse_repository,
)
from app.services.relay_gateway import gateway as relay_gateway

from .enums import (
    AuditEntityType,
    DeficientItemSource,
    POStatus,
    PullRequestSource,
    PullRequestStatus,
    ShopAssemblyRequestStatus,
)
from .inputs import ReconciliationItemInput
from .types import (
    AdminStats,
    AuditLogEntry,
    BackOrderedItem,
    ClerkUser,
    DeficientItemRow,
    GpCostCode,
    GpJob,
    GpVendor,
    HomeDashboardStats,
    InventoryHierarchyNode,
    InventoryItemDetail,
    LocationContents,
    LocationDistinctValues,
    LocationDuplicateGroup,
    LocationUtilizationEntry,
    LocationVariant,
    Notification,
    Opening,
    OpeningHardwareStatus,
    OpeningHardwareStatusItem,
    OpeningItem,
    OpeningItemDetail,
    PODocumentInfo,
    POLineItem,
    POStatistics,
    PriorOrderAsForProduct,
    ProductCodeNode,
    Project,
    ProjectExcludedItem,
    ProjectHardwareSchedule,
    ProjectProgressByProduct,
    ProjectScheduleHardwareItem,
    PullRequest,
    PullRequestItem,
    PurchaseOrder,
    ReceiveLineItem,
    ReceiveRecord,
    RecentReceiveRecord,
    ReconciliationResult,
    RelayCredential,
    RelayInstallInfo,
    RelayStatus,
    ReturnableLine,
    ShipmentReturn,
    ShipmentReturnItem,
    ShipReadyItems,
    ShipReadyLooseItem,
    ShopAssemblyOpening,
    ShopAssemblyOpeningItem,
    ShopAssemblyRequest,
    ShopAssemblyStats,
    Vendor,
    VendorInventoryNode,
    Warehouse,
    WarehouseDashboard,
)
from .types import (
    DeficiencyReview as DeficiencyReviewType,
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
from .types import (
    StockItem as StockItemType,
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
        gp_line_ord=li.gp_line_ord,
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


def _vendor_to_type(v) -> Vendor:
    return Vendor(
        id=strawberry.ID(str(v.id)),
        name=v.name,
        gp_vendor_id=v.gp_vendor_id,
        contact_name=v.contact_name,
        email=v.email,
        phone=v.phone,
        notes=v.notes,
        created_at=v.created_at,
        updated_at=v.updated_at,
    )


def _relay_install_to_type(ri) -> RelayInstallInfo:
    return RelayInstallInfo(
        id=strawberry.ID(str(ri.id)),
        label=ri.label,
        company=ri.company,
        hostname=ri.hostname,
        enrolled=ri.enrolled_at is not None,
        enrolled_at=ri.enrolled_at,
        last_seen_at=ri.last_seen_at,
        created_at=ri.created_at,
    )


def _gp_job_to_type(j: dict) -> GpJob:
    return GpJob(job_number=j["job_number"], job_name=j.get("job_name"))


def _gp_vendor_to_type(v: dict) -> GpVendor:
    return GpVendor(
        vendor_id=v["vendor_id"],
        vendor_name=v["vendor_name"],
        vendor_class=v.get("vendor_class"),
        status=v["status"],
    )


def _gp_cost_code_to_type(c: dict) -> GpCostCode:
    return GpCostCode(cost_code=c["cost_code"], description=c.get("description"), cost_element=c["cost_element"])


def _warehouse_to_type(w) -> Warehouse:
    return Warehouse(
        id=strawberry.ID(str(w.id)),
        name=w.name,
        code=w.code,
        address=w.address,
        city=w.city,
        province=w.province,
        postal_code=w.postal_code,
        is_primary=w.is_primary,
        is_active=w.is_active,
        created_at=w.created_at,
        updated_at=w.updated_at,
    )


def _po_to_type(po, receive_records=None) -> PurchaseOrder:
    documents = getattr(po, "documents", None) or []
    vendor = getattr(po, "vendor", None)
    return PurchaseOrder(
        id=strawberry.ID(str(po.id)),
        po_number=po.po_number,
        request_number=po.request_number,
        project_id=strawberry.ID(str(po.project_id)) if po.project_id else None,
        status=po.status,
        cost_code=po.cost_code,
        gp_company=po.gp_company,
        vendor=_vendor_to_type(vendor) if vendor is not None else None,
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


def _project_to_type(
    p: ProjectModel,
    *,
    include_openings: bool = True,
    opening_count: int | None = None,
) -> Project:
    # When include_openings=False, callers must supply opening_count to avoid
    # triggering a lazy load of the openings relationship.
    openings_list = (
        [
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
        ]
        if include_openings
        else []
    )
    if opening_count is None:
        opening_count = len(openings_list) if include_openings else 0
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
        off_site_storage_agreement=p.off_site_storage_agreement,
        gc_contact_name=p.gc_contact_name,
        gc_phone=p.gc_phone,
        gc_email=p.gc_email,
        created_at=p.created_at,
        updated_at=p.updated_at,
        opening_count=opening_count,
        openings=openings_list,
        purchase_orders=[],  # Loaded on demand in later tickets
    )


def _project_schedule_hardware_item_to_type(hi: dict) -> ProjectScheduleHardwareItem:
    return ProjectScheduleHardwareItem(
        opening_number=hi["opening_number"],
        product_code=hi["product_code"],
        material_id=hi["material_id"],
        hardware_category=hi["hardware_category"],
        item_quantity=hi["item_quantity"],
        unit_cost=hi["unit_cost"],
        unit_price=hi["unit_price"],
        list_price=hi["list_price"],
        vendor_discount=hi["vendor_discount"],
        markup_pct=hi["markup_pct"],
        vendor_no=hi["vendor_no"],
        phase_code=hi["phase_code"],
        item_category_code=hi["item_category_code"],
        product_group_code=hi["product_group_code"],
        submittal_id=hi["submittal_id"],
    )


def _project_hardware_schedule_to_type(data: dict) -> ProjectHardwareSchedule:
    project_type = _project_to_type(data["project"])
    return ProjectHardwareSchedule(
        project=project_type,
        openings=project_type.openings,
        hardware_items=[_project_schedule_hardware_item_to_type(hi) for hi in data["hardware_items"]],
    )


def _inventory_location_to_type(il) -> InventoryLocationType:
    deficient_qty = getattr(il, "deficient_quantity", 0) or 0
    stock_item_id = getattr(il, "stock_item_id", None)
    return InventoryLocationType(
        id=strawberry.ID(str(il.id)),
        project_id=strawberry.ID(str(il.project_id)),
        po_line_item_id=strawberry.ID(str(il.po_line_item_id)) if il.po_line_item_id else None,
        receive_line_item_id=(strawberry.ID(str(il.receive_line_item_id)) if il.receive_line_item_id else None),
        stock_item_id=strawberry.ID(str(stock_item_id)) if stock_item_id else None,
        warehouse_id=strawberry.ID(str(il.warehouse_id)) if getattr(il, "warehouse_id", None) else None,
        hardware_category=il.hardware_category,
        product_code=il.product_code,
        quantity=il.quantity,
        deficient_quantity=deficient_qty,
        available=il.quantity - deficient_qty,
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
        warehouse_id=strawberry.ID(str(oi.warehouse_id)) if getattr(oi, "warehouse_id", None) else None,
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
        opening_number=opening.opening_number,
        building=opening.building,
        floor=opening.floor,
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


def _shipment_return_item_to_type(sri) -> ShipmentReturnItem:
    return ShipmentReturnItem(
        id=strawberry.ID(str(sri.id)),
        shipment_return_id=strawberry.ID(str(sri.shipment_return_id)),
        packing_slip_item_id=strawberry.ID(str(sri.packing_slip_item_id)),
        disposition=sri.disposition,
        quantity=sri.quantity,
        hardware_category=sri.hardware_category,
        product_code=sri.product_code,
        opening_number=sri.opening_number,
        rma_reference=sri.rma_reference,
        reason_text=sri.reason_text,
        resulting_inventory_location_id=(
            strawberry.ID(str(sri.resulting_inventory_location_id)) if sri.resulting_inventory_location_id else None
        ),
        resulting_stock_item_id=(
            strawberry.ID(str(sri.resulting_stock_item_id)) if sri.resulting_stock_item_id else None
        ),
        created_at=sri.created_at,
    )


def _shipment_return_to_type(sr) -> ShipmentReturn:
    return ShipmentReturn(
        id=strawberry.ID(str(sr.id)),
        packing_slip_id=strawberry.ID(str(sr.packing_slip_id)),
        warehouse_id=strawberry.ID(str(sr.warehouse_id)),
        returned_by=sr.returned_by,
        returned_at=sr.returned_at,
        reference=sr.reference,
        created_at=sr.created_at,
        items=[_shipment_return_item_to_type(i) for i in sr.items],
    )


def _stock_item_to_type(si) -> StockItemType:
    deficient_qty = getattr(si, "deficient_quantity", 0) or 0
    return StockItemType(
        id=strawberry.ID(str(si.id)),
        warehouse_id=strawberry.ID(str(si.warehouse_id)) if getattr(si, "warehouse_id", None) else None,
        hardware_category=si.hardware_category,
        product_code=si.product_code,
        quantity=si.quantity,
        deficient_quantity=deficient_qty,
        available=si.quantity - deficient_qty,
        aisle=si.aisle,
        bay=si.bay,
        bin=si.bin,
        received_at=si.received_at,
        created_at=si.created_at,
        updated_at=si.updated_at,
    )


def _deficiency_review_to_type(dr) -> DeficiencyReviewType:
    return DeficiencyReviewType(
        id=strawberry.ID(str(dr.id)),
        inventory_location_id=(strawberry.ID(str(dr.inventory_location_id)) if dr.inventory_location_id else None),
        stock_item_id=strawberry.ID(str(dr.stock_item_id)) if dr.stock_item_id else None,
        resolution=dr.resolution,
        quantity=dr.quantity,
        reason_text=dr.reason_text,
        rma_reference=dr.rma_reference,
        reviewed_by=dr.reviewed_by,
        reviewed_at=dr.reviewed_at,
        resulting_stock_item_id=(
            strawberry.ID(str(dr.resulting_stock_item_id)) if dr.resulting_stock_item_id else None
        ),
    )


def _deficient_item_row_to_type(row: dict) -> DeficientItemRow:
    return DeficientItemRow(
        source=row["source"],
        inventory_location_id=(
            strawberry.ID(str(row["inventory_location_id"])) if row["inventory_location_id"] else None
        ),
        stock_item_id=strawberry.ID(str(row["stock_item_id"])) if row["stock_item_id"] else None,
        project_id=strawberry.ID(str(row["project_id"])) if row["project_id"] else None,
        hardware_category=row["hardware_category"],
        product_code=row["product_code"],
        deficient_quantity=row["deficient_quantity"],
        aisle=row["aisle"],
        bay=row["bay"],
        bin=row["bin"],
    )


@strawberry.type
class Query:
    @strawberry.field
    def projects(self) -> list[Project]:
        with SessionLocal() as session:
            stmt = select(ProjectModel).order_by(ProjectModel.created_at.desc())
            results = list(session.scalars(stmt).unique().all())
            count_rows = session.execute(
                select(OpeningModel.project_id, func.count()).group_by(OpeningModel.project_id)
            ).all()
            counts: dict[uuid.UUID, int] = {pid: c for pid, c in count_rows}
            return [_project_to_type(p, include_openings=False, opening_count=counts.get(p.id, 0)) for p in results]

    @strawberry.field
    def admin_projects(self, info: strawberry.Info) -> list[Project]:
        """Admin/Manager-only project list with all editable fields for the admin Projects page."""
        require_admin(info)
        with SessionLocal() as session:
            stmt = select(ProjectModel).order_by(ProjectModel.created_at.desc())
            results = list(session.scalars(stmt).unique().all())
            count_rows = session.execute(
                select(OpeningModel.project_id, func.count()).group_by(OpeningModel.project_id)
            ).all()
            counts: dict[uuid.UUID, int] = {pid: c for pid, c in count_rows}
            return [_project_to_type(p, include_openings=False, opening_count=counts.get(p.id, 0)) for p in results]

    @strawberry.field
    def project_by_schedule_id(self, project_id: str) -> Project | None:
        with SessionLocal() as session:
            stmt = (
                select(ProjectModel)
                .options(selectinload(ProjectModel.openings))
                .where(ProjectModel.project_id == project_id)
            )
            p = session.scalars(stmt).unique().first()
            if p is None:
                return None
            return _project_to_type(p)

    @strawberry.field
    def project_hardware_schedule(self, project_id: strawberry.ID) -> ProjectHardwareSchedule | None:
        from app.repositories import import_repository

        with SessionLocal() as session:
            data = import_repository.get_project_hardware_schedule(session, uuid.UUID(str(project_id)))
            if data is None:
                return None
            return _project_hardware_schedule_to_type(data)

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
    def prior_order_as_values(
        self,
        vendor_id: strawberry.ID,
        product_codes: list[str],
    ) -> list[PriorOrderAsForProduct]:
        with SessionLocal() as session:
            result = po_repository.get_prior_order_as_values(session, uuid.UUID(str(vendor_id)), product_codes)
            return [PriorOrderAsForProduct(product_code=pc, values=vals) for pc, vals in result.items()]

    @strawberry.field
    def po_statistics(self, project_id: strawberry.ID | None = None) -> POStatistics:
        with SessionLocal() as session:
            stats = po_repository.get_po_statistics(session, uuid.UUID(str(project_id)) if project_id else None)
            return POStatistics(
                total=stats["total"],
                draft=stats["draft"],
                gp_registered=stats["gp_registered"],
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
                .options(
                    selectinload(POModel.line_items),
                    selectinload(POModel.documents),
                    selectinload(POModel.vendor),
                )
                .where(
                    POModel.deleted_at.is_(None),
                    POModel.status.in_(
                        [
                            DBPOStatus.GP_REGISTERED,
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
    def packing_slips(self, project_id: strawberry.ID | None = None) -> list[PackingSlipType]:
        with SessionLocal() as session:
            slips = shipping_repository.list_packing_slips(session, uuid.UUID(str(project_id)) if project_id else None)
            return [_packing_slip_to_type(ps) for ps in slips]

    @strawberry.field
    def returnable_lines(self, packing_slip_id: strawberry.ID) -> list[ReturnableLine]:
        with SessionLocal() as session:
            lines = shipping_repository.get_returnable_lines(session, uuid.UUID(str(packing_slip_id)))
            return [
                ReturnableLine(
                    packing_slip_item_id=strawberry.ID(str(line["packing_slip_item_id"])),
                    opening_number=line["opening_number"],
                    product_code=line["product_code"],
                    hardware_category=line["hardware_category"],
                    shipped_quantity=line["shipped_quantity"],
                    returned_quantity=line["returned_quantity"],
                    returnable_quantity=line["returnable_quantity"],
                )
                for line in lines
            ]

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
            saos = shop_assembly_repository.get_assemble_list(
                session, uuid.UUID(str(project_id)) if project_id else None
            )
            return [_shop_assembly_opening_to_type(sao) for sao in saos]

    @strawberry.field
    def my_work(self, assigned_to: str) -> list[ShopAssemblyOpening]:
        with SessionLocal() as session:
            saos = shop_assembly_repository.get_my_work(session, assigned_to)
            return [_shop_assembly_opening_to_type(sao) for sao in saos]

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
    def vendors(self) -> list[Vendor]:
        with SessionLocal() as session:
            return [_vendor_to_type(v) for v in vendor_repository.list_vendors(session)]

    @strawberry.field
    def vendor(self, id: strawberry.ID) -> Vendor | None:
        from app.models.vendor import Vendor as VendorModel

        with SessionLocal() as session:
            v = session.get(VendorModel, uuid.UUID(str(id)))
            return _vendor_to_type(v) if v is not None else None

    @strawberry.field
    def relay_credential(self, info: strawberry.Info) -> RelayCredential:
        """Return the relay Bearer secret to the authenticated user (the frontend sends it to the
        on-prem relay). POC: the single enrolled install's secret."""
        require_user(info)
        with SessionLocal() as session:
            secret = relay_repository.get_credential(session)
            session.commit()
            return RelayCredential(secret=secret)

    @strawberry.field
    def relay_installs(self, info: strawberry.Info) -> list[RelayInstallInfo]:
        require_admin(info)
        with SessionLocal() as session:
            return [_relay_install_to_type(ri) for ri in relay_repository.list_installs(session)]

    @strawberry.field
    def relay_status(self, info: strawberry.Info) -> RelayStatus:
        """Whether the outbound relay WS channel is currently connected, for the relay status chip."""
        require_user(info)
        return RelayStatus(connected=relay_gateway.connected)

    @strawberry.field
    async def gp_jobs(self, info: strawberry.Info, company: str) -> list[GpJob]:
        """Live job master (JC00102) via the connected relay."""
        require_user(info)
        result = await relay_gateway.relay_call(company, "list_jobs")
        return [_gp_job_to_type(j) for j in result["jobs"]]

    @strawberry.field
    async def gp_vendors(self, info: strawberry.Info, company: str) -> list[GpVendor]:
        """Live active vendor list (PM00200) via the connected relay."""
        require_user(info)
        result = await relay_gateway.relay_call(company, "list_vendors")
        return [_gp_vendor_to_type(v) for v in result["vendors"]]

    @strawberry.field
    async def gp_buyers(self, info: strawberry.Info, company: str) -> list[str]:
        """Registered GP buyers (POP00101) via the connected relay, for the Create PO buyer dropdown."""
        require_user(info)
        result = await relay_gateway.relay_call(company, "list_buyers")
        return result["buyers"]

    @strawberry.field
    async def gp_cost_codes(self, info: strawberry.Info, company: str, job: str) -> list[GpCostCode]:
        """Active per-job cost codes (JC00701) via the connected relay, for the Create PO cost-code dropdown."""
        require_user(info)
        result = await relay_gateway.relay_call(company, "list_cost_codes", {"job": job})
        return [_gp_cost_code_to_type(c) for c in result["cost_codes"]]

    @strawberry.field
    def warehouses(self, include_inactive: bool = True) -> list[Warehouse]:
        with SessionLocal() as session:
            return [
                _warehouse_to_type(w)
                for w in warehouse_admin_repository.list_warehouses(session, include_inactive=include_inactive)
            ]

    @strawberry.field
    def warehouse(self, id: strawberry.ID) -> Warehouse | None:
        with SessionLocal() as session:
            w = session.get(warehouse_admin_repository.Warehouse, uuid.UUID(str(id)))
            return _warehouse_to_type(w) if w is not None else None

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
    def home_dashboard_stats(self) -> HomeDashboardStats:
        with SessionLocal() as session:
            d = dashboard_repository.get_home_dashboard_stats(session)
            return HomeDashboardStats(
                open_po_count=d["open_po_count"],
                pending_pull_request_count=d["pending_pull_request_count"],
                items_pending_receiving=d["items_pending_receiving"],
                project_count=d["project_count"],
            )

    @strawberry.field
    def shop_assembly_stats(self) -> ShopAssemblyStats:
        with SessionLocal() as session:
            d = dashboard_repository.get_shop_assembly_stats(session)
            return ShopAssemblyStats(
                pending_sar_count=d["pending_sar_count"],
                approved_sar_count=d["approved_sar_count"],
                active_pull_request_count=d["active_pull_request_count"],
            )

    @strawberry.field
    def admin_stats(self) -> AdminStats:
        users = user_repository.list_users()
        with SessionLocal() as session:
            d = dashboard_repository.get_admin_stats(session, user_count=len(users))
            return AdminStats(
                vendor_count=d["vendor_count"],
                user_count=d["user_count"],
                hardware_item_count=d["hardware_item_count"],
                opening_count=d["opening_count"],
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
    def location_contents(
        self,
        aisle: str,
        bay: str | None = None,
        bin: str | None = None,
        warehouse_id: strawberry.ID | None = None,
    ) -> LocationContents:
        with SessionLocal() as session:
            data = warehouse_repository.get_location_contents(
                session, aisle, bay, bin, uuid.UUID(str(warehouse_id)) if warehouse_id else None
            )
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
                stock_items=[_stock_item_to_type(si) for si in data["stock_items"]],
            )

    @strawberry.field
    def location_audit_history(
        self,
        aisle: str,
        bay: str | None = None,
        bin: str | None = None,
        limit: int = 10,
    ) -> list[AuditLogEntry]:
        with SessionLocal() as session:
            entries = warehouse_repository.get_location_audit_history(session, aisle, bay, bin, limit=limit)
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
                bays=values["bays"],
                bins=values["bins"],
            )

    @strawberry.field
    def location_duplicates(self) -> list[LocationDuplicateGroup]:
        with SessionLocal() as session:
            groups = warehouse_repository.get_location_duplicates(session)
            return [
                LocationDuplicateGroup(
                    canonical_aisle=g["canonical_aisle"],
                    canonical_bay=g["canonical_bay"],
                    canonical_bin=g["canonical_bin"],
                    variants=[LocationVariant(aisle=v["aisle"], bay=v["bay"], bin=v["bin"]) for v in g["variants"]],
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

    # ---------------------------------------------------------------------------
    # Stock pool + deficiency queries
    # ---------------------------------------------------------------------------

    @strawberry.field
    def stock_items(
        self,
        product_code_contains: str | None = None,
        hardware_category: str | None = None,
        aisle: str | None = None,
        only_deficient: bool = False,
        warehouse_id: strawberry.ID | None = None,
    ) -> list[StockItemType]:
        with SessionLocal() as session:
            rows = stock_repository.get_stock_items(
                session,
                product_code_contains=product_code_contains,
                hardware_category=hardware_category,
                aisle=aisle,
                only_deficient=only_deficient,
                warehouse_id=uuid.UUID(str(warehouse_id)) if warehouse_id else None,
            )
            return [_stock_item_to_type(r) for r in rows]

    @strawberry.field
    def stock_item(self, id: strawberry.ID) -> StockItemType | None:
        with SessionLocal() as session:
            try:
                row = stock_repository.get_stock_item(session, uuid.UUID(str(id)))
            except Exception:
                return None
            return _stock_item_to_type(row)

    @strawberry.field
    def deficient_items(
        self,
        project_id: strawberry.ID | None = None,
        source: DeficientItemSource | None = None,
    ) -> list[DeficientItemRow]:
        with SessionLocal() as session:
            rows = stock_repository.get_deficient_items(
                session,
                project_id=uuid.UUID(str(project_id)) if project_id else None,
                source=source,
            )
            return [_deficient_item_row_to_type(r) for r in rows]

    @strawberry.field
    def deficiency_reviews(
        self,
        inventory_location_id: strawberry.ID | None = None,
        stock_item_id: strawberry.ID | None = None,
        project_id: strawberry.ID | None = None,
    ) -> list[DeficiencyReviewType]:
        with SessionLocal() as session:
            rows = stock_repository.get_deficiency_reviews(
                session,
                inventory_location_id=(uuid.UUID(str(inventory_location_id)) if inventory_location_id else None),
                stock_item_id=uuid.UUID(str(stock_item_id)) if stock_item_id else None,
                project_id=uuid.UUID(str(project_id)) if project_id else None,
            )
            return [_deficiency_review_to_type(r) for r in rows]

    @strawberry.field
    def stock_matches_for_opening(self, opening_item_id: strawberry.ID) -> list[StockItemType]:
        with SessionLocal() as session:
            rows = stock_repository.get_stock_matches_for_opening(session, uuid.UUID(str(opening_item_id)))
            return [_stock_item_to_type(r) for r in rows]
