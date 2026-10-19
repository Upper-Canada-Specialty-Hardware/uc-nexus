"""Shipping queries + mutations: ship-ready items, packing slips, returns."""

import uuid

import strawberry
from sqlalchemy import func, select

from app.auth import (
    DRIVER_ROLE,
    ForbiddenError,
    caller_roles,
    current_user,
    resolve_display_name,
    tenant_scope,
    user_roster,
)
from app.database import SessionLocal
from app.errors import NotFoundError
from app.models.enums import ShipmentStatus as ShipmentStatusDB
from app.models.project import Opening as OpeningModel
from app.models.project import Project as ProjectModel
from app.models.shipping import PackingSlip as PackingSlipModel
from app.repositories import (
    drivers,
    po_trace,
    rack_locations,
    request_composer,
    shipment_containers,
    shipment_loads,
    shipment_method_repository,
    shipment_photos,
    shipping_repository,
    shipping_requests,
    tenancy,
)

from .converters import (
    container_to_type,
    packing_slip_to_type,
    project_to_type,
    shipment_load_to_type,
    shipment_photo_to_type,
    shipment_return_to_type,
    shipping_out_request_to_type,
)
from .enums import ShipmentContainerType as ShipmentContainerTypeEnum
from .enums import ShipmentPhotoKind as ShipmentPhotoKindEnum
from .enums import ShipmentStatus as ShipmentStatusEnum
from .enums import ShippingOutRequestStatus
from .inputs import (
    ConfirmShipmentFromContainersInput,
    CreateShipmentReturnInput,
    CreateShippingOutRequestInput,
    EditShippingOutRequestInput,
    MoveContainerItemsInput,
    SetContainerItemsInput,
    ShippingOutPRDraftItemInput,
    UpdateShipmentDetailsInput,
)
from .types import (
    PackingSlip,
    ProductRackLocations,
    RackLocation,
    RequestCoverageLine,
    ReturnableLine,
    ShipmentContainer,
    ShipmentDriver,
    ShipmentLoad,
    ShipmentMethod,
    ShipmentPhoto,
    ShipmentReturn,
    ShippingOutRequest,
    ShippingOutRequestReservedProduct,
    ShipReadyItems,
    ShipReadyLooseItem,
    SlipLinePoTrace,
    StagedLooseItem,
    StagingPool,
    StagingProjectSummary,
)


def _staged_lines(pool: dict) -> list[StagedLooseItem]:
    """A staged pool as the workspace and the overview both show it, by opening then product."""
    return [
        StagedLooseItem(
            opening_number=key[0],
            hardware_category=key[1],
            product_code=key[2],
            staged_quantity=counts["staged"],
            placed_quantity=counts["placed"],
            unplaced_quantity=max(0, counts["staged"] - counts["placed"]),
        )
        for key, counts in sorted(pool.items(), key=lambda pair: tuple(str(part) for part in pair[0]))
    ]


def _container_items_input(items) -> list[dict]:
    return [
        {
            "opening_number": i.opening_number,
            "hardware_category": i.hardware_category,
            "product_code": i.product_code,
            "quantity": i.quantity,
            "is_manual": i.is_manual,
        }
        for i in items
    ]


def _shipment_method_to_type(m) -> ShipmentMethod:
    return ShipmentMethod(
        id=strawberry.ID(str(m.id)),
        name=m.name,
        is_active=m.is_active,
        sort_order=m.sort_order,
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


def _delivery_details(input) -> dict:
    """The Delivery Request header off a mutation input, keyed the way the repository writes it.

    Read off `DELIVERY_REQUEST_FIELDS` rather than listed here, so the confirm input, the edit input
    and the columns cannot drift apart: a field added to the header reaches both mutations or neither.
    """
    return {field: getattr(input, field) for field in shipping_repository.DELIVERY_REQUEST_FIELDS}


def _resolve_driver(info: strawberry.Info, session, project_id: uuid.UUID, driver_user_id: str | None):
    """The driver a write names (#1726), checked against the Clerk roster: (user id, name), or None.
    The roster is only fetched when a driver is named - most shipments go by courier."""
    if not driver_user_id:
        return None
    company = session.scalar(select(ProjectModel.company).where(ProjectModel.id == project_id))
    return drivers.resolve_driver(user_roster(info.context), company, driver_user_id)


def _refuse_another_drivers_shipment(info: strawberry.Info, session, packing_slip_id: uuid.UUID, user_id: str) -> None:
    """An account that is only a driver moves only the shipments it drives (#1727).

    Anybody else working shipments - shipping, the warehouse, the office - still marks any of them, as
    before; the driver page is a narrower door, not a new rule for them.
    """
    roles = set(caller_roles(info.context))
    if roles != {DRIVER_ROLE}:
        return
    driver = session.scalar(select(PackingSlipModel.driver_user_id).where(PackingSlipModel.id == packing_slip_id))
    if driver != user_id:
        raise ForbiddenError("This shipment is another driver's.")


def _requests_to_types(session, reqs) -> list[ShippingOutRequest]:
    """Requests with their derived stage and return-note, in one extra query each for the whole list.

    Resolved here rather than as field resolvers so the list page pays two grouped reads, not a
    per-row lookup over Railway's network hop (CLAUDE.md perf rules) - mirrors the shop-assembly twin
    in `app/schemas/shop_assembly.py`.
    """
    stages = shipping_repository.get_request_stages(session, reqs)
    notes = shipping_repository.get_return_notes(session, reqs)
    return [shipping_out_request_to_type(r, stage=stages.get(r.id), return_note=notes.get(r.id)) for r in reqs]


@strawberry.type
class ShippingQueries:
    @strawberry.field
    def ship_ready_items(self, info: strawberry.Info, project_id: strawberry.ID | None = None) -> ShipReadyItems:
        with SessionLocal() as session:
            scope = tenant_scope(info)
            pid = uuid.UUID(str(project_id)) if project_id else None
            tenancy.require_project_in_scope(session, pid, scope)
            data = shipping_repository.get_ship_ready_items(session, pid, company=scope)
            return ShipReadyItems(
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
    def packing_slips(
        self,
        info: strawberry.Info,
        project_id: strawberry.ID | None = None,
        search: str | None = None,
        status: ShipmentStatusEnum | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[PackingSlip]:
        """One page of shipments, newest first (#1107). `search` matches the slip number; `limit`
        defaults to 25 and is capped at 200. `packingSlipCount` answers how many the filter matches."""
        with SessionLocal() as session:
            scope = tenant_scope(info)
            pid = uuid.UUID(str(project_id)) if project_id else None
            tenancy.require_project_in_scope(session, pid, scope)
            slips = shipping_repository.list_packing_slips(
                session,
                pid,
                company=scope,
                search=search,
                status=ShipmentStatusDB(status.value) if status is not None else None,
                limit=limit,
                offset=offset,
            )
            return [packing_slip_to_type(ps) for ps in slips]

    @strawberry.field
    def joinable_loads(self, info: strawberry.Info, project_id: strawberry.ID) -> list[ShipmentLoad]:
        """The loads a shipment of `projectId` can join (#1720): its company's loads still on the dock,
        soonest first. Confirming with none of them starts a new load."""
        with SessionLocal() as session:
            pid = uuid.UUID(str(project_id))
            tenancy.require_project_in_scope(session, pid, tenant_scope(info))
            project = session.get(ProjectModel, pid)
            if project is None:
                raise NotFoundError(f"Project {project_id} not found")
            return [shipment_load_to_type(load) for load in shipment_loads.joinable_loads(session, project.company)]

    @strawberry.field
    def project_rack_locations(self, info: strawberry.Info, project_id: strawberry.ID) -> list[ProductRackLocations]:
        """Where each of a project's products sits on the racks (#1730), for raising, accepting and returning
        shipping requests with the bin in front of the person rather than in a spreadsheet."""
        with SessionLocal() as session:
            pid = uuid.UUID(str(project_id))
            tenancy.require_project_in_scope(session, pid, tenant_scope(info))
            return [
                ProductRackLocations(
                    hardware_category=p["hardware_category"],
                    product_code=p["product_code"],
                    locations=[RackLocation(**loc) for loc in p["locations"]],
                )
                for p in rack_locations.project_rack_locations(session, pid)
            ]

    @strawberry.field
    def slip_po_trace(self, info: strawberry.Info, packing_slip_id: strawberry.ID) -> list[SlipLinePoTrace]:
        """Each line of a shipment with the POs its product could have come in on (#1732). Read when a
        shipment is opened, not with the list - it is a drill-down, and most rows are never opened."""
        with SessionLocal() as session:
            sid = uuid.UUID(str(packing_slip_id))
            tenancy.require_packing_slip_in_scope(session, sid, tenant_scope(info))
            return [
                SlipLinePoTrace(packing_slip_item_id=strawberry.ID(str(item_id)), po_numbers=numbers)
                for item_id, numbers in po_trace.slip_candidate_pos(session, sid).items()
            ]

    @strawberry.field
    def my_deliveries(self, info: strawberry.Info) -> list[PackingSlip]:
        """The caller's own shipments still on the road (#1727): what the driver page lists."""
        user_id = current_user(info)["user_id"]
        with SessionLocal() as session:
            slips = shipping_repository.list_driver_shipments(session, user_id, company=tenant_scope(info))
            return [packing_slip_to_type(ps) for ps in slips]

    @strawberry.field
    def shipment_drivers(self, info: strawberry.Info, project_id: strawberry.ID) -> list[ShipmentDriver]:
        """Who can drive a shipment of `projectId` (#1726): the Driver accounts of its company."""
        with SessionLocal() as session:
            pid = uuid.UUID(str(project_id))
            tenancy.require_project_in_scope(session, pid, tenant_scope(info))
            company = session.scalar(select(ProjectModel.company).where(ProjectModel.id == pid))
            if company is None:
                raise NotFoundError(f"Project {project_id} not found")
        return [
            ShipmentDriver(user_id=u["id"], name=drivers.display_name(u))
            for u in drivers.drivers_for(user_roster(info.context), company)
        ]

    @strawberry.field
    def packing_slip_count(
        self,
        info: strawberry.Info,
        project_id: strawberry.ID | None = None,
        search: str | None = None,
        status: ShipmentStatusEnum | None = None,
    ) -> int:
        """How many shipments `packingSlips` would page through for the same filter (#1107)."""
        with SessionLocal() as session:
            scope = tenant_scope(info)
            pid = uuid.UUID(str(project_id)) if project_id else None
            tenancy.require_project_in_scope(session, pid, scope)
            return shipping_repository.count_packing_slips(
                session,
                pid,
                company=scope,
                search=search,
                status=ShipmentStatusDB(status.value) if status is not None else None,
            )

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
            scope = tenant_scope(info)
            pid = uuid.UUID(str(project_id)) if project_id else None
            tenancy.require_project_in_scope(session, pid, scope)
            reqs = shipping_repository.get_shipping_out_requests(session, pid, status, reopenable_only, company=scope)
            return _requests_to_types(session, reqs)

    @strawberry.field
    def shipping_out_request(self, info: strawberry.Info, id: strawberry.ID) -> ShippingOutRequest | None:
        """One shipping-out request by id, for seeding the request workspace's edit mode.

        The workspace opens `/shipping/requests/:id/edit` as its own full-page route, so it reads the
        request it is editing directly rather than depending on the accept-queue list query having been
        mounted first (a cold deep-link or a refresh has no such list in the cache). Null when the id
        matches nothing.
        """
        with SessionLocal() as session:
            scope = tenant_scope(info)
            req = shipping_repository.get_shipping_out_request(session, uuid.UUID(str(id)))
            if req is None:
                return None
            tenancy.require_shipping_out_request_in_scope(session, req.id, scope)
            result = shipping_out_request_to_type(req)
            # #1257: the request's own project, archived or not, so the edit page never depends on the
            # projects list (which leaves archived jobs out). One request, so two small reads.
            project = session.get(ProjectModel, req.project_id)
            if project is not None:
                opening_count = session.scalar(
                    select(func.count()).select_from(OpeningModel).where(OpeningModel.project_id == project.id)
                )
                result.project = project_to_type(project, include_openings=False, opening_count=opening_count or 0)
            # #1262: the real claim, which the edit composer adds back as headroom.
            result.reserved_by_product = [
                ShippingOutRequestReservedProduct(hardware_category=cat, product_code=code, quantity=qty)
                for cat, code, qty in shipping_requests.get_reserved_by_product(session, req.id)
            ]
            return result

    @strawberry.field
    def request_coverage(
        self,
        info: strawberry.Info,
        project_id: strawberry.ID,
        opening_numbers: list[str],
        exclude_request_id: strawberry.ID | None = None,
    ) -> list[RequestCoverageLine]:
        """What the selected openings still have coming: `max(owed - sent - claimed, 0)` per product.

        The one answer both composers read - shop assembly and shipping out ask the same question at
        composition time. See `app.repositories.request_composer` for how each term is derived.
        """
        with SessionLocal() as session:
            scope = tenant_scope(info)
            tenancy.require_project_in_scope(session, uuid.UUID(str(project_id)), scope)
            # #1592: the edit composer leaves its own request out of "claimed by somebody else".
            excluded = uuid.UUID(str(exclude_request_id)) if exclude_request_id else None
            if excluded is not None:
                tenancy.require_shipping_out_request_in_scope(session, excluded, scope)
            rows = request_composer.get_request_coverage(
                session, uuid.UUID(str(project_id)), opening_numbers, exclude_request_id=excluded
            )
            return [
                RequestCoverageLine(
                    opening_number=row["opening_number"],
                    hardware_category=row["hardware_category"],
                    product_code=row["product_code"],
                    classification=row["classification"],
                    owed_quantity=row["owed_quantity"],
                    sent_quantity=row["sent_quantity"],
                    assembled_quantity=row["assembled_quantity"],
                    shipped_quantity=row["shipped_quantity"],
                    claimed_quantity=row["claimed_quantity"],
                    suggested_quantity=row["suggested_quantity"],
                    on_order_quantity=row["on_order_quantity"],
                    by_others=row["by_others"],
                )
                for row in rows
            ]

    @strawberry.field
    def staging_pool(self, info: strawberry.Info, project_id: strawberry.ID) -> StagingPool:
        """Everything staged for shipping and where it has been put (#451).

        One query for both halves of the workspace - what is still loose on the floor, and what is
        already in a container - because two would be able to disagree about whether something has
        been loaded, and that disagreement is exactly the mistake containers exist to prevent.
        """
        pid = uuid.UUID(str(project_id))
        with SessionLocal() as session:
            tenancy.require_project_in_scope(session, pid, tenant_scope(info))
            # Both reads are done here and handed to the pool builder, which would otherwise repeat
            # them internally - `get_ship_ready_items` alone is three statements plus a selectinload,
            # and this is the workspace's main read (CLAUDE.md perf rules).
            ready = shipping_repository.get_ship_ready_items(session, pid)
            containers = shipment_containers.get_containers(session, pid, open_only=True)
            pool = shipment_containers.build_staged_pool(session, pid, ready=ready, containers=containers)
            return StagingPool(
                loose_items=_staged_lines(pool),
                containers=[container_to_type(c) for c in containers],
            )

    @strawberry.field
    def staging_overview(self, info: strawberry.Info) -> list[StagingProjectSummary]:
        """Every project with something staged, grouped by project (#1698): what the staging page shows
        before anyone picks a project, so nobody has to know which job to search for."""
        with SessionLocal() as session:
            summaries = shipment_containers.build_staging_overview(session, company=tenant_scope(info))
            return [
                StagingProjectSummary(
                    project_id=strawberry.ID(str(s["project"].id)),
                    project_number=s["project"].project_id,
                    project_description=s["project"].description,
                    loose_items=_staged_lines(s["pool"]),
                    open_container_count=s["open_containers"],
                )
                for s in summaries
            ]

    @strawberry.field
    def shipment_methods(self, info: strawberry.Info, active_only: bool = False) -> list[ShipmentMethod]:
        """How a load can travel (#451). `activeOnly` is what the Delivery Request form passes; the
        management screen leaves it off so a retired method can still be seen and reactivated."""
        with SessionLocal() as session:
            return [
                _shipment_method_to_type(m)
                for m in shipment_method_repository.get_shipment_methods(
                    session, active_only=active_only, company=tenant_scope(info)
                )
            ]

    @strawberry.field
    def returnable_lines(self, info: strawberry.Info, packing_slip_id: strawberry.ID) -> list[ReturnableLine]:
        with SessionLocal() as session:
            tenancy.require_packing_slip_in_scope(session, uuid.UUID(str(packing_slip_id)), tenant_scope(info))
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
            "opening_number": item.opening_number,
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

        Everything past composition is identical to the Start-a-Request path - same guards, same
        reservation of what the loose lines claim (#342), same PENDING request somebody then
        accepts. Recorded against the Clerk-authenticated caller (#427).
        """
        auth = current_user(info)
        actor = resolve_display_name(auth["user_id"])
        with SessionLocal() as session:
            tenancy.require_project_in_scope(session, uuid.UUID(str(input.project_id)), tenant_scope(info))
            created = shipping_requests.create_shipping_out_requests(
                session,
                uuid.UUID(str(input.project_id)),
                [{"request_number": input.request_number, "items": _request_items(input.items)}],
                created_by=actor,
                created_by_user_id=auth["user_id"],
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
            tenancy.require_shipping_out_request_in_scope(session, uuid.UUID(str(input.id)), tenant_scope(info))
            req = shipping_requests.replace_shipping_out_request_items(
                session,
                uuid.UUID(str(input.id)),
                _request_items(input.items),
                expected_lines_version=input.expected_lines_version,
            )
            session.commit()
            refreshed = shipping_repository.get_shipping_out_request(session, req.id)
            return shipping_out_request_to_type(refreshed)

    @strawberry.mutation
    def create_shipment_container(
        self,
        info: strawberry.Info,
        project_id: strawberry.ID,
        container_type: ShipmentContainerTypeEnum,
        name: str,
    ) -> ShipmentContainer:
        """Start a skid, cart, box, envelope or bundle (#451). Named by whoever is loading it,
        because the label goes on the physical thing in marker."""
        auth = current_user(info)
        actor = resolve_display_name(auth["user_id"])
        with SessionLocal() as session:
            tenancy.require_project_in_scope(session, uuid.UUID(str(project_id)), tenant_scope(info))
            container = shipment_containers.create_container(
                session,
                uuid.UUID(str(project_id)),
                container_type=container_type,
                name=name,
                created_by=actor,
            )
            session.commit()
            session.refresh(container)
            return container_to_type(container)

    @strawberry.mutation
    def rename_shipment_container(self, info: strawberry.Info, id: strawberry.ID, name: str) -> ShipmentContainer:
        """Relabel an open container. Refused once it has shipped."""
        with SessionLocal() as session:
            tenancy.require_container_in_scope(session, uuid.UUID(str(id)), tenant_scope(info))
            container = shipment_containers.rename_container(session, uuid.UUID(str(id)), name)
            session.commit()
            session.refresh(container)
            return container_to_type(container)

    @strawberry.mutation
    def delete_shipment_container(self, info: strawberry.Info, id: strawberry.ID) -> bool:
        """Break an open container back down; its contents return to the unplaced pool."""
        with SessionLocal() as session:
            tenancy.require_container_in_scope(session, uuid.UUID(str(id)), tenant_scope(info))
            photo_keys = shipment_containers.delete_container(session, uuid.UUID(str(id)))
            session.commit()
        # #1728: its photos' rows went with it; their images go once that has committed.
        for key in photo_keys:
            shipment_photos.discard_object(key)
        return True

    @strawberry.mutation
    def set_container_items(self, info: strawberry.Info, input: SetContainerItemsInput) -> ShipmentContainer:
        """Rewrite a container's contents to exactly the placements sent, in that order (#451).

        The order IS the stacking order, so a drag-and-drop reorder is the same call as a placement.
        Gated on what is genuinely staged and unplaced."""
        with SessionLocal() as session:
            tenancy.require_container_in_scope(session, uuid.UUID(str(input.container_id)), tenant_scope(info))
            updated = shipment_containers.set_container_items(
                session,
                uuid.UUID(str(input.container_id)),
                _container_items_input(input.items),
            )
            session.commit()
            session.refresh(updated)
            return container_to_type(updated)

    @strawberry.mutation
    def move_container_items(self, info: strawberry.Info, input: MoveContainerItemsInput) -> list[ShipmentContainer]:
        """A move from one container to another as one save (#1178): both rewrites commit together or
        neither does, so a refused target never leaves the item out of both."""
        source_id = uuid.UUID(str(input.source.container_id))
        target_id = uuid.UUID(str(input.target.container_id))
        with SessionLocal() as session:
            tenancy.require_container_in_scope(session, source_id, tenant_scope(info))
            tenancy.require_container_in_scope(session, target_id, tenant_scope(info))
            source, target = shipment_containers.move_between_containers(
                session,
                source_id,
                _container_items_input(input.source.items),
                target_id,
                _container_items_input(input.target.items),
            )
            session.commit()
            session.refresh(source)
            session.refresh(target)
            return [container_to_type(source), container_to_type(target)]

    @strawberry.mutation
    def confirm_shipment_from_containers(
        self, info: strawberry.Info, input: ConfirmShipmentFromContainersInput
    ) -> PackingSlip:
        """Cut the packing slip for whole containers (#451).

        The container flow's confirm. It composes the slip's items out of what was loaded and stamps
        the slip onto each container, then hands off to the repository's `confirm_shipment` - the
        quarantine gate, the SHIP_READY transition and the loose arithmetic are not re-implemented
        here. The only confirm: the loose `confirmShipment` beside it was removed (#1107). Recorded
        against the Clerk-authenticated caller (#427)."""
        auth = current_user(info)
        actor = resolve_display_name(auth["user_id"])
        with SessionLocal() as session:
            tenancy.require_project_in_scope(session, uuid.UUID(str(input.project_id)), tenant_scope(info))
            slip = shipment_containers.confirm_shipment_from_containers(
                session,
                uuid.UUID(str(input.project_id)),
                [uuid.UUID(str(cid)) for cid in input.container_ids],
                shipped_by=actor,
                details=_delivery_details(input),
                expected_contents=(
                    None
                    if input.expected_contents is None
                    else {
                        uuid.UUID(str(e.container_id)): {uuid.UUID(str(i)) for i in e.item_ids}
                        for e in input.expected_contents
                    }
                ),
                load_id=uuid.UUID(str(input.load_id)) if input.load_id else None,
                driver=_resolve_driver(info, session, uuid.UUID(str(input.project_id)), input.driver_user_id),
            )
            session.commit()
            refreshed = shipping_repository.get_packing_slip(session, slip.id)
            return packing_slip_to_type(refreshed)

    @strawberry.mutation
    def create_shipment_method(
        self, info: strawberry.Info, name: str, sort_order: int = 0, company: str | None = None
    ) -> ShipmentMethod:
        """Add a way a load can travel (#451). Names are unique case-insensitively, so the list
        cannot grow two spellings of the same carrier."""
        with SessionLocal() as session:
            method = shipment_method_repository.create_shipment_method(
                session,
                name=name,
                sort_order=sort_order,
                # A scoped caller can only add one to their own list; a UC NEXUS ADMIN is unscoped and
                # names the company (#637).
                company=tenant_scope(info) or (company or ""),
            )
            session.commit()
            session.refresh(method)
            return _shipment_method_to_type(method)

    @strawberry.mutation
    def update_shipment_method(
        self,
        info: strawberry.Info,
        id: strawberry.ID,
        name: str | None = None,
        is_active: bool | None = None,
        sort_order: int | None = None,
    ) -> ShipmentMethod:
        """Rename, retire or reorder a method (#451). Only what is sent is changed.

        A rename does not touch the shipments that already went out under the old name - each one
        holds its own copy - so this only changes what future shipments are offered."""
        with SessionLocal() as session:
            tenancy.require_shipment_method_in_scope(session, uuid.UUID(str(id)), tenant_scope(info))
            method = shipment_method_repository.update_shipment_method(
                session, uuid.UUID(str(id)), name=name, is_active=is_active, sort_order=sort_order
            )
            session.commit()
            session.refresh(method)
            return _shipment_method_to_type(method)

    @strawberry.mutation
    def delete_shipment_method(self, info: strawberry.Info, id: strawberry.ID) -> bool:
        """Drop a method from the list (#451).

        No shipment references it - each snapshotted the name it shipped under - so this changes
        what can be picked next and never what was picked before. Retiring is the better move for a
        carrier that may come back; this is for a row that was a mistake."""
        with SessionLocal() as session:
            tenancy.require_shipment_method_in_scope(session, uuid.UUID(str(id)), tenant_scope(info))
            shipment_method_repository.delete_shipment_method(session, uuid.UUID(str(id)))
            session.commit()
            return True

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
            tenancy.require_shipping_out_request_in_scope(session, request_id, tenant_scope(info))
            shipping_repository.accept_shipping_out_request(session, request_id, actor)
            session.commit()
            refreshed = shipping_repository.get_shipping_out_request(session, request_id)
            return shipping_out_request_to_type(refreshed)

    @strawberry.mutation
    def reject_shipping_out_request(
        self, info: strawberry.Info, id: strawberry.ID, reason: str | None = None
    ) -> ShippingOutRequest:
        """Reject a PENDING shipping-out request (#293). Recorded against the Clerk-authenticated
        caller (#427). The reason is required and goes to the requester (#972)."""
        auth = current_user(info)
        actor = resolve_display_name(auth["user_id"])
        request_id = uuid.UUID(str(id))
        with SessionLocal() as session:
            tenancy.require_shipping_out_request_in_scope(session, request_id, tenant_scope(info))
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
            tenancy.require_shipping_out_request_in_scope(session, request_id, tenant_scope(info))
            shipping_repository.reopen_shipping_out_request(session, request_id)
            session.commit()
            refreshed = shipping_repository.get_shipping_out_request(session, request_id)
            return shipping_out_request_to_type(refreshed)

    @strawberry.mutation
    def update_shipment_details(self, info: strawberry.Info, input: UpdateShipmentDetailsInput) -> PackingSlip:
        """Correct the Delivery Request of a shipment that has not left yet (#447).

        Refused once the shipment is past SCHEDULED: from the moment it is picked up a driver holds a
        printed copy, and the stored record has to keep matching the paper the site will sign.

        Full replace over the header - a field sent as null is cleared. Nothing about what shipped is
        touched."""
        with SessionLocal() as session:
            tenancy.require_packing_slip_in_scope(session, uuid.UUID(str(input.id)), tenant_scope(info))
            project_id = session.scalar(
                select(PackingSlipModel.project_id).where(PackingSlipModel.id == uuid.UUID(str(input.id)))
            )
            ps = shipping_repository.update_shipment_details(
                session,
                uuid.UUID(str(input.id)),
                _delivery_details(input),
                driver=_resolve_driver(info, session, project_id, input.driver_user_id),
            )
            session.commit()
            refreshed = shipping_repository.get_packing_slip(session, ps.id)
            return packing_slip_to_type(refreshed)

    @strawberry.mutation
    def add_shipment_photo(
        self,
        info: strawberry.Info,
        kind: ShipmentPhotoKindEnum,
        file_name: str,
        content_type: str,
        file_data_base64: str,
        container_id: strawberry.ID | None = None,
        packing_slip_id: strawberry.ID | None = None,
    ) -> ShipmentPhoto:
        """Add a photo (#1728): a LOADING photo of a container, or a DELIVERY photo of a shipment that has
        left the dock. Images only. Recorded against the signed-in caller."""
        from app.models.enums import ShipmentPhotoKind as ShipmentPhotoKindDB

        auth = current_user(info)
        actor = resolve_display_name(auth["user_id"])
        cid = uuid.UUID(str(container_id)) if container_id else None
        sid = uuid.UUID(str(packing_slip_id)) if packing_slip_id else None
        with SessionLocal() as session:
            if cid is not None:
                tenancy.require_container_in_scope(session, cid, tenant_scope(info))
            if sid is not None:
                tenancy.require_packing_slip_in_scope(session, sid, tenant_scope(info))
                _refuse_another_drivers_shipment(info, session, sid, auth["user_id"])
            photo = shipment_photos.add_photo(
                session,
                kind=ShipmentPhotoKindDB(kind.value),
                container_id=cid,
                packing_slip_id=sid,
                file_name=file_name,
                content_type=content_type,
                file_data_base64=file_data_base64,
                taken_by=actor,
                taken_by_user_id=auth["user_id"],
            )
            s3_key = photo.s3_key
            try:
                session.commit()
            except Exception:
                shipment_photos.discard_object(s3_key)
                raise
            return shipment_photo_to_type(photo)

    @strawberry.mutation
    def delete_shipment_photo(self, info: strawberry.Info, id: strawberry.ID) -> bool:
        """Remove a photo taken by mistake (#1728)."""
        with SessionLocal() as session:
            tenancy.require_shipment_photo_in_scope(session, uuid.UUID(str(id)), tenant_scope(info))
            key = shipment_photos.delete_photo(session, uuid.UUID(str(id)))
            session.commit()
        shipment_photos.discard_object(key)
        return True

    @strawberry.mutation
    def move_shipment_to_load(
        self, info: strawberry.Info, id: strawberry.ID, load_id: strawberry.ID | None = None
    ) -> PackingSlip:
        """Move a scheduled shipment onto another load, or onto a new one when `loadId` is null (#1723).

        For the truck that changed after the paper was written: two projects that turned out to share
        one, or one taken off a truck it no longer fits. Refused once the shipment has been picked up."""
        auth = current_user(info)
        actor = resolve_display_name(auth["user_id"])
        with SessionLocal() as session:
            tenancy.require_packing_slip_in_scope(session, uuid.UUID(str(id)), tenant_scope(info))
            ps = shipping_repository.lock_packing_slip(session, uuid.UUID(str(id)))
            shipment_loads.move_slip_to_load(session, ps, uuid.UUID(str(load_id)) if load_id else None, actor)
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
            tenancy.require_packing_slip_in_scope(session, uuid.UUID(str(id)), tenant_scope(info))
            _refuse_another_drivers_shipment(info, session, uuid.UUID(str(id)), auth["user_id"])
            ps = shipping_repository.mark_shipment_picked_up(session, uuid.UUID(str(id)), actor)
            session.commit()
            refreshed = shipping_repository.get_packing_slip(session, ps.id)
            return packing_slip_to_type(refreshed)

    @strawberry.mutation
    def cancel_shipment(self, info: strawberry.Info, id: strawberry.ID) -> PackingSlip:
        """Call off a SCHEDULED shipment with nothing left to return (#1176): one made only of manual
        lines, which a return cannot reach. Moves no inventory."""
        with SessionLocal() as session:
            tenancy.require_packing_slip_in_scope(session, uuid.UUID(str(id)), tenant_scope(info))
            ps = shipping_repository.cancel_shipment(session, uuid.UUID(str(id)))
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
            tenancy.require_packing_slip_in_scope(session, uuid.UUID(str(id)), tenant_scope(info))
            _refuse_another_drivers_shipment(info, session, uuid.UUID(str(id)), auth["user_id"])
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
            scope = tenant_scope(info)
            tenancy.require_packing_slip_in_scope(session, uuid.UUID(str(input.packing_slip_id)), scope)
            tenancy.require_warehouse_in_scope(session, uuid.UUID(str(input.warehouse_id)), scope)
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
