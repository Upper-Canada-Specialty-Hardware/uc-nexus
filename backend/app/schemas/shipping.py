"""Shipping queries + mutations: ship-ready items, packing slips, returns."""

import uuid

import strawberry

from app.auth import current_user, resolve_display_name
from app.database import SessionLocal
from app.repositories import shipping_repository

from .converters import (
    opening_item_to_type,
    packing_slip_to_type,
    shipment_return_to_type,
    shipping_out_request_to_type,
)
from .enums import ShippingOutRequestStatus
from .inputs import ConfirmShipmentInput, CreateShipmentReturnInput, IgnoredActorArg
from .types import (
    PackingSlip,
    ReturnableLine,
    ShipmentReturn,
    ShippingOutRequest,
    ShipReadyItems,
    ShipReadyLooseItem,
)


@strawberry.type
class ShippingQueries:
    @strawberry.field
    def ship_ready_items(self, info: strawberry.Info, project_id: strawberry.ID | None = None) -> ShipReadyItems:
        with SessionLocal() as session:
            data = shipping_repository.get_ship_ready_items(session, uuid.UUID(str(project_id)) if project_id else None)
            return ShipReadyItems(
                opening_items=[opening_item_to_type(oi) for oi in data["opening_items"]],
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
    def packing_slips(self, info: strawberry.Info, project_id: strawberry.ID | None = None) -> list[PackingSlip]:
        with SessionLocal() as session:
            slips = shipping_repository.list_packing_slips(session, uuid.UUID(str(project_id)) if project_id else None)
            return [packing_slip_to_type(ps) for ps in slips]

    @strawberry.field
    def shipping_out_requests(
        self,
        info: strawberry.Info,
        project_id: strawberry.ID | None = None,
        status: ShippingOutRequestStatus | None = None,
        reopenable_only: bool = False,
    ) -> list[ShippingOutRequest]:
        """Accept UI (#293): shipping-out requests for a project, PENDING by default. reopenableOnly
        (#325) keeps only requests whose minted pull request is still PENDING - the Approved/reopen
        view uses it so it lists only requests Reopen can still act on."""
        with SessionLocal() as session:
            reqs = shipping_repository.get_shipping_out_requests(
                session, uuid.UUID(str(project_id)) if project_id else None, status, reopenable_only
            )
            return [shipping_out_request_to_type(r) for r in reqs]

    @strawberry.field
    def returnable_lines(self, info: strawberry.Info, packing_slip_id: strawberry.ID) -> list[ReturnableLine]:
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


@strawberry.type
class ShippingMutations:
    @strawberry.mutation
    def accept_shipping_out_request(
        self, info: strawberry.Info, id: strawberry.ID, accepted_by: IgnoredActorArg = None
    ) -> ShippingOutRequest:
        """Accept a PENDING shipping-out request (#293). Open to any signed-in user. Mints the
        warehouse PullRequest (SHIPPING_OUT, PENDING) from the request's items; the warehouse
        approve handles any inventory shortfall (no gate here).

        The approval names the Clerk-authenticated caller (#427), and carries onto the minted pull's
        `requestedBy`."""
        auth = current_user(info)
        actor = resolve_display_name(auth["user_id"])
        request_id = uuid.UUID(str(id))
        with SessionLocal() as session:
            shipping_repository.accept_shipping_out_request(session, request_id, actor)
            session.commit()
            refreshed = shipping_repository.get_shipping_out_request(session, request_id)
            return shipping_out_request_to_type(refreshed)

    @strawberry.mutation
    def reject_shipping_out_request(
        self, info: strawberry.Info, id: strawberry.ID, rejected_by: IgnoredActorArg = None, reason: str | None = None
    ) -> ShippingOutRequest:
        """Reject a PENDING shipping-out request (#293). Open to any signed-in user. Recorded against
        the Clerk-authenticated caller (#427)."""
        auth = current_user(info)
        actor = resolve_display_name(auth["user_id"])
        request_id = uuid.UUID(str(id))
        with SessionLocal() as session:
            shipping_repository.reject_shipping_out_request(session, request_id, actor, reason)
            session.commit()
            refreshed = shipping_repository.get_shipping_out_request(session, request_id)
            return shipping_out_request_to_type(refreshed)

    @strawberry.mutation
    def reopen_shipping_out_request(self, info: strawberry.Info, id: strawberry.ID) -> ShippingOutRequest:
        """Reopen an APPROVED shipping-out request back to PENDING (#325). Undoes an erroneous accept:
        hard-deletes the warehouse PullRequest the accept minted and flips the request to PENDING so it
        can be re-accepted or rejected. Refused if the warehouse has already worked the pull. Open to
        any signed-in user."""
        request_id = uuid.UUID(str(id))
        with SessionLocal() as session:
            shipping_repository.reopen_shipping_out_request(session, request_id)
            session.commit()
            refreshed = shipping_repository.get_shipping_out_request(session, request_id)
            return shipping_out_request_to_type(refreshed)

    @strawberry.mutation
    def confirm_shipment(self, info: strawberry.Info, input: ConfirmShipmentInput) -> PackingSlip:
        """Cut the packing slip for what actually went on the truck.

        `shippedBy` is printed on the slip and shown in the shipments grid, so it is the record of
        who released the hardware. It is the Clerk-authenticated caller as of #427; the input field
        is still accepted and ignored."""
        auth = current_user(info)
        actor = resolve_display_name(auth["user_id"])
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
                actor,
                items_data,
            )
            session.commit()
            refreshed = shipping_repository.get_packing_slip(session, ps.id)
            return packing_slip_to_type(refreshed)

    @strawberry.mutation
    def create_shipment_return(self, info: strawberry.Info, input: CreateShipmentReturnInput) -> ShipmentReturn:
        """Book hardware back off a packing slip. `returnedBy` is the Clerk-authenticated caller
        (#427); the input field is still accepted and ignored."""
        auth = current_user(info)
        actor = resolve_display_name(auth["user_id"])
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
                returned_by=actor,
                reference=input.reference,
                items=items_data,
            )
            session.commit()
            refreshed = shipping_repository.get_shipment_return(session, sr.id)
            return shipment_return_to_type(refreshed)
