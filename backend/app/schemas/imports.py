"""Hardware-schedule import queries + mutations (module name avoids the `import` keyword)."""

import uuid
from dataclasses import replace

import strawberry

from app.auth import require_user
from app.database import SessionLocal
from app.errors import InventoryShortfallError
from app.repositories import (
    import_repository,
    po_repository,
    project_repository,
    shipping_repository,
    shop_assembly_repository,
)
from app.services import notification_service

from .converters import (
    po_to_type,
    project_hardware_schedule_to_type,
    project_to_type,
    shipping_out_request_to_type,
    shop_assembly_request_to_type,
)
from .inputs import FinalizeImportSessionInput, ReconciliationItemInput
from .types import (
    FinalizeImportResult,
    ProjectExcludedItem,
    ProjectHardwareSchedule,
    ReconciliationResult,
)


@strawberry.type
class ImportQueries:
    @strawberry.field
    def project_hardware_schedule(
        self, info: strawberry.Info, project_id: strawberry.ID
    ) -> ProjectHardwareSchedule | None:
        require_user(info)
        with SessionLocal() as session:
            data = import_repository.get_project_hardware_schedule(session, uuid.UUID(str(project_id)))
            if data is None:
                return None
            return project_hardware_schedule_to_type(data)

    @strawberry.field
    def reconcile_schedule(
        self, info: strawberry.Info, project_id: strawberry.ID, items: list[ReconciliationItemInput]
    ) -> list[ReconciliationResult]:
        require_user(info)
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
    def project_excluded_items(self, info: strawberry.Info, project_id: strawberry.ID) -> list[ProjectExcludedItem]:
        require_user(info)
        with SessionLocal() as session:
            rows = import_repository.list_excluded_items(session, uuid.UUID(str(project_id)))
            return [
                ProjectExcludedItem(
                    hardware_category=row.hardware_category,
                    product_code=row.product_code,
                )
                for row in rows
            ]


@strawberry.type
class ImportMutations:
    @strawberry.mutation
    def finalize_import_session(self, info: strawberry.Info, input: FinalizeImportSessionInput) -> FinalizeImportResult:
        require_user(info)
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
                    "leaf_count": o.leaf_count,
                }
                for o in input.openings
            ],
            "hardware_items": [
                {
                    "opening_number": hi.opening_number,
                    "product_code": hi.product_code,
                    "hardware_category": hi.hardware_category,
                    "leaf": hi.leaf,
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
                            "leaf": item.leaf,
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
                    "leaf": sa.leaf,
                    "items": [
                        {
                            "hardware_category": item.hardware_category,
                            "product_code": item.product_code,
                            "quantity": item.quantity,
                            # None is forwarded as-is; the repository resolves it to `quantity`
                            # (fully allocated), which is the pre-allocator behaviour.
                            "allocated_quantity": item.allocated_quantity,
                        }
                        for item in sa.items
                    ],
                }
                for sa in (input.shop_assembly_openings or [])
            ]
            if input.shop_assembly_openings
            else None,
            "replace_schedule": input.replace_schedule,
            "acknowledge_incomplete_leaves": input.acknowledge_incomplete_leaves,
        }

        with SessionLocal() as session:
            # #342: creating a shop-assembly or shipping-out request gates on available inventory
            # (on-hand - deficient - other requests' reservations) and reserves what it takes. A
            # short selection raises InventoryShortfallError and nothing is written, so the creator
            # refines the selection here rather than the acceptor discovering it later.
            try:
                result = import_repository.finalize_import_session(session, input_data)
            except InventoryShortfallError as e:
                # Notify the PO only for combos that are genuinely *not in the building* - a combo
                # short only because another request has claimed it is not a purchasing problem, and
                # a backfill notification for it would send someone to order stock that already
                # exists. The refusal reaches the creator inline either way.
                session.rollback()
                # ...and for those combos, tell the PO only about the part that is genuinely absent.
                # `short` is measured against *available* (= on-hand - deficient - reservations), so
                # forwarding it verbatim asks purchasing to buy the reserved units a second time.
                # `short - reserved` is what the shelf is actually missing; floored at 0 because a
                # combo whose whole shortfall is other people's claims is not a purchasing problem at
                # all, and it has already been filtered out above.
                unstocked = [
                    replace(s, short=max(0, s.short - s.reserved)) for s in e.shortfalls if s.short > s.reserved
                ]
                if unstocked:
                    with SessionLocal() as notif_session:
                        notification_service.notify_po_shortfall(
                            notif_session,
                            project_id=e.project_id,
                            request_number=e.request_number,
                            shortfalls=unstocked,
                        )
                        notif_session.commit()
                raise
            session.commit()

            # Re-load everything with the relationships the response types walk
            project = project_repository.get_project_with_openings(session, result["project"].id)
            pos = [po_repository.reload_po(session, po_obj.id) for po_obj in result["purchase_orders"]]
            shipping_requests = [
                shipping_repository.get_shipping_out_request(session, req_obj.id)
                for req_obj in result["shipping_out_requests"]
            ]

            sar_type = None
            if result["shop_assembly_request"] is not None:
                refreshed_sar = shop_assembly_repository.get_request_with_openings(
                    session, result["shop_assembly_request"].id
                )
                sar_type = shop_assembly_request_to_type(refreshed_sar)

            return FinalizeImportResult(
                project=project_to_type(project),
                purchase_orders=[po_to_type(po) for po in pos],
                shipping_out_requests=[shipping_out_request_to_type(req) for req in shipping_requests],
                shop_assembly_request=sar_type,
            )
