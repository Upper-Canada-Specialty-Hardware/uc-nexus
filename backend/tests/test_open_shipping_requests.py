"""The shipping requests page's open view lists what the project page's tile counts (#1551).

The tile counts pending requests plus accepted ones whose pull is still in flight (#1197), and used to
link to the pending tab, which lists pending only - so nobody could find what it counted. The open view
lists by the same clause, so the number and the list agree."""

from sqlalchemy import update

from app.models.enums import PullRequestStatus
from app.models.pull_request import PullRequest
from app.repositories import project_repository, shipping_repository
from tests.test_accept_requests import _finalize_shipping, _make_project, _seed_inventory


def _request(session, project, opening):
    req = _finalize_shipping(session, project, qty=1, opening_number=opening)["shipping_out_requests"][0]
    session.flush()
    return req


def _set_pull_status(session, req, status):
    session.execute(update(PullRequest).where(PullRequest.id == req.pull_request_id).values(status=status))
    session.flush()


def test_the_open_view_lists_exactly_what_the_tile_counts(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)

    pending = _request(db_session, project, "A01")
    picking = _request(db_session, project, "A02")
    shipped = _request(db_session, project, "A03")
    cancelled = _request(db_session, project, "A04")
    rejected = _request(db_session, project, "A05")
    for req in (picking, shipped, cancelled):
        shipping_repository.accept_shipping_out_request(db_session, req.id, "manager")
    db_session.flush()
    _set_pull_status(db_session, picking, PullRequestStatus.IN_PROGRESS)
    _set_pull_status(db_session, shipped, PullRequestStatus.COMPLETED)
    _set_pull_status(db_session, cancelled, PullRequestStatus.CANCELLED)
    shipping_repository.reject_shipping_out_request(db_session, rejected.id, "manager", "not needed")
    db_session.flush()

    listed = shipping_repository.get_shipping_out_requests(db_session, project.id, open_only=True)
    count = project_repository.get_admin_project_detail(db_session, project.id)["open_shipping_request_count"]

    assert {r.request_number for r in listed} == {pending.request_number, picking.request_number}
    assert count == len(listed)


def test_open_only_ignores_the_status_argument(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=5)
    pending = _request(db_session, project, "A01")

    from app.models.enums import ShippingOutRequestStatus

    listed = shipping_repository.get_shipping_out_requests(
        db_session, project.id, ShippingOutRequestStatus.REJECTED, open_only=True
    )

    assert [r.id for r in listed] == [pending.id]
