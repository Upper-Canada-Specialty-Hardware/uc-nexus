"""The warehouse is told when a pull is created (#1391).

Accepting a shipping request and dispatching a shop assembly batch each mint a pull; each raises one
PULL_REQUEST_CREATED notice for the warehouse audience, tied to the pull. A pull discarded before anyone
worked it takes its notice with it.
"""

from sqlalchemy import select

from app.models.enums import NotificationType
from app.models.notification import Notification
from app.repositories import shipping_repository, shop_assembly_repository
from app.services import notification_service
from tests.shop_assembly_helpers import batch_request
from tests.test_accept_requests import _finalize_shipping, _finalize_shop_assembly, _make_project, _seed_inventory


def _created_notices(session, project_id):
    return session.scalars(
        select(Notification).where(
            Notification.project_id == project_id,
            Notification.type == NotificationType.PULL_REQUEST_CREATED,
        )
    ).all()


def test_accepting_a_shipping_request_tells_the_warehouse(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=5)
    req = _finalize_shipping(db_session, project, qty=2)["shipping_out_requests"][0]
    db_session.flush()

    shipping_repository.accept_shipping_out_request(db_session, req.id, "Sam Acceptor")
    db_session.flush()

    [notice] = _created_notices(db_session, project.id)
    assert notice.recipient_role == notification_service.WAREHOUSE_RECIPIENT_ROLE
    assert notice.pull_request_id == req.pull_request_id
    assert notice.message == (
        f"Pull Request {req.request_number} is waiting to be picked: shipping request accepted by Sam Acceptor."
    )


def test_dispatching_a_shop_assembly_batch_tells_the_warehouse(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=5)
    sar = _finalize_shop_assembly(db_session, project, qty=2)["shop_assembly_request"]
    db_session.flush()

    batch = batch_request(db_session, sar.id, created_by="Shop Manager")
    db_session.flush()

    [notice] = _created_notices(db_session, project.id)
    assert notice.recipient_role == notification_service.WAREHOUSE_RECIPIENT_ROLE
    assert notice.pull_request_id == batch.pull_request_id
    assert notice.message == (
        f"Pull Request {batch.batch_number} is waiting to be picked: shop assembly batch dispatched by Shop Manager."
    )


def test_a_discarded_batch_takes_its_notice_with_it(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=5)
    sar = _finalize_shop_assembly(db_session, project, qty=2)["shop_assembly_request"]
    db_session.flush()
    batch = batch_request(db_session, sar.id)
    db_session.flush()
    assert len(_created_notices(db_session, project.id)) == 1

    shop_assembly_repository.discard_shop_assembly_batch(db_session, batch.id)
    db_session.flush()

    assert _created_notices(db_session, project.id) == []


def test_a_reopened_shipping_request_takes_its_notice_with_it(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=5)
    req = _finalize_shipping(db_session, project, qty=2)["shipping_out_requests"][0]
    db_session.flush()
    shipping_repository.accept_shipping_out_request(db_session, req.id, "acceptor")
    db_session.flush()

    shipping_repository.reopen_shipping_out_request(db_session, req.id)
    db_session.flush()

    assert _created_notices(db_session, project.id) == []
