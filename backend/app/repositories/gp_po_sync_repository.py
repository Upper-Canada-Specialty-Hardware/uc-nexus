"""Persistence for the GP purchase-order mirror (gp-owned-po mirror).

The mirror upserts GP's own purchase orders into local rows keyed by (gp_company, po_number). It owns
only GP-derived fields; the Nexus-only overlay (documents, notes, vendor_quote_number, cost_code,
created_by_user_id, shipping/tariff) is never touched, so a Nexus-registered PO converges into its
mirror row unharmed. DRAFTs have no GP identity and are invisible to the sync.

Status past registration is derived from GP (source table + received/cancelled quantities); below that
the sync leaves the row alone, so the quote+ack VENDOR_CONFIRMED auto-transition keeps working and is
never stomped. Project attribution is optional: a PO whose job-bearing lines agree on one JOBNUMBR that
maps to a project gets that project (receives into project inventory); anything else is jobless/stock.
"""

import logging
import uuid
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from app.models.enums import HardwareItemState, POOrigin, POStatus
from app.models.gp_outbox import GpWriteOutbox
from app.models.gp_po_sync_state import GpPoSyncState
from app.models.gp_write import GpWriteIdempotency
from app.models.purchase_order import POLineItem, PurchaseOrder

logger = logging.getLogger(__name__)

# GP line status (POLNESTA / POSTATUS) is intentionally NOT trusted for the stage: its integer value
# mapping could not be verified against live GP from dev, and the received/cancelled quantities plus the
# source table (work vs posted history) answer the same question without that risk. A posted PO is
# terminal (closed, or cancelled if nothing survived); an open PO's stage follows how much has landed.

# GP-derived category fallback when a mirrored line's GP description is blank.
_GP_CATEGORY_FALLBACK = "GP"

# The Nexus-only overlay fields the mirror must never write. Listed here as the single record of the
# convergence contract; the upsert simply never assigns them.
NEXUS_ONLY_FIELDS = (
    "notes",
    "vendor_quote_number",
    "cost_code",
    "created_by_user_id",
    "shipping_cost",
    "tariff_amount",
    "request_number",
)


def _to_int_qty(value: float, *, po_number: str, ord_: int, field: str) -> int:
    """GP stores quantities as decimal; Nexus columns are integer (hardware is whole units). Round HALF
    UP - never int(round()), whose banker's rounding turns 2.5 into 2 and silently drops a unit - and
    log if a fractional value ever shows up, which would signal a UOM surprise."""
    rounded = int(Decimal(str(value or 0)).to_integral_value(rounding=ROUND_HALF_UP))
    if abs((value or 0) - rounded) > 1e-9:
        logger.warning(
            "gp po sync: fractional qty %s on %s ord %s (%s) rounded to %s", value, po_number, ord_, field, rounded
        )
    return rounded


def _net_ordered(line: dict) -> float:
    """Receivable quantity for a line: ordered minus cancelled, floored at zero."""
    return max(0.0, (line.get("qty") or 0) - (line.get("qty_cancelled") or 0))


def derive_po_stage(source_table: str, lines: list[dict]) -> POStatus:
    """The GP-derived stage for a mirrored PO. Returns one of GP_REGISTERED / PARTIALLY_RECEIVED /
    CLOSED / CANCELLED. The caller applies it only when it is PAST GP_REGISTERED (see upsert), so the
    Nexus VENDOR_CONFIRMED overlay is preserved.

    - posted history: terminal. CANCELLED if nothing survived cancellation and nothing was received,
      otherwise CLOSED.
    - open work: fully cancelled -> CANCELLED; nothing received -> GP_REGISTERED (baseline); some but
      not all received -> PARTIALLY_RECEIVED; all received -> CLOSED.
    """
    net_ordered = sum(_net_ordered(ln) for ln in lines)
    total_cancelled = sum(ln.get("qty_cancelled") or 0 for ln in lines)
    received = sum(ln.get("received") or 0 for ln in lines)
    has_lines = len(lines) > 0
    fully_cancelled = has_lines and net_ordered <= 0 and total_cancelled > 0

    if source_table == "history":
        return POStatus.CANCELLED if (fully_cancelled and received <= 0) else POStatus.CLOSED

    if fully_cancelled and received <= 0:
        return POStatus.CANCELLED
    if received <= 0:
        return POStatus.GP_REGISTERED
    if received < net_ordered:
        return POStatus.PARTIALLY_RECEIVED
    return POStatus.CLOSED


# Stages the sync is allowed to WRITE onto a row. A stage of GP_REGISTERED means "at or below
# registration"; the sync leaves the stored status alone there so a VENDOR_CONFIRMED overlay survives.
_APPLIED_STAGES = (POStatus.PARTIALLY_RECEIVED, POStatus.CLOSED, POStatus.CANCELLED)


def _match_project_id(lines: list[dict], project_map: dict[str, uuid.UUID]) -> uuid.UUID | None:
    """The project a mirrored PO belongs to, or None (jobless -> stock-pool receiving). Requires all
    job-bearing lines to agree on ONE JOBNUMBR that maps to a known project; disagreement or no job
    yields None."""
    jobs = {(ln.get("job") or "").strip() for ln in lines if (ln.get("job") or "").strip()}
    if len(jobs) != 1:
        return None
    return project_map.get(next(iter(jobs)))


def _parse_doc_date(doc_date: str | None) -> datetime | None:
    if not doc_date:
        return None
    try:
        return datetime.combine(date.fromisoformat(doc_date), datetime.min.time())
    except ValueError:
        return None


def _upsert_lines(session: Session, po: PurchaseOrder, gp_lines: list[dict], *, is_gp_origin: bool) -> None:
    """Match GP lines onto the PO's line rows by gp_line_ord. Received qty is GP's (authoritative) but
    floored at what Nexus already stored; ordered qty and unit cost are GP-owned too. product_code /
    hardware_category are written only for a GP-origin PO - a Nexus PO's lines carry the schedule's own
    categorization, which the mirror keeps. Existing lines absent from GP are left untouched rather than
    deleted, so mirrored inventory is never orphaned.

    A line GP has cancelled to nothing orderable (net <= 0, or a fractional remainder that rounds below
    one whole unit) is skipped when it is NEW - there is nothing to mirror. When it ALREADY exists it is
    ZEROED, not left at its stale ordered_quantity: a line fully cancelled in GP after first mirror would
    otherwise report phantom pending units in openPosSummary and the receive picker forever."""
    existing = {li.gp_line_ord: li for li in po.line_items if li.gp_line_ord is not None}
    for ln in gp_lines:
        ord_ = ln["ord"]
        li = existing.get(ord_)
        net = _net_ordered(ln)
        gp_received = _to_int_qty(ln.get("received") or 0, po_number=po.po_number, ord_=ord_, field="received")
        # QTYSHPPD floor: an unposted GP batch can report a lower received than a receipt Nexus already
        # booked; never let a mirror pass reduce received below the stored value, or the drop would
        # reopen the PO to double-receiving. A new line has no stored value to protect.
        received_qty = max(gp_received, li.received_quantity) if li is not None else gp_received
        unit_cost = ln.get("unit_cost") or 0
        ordered_qty = _to_int_qty(net, po_number=po.po_number, ord_=ord_, field="ordered") if net > 0 else 0

        if ordered_qty < 1:
            if li is not None:
                # Zero the outstanding while respecting ck_po_line_items_ordered_quantity_positive
                # (ordered >= 1): pin ordered to what has already been received (min 1). Pending
                # (ordered - received) is then 0 whenever anything landed; a never-received cancelled
                # line lands at ordered=1 / received=0, a single-unit residual the ck floor forces.
                li.received_quantity = received_qty
                li.ordered_quantity = max(1, received_qty)
                li.unit_cost = unit_cost
                if is_gp_origin:
                    li.product_code = (ln.get("item") or "").strip() or _GP_CATEGORY_FALLBACK
                    li.hardware_category = (ln.get("itemdesc") or "").strip() or _GP_CATEGORY_FALLBACK
            continue

        if li is None:
            li = POLineItem(
                id=uuid.uuid4(),
                po_id=po.id,
                gp_line_ord=ord_,
                product_code=(ln.get("item") or "").strip() or _GP_CATEGORY_FALLBACK,
                hardware_category=(ln.get("itemdesc") or "").strip() or _GP_CATEGORY_FALLBACK,
                ordered_quantity=ordered_qty,
                received_quantity=received_qty,
                unit_cost=unit_cost,
                classification=None,
            )
            session.add(li)
            po.line_items.append(li)
        else:
            li.ordered_quantity = ordered_qty
            li.received_quantity = received_qty
            li.unit_cost = unit_cost
            if is_gp_origin:
                li.product_code = (ln.get("item") or "").strip() or _GP_CATEGORY_FALLBACK
                li.hardware_category = (ln.get("itemdesc") or "").strip() or _GP_CATEGORY_FALLBACK


def _release_linked_hardware(session: Session, po: PurchaseOrder) -> None:
    """Release the schedule hardware a PO's lines claimed back to AVAILABLE - cancel_po's rule and what
    the repair migration 073 encodes. A cancelled PO must not keep HardwareItem rows IN_PO against it, or
    required_quantity rollups double-count and the items can never be recreated as AVAILABLE by a later
    import."""
    from app.models.hardware import HardwareItem

    line_ids = [li.id for li in po.line_items]
    if line_ids:
        session.execute(
            update(HardwareItem)
            .where(HardwareItem.po_line_item_id.in_(line_ids))
            .values(po_line_item_id=None, state=HardwareItemState.AVAILABLE)
        )


def _apply_stage(session: Session, row: PurchaseOrder, stage: POStatus, now: datetime) -> None:
    """Write a GP-derived stage past registration onto the row. A transition INTO CANCELLED carries the
    invariants a bare `row.status = CANCELLED` skipped (which cancel_po enforces and its own comment
    documents): soft-delete the row and release its linked hardware, so a dead PO stops being a live PO
    in the register / receive picker and stops double-counting required_quantity."""
    becoming_cancelled = stage == POStatus.CANCELLED and row.status != POStatus.CANCELLED
    row.status = stage
    if becoming_cancelled:
        row.deleted_at = now
        _release_linked_hardware(session, row)


def po_numbers_pending_registration(session: Session, company: str) -> frozenset[str]:
    """PO numbers GP has already minted for a Nexus registration whose local persist has NOT landed yet.
    The mirror must not race register_po_in_gp: on a relay reconnect the sync can read a just-created GP
    PO before the register persist stamps its number onto the draft, and mirroring it then inserts a
    GP-origin duplicate that both trips the (project, po_number) unique index and leaves the draft stuck
    DRAFT (retries re-hit the conflict). Skipping these numbers this pass lets the registration finish;
    the next pass mirrors the row it stamped, now found by the (company, po_number) key.

    Two sources: the idempotency ledger, whose relay_result carries GP's returned po_number until the
    persist commits its result_id; and any still-queued register write on the durable outbox."""
    pending: set[str] = set()

    for row in session.scalars(
        select(GpWriteIdempotency).where(
            GpWriteIdempotency.op == "register_po_in_gp",
            GpWriteIdempotency.result_id.is_(None),
            GpWriteIdempotency.relay_result.isnot(None),
        )
    ).all():
        result = row.relay_result or {}
        number = (result.get("po_number") or "").strip()
        if number and (result.get("company") or company) == company:
            pending.add(number)

    for row in session.scalars(
        select(GpWriteOutbox).where(
            GpWriteOutbox.op == "register_po_in_gp",
            GpWriteOutbox.status.in_(("PENDING", "IN_FLIGHT")),
            GpWriteOutbox.company == company,
        )
    ).all():
        number = ((row.payload or {}).get("po_number") or "").strip()
        if number:
            pending.add(number)

    return frozenset(pending)


def upsert_mirrored_po(
    session: Session,
    company: str,
    po: dict,
    project_map: dict[str, uuid.UUID],
    *,
    pending_registration: frozenset[str] = frozenset(),
) -> str:
    """Upsert one GP purchase order into a local row keyed by (company, po_number). Returns
    'created' | 'updated' | 'skipped'. Never touches NEXUS_ONLY_FIELDS. Caller commits."""
    po_number = (po.get("po_number") or "").strip()
    if not po_number:
        return "skipped"
    # A number GP just minted for a Nexus registration whose persist has not committed. Mirroring it now
    # would duplicate the row and wedge the registration - let the register finish, mirror it next pass.
    if po_number in pending_registration:
        return "skipped"

    lines = po.get("lines") or []
    stage = derive_po_stage(po.get("source_table") or "work", lines)
    project_id = _match_project_id(lines, project_map)
    vendor_id = (po.get("vendor_id") or "").strip() or None
    vendor_name = (po.get("vendor_name") or "").strip() or None
    ordered_at = _parse_doc_date(po.get("doc_date"))
    now = datetime.utcnow()

    row = (
        session.scalars(
            select(PurchaseOrder)
            .options(selectinload(PurchaseOrder.line_items))
            .where(PurchaseOrder.gp_company == company, PurchaseOrder.po_number == po_number)
        )
        .unique()
        .first()
    )
    if row is None:
        # Fall back to a legacy Nexus row stamped with this number before gp_company was recorded (NULL
        # company). Converging onto it here fills its company below, instead of inserting a GP-origin
        # duplicate that would trip ix_purchase_orders_(project|no_project)_po_number.
        row = (
            session.scalars(
                select(PurchaseOrder)
                .options(selectinload(PurchaseOrder.line_items))
                .where(PurchaseOrder.po_number == po_number, PurchaseOrder.gp_company.is_(None))
                .order_by(PurchaseOrder.created_at)
            )
            .unique()
            .first()
        )

    if row is None:
        # New rows start at their derived stage when past registration, else at the registration
        # baseline. A mirrored PO is never a DRAFT - it exists in GP by definition.
        status = stage if stage in _APPLIED_STAGES else POStatus.GP_REGISTERED
        row = PurchaseOrder(
            id=uuid.uuid4(),
            po_number=po_number,
            request_number=None,
            origin=POOrigin.GP,
            # The tenant (#637) and the GP company are the same value on a mirrored PO, and are still
            # two columns: `company` is never null and is what every scoped read filters on, while
            # `gp_company` stays the record of where in GP the PO actually lives.
            company=company,
            gp_company=company,
            project_id=project_id,
            gp_vendor_id=vendor_id,
            vendor_name_snapshot=vendor_name,
            status=status,
            ordered_at=ordered_at,
            gp_synced_at=now,
            # A PO GP reports as already cancelled is soft-deleted on arrival, exactly as cancel_po
            # leaves one, so it never surfaces as a live PO in the register or the receive picker.
            deleted_at=now if status == POStatus.CANCELLED else None,
        )
        session.add(row)
        session.flush()
        _upsert_lines(session, row, lines, is_gp_origin=True)
        if status == POStatus.CANCELLED:
            _release_linked_hardware(session, row)
        return "created"

    is_gp_origin = row.origin == POOrigin.GP
    # Fill a legacy NULL company so the (company, po_number) key finds this row directly next pass.
    if row.gp_company is None:
        row.gp_company = company
    # GP-owned header fields converge. Vendor is GP's authority; ordered_at reflects GP's doc date.
    row.gp_vendor_id = vendor_id
    row.vendor_name_snapshot = vendor_name
    if ordered_at is not None:
        row.ordered_at = ordered_at
    # Project attribution is write-once for a GP-origin row: fill a NULL project from the job match, but
    # never REPOINT one already set. Repointing on a JOBNUMBR edit would strand inventory received under
    # the old project and would silently revert a manual project edit on the next poll. A Nexus PO's
    # project was fixed at registration and the sync never touches it.
    if is_gp_origin and row.project_id is None and project_id is not None:
        row.project_id = project_id
    row.gp_synced_at = now
    _upsert_lines(session, row, lines, is_gp_origin=is_gp_origin)
    # Status only moves when the derived stage is past registration; otherwise the row (and any
    # VENDOR_CONFIRMED overlay) is left exactly as it is.
    if stage in _APPLIED_STAGES:
        _apply_stage(session, row, stage, now)
    return "updated"


# --- sync state --------------------------------------------------------------------------------------


def get_or_create_sync_state(session: Session, company: str) -> GpPoSyncState:
    state = session.scalars(select(GpPoSyncState).where(GpPoSyncState.company == company)).first()
    if state is None:
        state = GpPoSyncState(id=uuid.uuid4(), company=company)
        session.add(state)
        session.flush()
    return state


def advance_backfill(session: Session, company: str, *, cursor: str | None, done: bool) -> None:
    """Record backfill progress. `done` marks history fully drained (the loop then switches to
    incremental). `cursor`, when not None, stores the new keyset position; a None cursor leaves the
    stored cursor untouched - used when a page could not be fully persisted and must be re-read from
    where it already was, so a failed PO is never skipped past."""
    state = get_or_create_sync_state(session, company)
    if cursor is not None:
        state.backfill_cursor = cursor
    if done:
        state.backfill_done = True


def set_watermark(session: Session, company: str, watermark: datetime) -> None:
    state = get_or_create_sync_state(session, company)
    if state.watermark is None or watermark > state.watermark:
        state.watermark = watermark
