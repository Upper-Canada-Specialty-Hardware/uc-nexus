import uuid
from datetime import date

import strawberry
from sqlalchemy import select

from app.database import SessionLocal
from app.repositories import (
    notification_repository,
    po_repository,
    shipping_repository,
    shop_assembly_repository,
    user_repository,
    warehouse_repository,
)

from .enums import ApproveOutcome, PODocumentType
from .inputs import (
    AssignOpeningsInput,
    CompleteOpeningInput,
    ConfirmShipmentInput,
    CreatePOInput,
    CreateReceiveInput,
    FinalizeImportSessionInput,
)
from .queries import (
    _inventory_location_to_type,
    _notification_to_type,
    _opening_item_to_type,
    _packing_slip_to_type,
    _po_document_to_type,
    _po_line_item_to_type,
    _po_to_type,
    _project_to_type,
    _pull_request_to_type,
    _receive_record_to_type,
    _shop_assembly_opening_to_type,
    _shop_assembly_request_to_type,
)
from .types import (
    ApproveResult,
    ApproveShopAssemblyResult,
    ClerkUser,
    FinalizeImportResult,
    InventoryLocation,
    Notification,
    OpeningItem,
    PODocumentInfo,
    POLineItem,
    PullRequest,
    PurchaseOrder,
    ReceiveRecord,
    ShopAssemblyOpening,
    ShopAssemblyRequest,
)
from .types import (
    PackingSlip as PackingSlipType,
)


@strawberry.type
class Mutation:
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
            "project": {
                "project_id": input.project.project_id,
                "description": input.project.description,
                "job_site_name": input.project.job_site_name,
                "address": input.project.address,
                "city": input.project.city,
                "state": input.project.state,
                "zip": input.project.zip,
                "contractor": input.project.contractor,
                "project_manager": input.project.project_manager,
                "application": input.project.application,
                "submittal_job_no": input.project.submittal_job_no,
                "submittal_assignment_count": input.project.submittal_assignment_count,
                "estimator_code": input.project.estimator_code,
                "titan_user_id": input.project.titan_user_id,
            },
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
                    "vendor_name": po.vendor_name,
                    "vendor_contact": po.vendor_contact,
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
        }

        with SessionLocal() as session:
            result = import_repository.finalize_import_session(session, input_data)
            session.commit()

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

            # Re-load POs with line_items and documents
            pos = []
            for po_obj in result["purchase_orders"]:
                refreshed_po = (
                    session.scalars(
                        select(POModel)
                        .options(selectinload(POModel.line_items), selectinload(POModel.documents))
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

            return FinalizeImportResult(
                project=_project_to_type(project),
                purchase_orders=[_po_to_type(po) for po in pos],
                shipping_out_pull_requests=[_pull_request_to_type(pr) for pr in prs],
                shop_assembly_request=sar_type,
            )

    # PO
    @strawberry.mutation
    def create_po(self, input: CreatePOInput) -> PurchaseOrder:
        from sqlalchemy.orm import selectinload

        from app.models.purchase_order import PurchaseOrder as POModel

        project_id = uuid.UUID(str(input.project_id)) if input.project_id else None
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
                project_id=project_id,
                vendor_name=input.vendor_name,
                vendor_contact=input.vendor_contact,
            )
            session.commit()

            # Re-load with line_items and documents
            refreshed_po = (
                session.scalars(
                    select(POModel)
                    .options(selectinload(POModel.line_items), selectinload(POModel.documents))
                    .where(POModel.id == po.id)
                )
                .unique()
                .first()
            )
            return _po_to_type(refreshed_po)

    @strawberry.mutation
    def update_po(
        self,
        id: strawberry.ID,
        vendor_name: str | None = None,
        vendor_contact: str | None = None,
        expected_delivery_date: date | None = None,
        po_number: str | None = None,
        vendor_quote_number: str | None = None,
        project_id: strawberry.ID | None = None,
    ) -> PurchaseOrder:
        from app.repositories.po_repository import _UNSET

        pid = uuid.UUID(str(project_id)) if project_id else _UNSET
        with SessionLocal() as session:
            po = po_repository.update_po(
                session,
                uuid.UUID(str(id)),
                vendor_name,
                vendor_contact,
                expected_delivery_date,
                po_number=po_number,
                vendor_quote_number=vendor_quote_number,
                project_id=pid,
            )
            session.commit()
            session.refresh(po)
            return _po_to_type(po)

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
    def create_receive(self, input: CreateReceiveInput) -> ReceiveRecord:
        po_id = uuid.UUID(str(input.po_id))
        received_by = input.received_by
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
                    }
                    for loc in li.locations
                ],
            }
            for li in input.line_items
        ]
        with SessionLocal() as session:
            receive_record = warehouse_repository.create_receive(session, po_id, received_by, line_items_data)
            session.commit()
            session.refresh(receive_record)
            # Eagerly load line_items for the response
            from sqlalchemy import select
            from sqlalchemy.orm import selectinload

            from app.models.receiving import ReceiveRecord as ReceiveRecordModel

            stmt = (
                select(ReceiveRecordModel)
                .options(selectinload(ReceiveRecordModel.line_items))
                .where(ReceiveRecordModel.id == receive_record.id)
            )
            receive_record = session.scalars(stmt).unique().first()
            return _receive_record_to_type(receive_record)

    # Warehouse - Pull Requests
    @strawberry.mutation
    def approve_pull_request(self, id: strawberry.ID, approved_by: str) -> ApproveResult:
        with SessionLocal() as session:
            pr, outcome, notification = warehouse_repository.approve_pull_request(
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
                outcome=ApproveOutcome.APPROVED if outcome == "APPROVED" else ApproveOutcome.CANCELLED,
                notification=_notification_to_type(notification) if notification else None,
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
    ) -> OpeningItem:
        with SessionLocal() as session:
            result = warehouse_repository.move_opening_item_location(
                session, uuid.UUID(str(opening_item_id)), aisle, bay, bin
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

    # Shop Assembly
    @strawberry.mutation
    def approve_shop_assembly_request(self, id: strawberry.ID) -> ApproveShopAssemblyResult:
        with SessionLocal() as session:
            sar, pr = shop_assembly_repository.approve_shop_assembly_request(session, uuid.UUID(str(id)))
            session.commit()
            # Re-load with eager loading for relationships
            from sqlalchemy.orm import selectinload

            from app.models.pull_request import PullRequest as PRModel
            from app.models.shop_assembly import (
                ShopAssemblyOpening as SAOModel,
            )
            from app.models.shop_assembly import (
                ShopAssemblyRequest as SARModel,
            )

            sar = (
                session.scalars(
                    select(SARModel)
                    .options(selectinload(SARModel.openings).selectinload(SAOModel.items))
                    .where(SARModel.id == sar.id)
                )
                .unique()
                .first()
            )
            pr = (
                session.scalars(select(PRModel).options(selectinload(PRModel.items)).where(PRModel.id == pr.id))
                .unique()
                .first()
            )
            return ApproveShopAssemblyResult(
                shop_assembly_request=_shop_assembly_request_to_type(sar),
                pull_request=_pull_request_to_type(pr),
            )

    @strawberry.mutation
    def reject_shop_assembly_request(self, id: strawberry.ID, reason: str) -> ShopAssemblyRequest:
        with SessionLocal() as session:
            sar = shop_assembly_repository.reject_shop_assembly_request(session, uuid.UUID(str(id)), reason)
            session.commit()
            session.refresh(sar)
            return _shop_assembly_request_to_type(sar)

    @strawberry.mutation
    def assign_openings(self, input: AssignOpeningsInput) -> list[ShopAssemblyOpening]:
        opening_ids = [uuid.UUID(str(oid)) for oid in input.opening_ids]
        with SessionLocal() as session:
            result = shop_assembly_repository.assign_openings(session, opening_ids, input.assigned_to)
            session.commit()
            # Re-load with items + join Opening for opening_number/building/floor
            from sqlalchemy.orm import selectinload

            from app.models.project import Opening as OpeningModel
            from app.models.shop_assembly import ShopAssemblyOpening as SAOModel

            stmt = (
                select(SAOModel, OpeningModel)
                .join(OpeningModel, SAOModel.opening_id == OpeningModel.id)
                .options(selectinload(SAOModel.items))
                .where(SAOModel.id.in_([o.id for o in result]))
            )
            rows = list(session.execute(stmt).unique().all())
            return [_shop_assembly_opening_to_type(sao, opening_model=opening) for sao, opening in rows]

    @strawberry.mutation
    def remove_opening_from_user(self, opening_id: strawberry.ID) -> ShopAssemblyOpening:
        with SessionLocal() as session:
            result = shop_assembly_repository.remove_opening_from_user(session, uuid.UUID(str(opening_id)))
            session.commit()
            session.refresh(result)
            # Re-load with items + join Opening for opening_number/building/floor
            from sqlalchemy.orm import selectinload

            from app.models.project import Opening as OpeningModel
            from app.models.shop_assembly import ShopAssemblyOpening as SAOModel

            stmt = (
                select(SAOModel, OpeningModel)
                .join(OpeningModel, SAOModel.opening_id == OpeningModel.id)
                .options(selectinload(SAOModel.items))
                .where(SAOModel.id == result.id)
            )
            row = session.execute(stmt).unique().first()
            refreshed, opening = row
            return _shop_assembly_opening_to_type(refreshed, opening_model=opening)

    @strawberry.mutation
    def complete_opening(self, input: CompleteOpeningInput) -> OpeningItem:
        with SessionLocal() as session:
            result = shop_assembly_repository.complete_opening(
                session,
                uuid.UUID(str(input.opening_id)),
                input.aisle,
                input.bay,
                input.bin,
            )
            session.commit()
            session.refresh(result)
            # Re-load with installed_hardware
            from sqlalchemy.orm import selectinload

            from app.models.opening_item import OpeningItem as OIModel

            stmt = select(OIModel).options(selectinload(OIModel.installed_hardware)).where(OIModel.id == result.id)
            refreshed = session.scalars(stmt).unique().first()
            return _opening_item_to_type(refreshed)

    @strawberry.mutation
    def update_user_roles(self, user_id: str, roles: list[str]) -> ClerkUser:
        result = user_repository.update_user_roles(user_id, roles)
        return ClerkUser(
            id=result["id"],
            first_name=result["first_name"],
            last_name=result["last_name"],
            email=result["email"],
            roles=result["roles"],
            image_url=result["image_url"],
        )
