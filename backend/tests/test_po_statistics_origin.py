"""The status strip counts the same origin the register shows (#1358)."""

import uuid
from datetime import datetime

from app.models.enums import POOrigin, POStatus
from app.models.purchase_order import PurchaseOrder
from app.repositories import po_repository


def _po(session, origin, status=POStatus.GP_REGISTERED, company="ZORG", deleted=False, project_id=None):
    session.add(
        PurchaseOrder(
            id=uuid.uuid4(),
            request_number=f"PO-REQ-{uuid.uuid4().hex[:6]}",
            status=status,
            origin=origin,
            company=company,
            project_id=project_id,
            deleted_at=datetime.utcnow() if deleted else None,
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


def test_the_cancelled_count_takes_in_the_soft_deleted_cancelled_pos(db_session):
    """#1886: every cancel also sets deleted_at, so the Cancelled card always read 0. A cancelled PO is
    counted on its own card, still out of Total; a soft-deleted row of any other status stays uncounted,
    and another company's cancelled PO is not this company's."""
    company = f"Z{uuid.uuid4().hex[:6]}"
    _po(db_session, POOrigin.GP, company=company)
    _po(db_session, POOrigin.GP, status=POStatus.CANCELLED, company=company, deleted=True)
    _po(db_session, POOrigin.NEXUS, status=POStatus.CANCELLED, company=company, deleted=True)
    _po(db_session, POOrigin.NEXUS, status=POStatus.DRAFT, company=company, deleted=True)
    _po(db_session, POOrigin.GP, status=POStatus.CANCELLED, company=f"{company}X", deleted=True)

    every = po_repository.get_po_statistics(db_session, company=company)
    from_gp = po_repository.get_po_statistics(db_session, company=company, origin=POOrigin.GP)

    assert (every["total"], every["gp_registered"], every["draft"], every["cancelled"]) == (1, 1, 0, 2)
    assert (from_gp["total"], from_gp["cancelled"]) == (1, 1)


def test_the_admin_project_detail_counts_the_soft_deleted_cancelled_pos(db_session):
    """#1886: the admin project detail's PO counts filtered every soft-deleted row, and every cancel sets
    deleted_at, so its Cancelled read 0. The same rule as the register's strip: a cancelled PO is counted,
    a soft-deleted row of any other status is not, and another project's cancelled PO is not this one's."""
    from app.models.project import Project
    from app.repositories import project_repository

    project, other = (
        Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:8]}", description="Test", company="ZORG")
        for _ in range(2)
    )
    db_session.add_all([project, other])
    db_session.flush()
    _po(db_session, POOrigin.GP, project_id=project.id)
    _po(db_session, POOrigin.GP, status=POStatus.CANCELLED, deleted=True, project_id=project.id)
    _po(db_session, POOrigin.NEXUS, status=POStatus.DRAFT, deleted=True, project_id=project.id)
    _po(db_session, POOrigin.GP, status=POStatus.CANCELLED, deleted=True, project_id=other.id)

    detail = project_repository.get_admin_project_detail(db_session, project.id)

    assert dict(detail["po_counts_by_status"]) == {POStatus.GP_REGISTERED: 1, POStatus.CANCELLED: 1}
