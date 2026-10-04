"""A GP sync pass and a PO registration racing for the same new GP number (#1492).

The relay creates the PO in GP and replies; the registration records GP's number in the idempotency
ledger and then persists. A sync page that read its pending-registration set before that ledger write,
and reaches the number after it, used to insert a GP-origin copy - which took the (gp_company,
po_number) key, so the registration's persist was refused on every retry and the draft never left
DRAFT. The sync now re-checks the one number before inserting, and the registration's persist clears a
bare copy of its own PO; a copy anything in Nexus refers to is still a real duplicate and is refused.
"""

import uuid

import pytest
from sqlalchemy import select

from app.errors import ValidationError
from app.models.enums import POOrigin, POStatus
from app.models.gp_write import GpWriteIdempotency
from app.models.purchase_order import POLineItem, PurchaseOrder
from app.repositories import gp_po_sync_repository as sync_repo
from app.repositories import po_repository

COMPANY = "TUBC"


def _gp_po(po_number: str) -> dict:
    """A stock PO (no job) as the relay reports it."""
    return {
        "po_number": po_number,
        "gp_status": 1,
        "vendor_id": "GPV1",
        "vendor_name": "GP Vendor",
        "doc_date": "2026-10-04",
        "modified_at": "2026-10-04T09:00:00",
        "source_table": "work",
        "lines": [
            {
                "ord": 16384,
                "item": "HINGE",
                "itemdesc": "HG-100",
                "qty": 2,
                "qty_cancelled": 0,
                "received": 0,
                "unit_cost": 10,
                "job": None,
                "line_status": 1,
                "cost_code": None,
            }
        ],
    }


def _draft(session) -> PurchaseOrder:
    return po_repository.create_po(
        session,
        line_items=[
            {
                "hardware_category": "HINGE",
                "product_code": "HG-100",
                "ordered_quantity": 2,
                "unit_cost": 10.0,
                "classification": None,
                "order_as": "ALIAS-100",
            }
        ],
        project_id=None,
        company=COMPANY,
    )


def _register(session, po: PurchaseOrder, po_number: str) -> PurchaseOrder:
    return po_repository.register_po_in_gp(
        session,
        po.id,
        gp_vendor_id="GPV1",
        vendor_name_snapshot="GP Vendor",
        po_number=po_number,
        gp_company=COMPANY,
        line_items=[
            {
                "id": str(li.id),
                "hardware_category": li.hardware_category,
                "product_code": li.product_code,
                "ordered_quantity": li.ordered_quantity,
                "unit_cost": float(li.unit_cost),
                "classification": None,
                "order_as": li.order_as or "ALIAS",
            }
            for li in po.line_items
        ],
    )


def _rows_for(session, po_number: str) -> list[PurchaseOrder]:
    return list(session.scalars(select(PurchaseOrder).where(PurchaseOrder.po_number == po_number)).all())


def test_a_sync_page_that_read_its_pending_set_before_the_ledger_write_skips_the_number(db_session):
    po_number = f"PO{uuid.uuid4().hex[:8].upper()}"
    draft = _draft(db_session)
    # The registration's ledger write lands after the page computed its (empty) pending set.
    db_session.add(
        GpWriteIdempotency(
            key=f"k-{uuid.uuid4().hex}",
            op="register_po_in_gp",
            relay_result={"po_number": po_number, "company": COMPANY},
            result_id=None,
        )
    )
    db_session.flush()

    outcome = sync_repo.upsert_mirrored_po(db_session, COMPANY, _gp_po(po_number), {}, pending_registration=frozenset())

    assert outcome == "skipped"
    assert _rows_for(db_session, po_number) == []
    registered = _register(db_session, draft, po_number)
    assert registered.status == POStatus.GP_REGISTERED
    assert registered.po_number == po_number


def test_a_registration_takes_the_place_of_the_syncs_bare_copy_of_its_po(db_session):
    po_number = f"PO{uuid.uuid4().hex[:8].upper()}"
    draft = _draft(db_session)
    # The sync got there first and mirrored the PO the relay just created.
    assert sync_repo.upsert_mirrored_po(db_session, COMPANY, _gp_po(po_number), {}) == "created"
    copy = _rows_for(db_session, po_number)[0]
    assert copy.origin == POOrigin.GP

    registered = _register(db_session, draft, po_number)
    db_session.flush()

    rows = _rows_for(db_session, po_number)
    assert [r.id for r in rows] == [draft.id]
    assert registered.status == POStatus.GP_REGISTERED
    assert db_session.scalars(select(POLineItem).where(POLineItem.po_id == copy.id)).all() == []
    # The next pass converges onto the draft by the same key instead of re-creating a copy.
    assert sync_repo.upsert_mirrored_po(db_session, COMPANY, _gp_po(po_number), {}) == "updated"
    assert [r.id for r in _rows_for(db_session, po_number)] == [draft.id]


def test_a_copy_that_already_has_a_receipt_is_still_refused(db_session):
    po_number = f"PO{uuid.uuid4().hex[:8].upper()}"
    draft = _draft(db_session)
    assert sync_repo.upsert_mirrored_po(db_session, COMPANY, _gp_po(po_number), {}) == "created"
    copy = _rows_for(db_session, po_number)[0]
    # Something in Nexus now depends on it - a real PO, not a copy to clear.
    copy.line_items[0].received_quantity = 1
    db_session.flush()

    with pytest.raises(ValidationError):
        _register(db_session, draft, po_number)
    assert copy.id in [r.id for r in _rows_for(db_session, po_number)]
