import asyncio
import logging
import uuid
from datetime import date

import strawberry
from sqlalchemy import select

from app.auth import require_admin, require_user, resolve_display_name
from app.database import SessionLocal
from app.errors import InvalidStateTransitionError, InventoryShortfallError, NotFoundError, ValidationError
from app.repositories import (
    buyer_repository,
    notification_repository,
    po_document_settings_repository,
    po_repository,
    project_repository,
    relay_repository,
    shipping_repository,
    shop_assembly_repository,
    stock_repository,
    user_repository,
    vendor_repository,
    warehouse_admin_repository,
    warehouse_repository,
)
from app.services import gp_idempotency, gp_po, notification_service
from app.services.relay_gateway import gateway as relay_gateway

from .enums import ApproveOutcome, PODocumentType
from .inputs import (
    AdjustStockQuantityInput,
    AdoptGpJobInput,
    AllocateStockToProjectInput,
    AssignOpeningsInput,
    CompleteOpeningInput,
    ConfirmShipmentInput,
    CreateDraftPOInput,
    CreateReceiveInput,
    CreateShipmentReturnInput,
    CreateVendorInput,
    CreateWarehouseInput,
    DestockInventoryInput,
    EnrollRelayInstallInput,
    FinalizeImportSessionInput,
    MoveStockLocationInput,
    OverrideInventoryQuantityInput,
    ReclassifyStockItemInput,
    RegisterPOInput,
    ReportDeficiencyAtAssemblyInput,
    ReportInventoryDeficiencyInput,
    ReportStockDeficiencyInput,
    ResolveDeficiencyInput,
    SavePODocumentDataInput,
    TransferInventoryInput,
    UpdatePODocumentSettingsInput,
    UpdateProjectInput,
    UpdateVendorInput,
    UpdateWarehouseInput,
)
from .queries import (
    _buyer_assignment_to_type,
    _clerk_user_to_type,
    _deficiency_review_to_type,
    _inventory_location_to_type,
    _notification_to_type,
    _opening_item_to_type,
    _packing_slip_to_type,
    _po_document_settings_to_type,
    _po_document_to_type,
    _po_line_item_to_type,
    _po_to_type,
    _project_to_type,
    _pull_request_item_to_type,
    _pull_request_to_type,
    _receive_record_to_type,
    _shipment_return_to_type,
    _shop_assembly_opening_to_type,
    _shop_assembly_request_to_type,
    _stock_item_to_type,
    _vendor_to_type,
    _warehouse_to_type,
)
from .types import (
    ApproveResult,
    BuyerAssignment,
    ClerkUser,
    DeficiencyReview,
    FinalizeImportResult,
    InventoryLocation,
    InventoryShortfall,
    LocationMergeResult,
    Notification,
    OpeningItem,
    PODocumentInfo,
    PODocumentSettings,
    POLineItem,
    Project,
    PullRequest,
    PurchaseOrder,
    ReceiveRecord,
    ReclassifyStockResult,
    RelayEnrollResult,
    RelayInstallProvision,
    SAReplacementResult,
    ShipmentReturn,
    ShopAssemblyOpening,
    StockItem,
    TransferResult,
    Vendor,
    Warehouse,
)
from .types import (
    PackingSlip as PackingSlipType,
)

logger = logging.getLogger(__name__)


# --- GP-first write orchestration (issue #202 #1/#3) --------------------------------------------------
# create_po / register_po_in_gp / create_receive push to GP via the relay BEFORE persisting, and the two
# systems are not atomic. Each resolver runs as: idempotency short-circuit -> validate eligibility ->
# relay_call -> record the relay result (own commit) -> persist + stamp the record id. The sync DB and
# Clerk work is offloaded via asyncio.to_thread so no Postgres connection is held across the relay
# round-trip and the event loop running the /relay-link read loop is never blocked on a sync call.


def _load_po_type(po_id: uuid.UUID) -> PurchaseOrder:
    from sqlalchemy.orm import selectinload

    from app.models.purchase_order import PurchaseOrder as POModel

    with SessionLocal() as session:
        po = (
            session.scalars(
                select(POModel)
                .options(
                    selectinload(POModel.line_items),
                    selectinload(POModel.documents),
                    selectinload(POModel.vendor),
                )
                .where(POModel.id == po_id)
            )
            .unique()
            .first()
        )
        return _po_to_type(po)


def _resolve_line_manufacturers(session, project_id, line_items_data) -> list[str | None]:
    """Resolve the manufacturer for each payload line from the project's HardwareItem rows, joining on
    (project_id, hardware_category, product_code) - the key line_items_data already carries, so no new
    frontend input (issue #233). Returns a list parallel to line_items_data (None where nothing matches).

    A category+code can map to several imported items; the manufacturer is normally the same across them,
    but if they disagree we take the first non-null (deterministic by created_at, id) and log the conflict
    rather than guessing or failing. No project -> nothing to join against -> all None."""
    if project_id is None:
        return [None] * len(line_items_data)

    from app.models.hardware import HardwareItem

    cache: dict[tuple[str, str], str | None] = {}
    resolved: list[str | None] = []
    for li in line_items_data:
        key = (li["hardware_category"], li["product_code"])
        if key not in cache:
            rows = session.scalars(
                select(HardwareItem.manufacturer)
                .where(
                    HardwareItem.project_id == project_id,
                    HardwareItem.hardware_category == key[0],
                    HardwareItem.product_code == key[1],
                )
                .order_by(HardwareItem.created_at, HardwareItem.id)
            ).all()
            distinct = list(dict.fromkeys(m.strip() for m in rows if m and m.strip()))
            chosen = distinct[0] if distinct else None
            if len(distinct) > 1:
                logger.warning(
                    "manufacturer disagreement for line %s/%s in project %s: %s; using %r",
                    key[0],
                    key[1],
                    project_id,
                    distinct,
                    chosen,
                )
            cache[key] = chosen
        resolved.append(cache[key])
    return resolved


def _assert_buyer_identity(caller_gp_buyer_id: str | None, input_buyer_id: str) -> None:
    """Issue #216: a PO is pushed as the CALLER's GP buyer identity (Clerk publicMetadata.gpBuyerId),
    not a free pick - reject a missing identity or a mismatched buyer_id before anything hits GP."""
    if not caller_gp_buyer_id:
        raise ValidationError(
            "Your account has no GP buyer identity; an Admin must set it in User Management",
            field="buyer_id",
        )
    if (input_buyer_id or "").strip().upper() != caller_gp_buyer_id.strip().upper():
        raise ValidationError("POs can only be created as your own GP buyer", field="buyer_id")


def _prepare_register_po(*, po_id, vendor_id, gp_vendor_id, buyer_id, cost_code, line_items_data) -> dict:
    """Read-only pre-flight for register_po_in_gp: confirm the PO is a registerable DRAFT, resolve the
    job number, pre-validate, and build the relay create_po payload (po_number=None; GP assigns it).
    A lean scalar read - the resolver never needs the PO's documents/vendor here."""
    from app.models.enums import POStatus
    from app.models.project import Project as ProjectModel
    from app.models.purchase_order import PurchaseOrder as POModel
    from app.models.vendor import Vendor as VendorModel

    with SessionLocal() as session:
        po = session.scalars(select(POModel).where(POModel.id == po_id, POModel.deleted_at.is_(None))).first()
        if po is None:
            raise NotFoundError(f"Purchase order {po_id} not found")
        if po.status != POStatus.DRAFT:
            raise InvalidStateTransitionError(f"Only a Draft PO can be registered in GP; this one is {po.status.value}")

        if vendor_id is not None:
            vendor = session.get(VendorModel, vendor_id)
            if vendor is None:
                raise NotFoundError(f"Vendor {vendor_id} not found")

        job_number = None
        if po.project_id is not None:
            project = session.get(ProjectModel, po.project_id)
            if project is None:
                raise NotFoundError(f"Project {po.project_id} not found")
            job_number = project.project_id

        # Issue #216: registering a draft is the ordering action - same strict buyer gating.
        buyer_repository.validate_buyer_can_order(session, buyer_id, po.project_id, cost_code)

        manufacturers = _resolve_line_manufacturers(session, po.project_id, line_items_data)

    gp_po.validate_create_po_inputs(
        job_number=job_number, cost_code=cost_code, po_number=None, line_items=line_items_data
    )
    payload = gp_po.build_create_po_payload(
        vendor_gp_id=gp_vendor_id,
        vendor_contact_name=None,
        buyer_id=buyer_id,
        job_number=job_number,
        cost_code=cost_code,
        po_number=None,
        line_items=line_items_data,
    )
    # build_create_po_payload emits one line per line_items_data entry, in order, so index-align the
    # resolved manufacturers onto the relay payload lines (the relay caps/RTRIMs to USRDEFND1's char(50)).
    for line, manufacturer in zip(payload["lines"], manufacturers):
        line["manufacturer"] = manufacturer
    return payload


def _persist_register_po(
    *,
    key,
    po_id,
    gp_vendor_id,
    vendor_name_snapshot,
    gp_result,
    line_items_data,
    vendor_id,
    cost_code,
    buyer_id,
    shipping_cost,
    tariff_amount,
) -> PurchaseOrder:
    with SessionLocal() as session:
        po_repository.register_po_in_gp(
            session,
            po_id,
            gp_vendor_id=gp_vendor_id,
            vendor_name_snapshot=vendor_name_snapshot,
            po_number=gp_result["po_number"],
            gp_company=gp_result["company"],
            line_items=line_items_data,
            vendor_id=vendor_id,
            cost_code=cost_code,
            buyer_id=buyer_id,
            shipping_cost=shipping_cost,
            tariff_amount=tariff_amount,
        )
        gp_idempotency.stamp_result_id(session, key, "register_po_in_gp", gp_result, str(po_id))
        session.commit()
        return _load_po_within(session, po_id)


def _load_po_within(session, po_id) -> PurchaseOrder:
    from sqlalchemy.orm import selectinload

    from app.models.purchase_order import PurchaseOrder as POModel

    refreshed = (
        session.scalars(
            select(POModel)
            .options(
                selectinload(POModel.line_items),
                selectinload(POModel.documents),
                selectinload(POModel.vendor),
            )
            .where(POModel.id == po_id)
        )
        .unique()
        .first()
    )
    return _po_to_type(refreshed)


def _load_receive_type(receive_id: uuid.UUID) -> ReceiveRecord:
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
        return _receive_record_to_type(rec)


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
    from sqlalchemy.orm import selectinload

    from app.models.receiving import ReceiveRecord as ReceiveRecordModel

    with SessionLocal() as session:
        receive_record = warehouse_repository.create_receive(
            session, po_id, received_by, line_items_data, warehouse_id=warehouse_id
        )
        gp_idempotency.stamp_result_id(session, key, "create_receive", relay_result, str(receive_record.id))
        session.commit()
        rec = (
            session.scalars(
                select(ReceiveRecordModel)
                .options(selectinload(ReceiveRecordModel.line_items))
                .where(ReceiveRecordModel.id == receive_record.id)
            )
            .unique()
            .first()
        )
        return _receive_record_to_type(rec)


@strawberry.type
class Mutation:
    # Project
    @strawberry.mutation
    def adopt_gp_job(self, input: AdoptGpJobInput) -> Project:
        """Adopt a live GP job as a project (issue #198). The frontend picks the job from the live
        gpJobs query and posts its number + name here; job_number becomes the project's identity."""
        with SessionLocal() as session:
            project = project_repository.adopt_gp_job(
                session,
                job_number=input.job_number,
                job_name=input.job_name,
            )
            session.commit()
            session.refresh(project)
            return _project_to_type(project)

    @strawberry.mutation
    def update_project(self, info: strawberry.Info, id: strawberry.ID, input: UpdateProjectInput) -> Project:
        require_admin(info)
        with SessionLocal() as session:
            project = project_repository.update_project(
                session,
                uuid.UUID(str(id)),
                description=input.description,
                client=input.client,
                job_site_name=input.job_site_name,
                address=input.address,
                city=input.city,
                state=input.state,
                zip=input.zip,
                contractor=input.contractor,
                project_manager=input.project_manager,
                application=input.application,
                gc_contact_name=input.gc_contact_name,
                gc_phone=input.gc_phone,
                gc_email=input.gc_email,
                off_site_storage_agreement=input.off_site_storage_agreement,
            )
            session.commit()
            session.refresh(project)
            return _project_to_type(project)

    # Import
    @strawberry.mutation
    def finalize_import_session(self, input: FinalizeImportSessionInput) -> FinalizeImportResult:
        from sqlalchemy.orm import selectinload

        from app.models.project import Project as ProjectModel
        from app.models.pull_request import PullRequest as PRModel
        from app.models.purchase_order import PurchaseOrder as POModel
        from app.models.shop_assembly import (
            ShopAssemblyOpening as SAOModel_,
        )
        from app.models.shop_assembly import (
            ShopAssemblyRequest as SARModel,
        )
        from app.repositories import import_repository

        # Convert Strawberry input to dict
        input_data = {
            "project_id": str(input.project_id),
            "openings": [
                {
                    "opening_number": o.opening_number,
                    "building": o.building,
                    "floor": o.floor,
                    "location": o.location,
                    "location_to": o.location_to,
                    "location_from": o.location_from,
                    "hand": o.hand,
                    "width": o.width,
                    "length": o.length,
                    "door_thickness": o.door_thickness,
                    "jamb_thickness": o.jamb_thickness,
                    "door_type": o.door_type,
                    "frame_type": o.frame_type,
                    "interior_exterior": o.interior_exterior,
                    "keying": o.keying,
                    "heading_no": o.heading_no,
                    "single_pair": o.single_pair,
                    "assignment_multiplier": o.assignment_multiplier,
                }
                for o in input.openings
            ],
            "hardware_items": [
                {
                    "opening_number": hi.opening_number,
                    "product_code": hi.product_code,
                    "hardware_category": hi.hardware_category,
                    "item_quantity": hi.item_quantity,
                    "unit_cost": hi.unit_cost,
                    "unit_price": hi.unit_price,
                    "list_price": hi.list_price,
                    "vendor_discount": hi.vendor_discount,
                    "markup_pct": hi.markup_pct,
                    "vendor_no": hi.vendor_no,
                    "manufacturer": hi.manufacturer,
                    "phase_code": hi.phase_code,
                    "item_category_code": hi.item_category_code,
                    "product_group_code": hi.product_group_code,
                    "submittal_id": hi.submittal_id,
                }
                for hi in (input.hardware_items or [])
            ]
            if input.hardware_items
            else None,
            "po_drafts": [
                {
                    "po_number": po.po_number,
                    "vendor_id": str(po.vendor_id) if po.vendor_id else None,
                    "notes": po.notes,
                    "preferred_delivery_date": po.preferred_delivery_date,
                    "hardware_item_refs": [
                        {
                            "opening_number": ref.opening_number,
                            "product_code": ref.product_code,
                            "hardware_category": ref.hardware_category,
                        }
                        for ref in po.hardware_item_refs
                    ],
                    "line_item_aliases": [
                        {
                            "hardware_category": alias.hardware_category,
                            "product_code": alias.product_code,
                            "order_as": alias.order_as,
                        }
                        for alias in po.line_item_aliases
                    ],
                }
                for po in (input.po_drafts or [])
            ]
            if input.po_drafts
            else None,
            "classifications": [
                {
                    "hardware_category": c.hardware_category,
                    "product_code": c.product_code,
                    "unit_cost": c.unit_cost,
                    "classification": c.classification.value,
                }
                for c in (input.classifications or [])
            ]
            if input.classifications
            else None,
            "excluded_items": [
                {
                    "hardware_category": ei.hardware_category,
                    "product_code": ei.product_code,
                }
                for ei in (input.excluded_items or [])
            ]
            if input.excluded_items
            else None,
            "shipping_out_pr_drafts": [
                {
                    "request_number": pr.request_number,
                    "requested_by": pr.requested_by,
                    "items": [
                        {
                            "item_type": item.item_type.value,
                            "opening_number": item.opening_number,
                            "opening_item_id": str(item.opening_item_id) if item.opening_item_id else None,
                            "hardware_category": item.hardware_category,
                            "product_code": item.product_code,
                            "requested_quantity": item.requested_quantity,
                        }
                        for item in pr.items
                    ],
                }
                for pr in (input.shipping_out_pr_drafts or [])
            ]
            if input.shipping_out_pr_drafts
            else None,
            "include_shop_assembly_request": input.include_shop_assembly_request,
            "shop_assembly_request_number": input.shop_assembly_request_number,
            "shop_assembly_openings": [
                {
                    "opening_number": sa.opening_number,
                    "items": [
                        {
                            "hardware_category": item.hardware_category,
                            "product_code": item.product_code,
                            "quantity": item.quantity,
                        }
                        for item in sa.items
                    ],
                }
                for sa in (input.shop_assembly_openings or [])
            ]
            if input.shop_assembly_openings
            else None,
            "replace_schedule": input.replace_schedule,
        }

        with SessionLocal() as session:
            try:
                result = import_repository.finalize_import_session(session, input_data)
                session.commit()
            except InventoryShortfallError as e:
                # Gate 1 (#224): the shop-assembly task was refused. Roll the whole finalize back so
                # no PR (and no partial state) survives, then mint the PO backfill notification in a
                # fresh session so it outlives the rollback. Re-raise so the shortfall reaches the
                # creator inline.
                session.rollback()
                with SessionLocal() as notif_session:
                    notification_service.notify_po_shortfall(
                        notif_session,
                        project_id=e.project_id,
                        request_number=e.request_number,
                        shortfalls=e.shortfalls,
                    )
                    notif_session.commit()
                raise

            # Re-load project with openings
            project = (
                session.scalars(
                    select(ProjectModel)
                    .options(selectinload(ProjectModel.openings))
                    .where(ProjectModel.id == result["project"].id)
                )
                .unique()
                .first()
            )

            # Re-load POs with line_items, documents, and vendor
            pos = []
            for po_obj in result["purchase_orders"]:
                refreshed_po = (
                    session.scalars(
                        select(POModel)
                        .options(
                            selectinload(POModel.line_items),
                            selectinload(POModel.documents),
                            selectinload(POModel.vendor),
                        )
                        .where(POModel.id == po_obj.id)
                    )
                    .unique()
                    .first()
                )
                pos.append(refreshed_po)

            # Re-load PRs with items
            prs = []
            for pr_obj in result["shipping_out_pull_requests"]:
                refreshed_pr = (
                    session.scalars(select(PRModel).options(selectinload(PRModel.items)).where(PRModel.id == pr_obj.id))
                    .unique()
                    .first()
                )
                prs.append(refreshed_pr)

            # Re-load SAR with openings and items
            sar_type = None
            if result["shop_assembly_request"] is not None:
                refreshed_sar = (
                    session.scalars(
                        select(SARModel)
                        .options(selectinload(SARModel.openings).selectinload(SAOModel_.items))
                        .where(SARModel.id == result["shop_assembly_request"].id)
                    )
                    .unique()
                    .first()
                )
                sar_type = _shop_assembly_request_to_type(refreshed_sar)

            # Re-load the directly-minted shop-assembly PR (#222) with its items so the import
            # success UI can confirm it. Always None when the import created no shop-assembly task.
            sa_pr_type = None
            if result["shop_assembly_pull_request"] is not None:
                refreshed_sa_pr = (
                    session.scalars(
                        select(PRModel)
                        .options(selectinload(PRModel.items))
                        .where(PRModel.id == result["shop_assembly_pull_request"].id)
                    )
                    .unique()
                    .first()
                )
                sa_pr_type = _pull_request_to_type(refreshed_sa_pr)

            return FinalizeImportResult(
                project=_project_to_type(project),
                purchase_orders=[_po_to_type(po) for po in pos],
                shipping_out_pull_requests=[_pull_request_to_type(pr) for pr in prs],
                shop_assembly_request=sar_type,
                shop_assembly_pull_request=sa_pr_type,
            )

    # PO
    @strawberry.mutation
    def create_draft_po(self, info: strawberry.Info, input: CreateDraftPOInput) -> PurchaseOrder:
        """Issue #256: manual PO creation lands as a plain DRAFT - no relay round-trip, no GP fields,
        no buyer involved. Registering the draft into GP (register_po_in_gp) is the separate,
        conscious user action where GP vendor / buyer identity / cost code are captured and the
        issue #216 assignment gating applies."""
        require_user(info)
        line_items_data = [
            {
                "hardware_category": li.hardware_category,
                "product_code": li.product_code,
                "ordered_quantity": li.ordered_quantity,
                "unit_cost": li.unit_cost,
                "classification": li.classification.value if li.classification else None,
                "order_as": li.order_as,
            }
            for li in input.line_items
        ]
        with SessionLocal() as session:
            po = po_repository.create_po(
                session,
                line_items=line_items_data,
                project_id=uuid.UUID(str(input.project_id)) if input.project_id else None,
                vendor_id=uuid.UUID(str(input.vendor_id)) if input.vendor_id else None,
                notes=input.notes,
                shipping_cost=input.shipping_cost,
                tariff_amount=input.tariff_amount,
                preferred_delivery_date=input.preferred_delivery_date,
            )
            session.commit()
            return _load_po_within(session, po.id)

    @strawberry.mutation
    async def register_po_in_gp(self, info: strawberry.Info, input: RegisterPOInput) -> PurchaseOrder:
        """Register an imported DRAFT PO into GP (issue #175, the import-acceptance path; brokered
        server-side as of issue #199). Pushes the PO to GP via relay_call (create_po) BEFORE persisting
        anything, then maps the PO to the chosen GP vendor + cost code, replaces the draft's line items
        with the (possibly edited) set that was pushed (assigning gp_line_ord positionally), records GP's
        returned PONUMBER + company, and advances DRAFT -> GP_REGISTERED. The end state is identical to a
        manually created PO. Issue #200: the GP vendor is picked live (gpVendors) and sent as
        gp_vendor_id/gp_vendor_name - there is no local vendor-to-GP mirror to look up anymore.

        Issue #202 #1/#3: idempotency_key makes a retry a no-op in GP; the DRAFT-state guard and fields
        are checked before the relay_call so a double-submit never reaches GP; the DB work is offloaded
        so no Postgres connection is held across the relay round-trip."""
        auth = require_user(info)
        # Issue #216: the PO is registered as the caller's own GP buyer identity, never a free pick.
        caller_buyer = await asyncio.to_thread(user_repository.get_user_gp_buyer_id, auth["user_id"])
        _assert_buyer_identity(caller_buyer, input.buyer_id)
        key = gp_idempotency.validate_key(input.idempotency_key)

        pid = uuid.UUID(str(input.po_id))
        vendor_id = uuid.UUID(str(input.vendor_id)) if input.vendor_id else None
        line_items_data = [
            {
                "id": str(li.id) if li.id else None,
                "hardware_category": li.hardware_category,
                "product_code": li.product_code,
                "ordered_quantity": li.ordered_quantity,
                "unit_cost": li.unit_cost,
                "classification": li.classification.value if li.classification else None,
                "order_as": li.order_as,
            }
            for li in input.line_items
        ]

        state = await asyncio.to_thread(gp_idempotency.load, key)
        if state is not None and state.result_id is not None:
            return await asyncio.to_thread(_load_po_type, uuid.UUID(state.result_id))

        payload = await asyncio.to_thread(
            _prepare_register_po,
            po_id=pid,
            vendor_id=vendor_id,
            gp_vendor_id=input.gp_vendor_id,
            buyer_id=input.buyer_id,
            cost_code=input.cost_code,
            line_items_data=line_items_data,
        )

        if state is not None and state.relay_result is not None:
            gp_result = state.relay_result
        else:
            gp_result = await relay_gateway.relay_call(input.gp_company, "create_po", payload)
            await asyncio.to_thread(gp_idempotency.record_relay_result, key, "register_po_in_gp", gp_result)

        return await asyncio.to_thread(
            _persist_register_po,
            key=key,
            po_id=pid,
            gp_vendor_id=input.gp_vendor_id,
            vendor_name_snapshot=input.gp_vendor_name,
            gp_result=gp_result,
            line_items_data=line_items_data,
            vendor_id=vendor_id,
            cost_code=input.cost_code,
            buyer_id=input.buyer_id,
            shipping_cost=input.shipping_cost,
            tariff_amount=input.tariff_amount,
        )

    @strawberry.mutation
    def update_po(
        self,
        id: strawberry.ID,
        vendor_id: strawberry.ID | None = None,
        expected_delivery_date: date | None = None,
        preferred_delivery_date: date | None = None,
        po_number: str | None = None,
        vendor_quote_number: str | None = None,
        project_id: strawberry.ID | None = None,
        notes: str | None = None,
        # Issue #156: tri-state (omitted / null / value) - null clears, 0 is a valid entered value.
        shipping_cost: float | None = strawberry.UNSET,
        tariff_amount: float | None = strawberry.UNSET,
    ) -> PurchaseOrder:
        from sqlalchemy.orm import selectinload

        from app.models.purchase_order import PurchaseOrder as POModel
        from app.repositories.po_repository import _UNSET

        pid = uuid.UUID(str(project_id)) if project_id else _UNSET
        vid = uuid.UUID(str(vendor_id)) if vendor_id else _UNSET
        with SessionLocal() as session:
            po = po_repository.update_po(
                session,
                uuid.UUID(str(id)),
                vendor_id=vid,
                expected_delivery_date=expected_delivery_date,
                preferred_delivery_date=preferred_delivery_date,
                po_number=po_number,
                vendor_quote_number=vendor_quote_number,
                project_id=pid,
                notes=notes,
                shipping_cost=_UNSET if shipping_cost is strawberry.UNSET else shipping_cost,
                tariff_amount=_UNSET if tariff_amount is strawberry.UNSET else tariff_amount,
            )
            session.commit()
            refreshed_po = (
                session.scalars(
                    select(POModel)
                    .options(
                        selectinload(POModel.line_items),
                        selectinload(POModel.documents),
                        selectinload(POModel.vendor),
                    )
                    .where(POModel.id == po.id)
                )
                .unique()
                .first()
            )
            return _po_to_type(refreshed_po)

    @strawberry.mutation
    def mark_po_as_ordered(self, id: strawberry.ID) -> PurchaseOrder:
        with SessionLocal() as session:
            po = po_repository.mark_po_as_ordered(session, uuid.UUID(str(id)))
            session.commit()
            session.refresh(po)
            return _po_to_type(po)

    @strawberry.mutation
    def cancel_po(self, id: strawberry.ID) -> PurchaseOrder:
        with SessionLocal() as session:
            po = po_repository.cancel_po(session, uuid.UUID(str(id)))
            session.commit()
            session.refresh(po)
            return _po_to_type(po)

    @strawberry.mutation
    def update_po_line_item_order_as(self, id: strawberry.ID, order_as: str | None = None) -> POLineItem:
        with SessionLocal() as session:
            poli = po_repository.update_line_item_order_as(session, uuid.UUID(str(id)), order_as)
            session.commit()
            session.refresh(poli)
            return _po_line_item_to_type(poli)

    @strawberry.mutation
    def update_po_line_item_unit_cost(self, id: strawberry.ID, unit_cost: float) -> POLineItem:
        with SessionLocal() as session:
            poli = po_repository.update_line_item_unit_cost(session, uuid.UUID(str(id)), unit_cost)
            session.commit()
            session.refresh(poli)
            return _po_line_item_to_type(poli)

    # PO Documents
    @strawberry.mutation
    def upload_po_document(
        self,
        po_id: strawberry.ID,
        file_name: str,
        content_type: str,
        document_type: PODocumentType,
        file_data_base64: str,
    ) -> PODocumentInfo:
        from app.models.enums import PODocumentType as PODocTypeDB

        with SessionLocal() as session:
            doc = po_repository.upload_po_document(
                session,
                uuid.UUID(str(po_id)),
                file_name,
                content_type,
                PODocTypeDB(document_type.value),
                file_data_base64,
            )
            session.commit()
            session.refresh(doc)
            return _po_document_to_type(doc)

    @strawberry.mutation
    def delete_po_document(self, document_id: strawberry.ID) -> bool:
        with SessionLocal() as session:
            po_repository.delete_po_document(session, uuid.UUID(str(document_id)))
            session.commit()
            return True

    # Warehouse - Receiving
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
                        "bay": loc.bay,
                        "bin": loc.bin,
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

    # Warehouse - Pull Requests
    @strawberry.mutation
    def approve_pull_request(self, id: strawberry.ID, approved_by: str) -> ApproveResult:
        with SessionLocal() as session:
            pr, outcome, notification, shortfalls = warehouse_repository.approve_pull_request(
                session, uuid.UUID(str(id)), approved_by
            )
            session.commit()
            session.refresh(pr)
            # Re-load items since refresh might not load them
            from sqlalchemy.orm import selectinload

            from app.models.pull_request import PullRequest as PRModel

            stmt = select(PRModel).options(selectinload(PRModel.items)).where(PRModel.id == pr.id)
            pr = session.scalars(stmt).unique().first()

            return ApproveResult(
                pull_request=_pull_request_to_type(pr),
                outcome=ApproveOutcome.APPROVED if outcome == "APPROVED" else ApproveOutcome.INSUFFICIENT,
                notification=_notification_to_type(notification) if notification else None,
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
            session.refresh(pr)
            # Re-load items since refresh might not load them
            from sqlalchemy.orm import selectinload

            from app.models.pull_request import PullRequest as PRModel

            stmt = select(PRModel).options(selectinload(PRModel.items)).where(PRModel.id == pr.id)
            pr = session.scalars(stmt).unique().first()
            return _pull_request_to_type(pr)

    # Warehouse - Shipping
    @strawberry.mutation
    def confirm_shipment(self, input: ConfirmShipmentInput) -> PackingSlipType:
        from app.models.enums import PullRequestItemType

        project_id = uuid.UUID(str(input.project_id))
        items_data = []
        for item in input.items:
            d = {
                "item_type": PullRequestItemType(item.item_type.value),
                "quantity": item.quantity,
            }
            if item.opening_item_id is not None:
                d["opening_item_id"] = uuid.UUID(str(item.opening_item_id))
            if item.opening_number is not None:
                d["opening_number"] = item.opening_number
            if item.product_code is not None:
                d["product_code"] = item.product_code
            if item.hardware_category is not None:
                d["hardware_category"] = item.hardware_category
            items_data.append(d)

        with SessionLocal() as session:
            ps = shipping_repository.confirm_shipment(
                session,
                project_id,
                input.packing_slip_number,
                input.shipped_by,
                items_data,
            )
            session.commit()
            session.refresh(ps)
            # Re-load with items
            from sqlalchemy.orm import selectinload

            from app.models.shipping import PackingSlip as PSModel

            stmt = select(PSModel).options(selectinload(PSModel.items)).where(PSModel.id == ps.id)
            refreshed = session.scalars(stmt).unique().first()
            return _packing_slip_to_type(refreshed)

    @strawberry.mutation
    def create_shipment_return(self, input: CreateShipmentReturnInput) -> ShipmentReturn:
        from app.models.enums import ReturnDisposition

        items_data = [
            {
                "packing_slip_item_id": uuid.UUID(str(it.packing_slip_item_id)),
                "quantity": it.quantity,
                "disposition": ReturnDisposition(it.disposition.value),
                "rma_reference": it.rma_reference,
                "reason_text": it.reason_text,
            }
            for it in input.items
        ]

        with SessionLocal() as session:
            sr = shipping_repository.create_shipment_return(
                session,
                packing_slip_id=uuid.UUID(str(input.packing_slip_id)),
                warehouse_id=uuid.UUID(str(input.warehouse_id)),
                returned_by=input.returned_by,
                reference=input.reference,
                items=items_data,
            )
            session.commit()
            # Re-load with items
            from sqlalchemy.orm import selectinload

            from app.models.shipping import ShipmentReturn as SRModel

            stmt = select(SRModel).options(selectinload(SRModel.items)).where(SRModel.id == sr.id)
            refreshed = session.scalars(stmt).unique().first()
            return _shipment_return_to_type(refreshed)

    # Warehouse - Admin Corrections
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
            return _inventory_location_to_type(result)

    @strawberry.mutation
    def override_inventory_quantity(self, input: OverrideInventoryQuantityInput) -> InventoryLocation:
        with SessionLocal() as session:
            result = warehouse_repository.override_inventory_quantity(
                session,
                inv_id=uuid.UUID(str(input.inventory_location_id)),
                new_quantity=input.new_quantity,
                reason=input.reason_text,
                destinations=[
                    {"aisle": d.aisle, "bay": d.bay, "bin": d.bin, "quantity": d.quantity} for d in input.destinations
                ],
                performed_by=input.performed_by or "Warehouse",
            )
            session.commit()
            session.refresh(result)
            return _inventory_location_to_type(result)

    @strawberry.mutation
    def move_inventory_location(
        self,
        inventory_location_id: strawberry.ID,
        new_aisle: str,
        new_bay: str,
        new_bin: str,
    ) -> InventoryLocation:
        with SessionLocal() as session:
            result = warehouse_repository.move_inventory_location(
                session, uuid.UUID(str(inventory_location_id)), new_aisle, new_bay, new_bin
            )
            session.commit()
            session.refresh(result)
            return _inventory_location_to_type(result)

    @strawberry.mutation
    def mark_inventory_unlocated(self, inventory_location_id: strawberry.ID) -> InventoryLocation:
        with SessionLocal() as session:
            result = warehouse_repository.mark_inventory_unlocated(session, uuid.UUID(str(inventory_location_id)))
            session.commit()
            session.refresh(result)
            return _inventory_location_to_type(result)

    @strawberry.mutation
    def assign_inventory_location(
        self,
        inventory_location_id: strawberry.ID,
        aisle: str,
        bay: str,
        bin: str,
    ) -> InventoryLocation:
        with SessionLocal() as session:
            result = warehouse_repository.assign_inventory_location(
                session, uuid.UUID(str(inventory_location_id)), aisle, bay, bin
            )
            session.commit()
            session.refresh(result)
            return _inventory_location_to_type(result)

    @strawberry.mutation
    def move_opening_item_location(
        self,
        opening_item_id: strawberry.ID,
        aisle: str,
        bay: str,
        bin: str,
        warehouse_id: strawberry.ID | None = None,
    ) -> OpeningItem:
        with SessionLocal() as session:
            result = warehouse_repository.move_opening_item_location(
                session,
                uuid.UUID(str(opening_item_id)),
                aisle,
                bay,
                bin,
                warehouse_id=uuid.UUID(str(warehouse_id)) if warehouse_id else None,
            )
            session.commit()
            session.refresh(result)
            return _opening_item_to_type(result)

    @strawberry.mutation
    def mark_opening_item_unlocated(self, opening_item_id: strawberry.ID) -> OpeningItem:
        with SessionLocal() as session:
            result = warehouse_repository.mark_opening_item_unlocated(session, uuid.UUID(str(opening_item_id)))
            session.commit()
            session.refresh(result)
            return _opening_item_to_type(result)

    @strawberry.mutation
    def assign_opening_item_location(
        self,
        opening_item_id: strawberry.ID,
        aisle: str,
        bay: str,
        bin: str,
    ) -> OpeningItem:
        with SessionLocal() as session:
            result = warehouse_repository.assign_opening_item_location(
                session, uuid.UUID(str(opening_item_id)), aisle, bay, bin
            )
            session.commit()
            session.refresh(result)
            return _opening_item_to_type(result)

    # Notifications
    @strawberry.mutation
    def mark_notification_as_read(self, id: strawberry.ID) -> Notification:
        with SessionLocal() as session:
            notification = notification_repository.mark_as_read(session, uuid.UUID(str(id)))
            session.commit()
            session.refresh(notification)
            return _notification_to_type(notification)

    @strawberry.mutation
    def assign_openings(self, input: AssignOpeningsInput) -> list[ShopAssemblyOpening]:
        opening_ids = [uuid.UUID(str(oid)) for oid in input.opening_ids]
        with SessionLocal() as session:
            result = shop_assembly_repository.assign_openings(session, opening_ids, input.assigned_to)
            session.commit()
            from sqlalchemy.orm import selectinload

            from app.models.shop_assembly import ShopAssemblyOpening as SAOModel

            stmt = select(SAOModel).options(selectinload(SAOModel.items)).where(SAOModel.id.in_([o.id for o in result]))
            saos = list(session.scalars(stmt).unique().all())
            return [_shop_assembly_opening_to_type(sao) for sao in saos]

    @strawberry.mutation
    def remove_opening_from_user(self, opening_id: strawberry.ID) -> ShopAssemblyOpening:
        with SessionLocal() as session:
            result = shop_assembly_repository.remove_opening_from_user(session, uuid.UUID(str(opening_id)))
            session.commit()
            session.refresh(result)
            from sqlalchemy.orm import selectinload

            from app.models.shop_assembly import ShopAssemblyOpening as SAOModel

            stmt = select(SAOModel).options(selectinload(SAOModel.items)).where(SAOModel.id == result.id)
            refreshed = session.scalars(stmt).unique().first()
            return _shop_assembly_opening_to_type(refreshed)

    @strawberry.mutation
    def complete_opening(self, input: CompleteOpeningInput) -> OpeningItem:
        with SessionLocal() as session:
            item_results = [
                shop_assembly_repository.OpeningItemResult(
                    shop_assembly_opening_item_id=uuid.UUID(str(r.shop_assembly_opening_item_id)),
                    installed=r.installed,
                    deficient_reason=r.deficient_reason,
                )
                for r in input.item_results
            ]
            result = shop_assembly_repository.complete_opening(
                session,
                uuid.UUID(str(input.opening_id)),
                input.aisle,
                input.bay,
                input.bin,
                item_results=item_results,
                completed_by=input.completed_by,
            )
            session.commit()
            session.refresh(result)
            # Re-load with installed_hardware
            from sqlalchemy.orm import selectinload

            from app.models.opening_item import OpeningItem as OIModel

            stmt = select(OIModel).options(selectinload(OIModel.installed_hardware)).where(OIModel.id == result.id)
            refreshed = session.scalars(stmt).unique().first()
            return _opening_item_to_type(refreshed)

    # Vendors
    @strawberry.mutation
    def create_vendor(self, input: CreateVendorInput) -> Vendor:
        with SessionLocal() as session:
            vendor = vendor_repository.create_vendor(
                session,
                name=input.name,
                contact_name=input.contact_name,
                email=input.email,
                phone=input.phone,
                notes=input.notes,
            )
            session.commit()
            session.refresh(vendor)
            return _vendor_to_type(vendor)

    @strawberry.mutation
    def update_vendor(self, id: strawberry.ID, input: UpdateVendorInput) -> Vendor:
        with SessionLocal() as session:
            vendor = vendor_repository.update_vendor(
                session,
                uuid.UUID(str(id)),
                name=input.name,
                contact_name=input.contact_name,
                email=input.email,
                phone=input.phone,
                notes=input.notes,
            )
            session.commit()
            session.refresh(vendor)
            return _vendor_to_type(vendor)

    @strawberry.mutation
    def delete_vendor(self, id: strawberry.ID) -> bool:
        with SessionLocal() as session:
            vendor_repository.delete_vendor(session, uuid.UUID(str(id)))
            session.commit()
            return True

    # Relay installs (localhost relay <-> GP)
    @strawberry.mutation
    def provision_relay_install(self, info: strawberry.Info, label: str, company: str) -> RelayInstallProvision:
        """Admin: create a relay install + a one-time enrollment token shown ONCE. The relay uses the
        token during setup to register its self-generated Bearer secret (which never comes back here)."""
        require_admin(info)
        with SessionLocal() as session:
            install, token = relay_repository.provision_install(session, label=label, company=company)
            session.commit()
            return RelayInstallProvision(
                install_id=strawberry.ID(str(install.id)),
                label=install.label,
                company=install.company,
                enrollment_token=token,
                enrollment_token_expires_at=install.enrollment_token_expires_at,
            )

    @strawberry.mutation
    def enroll_relay_install(self, input: EnrollRelayInstallInput) -> RelayEnrollResult:
        """Called BY THE RELAY during one-time setup, authenticated by the enrollment token (not Clerk).
        Stores the relay's self-generated secret encrypted and consumes the token."""
        with SessionLocal() as session:
            install = relay_repository.enroll_install(
                session,
                enrollment_token=input.enrollment_token,
                hostname=input.hostname,
                secret=input.secret,
            )
            session.commit()
            return RelayEnrollResult(ok=True, install_id=strawberry.ID(str(install.id)))

    # Warehouses
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
            return _warehouse_to_type(wh)

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
            return _warehouse_to_type(wh)

    @strawberry.mutation
    def delete_warehouse(self, id: strawberry.ID) -> bool:
        with SessionLocal() as session:
            warehouse_admin_repository.delete_warehouse(session, uuid.UUID(str(id)))
            session.commit()
            return True

    @strawberry.mutation
    def update_po_document_settings(
        self, info: strawberry.Info, input: UpdatePODocumentSettingsInput
    ) -> PODocumentSettings:
        """Patch the single-row PO-document boilerplate (issue #230). Admin-only. Only fields the client
        actually sent (not UNSET) are written, so a partial edit leaves the rest intact."""
        require_admin(info)
        fields = {
            name: getattr(input, name)
            for name in (
                "tax_numbers",
                "mandatory_bullets",
                "shipping_accounts",
                "shipping_methods",
                "customs_broker_block",
                "fsc_note",
                "usa_tariff_note",
                "usa_tariff_effective_until",
                "company_from_address",
                "payment_terms",
                "confirm_with",
                "footer_notes",
                "signature_note",
            )
            if getattr(input, name) is not strawberry.UNSET
        }
        with SessionLocal() as session:
            settings = po_document_settings_repository.update_settings(session, **fields)
            session.commit()
            session.refresh(settings)
            return _po_document_settings_to_type(settings)

    @strawberry.mutation
    def save_po_document_data(
        self, info: strawberry.Info, po_id: strawberry.ID, input: SavePODocumentDataInput
    ) -> PurchaseOrder:
        """Persist the generate-dialog capture for a PO (issue #230) and return the PO with its now-saved
        documentData, so a re-open of the dialog pre-fills. require_user (any PO user generates)."""
        require_user(info)
        pid = uuid.UUID(str(po_id))
        with SessionLocal() as session:
            po_repository.upsert_po_document_data(
                session,
                pid,
                vendor_address=input.vendor_address,
                buyer_name=input.buyer_name,
                currency=input.currency,
                ship_to=input.ship_to,
                shipping_method=input.shipping_method,
                proposal_number=input.proposal_number,
                freight=input.freight,
                miscellaneous=input.miscellaneous,
                tax_amount=input.tax_amount,
                tax_label=input.tax_label,
                tariff_amount=input.tariff_amount,
                required_by_override=input.required_by_override,
                include_fsc=input.include_fsc,
                include_usa_tariff=input.include_usa_tariff,
                include_customs=input.include_customs,
            )
            session.commit()
            po = po_repository.get_purchase_order(session, pid)
            receive_records = po_repository.get_receive_records_for_po(session, pid)
            return _po_to_type(po, receive_records)

    @strawberry.mutation
    def update_user_roles(self, user_id: str, roles: list[str]) -> ClerkUser:
        return _clerk_user_to_type(user_repository.update_user_roles(user_id, roles))

    @strawberry.mutation
    def update_user_name(self, user_id: str, first_name: str, last_name: str) -> ClerkUser:
        """Issue #240: admin-driven display-name change (Clerk first/last name)."""
        return _clerk_user_to_type(user_repository.update_user_name(user_id, first_name, last_name))

    @strawberry.mutation
    def update_user_gp_buyer_id(self, user_id: str, gp_buyer_id: str | None = None) -> ClerkUser:
        """Issue #216: link a UC Nexus account to the GP BUYERID it acts as (null clears). The PO
        dialog auto-uses the caller's identity and createPo/registerPoInGp enforce it."""
        return _clerk_user_to_type(user_repository.update_user_gp_buyer_id(user_id, gp_buyer_id))

    @strawberry.mutation
    def save_buyer_assignment(
        self, info: strawberry.Info, buyer_id: str, project_ids: list[strawberry.ID], cost_codes: list[str]
    ) -> BuyerAssignment:
        """Issue #216: upsert a buyer's whole assignment (projects + designated cost codes). Admin."""
        require_admin(info)
        with SessionLocal() as session:
            assignment = buyer_repository.save_assignment(
                session,
                buyer_id,
                [uuid.UUID(str(pid)) for pid in project_ids],
                cost_codes,
            )
            session.commit()
            refreshed = buyer_repository.get_assignment(session, assignment.buyer_id)
            return _buyer_assignment_to_type(refreshed)

    @strawberry.mutation
    def delete_buyer_assignment(self, info: strawberry.Info, buyer_id: str) -> bool:
        require_admin(info)
        with SessionLocal() as session:
            buyer_repository.delete_assignment(session, buyer_id)
            session.commit()
            return True

    # ---------------------------------------------------------------------------
    # Stock pool + deficiency mutations
    # ---------------------------------------------------------------------------

    @strawberry.mutation
    def destock_inventory(self, input: DestockInventoryInput) -> StockItem:
        with SessionLocal() as session:
            result = stock_repository.destock_inventory(
                session,
                inventory_location_id=uuid.UUID(str(input.inventory_location_id)),
                quantity=input.quantity,
                source=input.source,
                reason_text=input.reason_text,
                target_aisle=input.target_aisle,
                target_bay=input.target_bay,
                target_bin=input.target_bin,
                performed_by=input.performed_by or "Admin/Manager",
            )
            session.commit()
            session.refresh(result)
            return _stock_item_to_type(result)

    @strawberry.mutation
    def transfer_inventory(self, input: TransferInventoryInput) -> TransferResult:
        with SessionLocal() as session:
            result = stock_repository.transfer_inventory(
                session,
                source_type=input.source_type.value,
                source_id=uuid.UUID(str(input.source_id)),
                quantity=input.quantity,
                dest_warehouse_id=uuid.UUID(str(input.dest_warehouse_id)),
                dest_aisle=input.dest_aisle,
                dest_bay=input.dest_bay,
                dest_bin=input.dest_bin,
                performed_by=input.performed_by or "Warehouse",
            )
            session.commit()
            return TransferResult(
                success=result["success"],
                quantity=result["quantity"],
                dest_warehouse_id=strawberry.ID(str(result["dest_warehouse_id"])),
            )

    @strawberry.mutation
    def allocate_stock_to_project(self, input: AllocateStockToProjectInput) -> InventoryLocation:
        with SessionLocal() as session:
            result = stock_repository.allocate_stock_to_project(
                session,
                stock_item_id=uuid.UUID(str(input.stock_item_id)),
                project_id=uuid.UUID(str(input.project_id)),
                target_hardware_category=input.target_hardware_category,
                target_product_code=input.target_product_code,
                quantity=input.quantity,
                target_aisle=input.target_aisle,
                target_bay=input.target_bay,
                target_bin=input.target_bin,
                performed_by=input.performed_by or "Admin/Manager",
            )
            session.commit()
            session.refresh(result)
            return _inventory_location_to_type(result)

    @strawberry.mutation
    def adjust_stock_quantity(self, input: AdjustStockQuantityInput) -> StockItem:
        with SessionLocal() as session:
            result = stock_repository.adjust_stock_quantity(
                session,
                stock_item_id=uuid.UUID(str(input.stock_item_id)),
                new_quantity=input.new_quantity,
                reason_text=input.reason_text,
                performed_by=input.performed_by or "Admin/Manager",
            )
            session.commit()
            session.refresh(result)
            return _stock_item_to_type(result)

    @strawberry.mutation
    def move_stock_location(self, input: MoveStockLocationInput) -> StockItem:
        with SessionLocal() as session:
            result = stock_repository.move_stock_location(
                session,
                stock_item_id=uuid.UUID(str(input.stock_item_id)),
                new_aisle=input.new_aisle,
                new_bay=input.new_bay,
                new_bin=input.new_bin,
                performed_by=input.performed_by or "Admin/Manager",
            )
            session.commit()
            session.refresh(result)
            return _stock_item_to_type(result)

    @strawberry.mutation
    def assign_stock_item_location(
        self,
        stock_item_id: strawberry.ID,
        aisle: str,
        bay: str,
        bin: str,
    ) -> StockItem:
        with SessionLocal() as session:
            result = stock_repository.assign_stock_item_location(
                session,
                stock_item_id=uuid.UUID(str(stock_item_id)),
                aisle=aisle,
                bay=bay,
                bin=bin,
                performed_by="Admin/Manager",
            )
            session.commit()
            session.refresh(result)
            return _stock_item_to_type(result)

    @strawberry.mutation
    def mark_stock_item_unlocated(self, stock_item_id: strawberry.ID) -> StockItem:
        with SessionLocal() as session:
            result = stock_repository.mark_stock_item_unlocated(
                session,
                stock_item_id=uuid.UUID(str(stock_item_id)),
                performed_by="Admin/Manager",
            )
            session.commit()
            session.refresh(result)
            return _stock_item_to_type(result)

    @strawberry.mutation
    def merge_locations(
        self,
        from_aisle: str,
        from_bay: str,
        from_bin: str,
        to_aisle: str,
        to_bay: str,
        to_bin: str,
    ) -> LocationMergeResult:
        with SessionLocal() as session:
            counts = warehouse_repository.merge_locations(
                session,
                from_aisle=from_aisle,
                from_bay=from_bay,
                from_bin=from_bin,
                to_aisle=to_aisle,
                to_bay=to_bay,
                to_bin=to_bin,
                performed_by="Admin/Manager",
            )
            session.commit()
            return LocationMergeResult(
                inventory_locations=counts["inventory_locations"],
                opening_items=counts["opening_items"],
                stock_items=counts["stock_items"],
            )

    @strawberry.mutation
    def reclassify_stock_item(self, input: ReclassifyStockItemInput) -> ReclassifyStockResult:
        with SessionLocal() as session:
            new_row, original = stock_repository.reclassify_stock_item(
                session,
                stock_item_id=uuid.UUID(str(input.stock_item_id)),
                new_hardware_category=input.new_hardware_category,
                new_product_code=input.new_product_code,
                quantity=input.quantity,
                reason_text=input.reason_text,
                performed_by=input.performed_by or "Admin/Manager",
            )
            session.commit()
            session.refresh(new_row)
            if original is not None:
                session.refresh(original)
            return ReclassifyStockResult(
                reclassified_stock_item=_stock_item_to_type(new_row),
                original_stock_item=_stock_item_to_type(original) if original else None,
            )

    @strawberry.mutation
    def report_inventory_deficiency(self, input: ReportInventoryDeficiencyInput) -> InventoryLocation:
        with SessionLocal() as session:
            il = stock_repository.report_inventory_deficiency(
                session,
                inventory_location_id=uuid.UUID(str(input.inventory_location_id)),
                quantity=input.quantity,
                reason_text=input.reason_text,
                performed_by=input.performed_by or "Admin/Manager",
            )
            session.commit()
            session.refresh(il)
            return _inventory_location_to_type(il)

    @strawberry.mutation
    def report_stock_deficiency(self, input: ReportStockDeficiencyInput) -> StockItem:
        with SessionLocal() as session:
            si = stock_repository.report_stock_deficiency(
                session,
                stock_item_id=uuid.UUID(str(input.stock_item_id)),
                quantity=input.quantity,
                reason_text=input.reason_text,
                performed_by=input.performed_by or "Admin/Manager",
            )
            session.commit()
            session.refresh(si)
            return _stock_item_to_type(si)

    @strawberry.mutation
    def report_deficiency_at_assembly(self, input: ReportDeficiencyAtAssemblyInput) -> SAReplacementResult:
        with SessionLocal() as session:
            il, pri = stock_repository.report_deficiency_at_assembly(
                session,
                sa_opening_item_id=uuid.UUID(str(input.shop_assembly_opening_item_id)),
                quantity=input.quantity,
                reason_text=input.reason_text,
                performed_by=input.performed_by or "Admin/Manager",
            )
            session.commit()
            session.refresh(il)
            session.refresh(pri)
            return SAReplacementResult(
                inventory_location=_inventory_location_to_type(il),
                replacement_pull_request_item=_pull_request_item_to_type(pri),
            )

    @strawberry.mutation
    def resolve_deficiency(self, input: ResolveDeficiencyInput) -> DeficiencyReview:
        with SessionLocal() as session:
            review = stock_repository.resolve_deficiency(
                session,
                inventory_location_id=(
                    uuid.UUID(str(input.inventory_location_id)) if input.inventory_location_id else None
                ),
                stock_item_id=(uuid.UUID(str(input.stock_item_id)) if input.stock_item_id else None),
                resolution=input.resolution,
                quantity=input.quantity,
                reason_text=input.reason_text,
                rma_reference=input.rma_reference,
                destock_source=input.destock_source,
                reviewed_by=input.reviewed_by or "Admin/Manager",
            )
            session.commit()
            session.refresh(review)
            return _deficiency_review_to_type(review)
