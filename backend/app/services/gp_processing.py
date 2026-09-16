"""GP-PROCESSING: read one purchase order back from GP the moment GP has it, and apply GP's copy.

A PO REGISTRATION stamps only what the relay hands back - the number, the company, the vendor, the
status, the cost code and the shipping cost - and dates the PO at the moment of the push. Everything
else that GP owns arrived minutes later, on the next NEW PO CHECK or OPEN-POS SYNC, so the person who
had just registered the PO opened it and found half its values missing. This service closes that gap:
GP confirms the registration, Nexus reads that one PO straight back by number, and the mirror's own
upsert writes GP's copy onto the row before anybody looks at it.

Nothing here is a second mirror. The read is the same relay op OPEN-POS RECONCILIATION uses
(`read_pos_by_number`), and the write is `gp_po_sync_repository.upsert_mirrored_po`, so the GP-OWNED
FIELDS converge exactly as they would on any sync pass, the NEXUS-ONLY FIELDS are left alone, a NEXUS
REGISTERED LINE keeps the schedule's hardware category and product code, and the status comes from
PO STATUS FROM QUANTITIES. The only thing this adds is when it happens.

The read is NOT budgeted through gp_load.paced_call. The GP READ LIMIT bounds the scheduled passes,
which walk whole companies on a timer; this is one key, read because a person pressed a button and is
waiting on the answer, and it goes out the way every other live GP lookup does.

It lives in its own module rather than in gp_po.py, whose whole contract is pure payload-mapping
functions with no database and no relay, and rather than in gp_po_sync.py, which is the scheduled
mirror loop. This is neither: a person-driven read of one PO.
"""

import asyncio
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.errors import ConflictError, InvalidStateTransitionError, NotFoundError
from app.models.enums import POStatus
from app.models.purchase_order import PurchaseOrder
from app.repositories import gp_po_sync_repository as sync_repo
from app.services.gp_po_sync import _load_project_map
from app.services.relay_gateway import gateway as relay_gateway

logger = logging.getLogger(__name__)

# A PO that GP has not shown us yet. Its own code rather than a plain CONFLICT because the caller's
# correct response is specific: offer the read again, and say the sync fills the PO in regardless.
NOT_READY_CODE = "GP_PROCESSING_NOT_READY"


def _not_in_gp_yet(po_number: str) -> ConflictError:
    return ConflictError(
        f"GP does not show purchase order {po_number} yet. It is registered, so the PO is in GP; "
        "try again in a moment, or open it and let the next sync fill it in.",
        code=NOT_READY_CODE,
    )


def readable_po(session: Session, po_id: uuid.UUID) -> tuple[str, str]:
    """(GP company, PO number) for a PO that is ready to be read back from GP.

    Shared with the resolver so the tenant check and this check are one read rather than two, and so
    there is one statement of what "ready" means: the PO exists, GP has given it a number, and it is
    past DRAFT. A DRAFT has no GP identity at all, which is why the refusal names that rather than
    the missing number."""
    row = session.execute(
        select(PurchaseOrder.status, PurchaseOrder.po_number, PurchaseOrder.gp_company).where(PurchaseOrder.id == po_id)
    ).first()
    if row is None:
        raise NotFoundError(f"Purchase order {po_id} not found")
    if row.status == POStatus.DRAFT:
        raise InvalidStateTransitionError(
            "This purchase order is still a draft, so there is nothing in GP to read back yet."
        )
    po_number = (row.po_number or "").strip()
    company = (row.gp_company or "").strip()
    if not po_number or not company:
        raise InvalidStateTransitionError(
            "This purchase order has no GP number yet, so there is nothing in GP to read back."
        )
    return company, po_number


def _target(company: str, po_id: uuid.UUID) -> str:
    """Validate the PO and hand back the number to ask GP for. Its own short session, because the
    relay round trip that follows must not hold a database connection."""
    with SessionLocal() as session:
        po_company, po_number = readable_po(session, po_id)
    if po_company != company:
        raise InvalidStateTransitionError(f"This purchase order is in GP company {po_company}, not {company}.")
    return po_number


def _apply(company: str, po_number: str, result: dict) -> None:
    """Write GP's copy of the PO onto the row through the mirror's own upsert.

    `pending_registration` is deliberately not passed: that guard exists to stop a scheduled pass
    mirroring a number GP has minted for a registration whose persist has not committed yet, and by
    the time this runs the persist is the thing that committed.

    A PO GP reports with no lines is "skipped" by the upsert, and is the same answer to the user as a
    PO GP has not listed at all - GP has it, but not in a shape worth writing over the row yet."""
    pos = result.get("pos") or []
    missing = {str(n).strip() for n in (result.get("missing") or [])}
    if po_number in missing:
        raise _not_in_gp_yet(po_number)
    po = next((p for p in pos if (p.get("po_number") or "").strip() == po_number), None)
    if po is None:
        raise _not_in_gp_yet(po_number)

    with SessionLocal() as session:
        project_map = _load_project_map(session, company)
        action = sync_repo.upsert_mirrored_po(session, company, po, project_map)
        if action == "skipped":
            raise _not_in_gp_yet(po_number)
        session.commit()
    logger.info("gp processing: %s %s applied GP's copy (%s)", company, po_number, action)


async def run_gp_processing(company: str, po_id: uuid.UUID) -> str:
    """Read one PO back from GP by number and apply GP's copy onto it. Returns the PO number.

    Raises NotFoundError / InvalidStateTransitionError when the PO is not one that can be read back,
    a ConflictError carrying NOT_READY_CODE when GP does not show it yet, and lets the relay's own
    errors (unavailable, timeout, too old for the op, GP said no) propagate as they do for every
    other live GP lookup, so a caller can tell them apart by their codes."""
    po_number = await asyncio.to_thread(_target, company, po_id)
    result = await relay_gateway.relay_call(company, "read_pos_by_number", {"po_numbers": [po_number]})
    await asyncio.to_thread(_apply, company, po_number, result or {})
    return po_number
