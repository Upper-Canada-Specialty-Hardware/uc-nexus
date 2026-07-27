"""ORM/dict -> Strawberry type builders shared by every domain schema module.

Each converter only reads relationships its callers eagerly loaded - see the GraphQL/SQLAlchemy
performance rules in CLAUDE.md before adding a field that walks a new relationship.
"""

import strawberry

from app.models.project import Project as ProjectModel

from .enums import PipelineStage
from .types import (
    AssemblyPipeline,
    AssemblyPipelineSummary,
    BuyerAssignment,
    BuyerAssignmentProject,
    ClerkUser,
    DeficiencyReview,
    DeficientItemRow,
    GpCostCode,
    GpJob,
    GpTaxDetail,
    GpVendor,
    InventoryLocation,
    Notification,
    Opening,
    OpeningItem,
    OpeningItemHardware,
    PackingSlip,
    PackingSlipItem,
    PipelineOpening,
    PODocumentData,
    PODocumentInfo,
    PODocumentSettings,
    POLineItem,
    Project,
    ProjectHardwareSchedule,
    ProjectScheduleHardwareItem,
    PullRequest,
    PullRequestItem,
    PurchaseOrder,
    ReceiveLineItem,
    ReceiveRecord,
    RelayInstallInfo,
    ReplacementWorkItem,
    ShipmentReturn,
    ShipmentReturnItem,
    ShippingOutRequest,
    ShippingOutRequestItem,
    ShopAssemblyOpening,
    ShopAssemblyOpeningItem,
    ShopAssemblyRequest,
    StockItem,
    Vendor,
    Warehouse,
)


def _po_line_item_manufacturer(li) -> str | None:
    """Issue #232: derive a PO line's manufacturer from its linked HardwareItem rows (distinct, first
    non-null if they disagree). Read only when the hardware_items relationship was eagerly loaded, so a
    PO path that didn't selectinload it returns None rather than triggering an N+1 lazy load."""
    from sqlalchemy import inspect as sa_inspect

    if "hardware_items" in sa_inspect(li).unloaded:
        return None
    for hi in li.hardware_items:
        if hi.manufacturer and hi.manufacturer.strip():
            return hi.manufacturer.strip()
    return None


def po_line_item_to_type(li) -> POLineItem:
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
        manufacturer=_po_line_item_manufacturer(li),
        created_at=li.created_at,
        updated_at=li.updated_at,
    )


def receive_line_item_to_type(rli) -> ReceiveLineItem:
    return ReceiveLineItem(
        id=strawberry.ID(str(rli.id)),
        receive_record_id=strawberry.ID(str(rli.receive_record_id)),
        po_line_item_id=strawberry.ID(str(rli.po_line_item_id)),
        hardware_category=rli.hardware_category,
        product_code=rli.product_code,
        quantity_received=rli.quantity_received,
        created_at=rli.created_at,
    )


def receive_record_to_type(rr) -> ReceiveRecord:
    return ReceiveRecord(
        id=strawberry.ID(str(rr.id)),
        po_id=strawberry.ID(str(rr.po_id)),
        received_at=rr.received_at,
        received_by=rr.received_by,
        created_at=rr.created_at,
        line_items=[receive_line_item_to_type(rli) for rli in rr.line_items],
    )


def po_document_to_type(doc) -> PODocumentInfo:
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


def vendor_to_type(v) -> Vendor:
    return Vendor(
        id=strawberry.ID(str(v.id)),
        name=v.name,
        contact_name=v.contact_name,
        email=v.email,
        phone=v.phone,
        notes=v.notes,
        created_at=v.created_at,
        updated_at=v.updated_at,
    )


def relay_install_to_type(ri) -> RelayInstallInfo:
    return RelayInstallInfo(
        id=strawberry.ID(str(ri.id)),
        label=ri.label,
        company=ri.company,
        hostname=ri.hostname,
        enrolled=ri.enrolled_at is not None,
        enrolled_at=ri.enrolled_at,
        last_seen_at=ri.last_seen_at,
        created_at=ri.created_at,
        adopted_at=ri.adopted_at,
        adopted_by=ri.adopted_by,
    )


def gp_job_to_type(j: dict) -> GpJob:
    return GpJob(job_number=j["job_number"], job_name=j.get("job_name"))


def gp_vendor_to_type(v: dict) -> GpVendor:
    return GpVendor(
        vendor_id=v["vendor_id"],
        vendor_name=v["vendor_name"],
        vendor_class=v.get("vendor_class"),
        status=v["status"],
        # older relays predate the currency field (issue #257); default to CAD so a mixed-version
        # relay doesn't break the vendor dropdown.
        currency=v.get("currency") or "CAD",
    )


def gp_cost_code_to_type(c: dict) -> GpCostCode:
    return GpCostCode(cost_code=c["cost_code"], description=c.get("description"), cost_element=c["cost_element"])


def gp_tax_detail_to_type(t: dict) -> GpTaxDetail:
    return GpTaxDetail(tax_detail_id=t["tax_detail_id"], description=t.get("description"), percent=t["percent"])


def warehouse_to_type(w) -> Warehouse:
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


def po_document_data_to_type(d) -> PODocumentData:
    return PODocumentData(
        id=strawberry.ID(str(d.id)),
        po_id=strawberry.ID(str(d.po_id)),
        vendor_address=d.vendor_address,
        buyer_name=d.buyer_name,
        currency=d.currency,
        ship_to=d.ship_to,
        shipping_method=d.shipping_method,
        proposal_number=d.proposal_number,
        freight=float(d.freight),
        miscellaneous=float(d.miscellaneous),
        tax_amount=float(d.tax_amount),
        tax_label=d.tax_label,
        tariff_amount=float(d.tariff_amount),
        required_by_override=d.required_by_override,
        include_fsc=d.include_fsc,
        include_usa_tariff=d.include_usa_tariff,
        include_customs=d.include_customs,
    )


def po_document_settings_to_type(s) -> PODocumentSettings:
    return PODocumentSettings(
        tax_numbers=s.tax_numbers,
        mandatory_bullets=list(s.mandatory_bullets or []),
        shipping_accounts=list(s.shipping_accounts or []),
        shipping_methods=list(s.shipping_methods or []),
        customs_broker_block=s.customs_broker_block,
        fsc_note=s.fsc_note,
        usa_tariff_note=s.usa_tariff_note,
        usa_tariff_effective_until=s.usa_tariff_effective_until,
        company_from_address=s.company_from_address,
        payment_terms=s.payment_terms,
        confirm_with=s.confirm_with,
        footer_notes=s.footer_notes,
        signature_note=s.signature_note,
        updated_at=s.updated_at,
    )


def clerk_user_to_type(u: dict) -> ClerkUser:
    return ClerkUser(
        id=u["id"],
        first_name=u["first_name"],
        last_name=u["last_name"],
        email=u["email"],
        roles=u["roles"],
        gp_buyer_id=u.get("gp_buyer_id"),
        image_url=u["image_url"],
    )


def buyer_assignment_to_type(a) -> BuyerAssignment:
    return BuyerAssignment(
        buyer_id=a.buyer_id,
        cost_codes=list(a.cost_codes or []),
        projects=[
            BuyerAssignmentProject(
                id=strawberry.ID(str(p.id)),
                project_id=p.project_id,
                description=p.description,
            )
            for p in a.projects
        ],
    )


def po_to_type(po, receive_records=None) -> PurchaseOrder:
    documents = getattr(po, "documents", None) or []
    vendor = getattr(po, "vendor", None)
    # Read document_data ONLY if the caller eager-loaded it (in __dict__): a bare attribute access would
    # lazy-load, turning list resolvers that don't need it into an N+1. get_purchase_orders /
    # get_purchase_order selectinload it (that's what the generate dialog reads); everything else gets None.
    doc_data = po.__dict__.get("document_data")
    return PurchaseOrder(
        id=strawberry.ID(str(po.id)),
        po_number=po.po_number,
        request_number=po.request_number,
        project_id=strawberry.ID(str(po.project_id)) if po.project_id else None,
        status=po.status,
        cost_code=po.cost_code,
        gp_company=po.gp_company,
        gp_vendor_id=po.gp_vendor_id,
        # dev data is disposable - the local-vendor fallback only covers rows from before this column
        # existed; every PO created going forward carries its own snapshot.
        vendor_name_snapshot=po.vendor_name_snapshot or (vendor.name if vendor is not None else None),
        buyer_id=po.buyer_id,
        vendor=vendor_to_type(vendor) if vendor is not None else None,
        vendor_quote_number=po.vendor_quote_number,
        shipping_cost=float(po.shipping_cost) if po.shipping_cost is not None else None,
        tariff_amount=float(po.tariff_amount) if po.tariff_amount is not None else None,
        notes=po.notes,
        preferred_delivery_date=po.preferred_delivery_date,
        expected_delivery_date=po.expected_delivery_date,
        ordered_at=po.ordered_at,
        created_at=po.created_at,
        updated_at=po.updated_at,
        line_items=[po_line_item_to_type(li) for li in po.line_items],
        receive_records=[receive_record_to_type(rr) for rr in (receive_records or [])],
        documents=[po_document_to_type(doc) for doc in documents],
        document_data=po_document_data_to_type(doc_data) if doc_data is not None else None,
    )


def project_to_type(
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
                leaf_count=o.leaf_count,
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


def project_schedule_hardware_item_to_type(hi: dict) -> ProjectScheduleHardwareItem:
    return ProjectScheduleHardwareItem(
        opening_number=hi["opening_number"],
        product_code=hi["product_code"],
        material_id=hi["material_id"],
        leaf=hi.get("leaf"),
        hardware_category=hi["hardware_category"],
        item_quantity=hi["item_quantity"],
        unit_cost=hi["unit_cost"],
        unit_price=hi["unit_price"],
        list_price=hi["list_price"],
        vendor_discount=hi["vendor_discount"],
        markup_pct=hi["markup_pct"],
        vendor_no=hi["vendor_no"],
        manufacturer=hi["manufacturer"],
        phase_code=hi["phase_code"],
        item_category_code=hi["item_category_code"],
        product_group_code=hi["product_group_code"],
        submittal_id=hi["submittal_id"],
    )


def project_hardware_schedule_to_type(data: dict) -> ProjectHardwareSchedule:
    project_type = project_to_type(data["project"])
    return ProjectHardwareSchedule(
        project=project_type,
        openings=project_type.openings,
        hardware_items=[project_schedule_hardware_item_to_type(hi) for hi in data["hardware_items"]],
    )


def inventory_location_to_type(il) -> InventoryLocation:
    deficient_qty = getattr(il, "deficient_quantity", 0) or 0
    stock_item_id = getattr(il, "stock_item_id", None)
    return InventoryLocation(
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
        received_at=il.received_at,
        created_at=il.created_at,
        updated_at=il.updated_at,
    )


def opening_item_hardware_to_type(oih) -> OpeningItemHardware:
    return OpeningItemHardware(
        id=strawberry.ID(str(oih.id)),
        opening_item_id=strawberry.ID(str(oih.opening_item_id)),
        product_code=oih.product_code,
        hardware_category=oih.hardware_category,
        quantity=oih.quantity,
    )


def opening_item_to_type(
    oi, *, leaf_count: int | None = None, awaiting_replacement_quantity: int | None = None
) -> OpeningItem:
    return OpeningItem(
        id=strawberry.ID(str(oi.id)),
        project_id=strawberry.ID(str(oi.project_id)),
        opening_id=strawberry.ID(str(oi.opening_id)),
        warehouse_id=strawberry.ID(str(oi.warehouse_id)) if getattr(oi, "warehouse_id", None) else None,
        opening_number=oi.opening_number,
        building=oi.building,
        floor=oi.floor,
        location=oi.location,
        leaf=oi.leaf,
        leaf_count=leaf_count,
        quantity=oi.quantity,
        assembly_completed_at=oi.assembly_completed_at,
        state=oi.state,
        aisle=oi.aisle,
        row=oi.row,
        bay=oi.bay,
        created_at=oi.created_at,
        updated_at=oi.updated_at,
        installed_hardware=[opening_item_hardware_to_type(h) for h in oi.installed_hardware],
        # Computed by the caller from one grouped aggregate over the whole list (#341), never
        # per-row here - this converter runs once per assembled leaf in a project.
        awaiting_replacement_quantity=awaiting_replacement_quantity,
    )


def shop_assembly_opening_item_to_type(item) -> ShopAssemblyOpeningItem:
    return ShopAssemblyOpeningItem(
        id=strawberry.ID(str(item.id)),
        shop_assembly_opening_id=strawberry.ID(str(item.shop_assembly_opening_id)),
        hardware_category=item.hardware_category,
        product_code=item.product_code,
        quantity=item.quantity,
        # Plain columns on the row the caller already loaded (#340) - reading them triggers no load.
        installed_quantity=item.installed_quantity,
        deficient_quantity=item.deficient_quantity,
        replacement_pending_quantity=item.replacement_pending_quantity,
    )


def replacement_work_item_to_type(row) -> ReplacementWorkItem:
    """A repository ReplacementWorkItem dataclass -> the GraphQL type (#341). The dataclass is
    already flat, so nothing here can trigger a load."""
    return ReplacementWorkItem(
        shop_assembly_opening_item_id=strawberry.ID(str(row.shop_assembly_opening_item_id)),
        shop_assembly_opening_id=strawberry.ID(str(row.shop_assembly_opening_id)),
        project_id=strawberry.ID(str(row.project_id)),
        opening_number=row.opening_number,
        leaf=row.leaf,
        building=row.building,
        floor=row.floor,
        hardware_category=row.hardware_category,
        product_code=row.product_code,
        pending_quantity=row.pending_quantity,
        assigned_to_user_id=row.assigned_to_user_id,
        assigned_to=row.assigned_to,
        opening_item_id=(strawberry.ID(str(row.opening_item_id)) if row.opening_item_id else None),
        opening_item_state=row.opening_item_state,
    )


def shop_assembly_opening_to_type(opening) -> ShopAssemblyOpening:
    return ShopAssemblyOpening(
        id=strawberry.ID(str(opening.id)),
        shop_assembly_request_id=(
            strawberry.ID(str(opening.shop_assembly_request_id)) if opening.shop_assembly_request_id else None
        ),
        pull_request_id=(strawberry.ID(str(opening.pull_request_id)) if opening.pull_request_id else None),
        opening_id=strawberry.ID(str(opening.opening_id)),
        pull_status=opening.pull_status,
        assigned_to_user_id=opening.assigned_to_user_id,
        assigned_to=opening.assigned_to,
        assembly_status=opening.assembly_status,
        completed_at=opening.completed_at,
        items=[shop_assembly_opening_item_to_type(i) for i in opening.items],
        leaf=opening.leaf,
        opening_number=opening.opening_number,
        building=opening.building,
        floor=opening.floor,
        staged_at=opening.staged_at,
        staged_by=opening.staged_by,
    )


def assembly_pipeline_summary_to_type(row) -> AssemblyPipelineSummary:
    """A repository AssemblyPipelineSummary dataclass -> the GraphQL type (#344).

    The dataclass is flat scalars the repository computed with grouped aggregates, so there is
    nothing here that could trigger a load - which is the whole point of the resolver handing this
    converter finished counts rather than an ORM row to walk.
    """
    return AssemblyPipelineSummary(
        request_id=strawberry.ID(str(row.request_id)),
        request_number=row.request_number,
        project_id=strawberry.ID(str(row.project_id)),
        project_code=row.project_code,
        project_name=row.project_name,
        request_status=row.request_status,
        created_by=row.created_by,
        created_at=row.created_at,
        accepted_by=row.accepted_by,
        accepted_at=row.accepted_at,
        rejected_by=row.rejected_by,
        rejected_at=row.rejected_at,
        integrity_note=row.integrity_note,
        pull_request_id=(strawberry.ID(str(row.pull_request_id)) if row.pull_request_id else None),
        pull_request_status=row.pull_request_status,
        pull_approved_at=row.pull_approved_at,
        pull_completed_at=row.pull_completed_at,
        staging_status=row.staging_status,
        cancelled_pull_count=row.cancelled_pull_count,
        last_cancelled_at=row.last_cancelled_at,
        last_cancelled_by=row.last_cancelled_by,
        last_cancellation_reason=row.last_cancellation_reason,
        opening_count=row.opening_count,
        staged_opening_count=row.staged_opening_count,
        assigned_opening_count=row.assigned_opening_count,
        in_progress_opening_count=row.in_progress_opening_count,
        completed_opening_count=row.completed_opening_count,
        shipped_opening_count=row.shipped_opening_count,
        planned_unit_count=row.planned_unit_count,
        installed_unit_count=row.installed_unit_count,
        deficient_unit_count=row.deficient_unit_count,
        replacement_pending_unit_count=row.replacement_pending_unit_count,
        awaiting_replacement_opening_count=row.awaiting_replacement_opening_count,
        replacement_after_ship_opening_count=row.replacement_after_ship_opening_count,
        stage=PipelineStage(row.stage),
    )


def pipeline_opening_to_type(row) -> PipelineOpening:
    """A repository PipelineOpening dataclass -> the GraphQL type (#344). Flat scalars throughout;
    the two derived readings are the dataclass's own properties, so the ladder and the flags are
    defined once, in the repository."""
    return PipelineOpening(
        shop_assembly_opening_id=strawberry.ID(str(row.shop_assembly_opening_id)),
        opening_number=row.opening_number,
        leaf=row.leaf,
        building=row.building,
        floor=row.floor,
        location=row.location,
        stage=PipelineStage(row.stage),
        pull_status=row.pull_status,
        staged_at=row.staged_at,
        staged_by=row.staged_by,
        assigned_to_user_id=row.assigned_to_user_id,
        assigned_to=row.assigned_to,
        assembly_status=row.assembly_status,
        completed_at=row.completed_at,
        planned_unit_count=row.planned_unit_count,
        installed_unit_count=row.installed_unit_count,
        deficient_unit_count=row.deficient_unit_count,
        replacement_pending_unit_count=row.replacement_pending_unit_count,
        awaiting_replacement_unit_count=row.awaiting_replacement_unit_count,
        replacement_arrived_after_ship=row.replacement_arrived_after_ship,
        opening_item_id=(strawberry.ID(str(row.opening_item_id)) if row.opening_item_id else None),
        opening_item_state=row.opening_item_state,
        assembled_location=row.assembled_location,
    )


def assembly_pipeline_to_type(pipeline) -> AssemblyPipeline:
    return AssemblyPipeline(
        summary=assembly_pipeline_summary_to_type(pipeline.summary),
        openings=[pipeline_opening_to_type(o) for o in pipeline.openings],
    )


def shop_assembly_request_to_type(sar) -> ShopAssemblyRequest:
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
        integrity_note=sar.integrity_note,
        openings=[shop_assembly_opening_to_type(o) for o in sar.openings],
    )


def shipping_out_request_item_to_type(item) -> ShippingOutRequestItem:
    return ShippingOutRequestItem(
        id=strawberry.ID(str(item.id)),
        shipping_out_request_id=strawberry.ID(str(item.shipping_out_request_id)),
        item_type=item.item_type,
        opening_number=item.opening_number,
        opening_item_id=strawberry.ID(str(item.opening_item_id)) if item.opening_item_id else None,
        leaf=item.leaf,
        hardware_category=item.hardware_category,
        product_code=item.product_code,
        requested_quantity=item.requested_quantity,
    )


def shipping_out_request_to_type(req) -> ShippingOutRequest:
    return ShippingOutRequest(
        id=strawberry.ID(str(req.id)),
        request_number=req.request_number,
        project_id=strawberry.ID(str(req.project_id)),
        status=req.status,
        created_by=req.created_by,
        approved_by=req.approved_by,
        rejected_by=req.rejected_by,
        rejection_reason=req.rejection_reason,
        created_at=req.created_at,
        approved_at=req.approved_at,
        rejected_at=req.rejected_at,
        integrity_note=req.integrity_note,
        pull_request_id=strawberry.ID(str(req.pull_request_id)) if req.pull_request_id else None,
        items=[shipping_out_request_item_to_type(i) for i in req.items],
    )


def pull_request_item_to_type(item) -> PullRequestItem:
    return PullRequestItem(
        id=strawberry.ID(str(item.id)),
        pull_request_id=strawberry.ID(str(item.pull_request_id)),
        item_type=item.item_type,
        opening_number=item.opening_number,
        opening_item_id=strawberry.ID(str(item.opening_item_id)) if item.opening_item_id else None,
        sa_opening_item_id=(strawberry.ID(str(item.sa_opening_item_id)) if item.sa_opening_item_id else None),
        leaf=item.leaf,
        hardware_category=item.hardware_category,
        product_code=item.product_code,
        requested_quantity=item.requested_quantity,
    )


def pull_request_to_type(pr, staging=None) -> PullRequest:
    """Model -> type. `staging` is a `warehouse.StagingSummary` the *caller* computed (#343).

    It is passed in rather than derived here because deriving it needs a query, and a converter that
    queries is an N+1 waiting to happen on the pull-request list (CLAUDE.md perf rules): the resolver
    fetches the counts for the whole page in one grouped aggregate and hands each row its own. None
    leaves the three staging fields null, which reads as "not applicable / not evaluated" - never as
    "nothing staged".
    """
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
        cancelled_by=pr.cancelled_by,
        cancellation_reason=pr.cancellation_reason,
        items=[pull_request_item_to_type(i) for i in pr.items],
        staging_status=staging.status if staging is not None else None,
        staged_opening_count=staging.staged_opening_count if staging is not None else None,
        total_opening_count=staging.total_opening_count if staging is not None else None,
    )


def notification_to_type(n) -> Notification:
    return Notification(
        id=strawberry.ID(str(n.id)),
        project_id=strawberry.ID(str(n.project_id)),
        recipient_role=n.recipient_role,
        type=n.type,
        message=n.message,
        is_read=n.is_read,
        created_at=n.created_at,
    )


def packing_slip_item_to_type(psi) -> PackingSlipItem:
    return PackingSlipItem(
        id=strawberry.ID(str(psi.id)),
        packing_slip_id=strawberry.ID(str(psi.packing_slip_id)),
        item_type=psi.item_type,
        opening_item_id=strawberry.ID(str(psi.opening_item_id)) if psi.opening_item_id else None,
        opening_number=psi.opening_number,
        leaf=psi.leaf,
        product_code=psi.product_code,
        hardware_category=psi.hardware_category,
        quantity=psi.quantity,
    )


def packing_slip_to_type(ps) -> PackingSlip:
    return PackingSlip(
        id=strawberry.ID(str(ps.id)),
        packing_slip_number=ps.packing_slip_number,
        project_id=strawberry.ID(str(ps.project_id)),
        shipped_by=ps.shipped_by,
        shipped_at=ps.shipped_at,
        created_at=ps.created_at,
        items=[packing_slip_item_to_type(i) for i in ps.items],
    )


def shipment_return_item_to_type(sri) -> ShipmentReturnItem:
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


def shipment_return_to_type(sr) -> ShipmentReturn:
    return ShipmentReturn(
        id=strawberry.ID(str(sr.id)),
        packing_slip_id=strawberry.ID(str(sr.packing_slip_id)),
        warehouse_id=strawberry.ID(str(sr.warehouse_id)),
        returned_by=sr.returned_by,
        returned_at=sr.returned_at,
        reference=sr.reference,
        created_at=sr.created_at,
        items=[shipment_return_item_to_type(i) for i in sr.items],
    )


def stock_item_to_type(si) -> StockItem:
    deficient_qty = getattr(si, "deficient_quantity", 0) or 0
    return StockItem(
        id=strawberry.ID(str(si.id)),
        warehouse_id=strawberry.ID(str(si.warehouse_id)) if getattr(si, "warehouse_id", None) else None,
        hardware_category=si.hardware_category,
        product_code=si.product_code,
        quantity=si.quantity,
        deficient_quantity=deficient_qty,
        available=si.quantity - deficient_qty,
        aisle=si.aisle,
        row=si.row,
        bay=si.bay,
        received_at=si.received_at,
        created_at=si.created_at,
        updated_at=si.updated_at,
    )


def deficiency_review_to_type(dr) -> DeficiencyReview:
    return DeficiencyReview(
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


def deficient_item_row_to_type(row: dict) -> DeficientItemRow:
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
        row=row["row"],
        bay=row["bay"],
    )
