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

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.enums import POOrigin, POStatus
from app.models.gp_po_sync_state import GpPoSyncState
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
    """GP stores quantities as decimal; Nexus columns are integer (hardware is whole units). Round to
    the nearest whole and log if a fractional value ever shows up, which would signal a UOM surprise."""
    rounded = int(round(value or 0))
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
    """Match GP lines onto the PO's line rows by gp_line_ord. Received qty is always GP's (authoritative);
    ordered qty and unit cost are GP-owned too. product_code / hardware_category are written only for a
    GP-origin PO - a Nexus PO's lines carry the schedule's own categorization, which the mirror keeps.
    Cancelled-to-zero lines are skipped (nothing to order or receive). Existing lines absent from GP are
    left untouched rather than deleted, so mirrored inventory is never orphaned."""
    existing = {li.gp_line_ord: li for li in po.line_items if li.gp_line_ord is not None}
    for ln in gp_lines:
        net = _net_ordered(ln)
        if net <= 0:
            continue
        ord_ = ln["ord"]
        ordered_qty = _to_int_qty(net, po_number=po.po_number, ord_=ord_, field="ordered")
        received_qty = _to_int_qty(ln.get("received") or 0, po_number=po.po_number, ord_=ord_, field="received")
        unit_cost = ln.get("unit_cost") or 0
        li = existing.get(ord_)
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


def upsert_mirrored_po(session: Session, company: str, po: dict, project_map: dict[str, uuid.UUID]) -> str:
    """Upsert one GP purchase order into a local row keyed by (company, po_number). Returns
    'created' | 'updated' | 'skipped'. Never touches NEXUS_ONLY_FIELDS. Caller commits."""
    po_number = (po.get("po_number") or "").strip()
    if not po_number:
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
        row = PurchaseOrder(
            id=uuid.uuid4(),
            po_number=po_number,
            request_number=None,
            origin=POOrigin.GP,
            gp_company=company,
            project_id=project_id,
            gp_vendor_id=vendor_id,
            vendor_name_snapshot=vendor_name,
            # New rows start at their derived stage when past registration, else at the registration
            # baseline. A mirrored PO is never a DRAFT - it exists in GP by definition.
            status=stage if stage in _APPLIED_STAGES else POStatus.GP_REGISTERED,
            ordered_at=ordered_at,
            gp_synced_at=now,
        )
        session.add(row)
        session.flush()
        _upsert_lines(session, row, lines, is_gp_origin=True)
        return "created"

    is_gp_origin = row.origin == POOrigin.GP
    # GP-owned header fields converge. Vendor is GP's authority; ordered_at reflects GP's doc date.
    row.gp_vendor_id = vendor_id
    row.vendor_name_snapshot = vendor_name
    if ordered_at is not None:
        row.ordered_at = ordered_at
    # Project attribution is the sync's to set only for a GP-origin row. A Nexus PO's project was fixed
    # at registration and must not be re-pointed by job matching.
    if is_gp_origin:
        row.project_id = project_id
    # Status only moves when the derived stage is past registration; otherwise the row (and any
    # VENDOR_CONFIRMED overlay) is left exactly as it is.
    if stage in _APPLIED_STAGES:
        row.status = stage
    row.gp_synced_at = now
    _upsert_lines(session, row, lines, is_gp_origin=is_gp_origin)
    return "updated"


# --- sync state --------------------------------------------------------------------------------------


def get_or_create_sync_state(session: Session, company: str) -> GpPoSyncState:
    state = session.scalars(select(GpPoSyncState).where(GpPoSyncState.company == company)).first()
    if state is None:
        state = GpPoSyncState(id=uuid.uuid4(), company=company)
        session.add(state)
        session.flush()
    return state


def advance_backfill(session: Session, company: str, *, next_cursor: str | None) -> None:
    """Record backfill progress. A None next_cursor means the page came back short - history drained,
    so the backfill is done and the loop switches to incremental."""
    state = get_or_create_sync_state(session, company)
    if next_cursor is None:
        state.backfill_done = True
    else:
        state.backfill_cursor = next_cursor


def set_watermark(session: Session, company: str, watermark: datetime) -> None:
    state = get_or_create_sync_state(session, company)
    if state.watermark is None or watermark > state.watermark:
        state.watermark = watermark
