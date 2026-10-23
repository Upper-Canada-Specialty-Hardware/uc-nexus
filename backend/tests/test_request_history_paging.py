"""The requests pages' finished tabs page on the server, newest first (#1888).

Shop assembly's Worked and Rejected tabs and shipping's Accepted and Rejected tabs read every request in
the status, oldest first, with all their children, on every visit. They now read a page at a time, newest
decided first, as pull history does (#1268); with no limit the live tabs keep their unpaged, oldest-first
read. Every read is narrowed to a project made fresh for the test, so rows other tests leave in a shared
database cannot leak into a page.
"""

import uuid
from datetime import datetime, timedelta

from app.models.enums import ShippingOutRequestStatus, ShopAssemblyRequestStatus
from app.models.project import Project
from app.models.shipping_out_request import ShippingOutRequest
from app.models.shop_assembly import ShopAssemblyRequest
from app.repositories import shipping_repository, shop_assembly_repository

BASE = datetime(2026, 3, 1, 9, 0, 0)


def _project(session) -> Project:
    p = Project(id=uuid.uuid4(), company="TUBC", project_id=f"RH-{uuid.uuid4().hex[:8]}", description="paging")
    session.add(p)
    session.flush()
    return p


def _shop(session, project, status, *, created, decided=None) -> ShopAssemblyRequest:
    at = BASE + timedelta(minutes=decided) if decided is not None else None
    r = ShopAssemblyRequest(
        id=uuid.uuid4(),
        request_number=f"SA-{uuid.uuid4().hex[:8]}",
        project_id=project.id,
        status=status,
        created_by="tester",
        created_at=BASE + timedelta(minutes=created),
        approved_at=at if status == ShopAssemblyRequestStatus.APPROVED else None,
        rejected_at=at if status == ShopAssemblyRequestStatus.REJECTED else None,
    )
    session.add(r)
    session.flush()
    return r


def _shipping(session, project, status, *, created, decided=None) -> ShippingOutRequest:
    at = BASE + timedelta(minutes=decided) if decided is not None else None
    r = ShippingOutRequest(
        id=uuid.uuid4(),
        request_number=f"SO-{uuid.uuid4().hex[:8]}",
        project_id=project.id,
        status=status,
        created_by="tester",
        created_at=BASE + timedelta(minutes=created),
        approved_at=at if status == ShippingOutRequestStatus.APPROVED else None,
        rejected_at=at if status == ShippingOutRequestStatus.REJECTED else None,
    )
    session.add(r)
    session.flush()
    return r


def test_worked_shop_requests_page_newest_worked_first(db_session):
    """Ordered by when each was finished with, not when it was raised: the one raised first but worked
    last leads the first page."""
    project = _project(db_session)
    approved = ShopAssemblyRequestStatus.APPROVED
    made = [_shop(db_session, project, approved, created=i, decided=10 + i).id for i in range(4)]
    late = _shop(db_session, project, approved, created=-5, decided=99).id
    newest_first = [late, *reversed(made)]

    pages = [
        shop_assembly_repository.get_shop_assembly_requests(
            db_session, project.id, approved, limit=2, offset=o, newest_first=True
        )
        for o in (0, 2, 4)
    ]

    assert [r.id for page in pages for r in page] == newest_first


def test_rejected_shop_requests_page_newest_rejected_first(db_session):
    project = _project(db_session)
    rejected = ShopAssemblyRequestStatus.REJECTED
    made = [_shop(db_session, project, rejected, created=i, decided=10 + i).id for i in range(3)]

    first = shop_assembly_repository.get_shop_assembly_requests(
        db_session, project.id, rejected, limit=2, newest_first=True
    )

    assert [r.id for r in first] == [made[2], made[1]]


def test_the_pending_shop_board_read_is_unchanged(db_session):
    """No limit keeps the Pending board's oldest-first, everything read."""
    project = _project(db_session)
    pending = ShopAssemblyRequestStatus.PENDING
    made = [_shop(db_session, project, pending, created=i).id for i in range(3)]

    board = shop_assembly_repository.get_shop_assembly_requests(db_session, project.id, pending)

    assert [r.id for r in board] == made


def test_accepted_shipping_requests_page_newest_accepted_first(db_session):
    project = _project(db_session)
    approved = ShippingOutRequestStatus.APPROVED
    made = [_shipping(db_session, project, approved, created=i, decided=10 + i).id for i in range(4)]
    late = _shipping(db_session, project, approved, created=-5, decided=99).id
    newest_first = [late, *reversed(made)]

    pages = [
        shipping_repository.get_shipping_out_requests(
            db_session, project.id, approved, limit=2, offset=o, newest_first=True
        )
        for o in (0, 2, 4)
    ]

    assert [r.id for page in pages for r in page] == newest_first


def test_the_pending_and_open_shipping_reads_are_unchanged(db_session):
    project = _project(db_session)
    pending = ShippingOutRequestStatus.PENDING
    made = [_shipping(db_session, project, pending, created=i).id for i in range(3)]

    assert [r.id for r in shipping_repository.get_shipping_out_requests(db_session, project.id, pending)] == made
    assert [r.id for r in shipping_repository.get_shipping_out_requests(db_session, project.id, open_only=True)] == made
