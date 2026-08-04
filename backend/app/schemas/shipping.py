"""Shipping queries + mutations: ship-ready items, packing slips, returns."""

import uuid

import strawberry

from app.auth import current_user, resolve_display_name
from app.database import SessionLocal
from app.repositories import shipping_coverage, shipping_repository, shipping_requests

from .converters import (
    opening_item_to_type,
    packing_slip_to_type,
    shipment_return_to_type,
    shipping_out_request_to_type,
)
from .enums import LeafStatus, ShippingOutRequestStatus
from .inputs import (
    ConfirmShipmentInput,
    CreateShipmentReturnInput,
    CreateShippingOutRequestInput,
    EditShippingOutRequestInput,
    ShippingOutPRDraftItemInput,
    UpdateShipmentDetailsInput,
)
from .types import (
    PackingSlip,
    ReturnableLine,
    ShipmentReturn,
    ShippingCoverageLeaf,
    ShippingCoverageLine,
    ShippingOutRequest,
    ShipReadyItems,
    ShipReadyLooseItem,
)


def _delivery_details(input) -> dict:
    """The Delivery Request header off a mutation input, keyed the way the repository writes it.

    Read off `DELIVERY_REQUEST_FIELDS` rather than listed here, so the confirm input, the edit input
    and the columns cannot drift apart: a field added to the header reaches both mutations or neither.
    """
    return {field: getattr(input, field) for field in shipping_repository.DELIVERY_REQUEST_FIELDS}


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
    def shipping_coverage(
        self,
        info: strawberry.Info,
        project_id: strawberry.ID,
        opening_numbers: list[str],
    ) -> list[ShippingCoverageLeaf]:
        """What the selected openings still owe the site, leaf by leaf (#451).

        The shipping-out builder asks this the moment openings are picked, so it can tell the user
        what belongs with them beyond the assembled leaves themselves: the site hardware that never
        goes near the bench, and the shop hardware assembly had to skip. See
        `app.repositories.shipping_coverage` for how each number is derived.
        """
        with SessionLocal() as session:
            leaves = shipping_coverage.get_shipping_coverage(session, uuid.UUID(str(project_id)), opening_numbers)
            return [
                ShippingCoverageLeaf(
                    opening_number=leaf["opening_number"],
                    leaf=leaf["leaf"],
                    status=LeafStatus(leaf["status"]),
                    opening_item_id=(strawberry.ID(str(leaf["opening_item_id"])) if leaf["opening_item_id"] else None),
                    claimed_by_request_number=leaf["claimed_by_request_number"],
                    lines=[
                        ShippingCoverageLine(
                            hardware_category=line["hardware_category"],
                            product_code=line["product_code"],
                            classification=line["classification"],
                            owed_quantity=line["owed_quantity"],
                            installed_quantity=line["installed_quantity"],
                            spoken_for_quantity=line["spoken_for_quantity"],
                            suggested_quantity=line["suggested_quantity"],
                            on_order_quantity=line["on_order_quantity"],
                        )
                        for line in leaf["lines"]
                    ],
                )
                for leaf in leaves
            ]

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


def _request_items(items: list[ShippingOutPRDraftItemInput]) -> list[dict]:
    """Request lines off a mutation input, keyed the way the repository builds them."""
    return [
        {
            "item_type": item.item_type.value,
            "opening_number": item.opening_number,
            "opening_item_id": str(item.opening_item_id) if item.opening_item_id else None,
            "leaf": item.leaf,
            "hardware_category": item.hardware_category,
            "product_code": item.product_code,
            "requested_quantity": item.requested_quantity,
        }
        for item in items
    ]


@strawberry.type
class ShippingMutations:
    @strawberry.mutation
    def create_shipping_out_request(
        self, info: strawberry.Info, input: CreateShippingOutRequestInput
    ) -> ShippingOutRequest:
        """Raise a shipping-out request from the Shipping module, off project inventory (#451).

        The schedule is not the only reason hardware goes to site. Before this, stock the schedule
        never accounted for could only be sent by walking back through the import wizard and finding
        an opening to hang it on, so the request said something about the job that was not true.

        Everything past composition is identical to the Start-a-Task path - same guards, same
        reservation of what the loose lines claim (#342), same PENDING request somebody then
        accepts. Recorded against the Clerk-authenticated caller (#427).
        """
        auth = current_user(info)
        actor = resolve_display_name(auth["user_id"])
        with SessionLocal() as session:
            created = shipping_requests.create_shipping_out_requests(
                session,
                uuid.UUID(str(input.project_id)),
                [{"request_number": input.request_number, "items": _request_items(input.items)}],
                created_by=actor,
                acknowledge_incomplete_leaves=input.acknowledge_incomplete_leaves,
            )
            session.commit()
            refreshed = shipping_repository.get_shipping_out_request(session, created[0].id)
            return shipping_out_request_to_type(refreshed)

    @strawberry.mutation
    def edit_shipping_out_request(
        self, info: strawberry.Info, input: EditShippingOutRequestInput
    ) -> ShippingOutRequest:
        """Rewrite a PENDING request's lines (#451).

        The point is that a request can be corrected before anyone accepts it: a line was missed, a
        quantity was wrong, the site asked for one more box. Refused once accepted, because the
        lines are on a warehouse pull by then and the floor may be picking against a printed sheet.

        Full replace over the item list, re-gated against availability with the request's own claim
        released first - so reducing a line is never refused for stock it already holds.
        """
        with SessionLocal() as session:
            req = shipping_requests.replace_shipping_out_request_items(
                session,
                uuid.UUID(str(input.id)),
                _request_items(input.items),
                acknowledge_incomplete_leaves=input.acknowledge_incomplete_leaves,
            )
            session.commit()
            refreshed = shipping_repository.get_shipping_out_request(session, req.id)
            return shipping_out_request_to_type(refreshed)

    @strawberry.mutation
    def accept_shipping_out_request(self, info: strawberry.Info, id: strawberry.ID) -> ShippingOutRequest:
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
        self, info: strawberry.Info, id: strawberry.ID, reason: str | None = None
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
        """Cut the packing slip for what actually went on the truck, and write its Delivery Request.

        `shippedBy` is printed on the slip and shown in the shipments grid, so it is the record of
        who released the hardware. It is the Clerk-authenticated caller as of #427; the input field
        that used to name it was dropped in #438.

        The slip is born SCHEDULED (#447), carrying the header the shipping department filled in.
        What this does to inventory is unchanged - the states that follow document the truck's
        journey, not the hardware's."""
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
                _delivery_details(input),
            )
            session.commit()
            refreshed = shipping_repository.get_packing_slip(session, ps.id)
            return packing_slip_to_type(refreshed)

    @strawberry.mutation
    def update_shipment_details(self, info: strawberry.Info, input: UpdateShipmentDetailsInput) -> PackingSlip:
        """Correct the Delivery Request of a shipment that has not left yet (#447).

        Refused once the shipment is past SCHEDULED: from the moment it is picked up a driver holds a
        printed copy, and the stored record has to keep matching the paper the site will sign.

        Full replace over the header - a field sent as null is cleared. Nothing about what shipped is
        touched."""
        with SessionLocal() as session:
            ps = shipping_repository.update_shipment_details(
                session,
                uuid.UUID(str(input.id)),
                _delivery_details(input),
            )
            session.commit()
            refreshed = shipping_repository.get_packing_slip(session, ps.id)
            return packing_slip_to_type(refreshed)

    @strawberry.mutation
    def mark_shipment_picked_up(self, info: strawberry.Info, id: strawberry.ID) -> PackingSlip:
        """The carrier has the load: SCHEDULED -> PICKED_UP (#447).

        Moves no inventory - the hardware was claimed when the shipment was confirmed. Recorded
        against the Clerk-authenticated caller (#427), which is also what closes the header to
        further edits."""
        auth = current_user(info)
        actor = resolve_display_name(auth["user_id"])
        with SessionLocal() as session:
            ps = shipping_repository.mark_shipment_picked_up(session, uuid.UUID(str(id)), actor)
            session.commit()
            refreshed = shipping_repository.get_packing_slip(session, ps.id)
            return packing_slip_to_type(refreshed)

    @strawberry.mutation
    def mark_shipment_delivered(self, info: strawberry.Info, id: strawberry.ID) -> PackingSlip:
        """The load reached the site: PICKED_UP -> DELIVERED (#447).

        Only from PICKED_UP, so a shipment can never be recorded as arriving somewhere it was never
        collected for. Recorded against the Clerk-authenticated caller (#427)."""
        auth = current_user(info)
        actor = resolve_display_name(auth["user_id"])
        with SessionLocal() as session:
            ps = shipping_repository.mark_shipment_delivered(session, uuid.UUID(str(id)), actor)
            session.commit()
            refreshed = shipping_repository.get_packing_slip(session, ps.id)
            return packing_slip_to_type(refreshed)

    @strawberry.mutation
    def create_shipment_return(self, info: strawberry.Info, input: CreateShipmentReturnInput) -> ShipmentReturn:
        """Book hardware back off a packing slip. `returnedBy` is the Clerk-authenticated caller
        (#427); the input field that used to name it was dropped in #438."""
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
