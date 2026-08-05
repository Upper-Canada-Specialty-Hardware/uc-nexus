"""Repository for hardware schedule import operations."""

import uuid
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from math import floor

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.errors import ConflictError, NotFoundError, ValidationError
from app.models.enums import (
    AssemblyStatus,
    Classification,
    HardwareItemState,
    OpeningItemState,
    POStatus,
    PullRequestItemType,
    PullRequestSource,
    PullRequestStatus,
    PullStatus,
    ReservationSource,
    ShippingOutRequestStatus,
    ShopAssemblyRequestStatus,
)
from app.models.hardware import HardwareItem as HardwareItemModel
from app.models.opening_item import OpeningItem as OpeningItemModel
from app.models.opening_item import OpeningItemHardware as OpeningItemHardwareModel
from app.models.project import Opening as OpeningModel
from app.models.project import Project as ProjectModel
from app.models.pull_request import PullRequest as PullRequestModel
from app.models.pull_request import PullRequestItem as PullRequestItemModel
from app.models.purchase_order import POLineItem as POLineItemModel
from app.models.purchase_order import PurchaseOrder as POModel
from app.models.shipping_out_request import (
    ShippingOutRequest as ShippingOutRequestModel,
)
from app.models.shipping_out_request import (
    ShippingOutRequestItem as ShippingOutRequestItemModel,
)
from app.models.shop_assembly import (
    ShopAssemblyOpening as SAOModel,
)
from app.models.shop_assembly import (
    ShopAssemblyOpeningItem as SAOItemModel,
)
from app.models.shop_assembly import (
    ShopAssemblyRequest as SARModel,
)
from app.repositories import project_repository
from app.repositories import shipping_requests as _shipping_requests


def get_project_hardware_schedule(
    session: Session,
    project_id: uuid.UUID,
) -> dict | None:
    """Load a project's persisted hardware schedule (openings + items) for wizard hydration."""
    project = (
        session.scalars(
            select(ProjectModel).where(ProjectModel.id == project_id).options(selectinload(ProjectModel.openings))
        )
        .unique()
        .first()
    )
    if project is None:
        return None

    opening_number_by_id = {o.id: o.opening_number for o in project.openings}

    hardware_items = session.scalars(select(HardwareItemModel).where(HardwareItemModel.project_id == project_id)).all()

    return {
        "project": project,
        "openings": list(project.openings),
        "hardware_items": [
            {
                "opening_number": opening_number_by_id.get(hi.opening_id, ""),
                "product_code": hi.product_code,
                "material_id": hi.material_id or str(hi.id),
                "leaf": hi.leaf,
                "hardware_category": hi.hardware_category,
                "item_quantity": hi.item_quantity,
                "unit_cost": float(hi.unit_cost) if hi.unit_cost is not None else None,
                "unit_price": float(hi.unit_price) if hi.unit_price is not None else None,
                "list_price": float(hi.list_price) if hi.list_price is not None else None,
                "vendor_discount": float(hi.vendor_discount) if hi.vendor_discount is not None else None,
                "markup_pct": float(hi.markup_pct) if hi.markup_pct is not None else None,
                "vendor_no": hi.vendor_no,
                "manufacturer": hi.manufacturer,
                "phase_code": hi.phase_code,
                "item_category_code": hi.item_category_code,
                "product_group_code": hi.product_group_code,
                "submittal_id": hi.submittal_id,
            }
            for hi in hardware_items
        ],
    }


def reconcile_schedule(
    session: Session,
    project_id: uuid.UUID,
    items: list[dict],
) -> list[dict]:
    """Compare needed items against existing HardwareItem lifecycle state."""
    from app.models.project_excluded_item import ProjectExcludedItem as PEIModel

    # Pre-load excluded items for this project
    excluded_rows = session.scalars(select(PEIModel).where(PEIModel.project_id == project_id)).all()
    excluded_set = {(r.hardware_category, r.product_code) for r in excluded_rows}

    results = []

    # Separate excluded (BY_OTHERS) items from items needing lifecycle queries
    lifecycle_items = []
    for item in items:
        if (item["hardware_category"], item["product_code"]) in excluded_set:
            results.append(
                {
                    "opening_number": item["opening_number"],
                    "hardware_category": item["hardware_category"],
                    "product_code": item["product_code"],
                    "quantity": item["quantity_needed"],
                    "status": "BY_OTHERS",
                }
            )
        else:
            lifecycle_items.append(item)

    if not lifecycle_items:
        return results

    # The (opening, product) pairs this call is asking about. Matching happens in Python rather than
    # as a SQL `tuple_(...).in_(pairs)` predicate: Postgres expands a row-constructor IN list into a
    # nested expression tree and parses it recursively, so a full-schedule selection (thousands of
    # openings x their hardware) overflowed `max_stack_depth` and the whole reconcile failed with
    # StatementTooComplex. Every query below is already scoped to the project and indexed on it, so
    # the predicate only ever trimmed rows the loops can skip just as cheaply - and at the scale that
    # broke it, it trimmed nothing at all.
    pair_set = {(item["opening_number"], item["product_code"]) for item in lifecycle_items}

    # ---- Bulk Query 1: HardwareItems linked to non-cancelled, non-deleted POs ----
    hi_stmt = (
        select(
            OpeningModel.opening_number,
            HardwareItemModel.product_code,
            HardwareItemModel.item_quantity,
            POModel.status.label("po_status"),
            POLineItemModel.ordered_quantity,
            POLineItemModel.received_quantity,
        )
        .join(OpeningModel, HardwareItemModel.opening_id == OpeningModel.id)
        .join(POLineItemModel, HardwareItemModel.po_line_item_id == POLineItemModel.id)
        .join(POModel, POLineItemModel.po_id == POModel.id)
        .where(
            HardwareItemModel.project_id == project_id,
            POModel.status != POStatus.CANCELLED,
            POModel.deleted_at.is_(None),
        )
    )
    hi_by_pair: dict[tuple[str, str], list] = defaultdict(list)
    for row in session.execute(hi_stmt).all():
        pair = (row.opening_number, row.product_code)
        if pair not in pair_set:
            continue
        hi_by_pair[pair].append(row)

    # ---- Bulk Query 2: PullRequest aggregates ----
    pr_stmt = (
        select(
            PullRequestItemModel.opening_number,
            PullRequestItemModel.product_code,
            PullRequestModel.source,
            PullRequestModel.status,
            func.sum(PullRequestItemModel.requested_quantity).label("total_pulled"),
        )
        .join(PullRequestItemModel, PullRequestItemModel.pull_request_id == PullRequestModel.id)
        .where(
            PullRequestModel.project_id == project_id,
            PullRequestModel.status != PullRequestStatus.CANCELLED,
        )
        .group_by(
            PullRequestItemModel.opening_number,
            PullRequestItemModel.product_code,
            PullRequestModel.source,
            PullRequestModel.status,
        )
    )
    pr_by_pair: dict[tuple[str, str], list] = defaultdict(list)
    for row in session.execute(pr_stmt).all():
        pair = (row.opening_number, row.product_code)
        if pair not in pair_set:
            continue
        pr_by_pair[pair].append(row)

    # ---- Bulk Query 3: OpeningItemHardware shipped + assembled sums ----
    oi_stmt = (
        select(
            OpeningItemModel.opening_number,
            OpeningItemHardwareModel.product_code,
            OpeningItemModel.state,
            func.sum(OpeningItemHardwareModel.quantity).label("qty"),
        )
        .join(OpeningItemModel, OpeningItemHardwareModel.opening_item_id == OpeningItemModel.id)
        .where(
            OpeningItemModel.project_id == project_id,
            OpeningItemModel.state.in_(
                [OpeningItemState.SHIPPED_OUT, OpeningItemState.IN_INVENTORY, OpeningItemState.SHIP_READY]
            ),
        )
        .group_by(
            OpeningItemModel.opening_number,
            OpeningItemHardwareModel.product_code,
            OpeningItemModel.state,
        )
    )
    shipped_by_pair: dict[tuple[str, str], int] = defaultdict(int)
    assembled_by_pair: dict[tuple[str, str], int] = defaultdict(int)
    for row in session.execute(oi_stmt).all():
        key = (row.opening_number, row.product_code)
        if key not in pair_set:
            continue
        if row.state == OpeningItemState.SHIPPED_OUT:
            shipped_by_pair[key] += row.qty or 0
        else:
            assembled_by_pair[key] += row.qty or 0

    # ---- Process each item using pre-loaded data ----
    for item in lifecycle_items:
        opening_number = item["opening_number"]
        hardware_category = item["hardware_category"]
        product_code = item["product_code"]
        quantity_needed = item["quantity_needed"]
        pair_key = (opening_number, product_code)

        # Step 2: Bucket quantities by PO status
        buckets: dict[str, int] = defaultdict(int)
        for row in hi_by_pair.get(pair_key, []):
            hi_qty = row.item_quantity
            po_status = row.po_status

            if po_status == POStatus.DRAFT:
                buckets["PO_DRAFTED"] += hi_qty
            elif po_status in (POStatus.GP_REGISTERED, POStatus.VENDOR_CONFIRMED):
                buckets["ORDERED"] += hi_qty
            elif po_status == POStatus.PARTIALLY_RECEIVED:
                if row.ordered_quantity > 0:
                    ratio = row.received_quantity / row.ordered_quantity
                else:
                    ratio = 0
                received_portion = floor(hi_qty * ratio)
                ordered_portion = hi_qty - received_portion
                if received_portion > 0:
                    buckets["RECEIVED"] += received_portion
                if ordered_portion > 0:
                    buckets["ORDERED"] += ordered_portion
            elif po_status == POStatus.CLOSED:
                buckets["RECEIVED"] += hi_qty

        # Step 3: PR deductions
        received_qty = buckets.get("RECEIVED", 0)
        if received_qty > 0:
            for pr_row in pr_by_pair.get(pair_key, []):
                pulled_qty = pr_row.total_pulled or 0
                deduct = min(pulled_qty, received_qty)
                if deduct <= 0:
                    continue

                if pr_row.source == PullRequestSource.SHOP_ASSEMBLY:
                    if pr_row.status in (PullRequestStatus.PENDING, PullRequestStatus.IN_PROGRESS):
                        buckets["ASSEMBLING"] += deduct
                        received_qty -= deduct
                    elif pr_row.status == PullRequestStatus.COMPLETED:
                        buckets["ASSEMBLED"] += deduct
                        received_qty -= deduct
                elif pr_row.source == PullRequestSource.SHIPPING_OUT:
                    if pr_row.status in (PullRequestStatus.PENDING, PullRequestStatus.IN_PROGRESS):
                        buckets["SHIPPING_OUT"] += deduct
                        received_qty -= deduct
                    elif pr_row.status == PullRequestStatus.COMPLETED:
                        buckets["SHIPPED_OUT"] += deduct
                        received_qty -= deduct

            buckets["RECEIVED"] = max(0, received_qty)

        # Step 4: Shipped cross-check
        oi_shipped = shipped_by_pair.get(pair_key, 0)
        existing_shipped = buckets.get("SHIPPED_OUT", 0)
        if oi_shipped > existing_shipped:
            extra = oi_shipped - existing_shipped
            from_received = min(extra, buckets.get("RECEIVED", 0))
            buckets["RECEIVED"] = max(0, buckets.get("RECEIVED", 0) - from_received)
            buckets["SHIPPED_OUT"] = existing_shipped + from_received

        # Step 4b: Assembled cross-check
        oi_assembled = assembled_by_pair.get(pair_key, 0)
        existing_assembled = buckets.get("ASSEMBLED", 0)
        if oi_assembled > existing_assembled:
            extra = oi_assembled - existing_assembled
            from_received = min(extra, buckets.get("RECEIVED", 0))
            buckets["RECEIVED"] = max(0, buckets.get("RECEIVED", 0) - from_received)
            buckets["ASSEMBLED"] = existing_assembled + from_received

        # Step 5: Calculate NOT_COVERED gap
        total_committed = sum(buckets.values())
        gap = max(0, quantity_needed - total_committed)
        if gap > 0:
            buckets["NOT_COVERED"] = gap

        # Step 6: Generate result rows
        for status_key, qty in buckets.items():
            if qty > 0:
                results.append(
                    {
                        "opening_number": opening_number,
                        "hardware_category": hardware_category,
                        "product_code": product_code,
                        "quantity": qty,
                        "status": status_key,
                    }
                )

    return results


def _opening_leaf_label(opening_number: str, leaf: int | None) -> str:
    """Same label, built from the raw pair rather than from a materialized OpeningItem."""
    return f"Opening {opening_number} Leaf {leaf}" if leaf is not None else f"Opening {opening_number}"


# The note stamped on a live in-flight request when a full-schedule re-upload lands underneath it.
SCHEDULE_CHANGED_NOTE = (
    "The hardware schedule was re-uploaded after this request was created, so its bill of hardware "
    "may no longer match the schedule. Review it before accepting."
)
SCHEDULE_CHANGED_DROPPED_NOTE = (
    "The hardware schedule was re-uploaded after this request was created and some of its openings "
    "no longer exist; those were dropped and their inventory reservations released. Review what is "
    "left before accepting."
)


def _gate_on_available_inventory(
    session: Session,
    project_id: uuid.UUID,
    needs: list[tuple[str, str, int]],
    *,
    label: str,
    request_number: str | None,
) -> None:
    """The creation-time inventory gate (#342), which now lives beside the arithmetic it applies.

    Kept as a name here because the shop-assembly finalize below reads better calling it, and
    because every test that pins the gate's behaviour names it.
    """
    from app.repositories import warehouse as warehouse_repository

    warehouse_repository.gate_on_available_inventory(
        session, project_id, needs, label=label, request_number=request_number
    )


def _allocated_quantity(item_input: dict) -> int:
    """What a checklist line actually claims out of inventory.

    A missing / null `allocated_quantity` means **fully allocated**. That default is what keeps every
    caller that predates the allocator - tests, scripts, a browser tab loaded before the deploy - on
    the old all-or-nothing behaviour: it asks for the whole line, and the availability gate bounces
    the finalize if the whole line does not fit. The allocator step always sends the number.
    """
    allocated = item_input.get("allocated_quantity")
    return item_input["quantity"] if allocated is None else allocated


def _validate_leaf_allocation(opening_number: str, sa_opening_input: dict) -> None:
    """Per-line bounds, and the one leaf-level rule the allocator enforces client-side.

    A leaf with nothing allocated on any line is an empty cart: nothing to pull, nothing to stage,
    nothing to assemble, and `complete_opening` would refuse it at the far end for having zero
    installed units. The wizard drops such leaves before submitting, so reaching here means a race
    (availability collapsed between load and send) or a non-UI caller - both of which are better
    refused than turned into a work unit that can never be finished.
    """
    items = sa_opening_input.get("items", [])
    for item in items:
        allocated = _allocated_quantity(item)
        if allocated < 0 or allocated > item["quantity"]:
            raise ValidationError(
                f"{_opening_leaf_label(opening_number, sa_opening_input.get('leaf'))} {item['product_code']}: "
                f"allocated quantity {allocated} must be between 0 and the {item['quantity']} unit(s) owed.",
                field="allocated_quantity",
            )
    if items and all(_allocated_quantity(item) == 0 for item in items):
        raise ValidationError(
            f"{_opening_leaf_label(opening_number, sa_opening_input.get('leaf'))} has no hardware allocated to it, "
            "so there is nothing to pull for it. Drop it from the request, or wait for stock.",
            field="allocated_quantity",
        )


def _live_shop_assembly_requests(session: Session, project_id: uuid.UUID) -> list[SARModel]:
    """Shop-assembly requests in a project that are still in flight: PENDING, or APPROVED while the
    pull they minted has not been worked (PENDING). Once the warehouse approves the pull, inventory
    has moved and the request is no longer something a re-upload may quietly rewrite."""
    return list(
        session.scalars(
            select(SARModel)
            .options(selectinload(SARModel.openings).selectinload(SAOModel.items))
            .outerjoin(PullRequestModel, SARModel.request_number == PullRequestModel.request_number)
            .where(
                SARModel.project_id == project_id,
                or_(
                    SARModel.status == ShopAssemblyRequestStatus.PENDING,
                    and_(
                        SARModel.status == ShopAssemblyRequestStatus.APPROVED,
                        or_(
                            PullRequestModel.id.is_(None),
                            PullRequestModel.status == PullRequestStatus.PENDING,
                        ),
                    ),
                ),
            )
        )
        .unique()
        .all()
    )


def _live_shipping_out_requests(session: Session, project_id: uuid.UUID) -> list[ShippingOutRequestModel]:
    """Shipping-out requests still in flight, on the same definition as their shop-assembly twin."""
    return list(
        session.scalars(
            select(ShippingOutRequestModel)
            .options(selectinload(ShippingOutRequestModel.items))
            .outerjoin(PullRequestModel, ShippingOutRequestModel.pull_request_id == PullRequestModel.id)
            .where(
                ShippingOutRequestModel.project_id == project_id,
                or_(
                    ShippingOutRequestModel.status == ShippingOutRequestStatus.PENDING,
                    and_(
                        ShippingOutRequestModel.status == ShippingOutRequestStatus.APPROVED,
                        or_(
                            PullRequestModel.id.is_(None),
                            PullRequestModel.status == PullRequestStatus.PENDING,
                        ),
                    ),
                ),
            )
        )
        .unique()
        .all()
    )


def _handle_schedule_replacement(
    session: Session,
    project: ProjectModel,
    new_opening_numbers: set[str],
) -> None:
    """Re-upload policy for in-flight requests (#342), run just before a `replace_schedule=True`
    finalize deletes the openings that are gone from the new schedule.

    **The re-upload is not blocked.** Replacing the schedule is how a real revision reaches the
    system, and refusing it whenever any request is open would mean the revision waits on the
    warehouse - the wrong way round. Instead the requests are made to tell the truth about
    themselves:

    - **PENDING requests are rewritten to what survived.** Work units and lines whose opening is
      gone are deleted, and the request's reservations are rebuilt from what is left - which
      releases exactly the claim the vanished openings were holding, no more. A request left with
      nothing at all is auto-REJECTED (which releases the rest by the ordinary reject path), because
      an empty request is not something anybody can accept.
    - **APPROVED requests are left alone.** Their pull already exists and is the authority on what
      the warehouse will hand over; silently shrinking it underneath the puller would be worse than
      a stale bill of hardware.
    - **Every live request is flagged** with `integrity_note`, not just the ones that lost openings,
      because a full-schedule replacement can change the hardware on an opening it kept. The
      acceptor sees the flag and can reject-and-recreate.

    Deliberately *not* done: re-deriving a surviving request's items from the new schedule. The
    request is a snapshot somebody made a decision about; rewriting its contents under them would
    make the flag a lie.
    """
    from app.repositories import warehouse as warehouse_repository

    vanished_ids = {o.id for o in project.openings if o.opening_number not in new_opening_numbers}
    vanished_numbers = {o.opening_number for o in project.openings if o.opening_number not in new_opening_numbers}

    for sar in _live_shop_assembly_requests(session, project.id):
        pending = sar.status == ShopAssemblyRequestStatus.PENDING
        lost = [o for o in sar.openings if o.opening_id in vanished_ids] if pending else []
        if lost:
            lost_ids = [o.id for o in lost]
            session.execute(delete(SAOItemModel).where(SAOItemModel.shop_assembly_opening_id.in_(lost_ids)))
            session.execute(delete(SAOModel).where(SAOModel.id.in_(lost_ids)))
            session.flush()
            session.refresh(sar, attribute_names=["openings"])

        if pending and not sar.openings:
            # Nothing left to assemble: reject it (which releases every remaining reservation) rather
            # than leave an empty request on the accept board.
            sar.status = ShopAssemblyRequestStatus.REJECTED
            sar.rejected_by = "Hardware Schedule Import"
            sar.rejection_reason = "All of this request's openings were removed by a hardware schedule re-upload."
            sar.rejected_at = datetime.utcnow()
            warehouse_repository.release_reservations(session, ReservationSource.SHOP_ASSEMBLY_REQUEST, sar.id)
            continue

        if lost:
            # Rebuild from what survived. Replace-in-place rather than a per-opening decrement: the
            # reservation rows are aggregates over the whole request, so "what it should hold now" is
            # the only number that is unambiguous.
            warehouse_repository.release_reservations(session, ReservationSource.SHOP_ASSEMBLY_REQUEST, sar.id)
            warehouse_repository.create_reservations(
                session,
                sar.project_id,
                ReservationSource.SHOP_ASSEMBLY_REQUEST,
                sar.id,
                # Allocated, not owed: the claim it held was minted from the allocation, and rebuilding
                # from `quantity` would inflate it into a claim on hardware this request never had.
                [
                    (item.hardware_category, item.product_code, item.allocated_quantity)
                    for o in sar.openings
                    for item in o.items
                ],
            )
        sar.integrity_note = SCHEDULE_CHANGED_DROPPED_NOTE if lost else SCHEDULE_CHANGED_NOTE

    for req in _live_shipping_out_requests(session, project.id):
        pending = req.status == ShippingOutRequestStatus.PENDING
        lost = [i for i in req.items if i.opening_number in vanished_numbers] if pending else []
        if lost:
            session.execute(
                delete(ShippingOutRequestItemModel).where(ShippingOutRequestItemModel.id.in_([i.id for i in lost]))
            )
            session.flush()
            session.refresh(req, attribute_names=["items"])

        if pending and not req.items:
            req.status = ShippingOutRequestStatus.REJECTED
            req.rejected_by = "Hardware Schedule Import"
            req.rejection_reason = "All of this request's lines were removed by a hardware schedule re-upload."
            req.rejected_at = datetime.utcnow()
            warehouse_repository.release_reservations(session, ReservationSource.SHIPPING_OUT_REQUEST, req.id)
            continue

        if lost:
            warehouse_repository.release_reservations(session, ReservationSource.SHIPPING_OUT_REQUEST, req.id)
            warehouse_repository.create_reservations(
                session,
                req.project_id,
                ReservationSource.SHIPPING_OUT_REQUEST,
                req.id,
                [
                    (i.hardware_category, i.product_code, i.requested_quantity)
                    for i in req.items
                    if i.item_type == PullRequestItemType.LOOSE and i.hardware_category and i.product_code
                ],
            )
        req.integrity_note = SCHEDULE_CHANGED_DROPPED_NOTE if lost else SCHEDULE_CHANGED_NOTE


def _apply_opening_fields(opening: OpeningModel, opening_input: dict) -> None:
    """Copy mutable fields from input dict onto an Opening model."""
    opening.building = opening_input.get("building")
    opening.floor = opening_input.get("floor")
    opening.location = opening_input.get("location")
    opening.location_to = opening_input.get("location_to")
    opening.location_from = opening_input.get("location_from")
    opening.hand = opening_input.get("hand")
    opening.width = opening_input.get("width")
    opening.length = opening_input.get("length")
    opening.door_thickness = opening_input.get("door_thickness")
    opening.jamb_thickness = opening_input.get("jamb_thickness")
    opening.door_type = opening_input.get("door_type")
    opening.frame_type = opening_input.get("frame_type")
    opening.interior_exterior = opening_input.get("interior_exterior")
    opening.keying = opening_input.get("keying")
    opening.heading_no = opening_input.get("heading_no")
    opening.single_pair = opening_input.get("single_pair")
    opening.assignment_multiplier = opening_input.get("assignment_multiplier")
    # Door-leaf count (#311): 1 (single) or 2 (pair), captured at import.
    opening.leaf_count = opening_input.get("leaf_count")


def finalize_import_session(
    session: Session,
    input_data: dict,
) -> dict:
    """Finalize an import session: attach openings/POs/PRs/SAR to an existing project atomically.

    Since #342 this is also where inventory is **reserved**: creating a shop-assembly or
    shipping-out request gates on `available = on-hand - deficient - active reservations` and, if it
    fits, writes the request's claim in the same transaction. A short selection raises
    `InventoryShortfallError` and nothing at all is created - the creator refines the selection,
    which is the only place in the flow where that is still a cheap thing to do.
    """
    # Local import: warehouse re-exports the reservation helpers, and importing it at module level
    # would close a cycle (warehouse -> shop_assembly_repository -> ... -> import_repository).
    from app.repositories import warehouse as warehouse_repository

    project_id = uuid.UUID(input_data["project_id"])
    openings_input = input_data.get("openings", [])
    hardware_items_input = input_data.get("hardware_items") or []
    po_drafts = input_data.get("po_drafts") or []
    classifications_input = input_data.get("classifications") or []
    excluded_items_input = input_data.get("excluded_items") or []
    shipping_pr_drafts = input_data.get("shipping_out_pr_drafts") or []
    include_sar = input_data.get("include_shop_assembly_request", False)
    sar_request_number = input_data.get("shop_assembly_request_number")
    sar_openings_input = input_data.get("shop_assembly_openings") or []
    replace_schedule = bool(input_data.get("replace_schedule", False))
    acknowledge_incomplete_leaves = bool(input_data.get("acknowledge_incomplete_leaves", False))

    # 1. Project lookup (must already exist)
    project_stmt = (
        select(ProjectModel).options(selectinload(ProjectModel.openings)).where(ProjectModel.id == project_id)
    )
    project = session.scalars(project_stmt).unique().first()

    if project is None:
        raise NotFoundError(f"Project {project_id} not found")

    # #425: quarantine gate. This one mutation is BOTH of Start a Request's write actions - it persists
    # the schedule, and it creates the shop-assembly and shipping-out requests that reserve inventory
    # against it. A project whose GP job cannot be received against must not accumulate any of that:
    # the requests would reserve stock, the POs drafted off the schedule would be unregisterable, and
    # someone would have to unpick all of it once accounting fixed the job. Passes when the verdict is
    # null (never checked) - see require_gp_setup_ok.
    project_repository.require_gp_setup_ok(session, project.id)

    # 2. Wipe AVAILABLE hardware items for this project — they are pure XML-derived rows
    # that will be regenerated from the current input. Existing IN_PO rows (attached to
    # prior POs) are preserved unless replace_schedule=True.
    session.execute(
        delete(HardwareItemModel).where(
            HardwareItemModel.project_id == project.id,
            HardwareItemModel.state == HardwareItemState.AVAILABLE,
        )
    )
    session.flush()

    if replace_schedule:
        # Full override: wipe every HardwareItem (including IN_PO) and drop openings
        # not present in the new schedule. Downstream PO/receiving/SAR/inventory
        # aggregates are preserved; only the per-opening source trail is lost.
        session.execute(delete(HardwareItemModel).where(HardwareItemModel.project_id == project.id))
        session.flush()

        new_opening_numbers = {o["opening_number"] for o in openings_input}
        # #342: reconcile in-flight requests with the new schedule BEFORE the openings they point at
        # are deleted - drop what vanished, release the reservations it was holding, flag the rest.
        _handle_schedule_replacement(session, project, new_opening_numbers)
        # ORM-aware delete so identity map / project.openings stay consistent.
        for opening in list(project.openings):
            if opening.opening_number not in new_opening_numbers:
                session.delete(opening)
        session.flush()
        session.refresh(project, attribute_names=["openings"])

    # 3. Upsert openings from input: add new ones; for replace mode also refresh existing fields.
    existing_openings_by_number = {o.opening_number: o for o in project.openings}
    for opening_input in openings_input:
        opening_number = opening_input["opening_number"]
        existing = existing_openings_by_number.get(opening_number)
        if existing is None:
            opening = OpeningModel(
                id=uuid.uuid4(),
                project_id=project.id,
                opening_number=opening_number,
            )
            _apply_opening_fields(opening, opening_input)
            session.add(opening)
            project.openings.append(opening)
            existing_openings_by_number[opening_number] = opening
        elif replace_schedule:
            _apply_opening_fields(existing, opening_input)
    session.flush()

    # Build opening_map: opening_number -> Opening.id
    opening_map: dict[str, uuid.UUID] = {o.opening_number: o.id for o in project.openings}

    # Track existing IN_PO HardwareItem keys so we don't re-create them as AVAILABLE.
    # (After the AVAILABLE wipe above and the optional full wipe under replace_schedule,
    # any remaining rows are IN_PO from prior sessions.)
    # Leaf is part of the key (#311): a pair's leaf-1 and leaf-2 rows for the same product are
    # distinct HardwareItems, so the dedup must not collapse them.
    existing_in_po_keys: set[tuple[uuid.UUID, str, str, int | None]] = {
        (hi.opening_id, hi.product_code, hi.hardware_category, hi.leaf)
        for hi in session.scalars(select(HardwareItemModel).where(HardwareItemModel.project_id == project.id)).all()
    }

    # 2. Build classification map
    classification_map: dict[tuple[str, str, float], Classification] = {}
    for c in classifications_input:
        key = (c["hardware_category"], c["product_code"], c["unit_cost"])
        classification_map[key] = Classification(c["classification"])

    # 2b. Manage project excluded items (By Others scope classification)
    if excluded_items_input is not None:
        from app.models.project_excluded_item import ProjectExcludedItem as PEIModel

        new_excluded_set = {(ei["hardware_category"], ei["product_code"]) for ei in excluded_items_input}

        # Load existing exclusions for this project
        existing_exclusions = session.scalars(select(PEIModel).where(PEIModel.project_id == project.id)).all()
        existing_set = {(e.hardware_category, e.product_code): e for e in existing_exclusions}

        # Add new exclusions
        for hw_cat, prod_code in new_excluded_set:
            if (hw_cat, prod_code) not in existing_set:
                session.add(
                    PEIModel(
                        id=uuid.uuid4(),
                        project_id=project.id,
                        hardware_category=hw_cat,
                        product_code=prod_code,
                    )
                )

        # Remove exclusions that are no longer By Others (user reclassified to By UCSH)
        for key, entity in existing_set.items():
            if key not in new_excluded_set:
                session.delete(entity)

        session.flush()

    # Collect PO ref keys so the AVAILABLE step below knows which items the PO block will claim.
    po_ref_keys: set[tuple[str, str, str]] = set()
    for po_draft in po_drafts:
        for ref in po_draft.get("hardware_item_refs", []):
            po_ref_keys.add((ref["opening_number"], ref["product_code"], ref["hardware_category"]))

    # 4. PO creation
    created_pos: list[POModel] = []
    if po_drafts:
        # Build hardware items lookup: (opening_number, product_code, hardware_category) -> list of
        # hardware item data. A leaf-agnostic PO ref matches every leaf row for that combo (#311),
        # so a pair's leaf-1 and leaf-2 rows both attach to the same PO line.
        hw_items_lookup: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
        for hi in hardware_items_input:
            key = (hi["opening_number"], hi["product_code"], hi["hardware_category"])
            hw_items_lookup[key].append(hi)

        # Generate request_number sequence for new POs
        from app.repositories.po_repository import generate_next_request_number

        next_request_number = generate_next_request_number(session)
        next_seq = int(next_request_number.replace("PO-REQ-", ""))

        for po_draft in po_drafts:
            # Validate PO number uniqueness within project if provided
            po_number = po_draft.get("po_number")
            if po_number and po_number.strip():
                existing_po = session.scalars(
                    select(POModel).where(
                        POModel.project_id == project.id,
                        POModel.po_number == po_number,
                        POModel.deleted_at.is_(None),
                    )
                ).first()
                if existing_po is not None:
                    raise ConflictError(
                        f"Purchase order {po_number} already exists in this project",
                        field="po_number",
                    )
            else:
                po_number = None

            # Auto-generate request_number
            request_number = f"PO-REQ-{next_seq:03d}"
            next_seq += 1

            # Create PO. No vendor: the wizard groups drafts by the TITAN manufacturer, which is not
            # a vendor - the GP vendor (PM00200) is picked later, at register time, and is the only
            # vendor a PO ever carries (#509).
            po = POModel(
                id=uuid.uuid4(),
                po_number=po_number,
                request_number=request_number,
                project_id=project.id,
                status=POStatus.DRAFT,
                notes=po_draft.get("notes"),
                # Issue #216: the PM's requested date, captured at PO-request creation.
                preferred_delivery_date=po_draft.get("preferred_delivery_date"),
                # Whoever finalized this wizard session, from the resolver's Clerk token. It is who a
                # receive against this PO later asks "inventory or ship out?".
                created_by_user_id=input_data.get("created_by_user_id"),
            )
            session.add(po)
            session.flush()

            # Collect hardware items for this PO and aggregate into line items
            # Key: (hardware_category, product_code, unit_cost, classification) -> list of HardwareItem models
            line_item_agg: dict[tuple, list] = defaultdict(list)

            for ref in po_draft.get("hardware_item_refs", []):
                ref_key = (ref["opening_number"], ref["product_code"], ref["hardware_category"])
                matched_rows = hw_items_lookup.get(ref_key)
                if not matched_rows:
                    raise NotFoundError(f"Hardware item not found: {ref_key}")

                opening_id = opening_map.get(ref["opening_number"])
                if opening_id is None:
                    raise NotFoundError(f"Opening {ref['opening_number']} not found in project")

                # One HardwareItem per matched leaf row (#311). Every leaf row rolls into the same PO
                # line via the unchanged agg key, so the line's ordered_quantity sums across leaves.
                for hi_data in matched_rows:
                    unit_cost = hi_data.get("unit_cost") or 0.0
                    class_key = (hi_data["hardware_category"], hi_data["product_code"], unit_cost)
                    classification = classification_map.get(class_key)

                    hw_item = HardwareItemModel(
                        id=uuid.uuid4(),
                        project_id=project.id,
                        opening_id=opening_id,
                        hardware_category=hi_data["hardware_category"],
                        product_code=hi_data["product_code"],
                        leaf=hi_data.get("leaf"),
                        item_quantity=hi_data["item_quantity"],
                        unit_cost=Decimal(str(unit_cost)) if unit_cost else None,
                        unit_price=Decimal(str(hi_data["unit_price"])) if hi_data.get("unit_price") else None,
                        list_price=Decimal(str(hi_data["list_price"])) if hi_data.get("list_price") else None,
                        vendor_discount=(
                            Decimal(str(hi_data["vendor_discount"])) if hi_data.get("vendor_discount") else None
                        ),
                        markup_pct=Decimal(str(hi_data["markup_pct"])) if hi_data.get("markup_pct") else None,
                        vendor_no=hi_data.get("vendor_no"),
                        manufacturer=hi_data.get("manufacturer"),
                        phase_code=hi_data.get("phase_code"),
                        item_category_code=hi_data.get("item_category_code"),
                        product_group_code=hi_data.get("product_group_code"),
                        submittal_id=hi_data.get("submittal_id"),
                        classification=classification,
                        state=HardwareItemState.IN_PO,
                    )
                    session.add(hw_item)

                    agg_key = (
                        hi_data["hardware_category"],
                        hi_data["product_code"],
                        unit_cost,
                        classification,
                    )
                    line_item_agg[agg_key].append(hw_item)

            session.flush()

            # Build alias lookup from line_item_aliases
            alias_lookup: dict[tuple[str, str], str] = {}
            for alias_entry in po_draft.get("line_item_aliases", []):
                key = (alias_entry["hardware_category"], alias_entry["product_code"])
                alias_lookup[key] = alias_entry["order_as"]

            # Create POLineItems from aggregation
            for (cat, code, cost, cls), hw_items in line_item_agg.items():
                total_qty = sum(hi.item_quantity for hi in hw_items)
                poli = POLineItemModel(
                    id=uuid.uuid4(),
                    po_id=po.id,
                    hardware_category=cat,
                    product_code=code,
                    classification=cls,
                    ordered_quantity=total_qty,
                    received_quantity=0,
                    unit_cost=Decimal(str(cost)) if cost else Decimal("0"),
                    order_as=alias_lookup.get((cat, code)),
                )
                session.add(poli)
                session.flush()

                # Update HardwareItems with po_line_item_id
                for hi in hw_items:
                    hi.po_line_item_id = poli.id

            created_pos.append(po)

    # 5. Persist remaining hardware items as AVAILABLE (everything in input not claimed by a PO).
    #    Skips items whose (opening_id, product, category) tuple already exists as IN_PO from
    #    a prior session, to avoid duplicating rows.
    available_keys_seen: set[tuple[uuid.UUID, str, str, int | None]] = set()
    for hi in hardware_items_input:
        # po_ref_keys stays leaf-agnostic (a PO ref names opening/product/category); it claims every
        # leaf row for that combo, so the AVAILABLE step below skips all of them.
        ref_key = (hi["opening_number"], hi["product_code"], hi["hardware_category"])
        if ref_key in po_ref_keys:
            continue
        opening_id = opening_map.get(hi["opening_number"])
        if opening_id is None:
            continue
        key_with_id = (opening_id, hi["product_code"], hi["hardware_category"], hi.get("leaf"))
        if key_with_id in existing_in_po_keys or key_with_id in available_keys_seen:
            continue
        available_keys_seen.add(key_with_id)

        unit_cost_val = hi.get("unit_cost") or 0.0
        class_key = (hi["hardware_category"], hi["product_code"], unit_cost_val)
        classification = classification_map.get(class_key)

        session.add(
            HardwareItemModel(
                id=uuid.uuid4(),
                project_id=project.id,
                opening_id=opening_id,
                hardware_category=hi["hardware_category"],
                product_code=hi["product_code"],
                material_id=hi.get("material_id"),
                leaf=hi.get("leaf"),
                item_quantity=hi["item_quantity"],
                unit_cost=Decimal(str(unit_cost_val)) if unit_cost_val else None,
                unit_price=Decimal(str(hi["unit_price"])) if hi.get("unit_price") else None,
                list_price=Decimal(str(hi["list_price"])) if hi.get("list_price") else None,
                vendor_discount=Decimal(str(hi["vendor_discount"])) if hi.get("vendor_discount") else None,
                markup_pct=Decimal(str(hi["markup_pct"])) if hi.get("markup_pct") else None,
                vendor_no=hi.get("vendor_no"),
                manufacturer=hi.get("manufacturer"),
                phase_code=hi.get("phase_code"),
                item_category_code=hi.get("item_category_code"),
                product_group_code=hi.get("product_group_code"),
                submittal_id=hi.get("submittal_id"),
                classification=classification,
                state=HardwareItemState.AVAILABLE,
            )
        )
    session.flush()

    # 6. Shipping-out requests (#293): Start a Request mints a PENDING ShippingOutRequest, NOT a
    # PullRequest. A signed-in user accepts it later, which mints the warehouse PullRequest.
    #
    # Every guard and the reservation gate live in shipping_requests (#451), because the Shipping
    # module raises requests straight off inventory now and both paths have to be held to the same
    # rules - a leaf that cannot ship twice does not become shippable twice by being asked from a
    # different screen.
    created_shipping_requests = _shipping_requests.create_shipping_out_requests(
        session,
        project.id,
        shipping_pr_drafts or [],
        created_by="Hardware Schedule Import",
        acknowledge_incomplete_leaves=acknowledge_incomplete_leaves,
    )

    # 7. Shop-assembly request + openings (#293)
    # Start a Request mints a PENDING ShopAssemblyRequest (NO PullRequest). The ShopAssemblyOpening/Item
    # rows hang off the SAR via shop_assembly_request_id; their pull_request_id stays NULL until a
    # signed-in user accepts the request (accept mints the PR and backfills pull_request_id).
    # Since #342 the inventory gate lives HERE, at creation, and creating the request reserves the
    # hardware. Accept is a pure human gate and re-checks nothing.
    sar = None
    if include_sar and sar_request_number:
        # Validate uniqueness against the SAR number space.
        existing_sar = session.scalars(select(SARModel).where(SARModel.request_number == sar_request_number)).first()
        if existing_sar is not None:
            raise ConflictError(
                f"Shop-assembly request {sar_request_number} already exists",
                field="shop_assembly_request_number",
            )

        from app.repositories import shipping_repository as _shipping_repository
        from app.repositories import shop_assembly_repository

        # Degenerate request validation (#342). A request with no work units, or a work unit with no
        # hardware on it, is unacceptable and unpullable - and a zero-item opening would reach shop
        # assembly as a leaf with an empty checklist, which #339 already refuses to complete.
        if not sar_openings_input:
            raise ValidationError(
                "A shop-assembly request must include at least one opening.",
                field="shop_assembly_openings",
            )

        opening_id_by_number: dict[str, uuid.UUID] = {}
        # Guard per (opening, leaf) (#311): assembling Leaf 1 must not block sending Leaf 2.
        opening_leaf_specs: list[tuple[str, uuid.UUID, int | None]] = []
        for sa_opening_input in sar_openings_input:
            opening_number = sa_opening_input["opening_number"]
            opening_id = opening_map.get(opening_number)
            if opening_id is None:
                raise NotFoundError(f"Opening {opening_number} not found in project")
            if not sa_opening_input.get("items"):
                raise ValidationError(
                    f"{_opening_leaf_label(opening_number, sa_opening_input.get('leaf'))} has no hardware on it, "
                    "so it cannot be sent to shop assembly.",
                    field="shop_assembly_openings",
                )
            _validate_leaf_allocation(opening_number, sa_opening_input)
            opening_id_by_number[opening_number] = opening_id
            opening_leaf_specs.append((opening_number, opening_id, sa_opening_input.get("leaf")))

        already_assembled = shop_assembly_repository.find_already_assembled_openings(
            session, project.id, opening_leaf_specs
        )
        if already_assembled:
            labels = ", ".join(f"{num} Leaf {leaf}" if leaf is not None else num for num, leaf in already_assembled)
            raise ValidationError(
                f"Opening {labels} is already assembled and cannot be sent to shop assembly.",
                field="shop_assembly_openings",
            )

        # Duplicate in-flight guard (#342): the already-assembled guard above catches a leaf that has
        # been *built*; this catches one that is still on its way - requested, pulled, or half-built.
        # Two live requests for one leaf both reserve and both pull, and the second lot of hardware
        # has nowhere to go.
        in_flight = shop_assembly_repository.find_in_flight_assembly_leaves(session, opening_leaf_specs)
        if in_flight:
            labels = ", ".join(
                sorted(
                    _opening_leaf_label(num, leaf) + (f" (on {request_number})" if request_number else "")
                    for num, leaf, request_number in in_flight
                )
            )
            raise ValidationError(
                f"These leaves are already in a live shop-assembly request: {labels}. "
                "Reject that request first, or pick different openings.",
                field="shop_assembly_openings",
            )

        # Cross-request-type conflict: a leaf a live shipping-out request has claimed is on its way
        # out of the building and cannot also be sent back to the bench.
        shipping_claims = _shipping_repository.find_live_shipping_claims(
            session,
            project.id,
            opening_leaf_specs=[(num, leaf) for num, _, leaf in opening_leaf_specs],
        )["by_opening_leaf"]
        if shipping_claims:
            labels = ", ".join(
                sorted(
                    f"{_opening_leaf_label(num, leaf)} (on shipping-out request {request_number})"
                    for (num, leaf), request_number in shipping_claims.items()
                )
            )
            raise ValidationError(
                f"These leaves are claimed by a live shipping-out request: {labels}. "
                "Resolve that request before sending them to shop assembly.",
                field="shop_assembly_openings",
            )

        # Reservation gate, now over the ALLOCATION rather than the demand. The request no longer has
        # to fit the schedule's full bill of hardware - the requester already decided what to claim
        # and what to send short - so what is gated is exactly what will be reserved and pulled.
        #
        # `_gate_on_available_inventory` itself is unchanged and still refuses the whole finalize.
        # It is not the shortfall gate any more; it is the **race** gate. The allocator built its
        # numbers from a snapshot of availability, and if that snapshot went stale between load and
        # send (another request took the stock, an admin wrote it off), reserving anyway would write
        # a claim on hardware that is not there. The wizard catches the refusal, refetches
        # availability, re-runs auto-assign and asks the user to look again.
        sar_needs = [
            (item["hardware_category"], item["product_code"], _allocated_quantity(item))
            for sa_opening_input in sar_openings_input
            for item in sa_opening_input.get("items", [])
            if _allocated_quantity(item) > 0
        ]
        _gate_on_available_inventory(
            session,
            project.id,
            sar_needs,
            label="shop-assembly request",
            request_number=sar_request_number,
        )
        # Everything the schedule owed but the allocation could not cover. Short combos are out of
        # available stock by construction - the allocator only leaves a line short once the pool for
        # that combo is exhausted - so this is always a genuine purchasing signal, not a claim
        # somebody else is holding. It fires *after* the request is created, unlike the refusal path
        # in app/schemas/imports.py, which stays for the race above.
        #
        # Totals are accumulated over EVERY line of a combo, not only the short ones. Purchasing acts
        # on the combo, so the number it needs is what this request wanted of that product against
        # what it got; counting only the short lines would report a request that took 4 hinges on one
        # leaf and missed 3 on another as "need 4, 1 available", which is true of neither.
        sar_totals_by_combo: dict[tuple[str, str], list[int]] = {}
        for sa_opening_input in sar_openings_input:
            for item in sa_opening_input.get("items", []):
                key = (item["hardware_category"], item["product_code"])
                totals = sar_totals_by_combo.setdefault(key, [0, 0])
                totals[0] += item["quantity"]
                totals[1] += _allocated_quantity(item)
        sar_short_by_combo = {
            key: (owed, allocated) for key, (owed, allocated) in sar_totals_by_combo.items() if owed > allocated
        }

        sar = SARModel(
            id=uuid.uuid4(),
            request_number=sar_request_number,
            project_id=project.id,
            status=ShopAssemblyRequestStatus.PENDING,
            created_by="Hardware Schedule Import",
        )
        session.add(sar)
        session.flush()

        for sa_opening_input in sar_openings_input:
            opening_number = sa_opening_input["opening_number"]
            opening_id = opening_id_by_number[opening_number]

            opening_row = existing_openings_by_number.get(opening_number)
            sa_opening = SAOModel(
                id=uuid.uuid4(),
                shop_assembly_request_id=sar.id,
                pull_request_id=None,
                opening_id=opening_id,
                opening_number=opening_number,
                leaf=sa_opening_input.get("leaf"),
                building=opening_row.building if opening_row else None,
                floor=opening_row.floor if opening_row else None,
                location=opening_row.location if opening_row else None,
                pull_status=PullStatus.NOT_PULLED,
                assembly_status=AssemblyStatus.PENDING,
            )
            session.add(sa_opening)
            session.flush()

            for item_input in sa_opening_input.get("items", []):
                session.add(
                    SAOItemModel(
                        id=uuid.uuid4(),
                        shop_assembly_opening_id=sa_opening.id,
                        hardware_category=item_input["hardware_category"],
                        product_code=item_input["product_code"],
                        # Owed stays the schedule's number even when nothing could be claimed for it.
                        # The checklist is what the leaf takes; the allocation is what turned up.
                        quantity=item_input["quantity"],
                        allocated_quantity=_allocated_quantity(item_input),
                    )
                )

        # The request holds its claim from here until the warehouse approves the pull that spends it
        # (#342). One row per combo across the whole request, not per opening - and over the
        # allocated quantities, so the pull the accept mints asks for exactly what is reserved and
        # `approve_pull_request` keeps its all-or-nothing property with no warehouse-side change.
        warehouse_repository.create_reservations(
            session,
            project.id,
            ReservationSource.SHOP_ASSEMBLY_REQUEST,
            sar.id,
            sar_needs,
        )

        if sar_short_by_combo:
            from app.services import notification_service

            notification_service.notify_po_shortfall(
                session,
                project_id=project.id,
                request_number=sar_request_number,
                shortfalls=[
                    warehouse_repository.Shortfall(
                        hardware_category=cat,
                        product_code=code,
                        requested=owed,
                        available=allocated,
                        short=owed - allocated,
                        reserved=0,
                    )
                    for (cat, code), (owed, allocated) in sorted(sar_short_by_combo.items())
                ],
                # The request exists and nothing is blocked - this is "here is what the project is
                # missing", not "a request failed".
                sent_short=True,
            )

    session.flush()

    return {
        "project": project,
        "purchase_orders": created_pos,
        "shipping_out_requests": created_shipping_requests,
        "shop_assembly_request": sar,
    }


def list_excluded_items(session: Session, project_id: uuid.UUID):
    from app.models.project_excluded_item import ProjectExcludedItem as PEIModel

    return list(session.scalars(select(PEIModel).where(PEIModel.project_id == project_id)).all())
