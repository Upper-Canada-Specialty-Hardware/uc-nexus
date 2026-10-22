"""Repository for hardware schedule import operations."""

import uuid
from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from sqlalchemy import String, and_, bindparam, delete, func, or_, select, tuple_, update
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Session, selectinload

from app.errors import ConflictError, NotFoundError, ValidationError
from app.models.enums import (
    Classification,
    HardwareItemState,
    NotificationType,
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
from app.services import notification_service


def get_project_hardware_schedule(
    session: Session,
    project_id: uuid.UUID,
) -> dict | None:
    """Load a project's persisted hardware schedule (openings + items) for wizard hydration, with its
    classification list (#1443), which the wizard fills listed products in from instead of asking."""
    from app.repositories import classification_override_repository

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

    # #1491: what the wizard hydrates is the latest schedule, so the units ordered past it are left out
    # and a row wholly past it is not offered at all. Hydrating them back in would make the next finalize
    # read the surplus as scheduled again and restate it as required.
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
                "item_quantity": hi.item_quantity - hi.beyond_schedule_quantity,
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
            if hi.item_quantity > hi.beyond_schedule_quantity
        ],
        "product_classifications": classification_override_repository.listed_classifications(session, project_id),
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


def _received_share_by_row(hi_rows) -> dict[uuid.UUID, int]:
    """How many of each partially received line's received units each tied schedule row holds (#1490).

    Rounding every row's proportional share down on its own lost them: a 20-unit line spread over 20
    openings at 1 each with 10 received gave every row floor(1 x 0.5) = 0, so all 20 openings read
    ORDERED and nothing downstream (pulls, shipments) could be placed against a received unit. The
    line's total share is worked out once - the units on its tied rows, scaled by received / ordered
    as before, so a line ordered beyond the schedule still splits its receipts in proportion - and
    then handed out across ALL of the line's tied rows in a fixed order (opening, leaf, row id), each
    filled up to its quantity. Every row of the project is in `hi_rows`, so a row's share is the same
    whichever openings a call asks about.
    """
    by_line: dict[uuid.UUID, list] = defaultdict(list)
    for row in hi_rows:
        if row.po_status == POStatus.PARTIALLY_RECEIVED:
            by_line[row.po_line_item_id].append(row)

    share: dict[uuid.UUID, int] = {}
    for rows in by_line.values():
        tied = sum(r.item_quantity for r in rows)
        ordered = rows[0].ordered_quantity or 0
        received = rows[0].received_quantity or 0
        if tied <= 0 or received <= 0:
            continue
        remaining = min(tied, received, received * tied // max(ordered, tied))
        for r in sorted(rows, key=lambda r: (r.opening_number, r.leaf is not None, r.leaf or 0, str(r.id))):
            if remaining <= 0:
                break
            take = min(r.item_quantity, remaining)
            share[r.id] = take
            remaining -= take
    return share


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

    # The (opening, category, product) keys this call is asking about - the wizard sends one item per
    # that triple, so a product listed under two categories at one opening is two items, and keying by
    # (opening, product) credited each of them with both categories' units (#1412). Matching happens
    # in Python rather than as a SQL `tuple_(...).in_(pairs)` predicate: Postgres expands a
    # row-constructor IN list into a nested expression tree and parses it recursively, so a
    # full-schedule selection (thousands of
    # openings x their hardware) overflowed `max_stack_depth` and the whole reconcile failed with
    # StatementTooComplex. Every query below is already scoped to the project and indexed on it, so
    # the predicate only ever trimmed rows the loops can skip just as cheaply - and at the scale that
    # broke it, it trimmed nothing at all.
    pair_set = {(item["opening_number"], item["hardware_category"], item["product_code"]) for item in lifecycle_items}

    # ---- Bulk Query 1: HardwareItems linked to non-cancelled, non-deleted POs ----
    hi_stmt = (
        select(
            HardwareItemModel.id,
            HardwareItemModel.leaf,
            HardwareItemModel.po_line_item_id,
            OpeningModel.opening_number,
            HardwareItemModel.hardware_category,
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
    hi_rows = session.execute(hi_stmt).all()
    received_share = _received_share_by_row(hi_rows)
    hi_by_pair: dict[tuple[str, str, str], list] = defaultdict(list)
    for row in hi_rows:
        pair = (row.opening_number, row.hardware_category, row.product_code)
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
            HardwareItemModel.hardware_category,
            HardwareItemModel.product_code,
            func.sum(HardwareItemModel.item_quantity).label("marked_quantity"),
        )
        .join(OpeningModel, HardwareItemModel.opening_id == OpeningModel.id)
        .where(
            HardwareItemModel.project_id == project_id,
            HardwareItemModel.state == HardwareItemState.IN_PO,
            HardwareItemModel.po_line_item_id.is_(None),
        )
        .group_by(OpeningModel.opening_number, HardwareItemModel.hardware_category, HardwareItemModel.product_code)
    )
    marked_by_pair: dict[tuple[str, str, str], int] = {}
    for row in session.execute(marked_stmt).all():
        pair = (row.opening_number, row.hardware_category, row.product_code)
        if pair not in pair_set:
            continue
        marked_by_pair[pair] = int(row.marked_quantity or 0)

    # ---- Bulk Query 2: PullRequest aggregates ----
    pr_stmt = (
        select(
            PullRequestItemModel.opening_number,
            PullRequestItemModel.hardware_category,
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
            PullRequestItemModel.hardware_category,
            PullRequestItemModel.product_code,
            PullRequestModel.source,
            PullRequestModel.status,
        )
    )
    pr_by_pair: dict[tuple[str, str, str], list] = defaultdict(list)
    for row in session.execute(pr_stmt).all():
        pair = (row.opening_number, row.hardware_category, row.product_code)
        if pair not in pair_set:
            continue
        pr_by_pair[pair].append(row)

    # ---- Bulk Query 3: what has physically shipped, off the packing slips ----
    # The slip is the record of departure now that no assembled unit carries one. Nothing here counts
    # assembly: a completed SHOP_ASSEMBLY pull is the only evidence the bench ever got the hardware,
    # and Step 3 has already bucketed it.
    # #1941: the shipping workspace's own reads - manual lines left out (free text that never came off
    # inventory), and what came back netted - so a re-import does not see a spare line or a returned
    # unit as the opening's hardware gone out.
    from app.repositories.request_composer import came_back_stmt, slip_shipped_stmt

    shipped_by_pair: dict[tuple[str, str, str], int] = defaultdict(int)
    for opening_number, category, code, quantity in session.execute(slip_shipped_stmt(project_id)).all():
        key = (opening_number, category, code)
        if key not in pair_set:
            continue
        shipped_by_pair[key] += int(quantity or 0)
    # Split by where it went: a return to the project is back on its shelf, a cancelled slip's return
    # to stock left the project. Either way the opening is owed it again.
    back_on_shelf: dict[tuple[str, str, str], int] = defaultdict(int)
    back_elsewhere: dict[tuple[str, str, str], int] = defaultdict(int)
    for opening_number, category, code, to_project, quantity in session.execute(came_back_stmt(project_id)).all():
        key = (opening_number, category, code)
        if key not in pair_set:
            continue
        (back_on_shelf if to_project else back_elsewhere)[key] += int(quantity or 0)

    # ---- Process each item using pre-loaded data ----
    for item in lifecycle_items:
        opening_number = item["opening_number"]
        hardware_category = item["hardware_category"]
        product_code = item["product_code"]
        quantity_needed = item["quantity_needed"]
        pair_key = (opening_number, hardware_category, product_code)

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
                # #1490: the row's share of the line's received units, handed out across every row
                # tied to the line rather than rounded down row by row.
                received_portion = received_share.get(row.id, 0)
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

        # Step 4b (#1941): what came back is not shipped out - the way the shipping workspace nets it
        # (max of pull and slip, less what came back). Returned to the project, it is on the shelf
        # again; returned to stock off a cancelled slip, it left the project and is owed again.
        to_shelf = min(back_on_shelf.get(pair_key, 0), buckets.get("SHIPPED_OUT", 0))
        buckets["SHIPPED_OUT"] = buckets.get("SHIPPED_OUT", 0) - to_shelf
        buckets["RECEIVED"] = buckets.get("RECEIVED", 0) + to_shelf
        gone = min(back_elsewhere.get(pair_key, 0), buckets["SHIPPED_OUT"])
        buckets["SHIPPED_OUT"] -= gone

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


# The actor stamped when the schedule itself, not a person, makes the change: the re-upload closing
# out or rejecting requests whose openings it removed. #859: it is no longer the requester of what a
# finalize raises - that is the signed-in person, passed in as `created_by`. It stays the default
# only for direct repository callers (the tests), which have no signed-in person.
SCHEDULE_IMPORT_ACTOR = "Hardware Schedule Import"

# The note stamped on a live in-flight request when a full-schedule re-upload lands underneath it.
SCHEDULE_CHANGED_NOTE = (
    "The hardware schedule was re-uploaded after this request was created, so its bill of hardware "
    "may no longer match the schedule. Review it before accepting."
)
SCHEDULE_CHANGED_DROPPED_NOTE = (
    # "any claim they were holding" rather than a flat "their reservations were released", because
    # since #646 that is only true of a shipping-out request: a pending shop-assembly opening has
    # never held one, and telling its manager stock was just freed would be a lie.
    "The hardware schedule was re-uploaded after this request was created and some of its openings "
    "no longer exist; those were dropped, along with any claim they were holding on inventory. "
    "Review what is left before accepting."
)
# #1855: a shop-assembly request has no accept step - the manager batches it - so its notes ask for the
# review before batching, and batching clears them (`create_shop_assembly_batch`). Its dropped openings
# were pending, which never hold a claim (#646), so there is none to mention.
SHOP_SCHEDULE_CHANGED_NOTE = (
    "The hardware schedule was re-uploaded after this request was created, so its bill of hardware "
    "may no longer match the schedule. Review it before batching."
)
SHOP_SCHEDULE_CHANGED_DROPPED_NOTE = (
    "The hardware schedule was re-uploaded after this request was created and some of its openings "
    "no longer exist; those were dropped. Review what is left before batching."
)


def _removed_openings(numbers: set[str]) -> str:
    """The openings a re-upload took off a shop request, for its note (#1955): "opening A01" or
    "openings A01, A02"."""
    if not numbers:
        return "its openings"
    names = ", ".join(sorted(numbers))
    return f"opening {names}" if len(numbers) == 1 else f"openings {names}"


def _live_shop_assembly_requests(session: Session, project_id: uuid.UUID) -> list[SARModel]:
    """Shop-assembly requests in a project that are still in flight (#646).

    PENDING is always in flight - it has openings waiting on the manager. A closed-out (APPROVED)
    request is in flight only while every batch it dispatched is still an unworked PENDING pull;
    once the warehouse starts one, inventory has moved and the request is no longer something a
    re-upload may quietly rewrite. Either way the rewrite below only touches PENDING openings; a
    closed-out request just gets the flag.

    #1852: the candidates are row-locked, in id order and after the project lock the finalize took,
    before anything is read off them. A batch locks the same row before it marks openings BATCHED
    (`shop_assembly_repository._locked_request`), so unlocked, a batch committing between this read and
    the deletes below had its batched opening deleted, and a request holding a live batch was REJECTED
    as though nothing had been dispatched. Now one waits for the other, and the read below sees what
    the other committed.
    """
    from app.services.locking import lock_rows

    lock_rows(
        session,
        SARModel,
        list(
            session.scalars(
                select(SARModel.id).where(
                    SARModel.project_id == project_id,
                    SARModel.status.in_([ShopAssemblyRequestStatus.PENDING, ShopAssemblyRequestStatus.APPROVED]),
                )
            ).all()
        ),
    )
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
            # A finalize can dispatch a batch and then replace the schedule in the same transaction,
            # and without this the identity-mapped request comes back carrying the empty `batches`
            # collection its first load saw - which reads as "never dispatched" and would auto-REJECT
            # a request that has real hardware on the warehouse floor. Same reasoning as the readers
            # in shop_assembly_repository. It is also what makes the lock above count (#1852): a copy
            # already in the session would otherwise hide a batch committed while the lock was waited on.
            .execution_options(populate_existing=True)
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
      closes out instead, since some of it genuinely happened. Either way a shop-assembly request's
      note names the openings that went, and an auto-rejected one tells the shop (#1955).
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
            # #1955: either way the request leaves the board, so its note says which openings the
            # re-upload took - they are gone from the request, and nothing else names them.
            removed = _removed_openings({o.opening_number for o in lost_openings})
            if any(b.status == ShopAssemblyBatchStatus.ACTIVE for b in sar.batches):
                # Part-worked: the batches that already went out are the record of what happened, so
                # the request closes out rather than being rejected as though nothing had. Only a live
                # batch counts (#1156): a cancelled one sent nothing to the shop, and closing on it read
                # the request as Done on the Worked tab.
                sar.status = ShopAssemblyRequestStatus.APPROVED
                sar.approved_by = SCHEDULE_IMPORT_ACTOR
                sar.approved_at = datetime.utcnow()
                sar.integrity_note = (
                    f"The hardware schedule was re-uploaded and removed {removed} while still waiting on "
                    "this request, so the request closed out with the batches already sent."
                )
            else:
                # Nothing left to assemble and nothing ever dispatched: reject it rather than leave an
                # empty request on the manager's board.
                sar.status = ShopAssemblyRequestStatus.REJECTED
                sar.rejected_by = SCHEDULE_IMPORT_ACTOR
                sar.rejection_reason = "All of this request's openings were removed by a hardware schedule re-upload."
                sar.rejected_at = datetime.utcnow()
                sar.integrity_note = (
                    f"The hardware schedule was re-uploaded and removed {removed}, all this request was "
                    "waiting on; nothing had been batched, so the request was rejected."
                )
                # #1955: the shop is told, as a manager's reject tells it (#1242).
                notification_service.create_notification(
                    session,
                    project_id=sar.project_id,
                    recipient_role=notification_service.SHOP_ASSEMBLY_RECIPIENT_ROLE,
                    notification_type=NotificationType.SHOP_ASSEMBLY_REQUEST_REJECTED,
                    message=(
                        f"{SCHEDULE_IMPORT_ACTOR} rejected shop assembly request {sar.request_number} - "
                        f"{sar.rejection_reason}"
                    ),
                )
            continue

        sar.integrity_note = SHOP_SCHEDULE_CHANGED_DROPPED_NOTE if lost_openings else SHOP_SCHEDULE_CHANGED_NOTE

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
            req.rejected_by = SCHEDULE_IMPORT_ACTOR
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
    already_ordered: dict[tuple[str, str, str, int | None], int] | None = None,
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

    `already_ordered` maps (opening_number, product_code, hardware_category, leaf) to units a prior
    session already put on a PO (#1156). The input row is the schedule's whole requirement (#1122), so
    those units come off each leaf's bucket first: a draft can claim only what is not yet ordered, a
    whole-combo ref resolves to that remainder, and remaining_by_idx is already net of the order.
    """
    # One mutable pool per combo: each bucket is [row_index, remaining] against hardware_items_input,
    # in input order, net of what is already ordered for that leaf.
    ordered_left = defaultdict(int, already_ordered or {})
    combo_buckets: dict[tuple[str, str, str], list[list]] = defaultdict(list)
    combo_ordered: dict[tuple[str, str, str], int] = defaultdict(int)
    for idx, hi in enumerate(hardware_items_input):
        combo = (hi["opening_number"], hi["product_code"], hi["hardware_category"])
        leaf_key = (*combo, hi.get("leaf"))
        covered = min(hi["item_quantity"], ordered_left[leaf_key])
        ordered_left[leaf_key] -= covered
        combo_ordered[combo] += covered
        combo_buckets[combo].append([idx, hi["item_quantity"] - covered])
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
            ordered = combo_ordered.get(combo, 0)
            held = f"only {total} not yet on a purchase order ({ordered} already are)" if ordered else f"only {total}"
            raise ValidationError(
                f"Purchase order drafts claim {want} of {combo[1]} ({combo[2]}) at opening {combo[0]}, "
                f"but the schedule holds {held}.",
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


def draft_claim_counts(
    hardware_items_input: list[dict],
    po_drafts: list[dict],
    per_draft_claims: list[list[tuple[int, int]]],
) -> list[tuple[int, int]]:
    """Per draft, (units its lines asked for, units plan_po_claims gave it) - #1883.

    A ref with quantity=None asks for the whole combo as the schedule holds it, before what is already
    on a PO comes off: that is what the wizard means by "the whole opening". A combo already ordered
    resolves to its unordered remainder (#1186), so a buy-again line on a covered product asks for units
    and gets none; finalize reports the gap rather than calling the import a plain success.
    """
    combo_gross: dict[tuple[str, str, str], int] = defaultdict(int)
    for hi in hardware_items_input:
        combo_gross[(hi["opening_number"], hi["product_code"], hi["hardware_category"])] += hi["item_quantity"]
    counts: list[tuple[int, int]] = []
    for po_draft, claims in zip(po_drafts, per_draft_claims, strict=True):
        requested = 0
        for ref in po_draft.get("hardware_item_refs", []):
            want = ref.get("quantity")
            combo = (ref["opening_number"], ref["product_code"], ref["hardware_category"])
            requested += combo_gross.get(combo, 0) if want is None else want
        counts.append((requested, sum(take for _, take in claims)))
    return counts


def restate_beyond_schedule(
    session: Session,
    project_id: uuid.UUID,
    hardware_items_input: list[dict],
    opening_map: dict[str, uuid.UUID],
) -> None:
    """Restate how much of a project's ordered hardware the latest schedule no longer asks for (#1491).

    A finalize restates the schedule from its `hardware_items` input, but the rows already on a PO
    survive it (#1123), so a revision that lowers or drops a product already ordered leaves more on
    POs than the schedule needs. Per (opening, product, category, leaf) - the key step 5 persists by -
    S is what the input asks for (0 when the input no longer has the key) and O is what the key's
    IN_PO rows hold; max(0, O - S) of them are past the schedule. That surplus is spread over the
    key's IN_PO rows oldest first, each taking at most its own quantity, and every other row of the
    project is set to 0. The rows themselves are left as they are; only how they are reported changes.

    One query loads the project's rows, so it runs after every write of the finalize, the SharePoint
    re-marking included, and sees the rows as the finalize leaves them.
    """
    scheduled: dict[tuple[uuid.UUID, str, str, int | None], int] = defaultdict(int)
    for hi in hardware_items_input:
        opening_id = opening_map.get(hi["opening_number"])
        if opening_id is not None:
            scheduled[(opening_id, hi["product_code"], hi["hardware_category"], hi.get("leaf"))] += hi["item_quantity"]

    rows = session.scalars(
        select(HardwareItemModel)
        .where(HardwareItemModel.project_id == project_id)
        .order_by(HardwareItemModel.created_at, HardwareItemModel.id)
    ).all()
    ordered: dict[tuple[uuid.UUID, str, str, int | None], list[HardwareItemModel]] = defaultdict(list)
    for row in rows:
        if row.state == HardwareItemState.IN_PO:
            ordered[(row.opening_id, row.product_code, row.hardware_category, row.leaf)].append(row)
        elif row.beyond_schedule_quantity:
            row.beyond_schedule_quantity = 0

    for key, key_rows in ordered.items():
        beyond = max(0, sum(row.item_quantity for row in key_rows) - scheduled.get(key, 0))
        for row in key_rows:
            take = min(beyond, row.item_quantity)
            if row.beyond_schedule_quantity != take:
                row.beyond_schedule_quantity = take
            beyond -= take
    session.flush()


# #1938: a schedule row's prices and markup are Numeric(10,4) columns, at most 999,999.9999. The parser
# refuses a row past that; this is the backstop, so a row sent past it is named rather than overflowing at
# flush as the masked server error.
_MAX_SCHEDULE_VALUE = Decimal(1_000_000)
_SCHEDULE_VALUE_FIELDS = {
    "unit_cost": "unit cost",
    "unit_price": "unit price",
    "list_price": "list price",
    "vendor_discount": "vendor discount",
    "markup_pct": "markup",
}


def refuse_schedule_values_too_large(hardware_items: list[dict]) -> None:
    """Refuse schedule rows whose prices or markup their columns can't hold, naming each row (#1938)."""
    rows = []
    for hi in hardware_items:
        past = [
            f"{label} {hi[key]}"
            for key, label in _SCHEDULE_VALUE_FIELDS.items()
            if hi.get(key) is not None and abs(Decimal(str(hi[key]))) >= _MAX_SCHEDULE_VALUE
        ]
        if past:
            rows.append(f"opening {hi.get('opening_number')} {hi.get('product_code')} ({', '.join(past)})")
    if rows:
        shown = "; ".join(rows[:5]) + (f"; and {len(rows) - 5} more" if len(rows) > 5 else "")
        raise ValidationError(
            f"A schedule price or markup must be under {_MAX_SCHEDULE_VALUE:,} - fix these rows: {shown}",
            field="hardware_items",
        )


def finalize_import_session(
    session: Session,
    input_data: dict,
    *,
    created_by: str = SCHEDULE_IMPORT_ACTOR,
) -> dict:
    """Finalize an import session: attach openings/POs/PRs/SAR to an existing project atomically.

    `created_by` is the display name of whoever finalized (#859), stamped as the requester on the
    shipping-out and shop-assembly requests this raises.

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
    # #1412: None means "leave the project's By Others exclusions alone" - only a PO import sends a
    # list, and an empty list is a real answer (every product moved back to UCSH). Coalescing None to
    # [] here made every shop-assembly request and schedule replace delete them all.
    excluded_items_input = input_data.get("excluded_items")
    shipping_pr_drafts = input_data.get("shipping_out_pr_drafts") or []
    include_sar = input_data.get("include_shop_assembly_request", False)
    # #493: the client's shop_assembly_request_number is deprecated and ignored. The number is
    # minted from the project's counter below.
    sar_items_input = input_data.get("shop_assembly_items") or []
    replace_schedule = bool(input_data.get("replace_schedule", False))
    # #627: the source XML file name, present only when the hardware items came from a fresh parse.
    schedule_filename = input_data.get("schedule_filename")

    # #1917: a replace drops every opening it isn't sent, so one sent none (a wrong export, a cut-off
    # file) deleted every opening with nothing ordered, wiped every unordered row and rejected every
    # pending request. A schedule with no openings is not a schedule to replace one with.
    if replace_schedule and not openings_input:
        raise ValidationError(
            "The new schedule has no openings, so it can't replace this project's schedule. "
            "Check the file is the right export.",
            field="openings",
        )
    refuse_schedule_values_too_large(hardware_items_input)

    # 1. Project lookup (must already exist), row-locked so finalizes on one project run one at a time
    # (#1156). Unlocked, two concurrent finalizes each wiped and re-inserted the AVAILABLE schedule: the
    # second's delete skipped the first's new rows and it inserted a full set on top, doubling the
    # requirement. FOR NO KEY UPDATE (key_share) serializes finalizes without blocking the KEY SHARE
    # locks that inserting rows which reference the project take, the same mode the shipment containers
    # take on it. populate_existing so the openings are read after the lock, not from a stale session.
    project_stmt = (
        select(ProjectModel)
        .options(selectinload(ProjectModel.openings))
        .where(ProjectModel.id == project_id)
        .with_for_update(key_share=True, of=ProjectModel)
        .execution_options(populate_existing=True)
    )
    project = session.scalars(project_stmt).unique().first()

    if project is None:
        raise NotFoundError(f"Project {project_id} not found")

    # #1918: the lock serializes finalizes but never noticed the schedule changed between them, so a tab
    # finalizing the schedule it loaded after someone replaced it put its stale rows back and recreated the
    # openings the newer revision dropped. The wizard sends the revision it started from (None: it expected
    # no schedule yet, revision 0); read under the lock, a moved count is refused. Omitted = not checked.
    if "expected_schedule_revision" in input_data:
        expected_revision = input_data["expected_schedule_revision"] or 0
        if expected_revision != project.schedule_revision:
            raise ConflictError(
                "The schedule changed since you opened this. Reload it and start again.",
                field="expected_schedule_revision",
            )
    # Bumped by every finalize that writes what a second open tab works from: a replace, a freshly parsed
    # file (the only kind that carries its file name), the first import, and a PO import - which sends the
    # exclusions it loaded (deleting any not listed) and rewrites unordered rows at its costs, so a stale
    # tab's would undo another's By Others marks and cost corrections. Only a request raised off the
    # schedule as it stands writes none of that, and bumping on it refused the other tab for nothing.
    if (
        replace_schedule
        or schedule_filename
        or project.schedule_revision == 0
        or po_drafts
        or excluded_items_input is not None
    ):
        project.schedule_revision += 1

    # #425: quarantine gate. This one mutation is BOTH of Start a Request's write actions - it persists
    # the schedule, and it creates the shop-assembly and shipping-out requests that reserve inventory
    # against it. A project whose GP job cannot be received against must not accumulate any of that:
    # the requests would reserve stock, the POs drafted off the schedule would be unregisterable, and
    # someone would have to unpick all of it once accounting fixed the job. Passes when the verdict is
    # null (never checked) - see require_gp_setup_ok.
    project_repository.require_gp_setup_ok(session, project.id)

    # #1343: a schedule category that is also one of the company's inventory item type codes would make
    # those rows read as catalog stock and skip the schedule check. Type creation refuses the reverse
    # (custom_items_repository._check_code_free); this is the other half. Codes are stored uppercase,
    # so the compare is too. A retired type still owns its code.
    from app.models.inventory_item_type import InventoryItemType

    categories = {(hi.get("hardware_category") or "").strip().upper() for hi in hardware_items_input} - {""}
    if categories:
        clashes = sorted(
            session.scalars(
                select(InventoryItemType.code).where(
                    InventoryItemType.company == project.company,
                    func.upper(InventoryItemType.code).in_(categories),
                )
            ).all()
        )
        if clashes:
            raise ValidationError(
                f"The schedule's hardware categor{'ies' if len(clashes) > 1 else 'y'} {', '.join(clashes)} "
                f"{'are' if len(clashes) > 1 else 'is'} also an inventory item type code in {project.company}. "
                "Rename the category in the schedule or the type before importing.",
                field="hardware_items",
            )

    # #627: record the source XML file name when this finalize came from a fresh parse. None on a
    # hydrate-from-persisted finalize, which re-sends the persisted items unchanged - leaving the
    # stored name untouched so it survives.
    if schedule_filename is not None:
        project.schedule_filename = schedule_filename

    # 1b. Build classification map. The wizard keys classifications by the PARSED cost, while the rows
    # it sends carry the PO step's corrected cost (#1263), so an exact (category, code, cost) match can
    # miss. Cost is a product property (#570), so a miss falls back to the product's one classification
    # - left None only when the product was given different answers at different costs.
    classification_map: dict[tuple[str, str, float], Classification] = {}
    by_product: dict[tuple[str, str], set[Classification]] = defaultdict(set)
    for c in classifications_input:
        key = (c["hardware_category"], c["product_code"], c["unit_cost"])
        classification_map[key] = Classification(c["classification"])
        by_product[(c["hardware_category"], c["product_code"])].add(classification_map[key])
    product_classification = {product: next(iter(cls)) for product, cls in by_product.items() if len(cls) == 1}

    # 1c. The project's classification list (#1443). The product owner ruled that a schedule import
    # doesn't change an existing product's Site / Shop - that is done on the Hardware Classifications
    # page - so a finalize that answers a listed product differently is refused whole, before anything is
    # written. A listed product's rows all take the list's value, whatever this finalize was given; a
    # product not yet listed takes its first value from this finalize and is appended at step 5a. Read
    # under the project lock, which the page's save takes too, so the list cannot change underneath.
    from app.repositories import classification_override_repository

    listed = classification_override_repository.listed_classifications(session, project.id)
    classification_override_repository.refuse_import_reclassifying_listed(listed, by_product)
    # A Mixed product - not listed, its rows disagree - that this finalize settles on one value is a change
    # to work already planned around it, so it is held to the override's plan (#1442): refused while a shop
    # batch for it is still being pulled, and a product leaving the shop comes off the openings still
    # waiting on a pending shop request (applied after step 5a). Planned here, before step 2 rewrites the
    # rows, so it reads what the project held; the pending shop requests are locked after the project, the
    # order set_product_classifications takes them.
    reclassification_plans = classification_override_repository.plan_import_reclassification(
        session, project.id, product_classification, listed
    )

    # #1919: a Mixed product this finalize didn't pick is on neither the list nor this finalize's picks, so
    # the unordered rows step 2 wipes came back from step 5 with no classification, and the shop composer
    # stopped counting them. #1443 ruled an import doesn't change a product's classification, so what a row
    # had is the last fallback - read before the wipe, keyed by cost the way classification_for is asked. A
    # key whose rows disagree is left out.
    stored_by_key: dict[tuple[str, str, float], set[Classification]] = defaultdict(set)
    for category, code, cost, stored in session.execute(
        select(
            HardwareItemModel.hardware_category,
            HardwareItemModel.product_code,
            HardwareItemModel.unit_cost,
            HardwareItemModel.classification,
        ).where(
            HardwareItemModel.project_id == project.id,
            HardwareItemModel.state == HardwareItemState.AVAILABLE,
            HardwareItemModel.classification.is_not(None),
        )
    ).all():
        stored_by_key[(category, code, float(cost) if cost else 0.0)].add(stored)
    stored_classification = {key: next(iter(cls)) for key, cls in stored_by_key.items() if len(cls) == 1}

    def classification_for(hardware_category: str, product_code: str, unit_cost: float):
        listed_value = listed.get((hardware_category, product_code))
        if listed_value is not None:
            return listed_value
        exact = classification_map.get((hardware_category, product_code, unit_cost))
        if exact is not None:
            return exact
        product_value = product_classification.get((hardware_category, product_code))
        if product_value is not None:
            return product_value
        return stored_classification.get((hardware_category, product_code, float(unit_cost)))

    # #1392: a product the project already has as Shop / Site can't be taken to By Others by a replace.
    # Checked here, before step 2 rewrites the rows, for the same reason.
    if excluded_items_input is not None:
        classification_override_repository.refuse_classified_into_by_others(
            session, project.id, {(ei["hardware_category"], ei["product_code"]) for ei in excluded_items_input}
        )

    # 2. Wipe AVAILABLE hardware items for this project — they are pure XML-derived rows
    # that will be regenerated from the current input. IN_PO rows (attached to prior POs, or marked
    # purchased by the SharePoint migration) are always preserved, replace_schedule included (#1123):
    # a new schedule does not change the fact that the hardware has already been ordered.
    session.execute(
        delete(HardwareItemModel).where(
            HardwareItemModel.project_id == project.id,
            HardwareItemModel.state == HardwareItemState.AVAILABLE,
        )
    )
    session.flush()

    if replace_schedule:
        # Full override of the schedule: drop openings not present in the new schedule. Ordered
        # hardware stays where it is (#1123). A row whose (opening, product, category, leaf) is still in
        # the new schedule is carried over by step 5, which only persists the unordered remainder as
        # AVAILABLE. A row the new schedule no longer has stays IN_PO on its opening, and an opening that
        # still holds ordered hardware is kept for it even when the new schedule dropped it - the order
        # is real, and the PO line and the per-opening reconcile still point at it.
        #
        # INTENTIONAL BUSINESS LOGIC - DO NOT CHANGE (product owner ruling, #1527, 2026-10-20): the match
        # is by product code, and a changed code is a different product, not a rename. A code only
        # changes in TITAN, so a revision that drops code A and adds code B reads as A removed and B
        # added, and Nexus does not offer to carry what was ordered under A over to B. A's ordered rows
        # stay on their openings and are surplus to the schedule (#1491); B arrives unordered.
        new_opening_numbers = {o["opening_number"] for o in openings_input}
        # #342: reconcile in-flight requests with the new schedule BEFORE the openings they point at
        # are deleted - drop what vanished, release the reservations it was holding, flag the rest.
        _handle_schedule_replacement(session, project, new_opening_numbers)
        ordered_opening_ids = set(
            session.scalars(
                select(HardwareItemModel.opening_id).where(HardwareItemModel.project_id == project.id).distinct()
            ).all()
        )
        # ORM-aware delete so identity map / project.openings stay consistent.
        for opening in list(project.openings):
            if opening.opening_number not in new_opening_numbers and opening.id not in ordered_opening_ids:
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

    # Units already ordered per key, so step 5 persists only the unordered remainder as AVAILABLE.
    # (After the AVAILABLE wipe above, any remaining rows are IN_PO from prior sessions.) This is a
    # quantity, not a key set (#1122): a combo a PO took only part of persisted as an IN_PO row plus an
    # AVAILABLE remainder, and skipping the whole key here dropped that remainder on the next finalize.
    # Leaf is part of the key (#311): a pair's leaf-1 and leaf-2 rows for the same product are
    # distinct HardwareItems, so the dedup must not collapse them.
    already_ordered_qty: dict[tuple[uuid.UUID, str, str, int | None], int] = defaultdict(int)
    for hi in session.scalars(select(HardwareItemModel).where(HardwareItemModel.project_id == project.id)).all():
        already_ordered_qty[(hi.opening_id, hi.product_code, hi.hardware_category, hi.leaf)] += hi.item_quantity

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
    # #1156: the units already ordered come off the pool first, keyed by opening number for the planner,
    # so a draft (a stale tab's included) can claim only what is not yet on a PO.
    opening_number_by_id = {oid: number for number, oid in opening_map.items()}
    ordered_by_number: dict[tuple[str, str, str, int | None], int] = defaultdict(int)
    for (opening_id, product_code, hardware_category, leaf), qty in already_ordered_qty.items():
        number = opening_number_by_id.get(opening_id)
        if number is not None:
            ordered_by_number[(number, product_code, hardware_category, leaf)] += qty
    per_draft_claims, remaining_by_idx = plan_po_claims(hardware_items_input, po_drafts, ordered_by_number)

    # 4. PO creation
    created_pos: list[POModel] = []
    # #1883: one outcome per draft sent, in po_drafts order - the PO it made (None when skipped) and the
    # units it asked for against the units it got - so the wizard can say which came back short.
    draft_outcomes: list[dict] = [
        {"draft_index": i, "purchase_order": None, "requested_quantity": requested, "claimed_quantity": claimed}
        for i, (requested, claimed) in enumerate(draft_claim_counts(hardware_items_input, po_drafts, per_draft_claims))
    ]
    if po_drafts:
        # Generate request_number sequence for new POs
        from app.repositories.po_repository import generate_next_request_number, request_number_prefix

        request_prefix = request_number_prefix(project.company)
        next_request_number = generate_next_request_number(session, project.company)
        next_seq = int(next_request_number[len(request_prefix) :])

        for draft_idx, po_draft in enumerate(po_drafts):
            # #640: a draft that claims nothing would persist as a PO with zero line items - a blank PO
            # that can never be registered, received or closed, and that the register shows as a live
            # request forever. The claims are the sole source of the line items built below, so an empty
            # claim list is exactly "this PO would have no lines". Skipped rather than rejected: the
            # openings, schedule and requests in the same finalize are still exactly what the user asked
            # for, and a group with nothing in it has no order to lose. Skipping before the request
            # number is minted also keeps PO-REQ-NNN gapless. The wizard drops empty groups client-side;
            # this is the server's own guard.
            if not per_draft_claims[draft_idx]:
                continue

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
            request_number = f"{request_prefix}{next_seq:03d}"
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
                # The tenant, taken from the PROJECT rather than from the caller (#637). A PO and the
                # job it is raised against always belong to one company, and the wizard is always
                # working on a project - so there is no second answer to reconcile here, and none to
                # thread down from the resolver.
                company=project.company,
                status=POStatus.DRAFT,
                notes=po_draft.get("notes"),
                # Issue #216: the PM's requested date, captured at PO-request creation.
                preferred_delivery_date=po_draft.get("preferred_delivery_date"),
                # #490: the buyer's cost-code pick, if the relay was up to offer the job's list.
                # Register still validates against GP - this is a default, not a decision.
                cost_code=(po_draft.get("cost_code") or None),
                # #737: the vendor quote the buyer typed on the draft card; Nexus-only, like #481's.
                vendor_quote_number=(po_draft.get("vendor_quote_number") or "").strip() or None,
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
                classification = classification_for(hi_data["hardware_category"], hi_data["product_code"], unit_cost)

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
                    # #850: a wizard PO is always on a project, so its lines book to the job with the
                    # draft's own cost code - the same start a hand-typed line gets in the register
                    # dialog. Left to the column default they opened unticked, and a buyer who just
                    # pressed Register sent GP non-inventoried lines with no cost code.
                    job_cost=True,
                    cost_code=po.cost_code,
                )
                session.add(poli)
                session.flush()

                # Update HardwareItems with po_line_item_id
                for hi in hw_items:
                    hi.po_line_item_id = poli.id

            created_pos.append(po)
            draft_outcomes[draft_idx]["purchase_order"] = po

    # 5. Persist the unclaimed remainder of every hardware item as AVAILABLE. #570: a combo the PO
    #    block took in full leaves nothing here; a partially-claimed combo persists what plan_po_claims
    #    left in remaining_by_idx (item_quantity = the remainder); an unreferenced combo persists in
    #    full. Units of the same (opening, product, category, leaf) already ordered in a prior session
    #    have already come off (#1122, #1156): plan_po_claims took them out of the pool before any draft
    #    claimed, so remaining_by_idx is what is still unpurchased.
    available_keys_seen: set[tuple[uuid.UUID, str, str, int | None]] = set()
    for idx, hi in enumerate(hardware_items_input):
        remaining = remaining_by_idx.get(idx, hi["item_quantity"])
        if remaining <= 0:
            continue
        opening_id = opening_map.get(hi["opening_number"])
        if opening_id is None:
            continue
        key_with_id = (opening_id, hi["product_code"], hi["hardware_category"], hi.get("leaf"))
        if key_with_id in available_keys_seen:
            continue
        available_keys_seen.add(key_with_id)

        unit_cost_val = hi.get("unit_cost") or 0.0
        classification = classification_for(hi["hardware_category"], hi["product_code"], unit_cost_val)

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

    # 5a. A classification given in this finalize holds for the whole product (#1264). The steps above
    # set it only on rows they create, so a product half on a PO from an earlier session kept its old
    # value on the surviving IN_PO rows and read mixed. Only Site/Shop arrive here; By Others is the
    # exclusion table's business and is not touched. A product given different answers at different
    # costs is left as the rows were written. A listed product on this schedule takes the list's value
    # whether or not this finalize classified it (#1443), which is the value step 1c checked it against.
    schedule_products = {(hi["hardware_category"], hi["product_code"]) for hi in hardware_items_input}
    whole_product = {
        **product_classification,
        **{product: value for product, value in listed.items() if product in schedule_products},
    }
    # One UPDATE per value rather than per product (#1890): a schedule of hundreds of products was as many
    # round trips. The products are matched against two arrays unnested side by side, not a literal
    # row-constructor IN list, which Postgres parses recursively and overflows at schedule scale (see
    # reconcile_schedule). "fetch" still writes the new value onto the rows this session holds,
    # so the steps below read them as they now are.
    products_by_value: dict[Classification, list[tuple[str, str]]] = {}
    for product, classification in whole_product.items():
        products_by_value.setdefault(classification, []).append(product)
    for classification, products in products_by_value.items():
        unnested = (
            func.unnest(
                bindparam("categories", [c for c, _ in products], type_=ARRAY(String)),
                bindparam("codes", [p for _, p in products], type_=ARRAY(String)),
            )
            .table_valued("hardware_category", "product_code")
            # AS anon(hardware_category, product_code): without the column list Postgres names neither.
            .render_derived()
        )
        pairs = select(unnested.c.hardware_category, unnested.c.product_code)
        session.execute(
            update(HardwareItemModel)
            .where(
                HardwareItemModel.project_id == project.id,
                tuple_(HardwareItemModel.hardware_category, HardwareItemModel.product_code).in_(pairs),
                or_(HardwareItemModel.classification.is_(None), HardwareItemModel.classification != classification),
            )
            .values(classification=classification)
            .execution_options(synchronize_session="fetch")
        )
    session.flush()
    # The rest of the override's plan for a Mixed product (#1442, planned at 1c): off the openings still
    # waiting on a pending shop request, and each change logged with the override page's.
    classification_override_repository.apply_import_reclassification(
        session, project.id, reclassification_plans, changed_by=created_by
    )
    # A product this finalize gave its first classification is appended to the project's list (#1443), so
    # a later schedule that drops it does not forget it. One given different answers at different costs
    # has no one value to list, a By Others product is the exclusion table's, and an answer for a product
    # with no schedule rows is about nothing the project holds, so none of those is listed.
    by_others = {(e.hardware_category, e.product_code) for e in list_excluded_items(session, project.id)}
    with_rows = set(
        session.execute(
            select(HardwareItemModel.hardware_category, HardwareItemModel.product_code)
            .where(HardwareItemModel.project_id == project.id)
            .distinct()
        )
        .tuples()
        .all()
    )
    classification_override_repository.write_list(
        session,
        project.id,
        {
            product: value
            for product, value in product_classification.items()
            if product in with_rows and product not in listed and product not in by_others
        },
        updated_by=created_by,
    )

    # 5b. Re-apply the SharePoint migration's purchased-marking. Since #1123 a replace_schedule keeps
    # the null-linked IN_PO rows too, so the preserved rows already cover the targets and this is
    # normally a no-op; it stays as the backstop for marks whose rows were lost before that. The
    # recorded coverage targets are marked against whatever rows this finalize just wrote. One indexed
    # SELECT on a project the migration never touched.
    from app.repositories import sharepoint_migration_repository

    sharepoint_migration_repository.reapply_migration_marks(session, project.id)

    # 5c. Units ordered past the schedule this finalize restated are surplus, not required (#1491). Run
    # after every hardware write above, the re-marking included, so it reads the rows as they now are.
    restate_beyond_schedule(session, project.id, hardware_items_input, opening_map)

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
        created_by=created_by,
        created_by_user_id=input_data.get("created_by_user_id"),
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
            created_by=created_by,
        )

    session.flush()

    return {
        "project": project,
        "purchase_orders": created_pos,
        "po_draft_outcomes": draft_outcomes,
        "shipping_out_requests": created_shipping_requests,
        "shop_assembly_request": sar,
    }


def list_excluded_items(session: Session, project_id: uuid.UUID):
    from app.models.project_excluded_item import ProjectExcludedItem as PEIModel

    return list(session.scalars(select(PEIModel).where(PEIModel.project_id == project_id)).all())
