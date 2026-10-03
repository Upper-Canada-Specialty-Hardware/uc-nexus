"""The bell shows each person their own notifications (#1111, #1112).

Before this, every signed-in user polled the newest notifications of every company and every role,
and one shared flag meant the first person to open a notification cleared it for everybody. These
tests pin the three rules that replaced that: a notification is seen only inside its project's
company, only by its audience's roles or the one person it names, and "read" is per person.
"""

import uuid

import pytest

from app.errors import NotFoundError
from app.models.enums import NotificationType
from app.models.project import Project
from app.repositories import notification_repository as repo
from app.repositories.notification_repository import MAX_NOTIFICATIONS_LIMIT, Reader
from app.services import notification_service as svc

OTHER = "TFAKE"


def _project(session, company) -> Project:
    p = Project(
        id=uuid.uuid4(),
        company=company,
        project_id=f"NT-{uuid.uuid4().hex[:8]}",
        description=f"{company} job",
        archived=False,
    )
    session.add(p)
    session.flush()
    return p


def _raise(session, project, *, role=None, user=None, message="m"):
    n = svc.create_notification(
        session,
        project.id,
        role,
        NotificationType.SHIPMENT_COMPLETED,
        message,
        recipient_user_id=user,
    )
    session.flush()
    return n


def _ids(session, reader, **kw):
    return {n.id for n, _ in repo.get_notifications(session, reader, limit=MAX_NOTIFICATIONS_LIMIT, **kw)}


def _warehouse_staff(company="TUBC", user="user_staff"):
    return Reader(user_id=user, roles=("Warehouse Staff",), scope=company)


# --- who sees what ---------------------------------------------------------------------------------


def test_a_notification_is_seen_only_inside_its_company(db_session):
    mine = _raise(db_session, _project(db_session, "TUBC"), role=svc.WAREHOUSE_RECIPIENT_ROLE)
    theirs = _raise(db_session, _project(db_session, OTHER), role=svc.WAREHOUSE_RECIPIENT_ROLE)

    seen = _ids(db_session, _warehouse_staff())

    assert mine.id in seen
    assert theirs.id not in seen


def test_an_audience_is_seen_only_by_its_roles(db_session):
    project = _project(db_session, "TUBC")
    for_warehouse = _raise(db_session, project, role=svc.WAREHOUSE_RECIPIENT_ROLE)
    for_managers = _raise(db_session, project, role=svc.WAREHOUSE_MANAGER_RECIPIENT_ROLE)
    for_po = _raise(db_session, project, role=svc.PO_RECIPIENT_ROLE)

    staff = _ids(db_session, _warehouse_staff())
    manager = _ids(db_session, Reader(user_id="user_mgr", roles=("Warehouse Manager",), scope="TUBC"))

    assert for_warehouse.id in staff and for_managers.id not in staff and for_po.id not in staff
    assert {for_warehouse.id, for_managers.id} <= manager and for_po.id not in manager


def test_a_person_targeted_notification_is_seen_only_by_that_person(db_session):
    project = _project(db_session, "TUBC")
    mine = _raise(db_session, project, user="user_staff")
    someone_elses = _raise(db_session, project, user="user_other")

    seen = _ids(db_session, _warehouse_staff())
    owner = _ids(db_session, Reader(user_id="user_owner", roles=("Tenant Owner",), scope="TUBC"))

    assert mine.id in seen and someone_elses.id not in seen
    assert mine.id not in owner, "a tenant owner sees every audience, not other people's own notices"


def test_a_tenant_owner_sees_every_audience_in_their_company(db_session):
    project = _project(db_session, "TUBC")
    raised = {_raise(db_session, project, role=audience).id for audience in svc.AUDIENCE_ROLES}

    owner = _ids(db_session, Reader(user_id="user_owner", roles=("Tenant Owner",), scope="TUBC"))

    assert raised <= owner


def test_an_admin_with_no_company_picked_sees_every_company(db_session):
    a = _raise(db_session, _project(db_session, "TUBC"), role=svc.PO_RECIPIENT_ROLE)
    b = _raise(db_session, _project(db_session, OTHER), role=svc.PO_RECIPIENT_ROLE)

    seen = _ids(db_session, Reader(user_id="user_admin", roles=("UC Nexus Admin",), scope=None))

    assert {a.id, b.id} <= seen


# --- read state is per person -----------------------------------------------------------------------


def test_one_person_reading_leaves_it_unread_for_everyone_else(db_session):
    n = _raise(db_session, _project(db_session, "TUBC"), role=svc.WAREHOUSE_RECIPIENT_ROLE)
    alice = _warehouse_staff(user="user_alice")
    bob = _warehouse_staff(user="user_bob")

    repo.mark_as_read(db_session, n.id, alice)

    assert n.id not in _ids(db_session, alice, unread_only=True)
    assert n.id in _ids(db_session, bob, unread_only=True)
    read_state = dict(repo.get_notifications(db_session, bob, limit=MAX_NOTIFICATIONS_LIMIT))
    assert read_state[n] is False


def test_marking_one_read_twice_is_harmless(db_session):
    n = _raise(db_session, _project(db_session, "TUBC"), role=svc.WAREHOUSE_RECIPIENT_ROLE)
    reader = _warehouse_staff()

    repo.mark_as_read(db_session, n.id, reader)
    repo.mark_as_read(db_session, n.id, reader)

    assert n.id not in _ids(db_session, reader, unread_only=True)


def test_a_notification_the_caller_cannot_see_reads_as_absent(db_session):
    theirs = _raise(db_session, _project(db_session, OTHER), role=svc.WAREHOUSE_RECIPIENT_ROLE)

    with pytest.raises(NotFoundError):
        repo.mark_as_read(db_session, theirs.id, _warehouse_staff())


# --- the badge count and mark all read (#1112) --------------------------------------------------------


def test_the_unread_count_counts_only_what_the_caller_can_see_and_has_not_read(db_session):
    project = _project(db_session, "TUBC")
    reader = _warehouse_staff()
    before = repo.count_unread(db_session, reader)
    first = _raise(db_session, project, role=svc.WAREHOUSE_RECIPIENT_ROLE)
    _raise(db_session, project, role=svc.WAREHOUSE_RECIPIENT_ROLE)
    _raise(db_session, project, role=svc.PO_RECIPIENT_ROLE)
    _raise(db_session, _project(db_session, OTHER), role=svc.WAREHOUSE_RECIPIENT_ROLE)

    assert repo.count_unread(db_session, reader) == before + 2
    repo.mark_as_read(db_session, first.id, reader)
    assert repo.count_unread(db_session, reader) == before + 1


def test_the_count_is_not_capped_at_99(db_session):
    project = _project(db_session, "TUBC")
    reader = _warehouse_staff()
    before = repo.count_unread(db_session, reader)
    for _ in range(120):
        _raise(db_session, project, role=svc.WAREHOUSE_RECIPIENT_ROLE)

    assert repo.count_unread(db_session, reader) == before + 120


def test_mark_all_read_clears_the_callers_whole_backlog_and_nobody_elses(db_session):
    project = _project(db_session, "TUBC")
    for _ in range(130):
        _raise(db_session, project, role=svc.WAREHOUSE_RECIPIENT_ROLE)
    alice = _warehouse_staff(user="user_alice")
    bob = _warehouse_staff(user="user_bob")
    bob_before = repo.count_unread(db_session, bob)

    marked = repo.mark_all_as_read(db_session, alice)

    assert marked >= 130
    assert repo.count_unread(db_session, alice) == 0
    assert repo.count_unread(db_session, bob) == bob_before
    assert repo.mark_all_as_read(db_session, alice) == 0


def test_mark_all_read_leaves_other_companies_alone(db_session):
    theirs = _raise(db_session, _project(db_session, OTHER), role=svc.WAREHOUSE_RECIPIENT_ROLE)
    other_reader = _warehouse_staff(company=OTHER, user="user_staff")

    repo.mark_all_as_read(db_session, _warehouse_staff(user="user_staff"))

    assert theirs.id in _ids(db_session, other_reader, unread_only=True)


def test_the_list_limit_is_capped(db_session):
    project = _project(db_session, "TUBC")
    for _ in range(MAX_NOTIFICATIONS_LIMIT + 5):
        _raise(db_session, project, role=svc.WAREHOUSE_RECIPIENT_ROLE)

    rows = repo.get_notifications(db_session, _warehouse_staff(), limit=100_000)

    assert len(rows) == MAX_NOTIFICATIONS_LIMIT


# --- writers ---------------------------------------------------------------------------------------


def test_a_notification_names_exactly_one_recipient():
    with pytest.raises(ValueError):
        svc.create_notification(None, uuid.uuid4(), None, NotificationType.SHIPMENT_COMPLETED, "m")
    with pytest.raises(ValueError):
        svc.create_notification(
            None, uuid.uuid4(), "PO", NotificationType.SHIPMENT_COMPLETED, "m", recipient_user_id="user_x"
        )


def test_an_unknown_audience_is_refused():
    with pytest.raises(ValueError):
        svc.create_notification(None, uuid.uuid4(), "Warehouse Staff", NotificationType.SHIPMENT_COMPLETED, "m")


@pytest.mark.parametrize(
    ("roles", "expected"),
    [
        (["Warehouse Staff"], ["WAREHOUSE"]),
        (["Warehouse Manager"], ["WAREHOUSE", "WAREHOUSE_MANAGER"]),
        (["Shop Assembly User"], ["SHOP_ASSEMBLY"]),
        (["Shipping Out", "PO User"], ["PO", "SHIPPING"]),
        ([], []),
        (["Tenant Owner"], None),
        (["UC Nexus Admin"], None),
    ],
)
def test_audiences_follow_the_roles(roles, expected):
    assert svc.audiences_for(roles) == expected


def test_a_pull_is_announced_to_the_module_that_asked_for_it():
    assert svc.pull_audience("SHIPPING_OUT") == svc.SHIPPING_RECIPIENT_ROLE
    assert svc.pull_audience("SHOP_ASSEMBLY") == svc.SHOP_ASSEMBLY_RECIPIENT_ROLE
