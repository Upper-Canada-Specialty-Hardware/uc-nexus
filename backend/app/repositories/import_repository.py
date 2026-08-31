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
    Classification,
    HardwareItemState,
    POStatus,
    PullRequestSource,
    PullRequestStatus,
    ReservationSource,
    ShippingOutRequestStatus,
    ShopAssemblyBatchStatus,
    ShopAssemblyOpeningStatus,
    ShopAssemblyRequestStatus,
)
from app.models.hardware import HardwareItem as HardwareItemModel
from app.models.project import Opening as OpeningModel
from app.models.project import Project as ProjectModel
from app.models.pull_request import PullRequest as PullRequestModel
from app.models.pull_request import PullRequestItem as PullRequestItemModel
from app.models.purchase_order import POLineItem as POLineItemModel
from app.models.purchase_order import PurchaseOrder as POModel
from app.models.shipping import PackingSlip as PackingSlipModel
from app.models.shipping import PackingSlipItem as PackingSlipItemModel
from app.models.shipping_out_request import (
    ShippingOutRequest as ShippingOutRequestModel,
)
from app.models.shipping_out_request import (
    ShippingOutRequestItem as ShippingOutRequestItemModel,
)
from app.models.shop_assembly import (
    ShopAssemblyBatch as SARBatchModel,
)
from app.models.shop_assembly import (
    ShopAssemblyRequest as SARModel,
)
from app.models.shop_assembly import (
    ShopAssemblyRequestItem as SARItemModel,
)
from app.models.shop_assembly import (
    ShopAssemblyRequestOpening as SAROpeningModel,
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
                "classification": hi.classification,
            }
            for hi in hardware_items
        ],
    }


def get_project_openings(session: Session, project_id: uuid.UUID) -> dict:
    """A project's openings for an opening picker, plus the opening and hardware-item counts.

    Trimmed on purpose: `get_project_hardware_schedule` above materializes every HardwareItem row
    to answer wizard hydration, and reusing it to fill a three-field opening picker made the shipping
    request composer pay that cost for nothing (#608 review). This selects only the opening columns
    the picker filters/displays on, and answers the item count with a grouped COUNT.
    """
    rows = session.execute(
        select(
            OpeningModel.opening_number,
            OpeningModel.building,
            OpeningModel.floor,
            OpeningModel.location,
            OpeningModel.hand,
            OpeningModel.door_type,
            OpeningModel.frame_type,
            OpeningModel.interior_exterior,
            OpeningModel.keying,
            OpeningModel.leaf_count,
        )
        .where(OpeningModel.project_id == project_id)
        .order_by(OpeningModel.opening_number)
    ).all()
    hardware_item_count = (
        session.scalar(
            select(func.count()).select_from(HardwareItemModel).where(HardwareItemModel.project_id == project_id)
        )
        or 0
    )
    return {
        "openings": [dict(row._mapping) for row in rows],
        "opening_count": len(rows),
        "hardware_item_count": hardware_item_count,
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

    # ---- Bulk Query 1b: null-linked IN_PO rows (the SharePoint migration's purchased-marking) ----
    # These carry no PO line, so the inner join above never sees them - and without this they fell
    # into NOT_COVERED, got auto-selected on a PO re-import, and finalize minted a duplicate row per
    # combo while a real PO was drafted for units already on the shelf. They bucket as RECEIVED:
    # bought and received under the retired system is exactly what the marking asserts.
    marked_stmt = (
        select(
            OpeningModel.opening_number,
            HardwareItemModel.product_code,
            func.sum(HardwareItemModel.item_quantity).label("marked_quantity"),
        )
        .join(OpeningModel, HardwareItemModel.opening_id == OpeningModel.id)
        .where(
            HardwareItemModel.project_id == project_id,
            HardwareItemModel.state == HardwareItemState.IN_PO,
            HardwareItemModel.po_line_item_id.is_(None),
        )
        .group_by(OpeningModel.opening_number, HardwareItemModel.product_code)
    )
    marked_by_pair: dict[tuple[str, str], int] = {}
    for row in session.execute(marked_stmt).all():
        pair = (row.opening_number, row.product_code)
        if pair not in pair_set:
            continue
        marked_by_pair[pair] = int(row.marked_quantity or 0)

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

    # ---- Bulk Query 3: what has physically shipped, off the packing slips ----
    # The slip is the record of departure now that no assembled unit carries one. Nothing here counts
    # assembly: a completed SHOP_ASSEMBLY pull is the only evidence the bench ever got the hardware,
    # and Step 3 has already bucketed it.
    slip_stmt = (
        select(
            PackingSlipItemModel.opening_number,
            PackingSlipItemModel.product_code,
            func.sum(PackingSlipItemModel.quantity).label("qty"),
        )
        .join(PackingSlipModel, PackingSlipItemModel.packing_slip_id == PackingSlipModel.id)
        .where(PackingSlipModel.project_id == project_id)
        .group_by(PackingSlipItemModel.opening_number, PackingSlipItemModel.product_code)
    )
    shipped_by_pair: dict[tuple[str, str], int] = defaultdict(int)
    for row in session.execute(slip_stmt).all():
        key = (row.opening_number, row.product_code)
        if key not in pair_set:
            continue
        shipped_by_pair[key] += row.qty or 0

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

        # Migration-marked rows (Bulk Query 1b): received, just not through a Nexus PO.
        buckets["RECEIVED"] += marked_by_pair.get(pair_key, 0)

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

        # Step 4: Shipped cross-check against the slips
        slip_shipped = shipped_by_pair.get(pair_key, 0)
        existing_shipped = buckets.get("SHIPPED_OUT", 0)
        if slip_shipped > existing_shipped:
            extra = slip_shipped - existing_shipped
            from_received = min(extra, buckets.get("RECEIVED", 0))
            buckets["RECEIVED"] = max(0, buckets.get("RECEIVED", 0) - from_received)
            buckets["SHIPPED_OUT"] = existing_shipped + from_received

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


def _live_shop_assembly_requests(session: Session, project_id: uuid.UUID) -> list[SARModel]:
    """Shop-assembly requests in a project that are still in flight (#646).

    PENDING is always in flight - it has openings waiting on the manager. A closed-out (APPROVED)
    request is in flight only while every batch it dispatched is still an unworked PENDING pull;
    once the warehouse starts one, inventory has moved and the request is no longer something a
    re-upload may quietly rewrite. Either way the rewrite below only touches PENDING openings; a
    closed-out request just gets the flag.
    """
    worked_batch = (
        select(SARBatchModel.id)
        .join(PullRequestModel, SARBatchModel.pull_request_id == PullRequestModel.id)
        .where(
            SARBatchModel.shop_assembly_request_id == SARModel.id,
            SARBatchModel.status == ShopAssemblyBatchStatus.ACTIVE,
            PullRequestModel.status != PullRequestStatus.PENDING,
        )
    )
    return list(
        session.scalars(
            select(SARModel)
            .options(
                selectinload(SARModel.items),
                selectinload(SARModel.openings),
                selectinload(SARModel.batches),
            )
            .where(
                SARModel.project_id == project_id,
                or_(
                    SARModel.status == ShopAssemblyRequestStatus.PENDING,
                    and_(
                        SARModel.status == ShopAssemblyRequestStatus.APPROVED,
                        ~worked_batch.exists(),
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

    - **PENDING requests are rewritten to what survived.** Lines whose opening is gone are deleted,
      and for shipping out the reservations are rebuilt from what is left - which releases exactly
      the claim the vanished openings were holding, no more. A shop-assembly request rebuilds
      nothing, because its pending openings never held a claim (#646). A request left with nothing at
      all is auto-REJECTED (which for shipping out releases the rest by the ordinary reject path),
      because an empty request is not something anybody can work; a part-batched shop-assembly one
      closes out instead, since some of it genuinely happened.
    - **Openings already dispatched or dismissed are left alone.** A batched opening is on a pull
      that is the authority on what the warehouse will hand over, and silently shrinking it
      underneath the puller would be worse than a stale bill of hardware; a dismissed one is a
      decision somebody made.
    - **Every live request is flagged** with `integrity_note`, not just the ones that lost openings,
      because a full-schedule replacement can change the hardware on an opening it kept. The
      acceptor sees the flag and can reject-and-recreate.

    Deliberately *not* done: re-deriving a surviving request's items from the new schedule. The
    request is a snapshot somebody made a decision about; rewriting its contents under them would
    make the flag a lie.
    """
    from app.repositories import warehouse as warehouse_repository

    vanished_numbers = {o.opening_number for o in project.openings if o.opening_number not in new_opening_numbers}

    for sar in _live_shop_assembly_requests(session, project.id):
        pending = sar.status == ShopAssemblyRequestStatus.PENDING
        # Only openings still waiting on the manager may be rewritten. A batched one is on a pull the
        # warehouse is working, and a dismissed one is a decision somebody made - neither is the
        # re-upload's to revise. Nothing here releases a reservation, because a pending opening has
        # never held one (#646).
        lost_openings = (
            [
                o
                for o in sar.openings
                if o.status == ShopAssemblyOpeningStatus.PENDING and o.opening_number in vanished_numbers
            ]
            if pending
            else []
        )
        if lost_openings:
            gone = {o.opening_number for o in lost_openings}
            session.execute(
                delete(SARItemModel).where(
                    SARItemModel.shop_assembly_request_id == sar.id,
                    SARItemModel.opening_number.in_(gone),
                )
            )
            session.execute(delete(SAROpeningModel).where(SAROpeningModel.id.in_([o.id for o in lost_openings])))
            session.flush()
            session.refresh(sar, attribute_names=["items", "openings"])

        if pending and not any(o.status == ShopAssemblyOpeningStatus.PENDING for o in sar.openings):
            if sar.batches:
                # Part-worked: the batches that already went out are the record of what happened, so
                # the request closes out rather than being rejected as though nothing had.
                sar.status = ShopAssemblyRequestStatus.APPROVED
                sar.approved_by = "Hardware Schedule Import"
                sar.approved_at = datetime.utcnow()
            else:
                # Nothing left to assemble and nothing ever dispatched: reject it rather than leave an
                # empty request on the manager's board.
                sar.status = ShopAssemblyRequestStatus.REJECTED
                sar.rejected_by = "Hardware Schedule Import"
                sar.rejection_reason = "All of this request's openings were removed by a hardware schedule re-upload."
                sar.rejected_at = datetime.utcnow()
            continue

        sar.integrity_note = SCHEDULE_CHANGED_DROPPED_NOTE if lost_openings else SCHEDULE_CHANGED_NOTE

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
                [(i.hardware_category, i.product_code, i.requested_quantity) for i in req.items],
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


def plan_po_claims(
    hardware_items_input: list[dict],
    po_drafts: list[dict],
) -> tuple[list[list[tuple[int, int]]], dict[int, int]]:
    """Plan how #570 quantity-aware PO drafts claim the schedule's hardware rows.

    Pure and DB-free, so the splitting and cross-draft coordination that are the delicate part of
    finalize can be unit-tested on their own. Given the flat schedule rows (`hardware_items_input`, in
    input order) and the PO drafts, returns:

      per_draft_claims: one list per draft, in po_drafts order - a list of (row_index, quantity)
        naming which hardware_items_input rows the draft claims and how many units of each. A boundary
        leaf shared between two drafts appears once in each, with the split counts.
      remaining_by_idx: row_index -> unclaimed units, for the AVAILABLE persist.

    A combo is (opening_number, product_code, hardware_category); its leaf rows are its buckets. A ref
    with quantity=None claims the whole remaining combo (today's all-or-nothing); a number claims that
    many units, splitting the boundary leaf. Drafts claim in order, so an earlier draft takes the first
    units of a combo and a later one continues where it left off. Raises ValidationError when the
    claims for a combo exceed its total, NotFoundError when a ref names a combo the schedule lacks.
    """
    # One mutable pool per combo: each bucket is [row_index, remaining] against hardware_items_input,
    # in input order.
    combo_buckets: dict[tuple[str, str, str], list[list]] = defaultdict(list)
    for idx, hi in enumerate(hardware_items_input):
        combo = (hi["opening_number"], hi["product_code"], hi["hardware_category"])
        combo_buckets[combo].append([idx, hi["item_quantity"]])
    combo_total = {combo: sum(b[1] for b in buckets) for combo, buckets in combo_buckets.items()}

    # Up-front cap check: units claimed of a combo cannot exceed what the schedule holds. None resolves
    # to the whole combo, so a None plus any other claim on the same combo trips the cap. A combo
    # absent from the schedule is left to the per-ref NotFoundError below, not reported as an overclaim.
    claimed_per_combo: dict[tuple[str, str, str], int] = defaultdict(int)
    for po_draft in po_drafts:
        for ref in po_draft.get("hardware_item_refs", []):
            combo = (ref["opening_number"], ref["product_code"], ref["hardware_category"])
            want = ref.get("quantity")
            claimed_per_combo[combo] += combo_total.get(combo, 0) if want is None else want
    for combo, want in claimed_per_combo.items():
        total = combo_total.get(combo)
        if total is not None and want > total:
            raise ValidationError(
                f"Purchase order drafts claim {want} of {combo[1]} ({combo[2]}) at opening {combo[0]}, "
                f"but the schedule holds only {total}.",
                field="po_drafts",
            )

    per_draft_claims: list[list[tuple[int, int]]] = []
    for po_draft in po_drafts:
        claims: list[tuple[int, int]] = []
        for ref in po_draft.get("hardware_item_refs", []):
            combo = (ref["opening_number"], ref["product_code"], ref["hardware_category"])
            buckets = combo_buckets.get(combo)
            if not buckets:
                raise NotFoundError(f"Hardware item not found: {combo}")

            want = ref.get("quantity")
            available = sum(b[1] for b in buckets)
            need = available if want is None else want
            if need > available:
                # A later draft asking for a slice the pool has already handed out.
                raise ValidationError(
                    f"Purchase order drafts claim more of {combo[1]} ({combo[2]}) at opening "
                    f"{combo[0]} than the schedule holds.",
                    field="po_drafts",
                )

            # Claim leaf buckets greedily; the boundary leaf splits - its claimed part is recorded here
            # and its remainder stays in the bucket for the next draft or the AVAILABLE step.
            for bucket in buckets:
                if need <= 0:
                    break
                if bucket[1] <= 0:
                    continue
                take = min(bucket[1], need)
                bucket[1] -= take
                need -= take
                claims.append((bucket[0], take))
        per_draft_claims.append(claims)

    remaining_by_idx = {bucket[0]: bucket[1] for buckets in combo_buckets.values() for bucket in buckets}
    return per_draft_claims, remaining_by_idx


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
    project_id = uuid.UUID(input_data["project_id"])
    openings_input = input_data.get("openings", [])
    hardware_items_input = input_data.get("hardware_items") or []
    po_drafts = input_data.get("po_drafts") or []
    classifications_input = input_data.get("classifications") or []
    excluded_items_input = input_data.get("excluded_items") or []
    shipping_pr_drafts = input_data.get("shipping_out_pr_drafts") or []
    include_sar = input_data.get("include_shop_assembly_request", False)
    # #493: the client's shop_assembly_request_number is deprecated and ignored. The number is
    # minted from the project's counter below.
    sar_items_input = input_data.get("shop_assembly_items") or []
    replace_schedule = bool(input_data.get("replace_schedule", False))
    # #627: the source XML file name, present only when the hardware items came from a fresh parse.
    schedule_filename = input_data.get("schedule_filename")

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

    # #627: record the source XML file name when this finalize came from a fresh parse. None on a
    # hydrate-from-persisted finalize, which re-sends the persisted items unchanged - leaving the
    # stored name untouched so it survives.
    if schedule_filename is not None:
        project.schedule_filename = schedule_filename

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

    # #570: PO drafts claim combos by quantity now, not all-or-nothing. plan_po_claims works out, per
    # draft, which schedule rows it takes and how many units of each - a boundary leaf shared between
    # two drafts is split - plus what quantity of every row is left unclaimed for the AVAILABLE step.
    # It is pure and DB-free, so the delicate splitting/coordination is unit-tested on its own and the
    # block below only materializes the plan. Built unconditionally: with no drafts the remainder is
    # the whole schedule.
    per_draft_claims, remaining_by_idx = plan_po_claims(hardware_items_input, po_drafts)

    # 4. PO creation
    created_pos: list[POModel] = []
    if po_drafts:
        # Generate request_number sequence for new POs
        from app.repositories.po_repository import generate_next_request_number

        next_request_number = generate_next_request_number(session)
        next_seq = int(next_request_number.replace("PO-REQ-", ""))

        for draft_idx, po_draft in enumerate(po_drafts):
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

            # Create PO. The wizard's per-draft vendor label seeds vendor_name_snapshot (#632) so the
            # register table and bestGuessGpVendor have something to show for a request; the GP vendor
            # (PM00200) picked at register time is still the only vendor authority - registering
            # overwrites the snapshot with the confirmed GP display name (#509).
            po = POModel(
                id=uuid.uuid4(),
                po_number=po_number,
                request_number=request_number,
                vendor_name_snapshot=(po_draft.get("vendor_name") or "").strip() or None,
                project_id=project.id,
                status=POStatus.DRAFT,
                notes=po_draft.get("notes"),
                # Issue #216: the PM's requested date, captured at PO-request creation.
                preferred_delivery_date=po_draft.get("preferred_delivery_date"),
                # #490: the buyer's cost-code pick, if the relay was up to offer the job's list.
                # Register still validates against GP - this is a default, not a decision.
                cost_code=(po_draft.get("cost_code") or None),
                # Whoever finalized this wizard session, from the resolver's Clerk token. It is who a
                # receive against this PO later asks "inventory or ship out?".
                created_by_user_id=input_data.get("created_by_user_id"),
            )
            session.add(po)
            session.flush()

            # Collect hardware items for this PO and aggregate into line items
            # Key: (hardware_category, product_code, unit_cost, classification) -> list of HardwareItem models
            line_item_agg: dict[tuple, list] = defaultdict(list)

            # Materialize this draft's planned claims. Each (row_index, take) is one HardwareItem the
            # draft claims - a boundary leaf split by the planner arrives as a smaller `take`. Rows for
            # the same (category, product, cost, classification) roll into one PO line via the agg key,
            # so the line's ordered_quantity sums across leaves and across splits.
            for row_idx, take in per_draft_claims[draft_idx]:
                hi_data = hardware_items_input[row_idx]

                opening_id = opening_map.get(hi_data["opening_number"])
                if opening_id is None:
                    raise NotFoundError(f"Opening {hi_data['opening_number']} not found in project")

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
                    item_quantity=take,
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

    # 5. Persist the unclaimed remainder of every hardware item as AVAILABLE. #570: a combo the PO
    #    block took in full leaves nothing here; a partially-claimed combo persists what plan_po_claims
    #    left in remaining_by_idx (item_quantity = the remainder); an unreferenced combo persists in
    #    full. Skips a row whose (opening_id, product, category, leaf) already exists as IN_PO from a
    #    prior session, to avoid duplicating rows.
    available_keys_seen: set[tuple[uuid.UUID, str, str, int | None]] = set()
    for idx, hi in enumerate(hardware_items_input):
        remaining = remaining_by_idx.get(idx, hi["item_quantity"])
        if remaining <= 0:
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
                item_quantity=remaining,
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

    # 5b. Re-apply the SharePoint migration's purchased-marking. A replace_schedule wipe above took
    # the null-linked IN_PO rows with it, and without this the project reads as never-purchased
    # again and the next PO draft offers to re-buy the migrated shelf stock. The recorded coverage
    # targets are marked against whatever rows this finalize just wrote; on a normal re-import the
    # preserved rows already cover the targets and this is a no-op. One indexed SELECT on a project
    # the migration never touched.
    from app.repositories import sharepoint_migration_repository

    sharepoint_migration_repository.reapply_migration_marks(session, project.id)

    # 6. Shipping-out requests (#293): Start a Request mints a PENDING ShippingOutRequest, NOT a
    # PullRequest. A signed-in user accepts it later, which mints the warehouse PullRequest.
    #
    # Every guard and the reservation gate live in shipping_requests (#451), because the Shipping
    # module raises requests straight off inventory now and both paths have to be held to the same
    # rules by the same code, whichever screen composed them.
    created_shipping_requests = _shipping_requests.create_shipping_out_requests(
        session,
        project.id,
        shipping_pr_drafts or [],
        created_by="Hardware Schedule Import",
    )

    # 7. Shop-assembly request (#646)
    # The PM is flagging openings, not composing a pull: this mints a PENDING ShopAssemblyRequest
    # with the openings and what each is still owed, and nothing else - no availability gate, no
    # reservation, no pull. The Shop Assembly Manager batches it later, and each batch is what gates,
    # reserves and mints.
    #
    # There is no duplicate-opening guard any more. Two requests naming the same opening are both
    # legitimate - the opening genuinely may be owed hardware twice - and the composer is what stops
    # anyone raising the second one by accident: an opening's live requests count against it as
    # `claimed`, so it suggests zero rather than offering the same units again.
    sar = None
    if include_sar:
        from app.repositories import shop_assembly_repository

        if not sar_items_input:
            raise ValidationError(
                "A shop-assembly request must include at least one line.",
                field="shop_assembly_items",
            )

        for item_input in sar_items_input:
            opening_number = item_input.get("opening_number")
            if opening_number and opening_number not in opening_map:
                raise NotFoundError(f"Opening {opening_number} not found in project")

        sar = shop_assembly_repository.create_shop_assembly_request(
            session,
            project.id,
            [
                {
                    "opening_number": item_input.get("opening_number"),
                    "hardware_category": item_input["hardware_category"],
                    "product_code": item_input["product_code"],
                    # `quantity` is what a pre-#646 tab called the composer's suggestion, which is
                    # exactly what a request line is owed. Any `allocated_quantity` such a tab also
                    # sends is ignored - nothing is allocated at creation any more.
                    "requested_quantity": item_input["quantity"],
                }
                for item_input in sar_items_input
            ],
            created_by="Hardware Schedule Import",
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
