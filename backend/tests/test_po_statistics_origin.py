"""The status strip counts the same origin the register shows (#1358)."""

import uuid

from app.models.enums import POOrigin, POStatus
from app.models.purchase_order import PurchaseOrder
from app.repositories import po_repository


def _po(session, origin, status=POStatus.GP_REGISTERED, company="ZORG"):
    session.add(
        PurchaseOrder(
            id=uuid.uuid4(),
            request_number=f"PO-REQ-{uuid.uuid4().hex[:6]}",
            status=status,
            origin=origin,
            company=company,
        )
    )
    session.flush()


def test_origin_narrows_the_counts(db_session):
    # A company of its own, so the counts are only this test's rows.
    _po(db_session, POOrigin.GP)
    _po(db_session, POOrigin.GP)
    _po(db_session, POOrigin.NEXUS, status=POStatus.DRAFT)

    every = po_repository.get_po_statistics(db_session, company="ZORG")
    from_gp = po_repository.get_po_statistics(db_session, company="ZORG", origin=POOrigin.GP)
    from_nexus = po_repository.get_po_statistics(db_session, company="ZORG", origin=POOrigin.NEXUS)

    assert (every["total"], every["gp_registered"], every["draft"]) == (3, 2, 1)
    assert (from_gp["total"], from_gp["gp_registered"], from_gp["draft"]) == (2, 2, 0)
    assert (from_nexus["total"], from_nexus["gp_registered"], from_nexus["draft"]) == (1, 0, 1)
