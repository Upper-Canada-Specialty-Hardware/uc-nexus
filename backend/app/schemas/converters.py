"""ORM/dict -> Strawberry type builders shared by every domain schema module.

Each converter only reads relationships its callers eagerly loaded - see the GraphQL/SQLAlchemy
performance rules in CLAUDE.md before adding a field that walks a new relationship.
"""

import strawberry

from app.models.enums import ShippingOutRequestStatus as ShippingOutRequestStatusDB
from app.models.enums import ShopAssemblyRequestStatus as ShopAssemblyRequestStatusDB
from app.models.project import Project as ProjectModel
from app.repositories import project_repository, shipping_repository

from .enums import GpOutboxStatus, RelayEventKind, RequestStage
from .types import (
    BuyerAssignment,
    BuyerAssignmentProject,
    ClerkUser,
    DeficiencyReview,
    DeficientItemRow,
    GpBuyer,
    GpCostCode,
    GpCostCodeMasterEntry,
    GpCustomer,
    GpCustomerAddress,
    GpEmployee,
    GpJob,
    GpOutboxEntry,
    GpOutboxSummary,
    GpSetupIssue,
    GpTaxDetail,
    GpTaxSchedule,
    GpVendor,
    InventoryLocation,
    Notification,
    Opening,
    OpenPOSummary,
    PackingSlip,
    PackingSlipItem,
    PickSheet,
    PickSheetLocation,
    PickSheetOpening,
    PickSheetSection,
    PODocumentData,
    PODocumentInfo,
    PODocumentSettings,
    POLineItem,
    POListRow,
    Project,
    ProjectHardwareSchedule,
    ProjectScheduleHardwareItem,
    PullRequest,
    PullRequestItem,
    PurchaseOrder,
    ReceiveDraft,
    ReceiveDraftLineItem,
    ReceiveDraftLocation,
    ReceiveLineItem,
    ReceiveRecord,
    RelayEvent,
    RelayInstallInfo,
    ShipmentContainer,
    ShipmentContainerItem,
    ShipmentReturn,
    ShipmentReturnItem,
    ShippingOutRequest,
    ShippingOutRequestItem,
    ShopAssemblyAllocationLine,
    ShopAssemblyAllocationOpening,
    ShopAssemblyAllocationReview,
    ShopAssemblyBatch,
    ShopAssemblyBatchItem,
    ShopAssemblyRequest,
    ShopAssemblyRequestItem,
    ShopAssemblyRequestOpening,
    StockItem,
    Warehouse,
    WarehouseLocation,
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
        receipt_number=rr.receipt_number,
        batch_number=rr.batch_number,
        notes=rr.notes,
        created_at=rr.created_at,
        line_items=[receive_line_item_to_type(rli) for rli in rr.line_items],
    )


def receive_draft_line_item_to_type(li) -> ReceiveDraftLineItem:
    return ReceiveDraftLineItem(
        id=strawberry.ID(str(li.id)),
        po_line_item_id=strawberry.ID(str(li.po_line_item_id)),
        hardware_category=li.hardware_category,
        product_code=li.product_code,
        quantity_received=li.quantity_received,
        locations=[
            ReceiveDraftLocation(
                aisle=loc.get("aisle") or "",
                row=loc.get("row") or "",
                bay=loc.get("bay") or "",
                quantity=loc.get("quantity") or 0,
                deficient_quantity=loc.get("deficient_quantity") or 0,
            )
            for loc in (li.locations or [])
        ],
    )


def receive_draft_to_type(draft, po) -> ReceiveDraft:
    """The draft plus the PO fields every consumer renders beside it. `po` is passed in rather than
    walked off a relationship so a list read stays one query."""
    return ReceiveDraft(
        id=strawberry.ID(str(draft.id)),
        status=draft.status,
        po_id=strawberry.ID(str(draft.po_id)),
        po_number=po.po_number if po is not None else None,
        project_id=strawberry.ID(str(po.project_id)) if po is not None and po.project_id else None,
        warehouse_id=strawberry.ID(str(draft.warehouse_id)) if draft.warehouse_id else None,
        created_by_user_id=draft.created_by_user_id,
        created_by=draft.created_by_name,
        reviewed_by=draft.reviewed_by_name,
        reviewed_at=draft.reviewed_at,
        rejection_reason=draft.rejection_reason,
        approval_idempotency_key=draft.approval_idempotency_key,
        receive_record_id=strawberry.ID(str(draft.receive_record_id)) if draft.receive_record_id else None,
        outbox_entry_id=(
            strawberry.ID(str(draft.approved_outbox_entry_id)) if draft.approved_outbox_entry_id else None
        ),
        packing_slip_document_id=(
            strawberry.ID(str(draft.packing_slip_document_id)) if draft.packing_slip_document_id else None
        ),
        notes=draft.notes,
        total_quantity=sum(li.quantity_received for li in draft.line_items),
        created_at=draft.created_at,
        updated_at=draft.updated_at,
        line_items=[receive_draft_line_item_to_type(li) for li in draft.line_items],
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


def relay_install_to_type(ri) -> RelayInstallInfo:
    return RelayInstallInfo(
        id=strawberry.ID(str(ri.id)),
        label=ri.label,
        hostname=ri.hostname,
        enrolled=ri.enrolled_at is not None,
        enrolled_at=ri.enrolled_at,
        last_seen_at=ri.last_seen_at,
        created_at=ri.created_at,
        adopted_at=ri.adopted_at,
        adopted_by=ri.adopted_by,
        secret_hash=ri.secret_hash,
    )


def relay_event_to_type(e) -> RelayEvent:
    # `kind` is stored as a plain string (String + CHECK, per migration 103), so it is mapped back
    # through the enum here rather than handed to Strawberry raw - a value the enum does not know is a
    # schema violation worth raising on, not a string to pass through.
    return RelayEvent(
        id=strawberry.ID(str(e.id)),
        at=e.at,
        kind=RelayEventKind(e.kind),
        install_id=strawberry.ID(str(e.install_id)) if e.install_id else None,
        install_label=e.install_label,
        build=e.build,
        companies=list(e.companies) if e.companies is not None else None,
        reason=e.reason,
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


def gp_buyer_to_type(b: dict) -> GpBuyer:
    return GpBuyer(buyer_id=b["buyer_id"], description=b.get("description"))


def gp_cost_code_to_type(c: dict) -> GpCostCode:
    return GpCostCode(cost_code=c["cost_code"], description=c.get("description"), cost_element=c["cost_element"])


def gp_cost_code_master_entry_to_type(c: dict) -> GpCostCodeMasterEntry:
    # The master row carries more than the picker needs (alias, profit type, transaction type, the
    # account index itself). Only what the dialog shows and sends back is mapped: the account is GP's
    # to resolve at create time, so handing it to the client would invite it being sent back.
    return GpCostCodeMasterEntry(
        cost_code=c["cost_code"],
        description=c.get("description"),
        cost_element=c["cost_element"],
        mapped=bool(c["mapped"]),
    )


def gp_tax_detail_to_type(t: dict) -> GpTaxDetail:
    return GpTaxDetail(tax_detail_id=t["tax_detail_id"], description=t.get("description"), percent=t["percent"])


def gp_customer_to_type(c: dict) -> GpCustomer:
    return GpCustomer(customer_number=c["customer_number"], customer_name=c.get("customer_name"))


def gp_employee_to_type(e: dict) -> GpEmployee:
    return GpEmployee(
        employee_id=e["employee_id"],
        first_name=e.get("first_name"),
        last_name=e.get("last_name"),
    )


def gp_customer_address_to_type(a: dict) -> GpCustomerAddress:
    return GpCustomerAddress(
        address_code=a["address_code"],
        address1=a.get("address1"),
        city=a.get("city"),
        state=a.get("state"),
    )


def gp_tax_schedule_to_type(s: dict) -> GpTaxSchedule:
    return GpTaxSchedule(tax_schedule_id=s["tax_schedule_id"], description=s.get("description"))


def warehouse_to_type(w) -> Warehouse:
    return Warehouse(
        id=strawberry.ID(str(w.id)),
        company=w.company,
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


def warehouse_location_to_type(wl) -> WarehouseLocation:
    return WarehouseLocation(
        id=strawberry.ID(str(wl.id)),
        warehouse_id=strawberry.ID(str(wl.warehouse_id)),
        aisle=wl.aisle,
        row=wl.row,
        bay=wl.bay,
        active=wl.active,
        created_at=wl.created_at,
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
        quotation_number=d.quotation_number,
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
        company=u.get("company"),
        image_url=u["image_url"],
    )


def buyer_assignment_to_type(a) -> BuyerAssignment:
    return BuyerAssignment(
        buyer_id=a.buyer_id,
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
    # Read document_data ONLY if the caller eager-loaded it (in __dict__): a bare attribute access would
    # lazy-load, turning list resolvers that don't need it into an N+1. get_purchase_orders /
    # get_purchase_order selectinload it (that's what the generate dialog reads); everything else gets None.
    doc_data = po.__dict__.get("document_data")
    return PurchaseOrder(
        id=strawberry.ID(str(po.id)),
        po_number=po.po_number,
        request_number=po.request_number,
        origin=po.origin,
        gp_synced_at=po.gp_synced_at,
        project_id=strawberry.ID(str(po.project_id)) if po.project_id else None,
        status=po.status,
        cost_code=po.cost_code,
        company=po.company,
        gp_company=po.gp_company,
        gp_vendor_id=po.gp_vendor_id,
        # The GP vendor pick, the only vendor a PO has. Null on a DRAFT that has not been registered
        # into GP yet, which the UI renders as an empty vendor rather than inventing a stand-in.
        vendor_name_snapshot=po.vendor_name_snapshot,
        buyer_id=po.buyer_id,
        created_by_user_id=po.created_by_user_id,
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


def open_po_summary_to_type(po, pending_quantity: int, pending_line_count: int) -> OpenPOSummary:
    """A lean receiving-picker row (gp-owned-po mirror). Pending scalars come from the caller's grouped
    query, never from po.line_items."""
    return OpenPOSummary(
        id=strawberry.ID(str(po.id)),
        po_number=po.po_number,
        project_id=strawberry.ID(str(po.project_id)) if po.project_id else None,
        status=po.status,
        origin=po.origin,
        gp_vendor_id=po.gp_vendor_id,
        vendor_name_snapshot=po.vendor_name_snapshot,
        notes=po.notes,
        ordered_at=po.ordered_at,
        expected_delivery_date=po.expected_delivery_date,
        pending_line_count=pending_line_count,
        pending_quantity=pending_quantity,
    )


def po_list_row_to_type(po, line_item_count: int, created_by: str | None = None) -> POListRow:
    """A slim register row (gp-owned-po mirror). line_item_count is supplied by the caller from a
    grouped count query, never read off po.line_items - the register never loads the collection.
    created_by is likewise resolved by the caller (batched over the page's distinct author ids, #632)
    rather than one Clerk lookup per row."""
    return POListRow(
        id=strawberry.ID(str(po.id)),
        po_number=po.po_number,
        request_number=po.request_number,
        project_id=strawberry.ID(str(po.project_id)) if po.project_id else None,
        status=po.status,
        origin=po.origin,
        company=po.company,
        gp_company=po.gp_company,
        vendor_name_snapshot=po.vendor_name_snapshot,
        created_by=created_by,
        ordered_at=po.ordered_at,
        expected_delivery_date=po.expected_delivery_date,
        created_at=po.created_at,
        gp_synced_at=po.gp_synced_at,
        line_item_count=line_item_count,
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
        company=p.company,
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
        schedule_filename=p.schedule_filename,
        off_site_storage_agreement=p.off_site_storage_agreement,
        gc_contact_name=p.gc_contact_name,
        gc_phone=p.gc_phone,
        gc_email=p.gc_email,
        created_at=p.created_at,
        updated_at=p.updated_at,
        opening_count=opening_count,
        # #425: scalar columns off the row already loaded, so this is free in both list and detail
        # contexts and needs no include_ flag. The JSON detail column is parsed here rather than
        # exposed raw - a GraphQL type is the wrong place for a client-side JSON.parse.
        gp_setup_ok=p.gp_setup_ok,
        gp_setup_checked_at=p.gp_setup_checked_at,
        gp_setup_issues=[
            GpSetupIssue(cost_code=issue["cost_code"], account_index=issue["account_index"])
            for issue in project_repository.parse_gp_setup_issues(p.gp_setup_detail)
        ],
        archived=p.archived,
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
        classification=hi.get("classification"),
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


def shop_assembly_request_item_to_type(item) -> ShopAssemblyRequestItem:
    return ShopAssemblyRequestItem(
        id=strawberry.ID(str(item.id)),
        shop_assembly_request_id=strawberry.ID(str(item.shop_assembly_request_id)),
        opening_number=item.opening_number,
        hardware_category=item.hardware_category,
        product_code=item.product_code,
        requested_quantity=item.requested_quantity,
    )


def shop_assembly_request_opening_to_type(opening) -> ShopAssemblyRequestOpening:
    return ShopAssemblyRequestOpening(
        id=strawberry.ID(str(opening.id)),
        shop_assembly_request_id=strawberry.ID(str(opening.shop_assembly_request_id)),
        opening_number=opening.opening_number,
        status=opening.status,
        batch_id=strawberry.ID(str(opening.batch_id)) if opening.batch_id else None,
        dismissed_by=opening.dismissed_by,
        dismissed_at=opening.dismissed_at,
        dismissal_reason=opening.dismissal_reason,
    )


def shop_assembly_batch_item_to_type(item) -> ShopAssemblyBatchItem:
    return ShopAssemblyBatchItem(
        id=strawberry.ID(str(item.id)),
        shop_assembly_batch_id=strawberry.ID(str(item.shop_assembly_batch_id)),
        opening_number=item.opening_number,
        hardware_category=item.hardware_category,
        product_code=item.product_code,
        allocated_quantity=item.allocated_quantity,
    )


def shop_assembly_batch_to_type(batch, *, pull_status=None) -> ShopAssemblyBatch:
    """Model -> type. `pull_status` is resolved by the *caller* in one query for the whole list, for
    the same reason the stage is (CLAUDE.md perf rules)."""
    return ShopAssemblyBatch(
        id=strawberry.ID(str(batch.id)),
        shop_assembly_request_id=strawberry.ID(str(batch.shop_assembly_request_id)),
        sequence=batch.sequence,
        batch_number=batch.batch_number,
        status=batch.status,
        created_by=batch.created_by,
        created_at=batch.created_at,
        pull_request_id=strawberry.ID(str(batch.pull_request_id)) if batch.pull_request_id else None,
        pull_status=pull_status,
        items=[shop_assembly_batch_item_to_type(i) for i in sorted(batch.items, key=lambda i: i.opening_number)],
    )


def shop_assembly_request_to_type(
    sar,
    *,
    stage: str | None = None,
    return_note: str | None = None,
    pull_status_by_id: dict | None = None,
) -> ShopAssemblyRequest:
    """Model -> type. `stage`, `return_note` and the batches' pull statuses are resolved by the
    *caller* in one query for the whole list.

    Passed in rather than derived here for the same reason `pull_request_to_type` takes its
    staging counts: a converter that queries is an N+1 waiting to happen on a list page
    (CLAUDE.md perf rules).
    """
    statuses = pull_status_by_id or {}
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
        items=[shop_assembly_request_item_to_type(i) for i in sar.items],
        openings=[
            shop_assembly_request_opening_to_type(o) for o in sorted(sar.openings, key=lambda o: o.opening_number)
        ],
        batches=[
            shop_assembly_batch_to_type(b, pull_status=statuses.get(b.pull_request_id))
            for b in sorted(sar.batches, key=lambda b: b.sequence)
        ],
        stage=RequestStage(stage or _fallback_stage(sar)),
        return_note=return_note,
    )


def _fallback_stage(sar) -> str:
    """The stage a caller that did not resolve one would have got. Never guesses past ACCEPTED:
    without the pulls' statuses there is no evidence any of them has been started or finished."""
    if sar.status == ShopAssemblyRequestStatusDB.REJECTED:
        return "REJECTED"
    if sar.status == ShopAssemblyRequestStatusDB.PENDING:
        return "REQUESTED"
    return "ACCEPTED" if sar.batches else "DONE"


def shop_assembly_allocation_review_to_type(review: dict) -> ShopAssemblyAllocationReview:
    """The manager's batch-composition read (#643). The repository already did the two aggregates;
    this only reshapes them."""
    request = review["request"]
    return ShopAssemblyAllocationReview(
        request_id=strawberry.ID(str(request.id)),
        request_number=request.request_number,
        project_id=strawberry.ID(str(request.project_id)),
        status=request.status,
        created_by=request.created_by,
        created_at=request.created_at,
        integrity_note=request.integrity_note,
        openings=[
            ShopAssemblyAllocationOpening(
                opening_number=opening["opening_number"],
                lines=[ShopAssemblyAllocationLine(**line) for line in opening["lines"]],
            )
            for opening in review["openings"]
        ],
    )


def shipping_out_request_item_to_type(item) -> ShippingOutRequestItem:
    return ShippingOutRequestItem(
        id=strawberry.ID(str(item.id)),
        shipping_out_request_id=strawberry.ID(str(item.shipping_out_request_id)),
        opening_number=item.opening_number,
        hardware_category=item.hardware_category,
        product_code=item.product_code,
        requested_quantity=item.requested_quantity,
    )


def shipping_out_request_to_type(
    req, *, stage: str | None = None, return_note: str | None = None
) -> ShippingOutRequest:
    """Model -> type. `stage` and `return_note` are resolved by the *caller* in one query for the
    whole list, mirroring `shop_assembly_request_to_type` (CLAUDE.md perf rules)."""
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
        stage=RequestStage(stage or _fallback_shipping_stage(req)),
        return_note=return_note,
    )


def _fallback_shipping_stage(req) -> str:
    """The stage a caller that did not resolve one would have got - never past ACCEPTED, since
    without the pull's status there is no evidence it has been started or finished."""
    if req.status == ShippingOutRequestStatusDB.REJECTED:
        return "REJECTED"
    if req.status == ShippingOutRequestStatusDB.PENDING or req.pull_request_id is None:
        return "REQUESTED"
    return "ACCEPTED"


def pull_request_item_to_type(item) -> PullRequestItem:
    return PullRequestItem(
        id=strawberry.ID(str(item.id)),
        pull_request_id=strawberry.ID(str(item.pull_request_id)),
        opening_number=item.opening_number,
        hardware_category=item.hardware_category,
        product_code=item.product_code,
        requested_quantity=item.requested_quantity,
    )


def pull_request_to_type(pr, partially_picked=None) -> PullRequest:
    """Model -> type.

    `partially_picked` (#367) is passed in rather than derived here because deriving it needs a
    query, and a converter that queries is an N+1 waiting to happen on the pull-request list
    (CLAUDE.md perf rules): the resolver fetches it for the whole page in one grouped read over
    `pull_pick_lines`. None means not evaluated, which is also the honest answer for a pull that is
    already picked.
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
        picked_at=pr.picked_at,
        picked_by=pr.picked_by,
        completed_at=pr.completed_at,
        cancelled_at=pr.cancelled_at,
        cancelled_by=pr.cancelled_by,
        cancellation_reason=pr.cancellation_reason,
        items=[pull_request_item_to_type(i) for i in pr.items],
        partially_picked=partially_picked,
    )


def pick_sheet_to_type(sheet, partially_picked=None) -> PickSheet:
    """`warehouse.PickSheet` -> the GraphQL type (#367).

    The repository has already done every read this needs in a fixed number of queries, so this is a
    pure shape change - nothing here touches the session. `remainingQuantity` is exposed rather than
    left to the client to subtract, because the pick screen, the PDF and the confirm gate must all
    agree on one definition of "still to pick"."""
    return PickSheet(
        pull_request=pull_request_to_type(sheet.pull_request, partially_picked),
        sections=[
            PickSheetSection(
                hardware_category=section.hardware_category,
                product_code=section.product_code,
                required_quantity=section.required_quantity,
                applied_quantity=section.applied_quantity,
                remaining_quantity=section.remaining_quantity,
                claimable_quantity=section.claimable_quantity,
                claimable_shortfall=section.claimable_shortfall,
                openings=[
                    PickSheetOpening(opening_number=opening.opening_number, quantity=opening.quantity)
                    for opening in section.openings
                ],
                locations=[
                    PickSheetLocation(
                        inventory_location_id=strawberry.ID(str(loc.inventory_location_id)),
                        warehouse_id=strawberry.ID(str(loc.warehouse_id)) if loc.warehouse_id else None,
                        warehouse_code=loc.warehouse_code,
                        aisle=loc.aisle,
                        row=loc.row,
                        bay=loc.bay,
                        available=loc.available,
                        received_at=loc.received_at,
                        draft_quantity=loc.draft_quantity,
                        applied_quantity=loc.applied_quantity,
                        order_as=loc.order_as,
                        po_number=loc.po_number,
                    )
                    for loc in section.locations
                ],
            )
            for section in sheet.sections
        ],
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
        opening_number=psi.opening_number,
        building=psi.building,
        floor=psi.floor,
        location=psi.location,
        product_code=psi.product_code,
        hardware_category=psi.hardware_category,
        quantity=psi.quantity,
        is_manual=psi.is_manual,
    )


def container_to_type(c) -> ShipmentContainer:
    """One container and its contents, in load order (#451).

    Items are sorted by `position` here rather than left in whatever order the relationship loaded
    them: position 0 is what went on first, which on a skid is the bottom of the stack, and a
    Delivery Request that printed the stack in a different order every time would be worse than one
    that printed no order at all.
    """
    return ShipmentContainer(
        id=strawberry.ID(str(c.id)),
        project_id=strawberry.ID(str(c.project_id)),
        container_type=c.container_type,
        name=c.name,
        packing_slip_id=strawberry.ID(str(c.packing_slip_id)) if c.packing_slip_id else None,
        created_by=c.created_by,
        created_at=c.created_at,
        updated_at=c.updated_at,
        items=[
            ShipmentContainerItem(
                id=strawberry.ID(str(i.id)),
                shipment_container_id=strawberry.ID(str(i.shipment_container_id)),
                opening_number=i.opening_number,
                hardware_category=i.hardware_category,
                product_code=i.product_code,
                quantity=i.quantity,
                is_manual=i.is_manual,
                position=i.position,
            )
            for i in sorted(c.items, key=lambda i: i.position)
        ],
    )


def packing_slip_to_type(ps) -> PackingSlip:
    """The shipment and its whole Delivery Request header (#447).

    Shared by the list read, the confirm and the three lifecycle mutations, which is deliberate: they
    all answer with the same PackingSlip, and Apollo normalises on `id`, so a mutation returning a
    narrower shape than the list would leave the row it just changed half-stale in the cache.

    The header is copied off `DELIVERY_REQUEST_FIELDS` rather than named field by field (#453). Named
    here, a twenty-first field that reached the column and the input but not this function would read
    back as null on every query while the write looked like it had worked - and nothing about that
    fails a build.
    """
    header = {field: getattr(ps, field) for field in shipping_repository.DELIVERY_REQUEST_FIELDS}
    # The one header column that is not already a GraphQL scalar: weight_lbs is Numeric(10, 2), which
    # comes back as Decimal, and Strawberry's Float will not take one.
    header["weight_lbs"] = float(header["weight_lbs"]) if header["weight_lbs"] is not None else None
    return PackingSlip(
        id=strawberry.ID(str(ps.id)),
        packing_slip_number=ps.packing_slip_number,
        project_id=strawberry.ID(str(ps.project_id)),
        status=ps.status,
        shipped_by=ps.shipped_by,
        shipped_at=ps.shipped_at,
        created_at=ps.created_at,
        **header,
        picked_up_at=ps.picked_up_at,
        picked_up_by=ps.picked_up_by,
        delivered_at=ps.delivered_at,
        delivered_by=ps.delivered_by,
        items=[packing_slip_item_to_type(i) for i in ps.items],
        containers=[container_to_type(c) for c in ps.containers],
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
        unit_cost=float(si.unit_cost) if getattr(si, "unit_cost", None) is not None else None,
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


def gp_outbox_entry_to_type(row) -> GpOutboxEntry:
    """Reads only the row's own scalar columns - no relationships, so nothing here can trigger a
    lazy load (see the GraphQL/SQLAlchemy rules in CLAUDE.md)."""
    return GpOutboxEntry(
        id=strawberry.ID(str(row.id)),
        label=row.label,
        op=row.op,
        company=row.company,
        status=GpOutboxStatus(row.status),
        attempts=row.attempts,
        next_attempt_at=row.next_attempt_at,
        created_at=row.created_at,
        entity_key=row.entity_key,
        last_error=row.last_error,
        failure_kind=row.failure_kind,
    )


def gp_outbox_summary_to_type(data: dict) -> GpOutboxSummary:
    return GpOutboxSummary(
        pending=data["pending"],
        in_flight=data["in_flight"],
        failed=data["failed"],
        oldest_pending_at=data["oldest_pending_at"],
        last_drained_at=data["last_drained_at"],
    )
