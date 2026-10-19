"""Shipment loads: the truck trip packing slips ride on (#1720).

What is pinned here is what people will say out loud and plan around: the name a load gets, that a
second load the same day does not take the first one's name, and which loads a new slip may join.
"""

import uuid
from datetime import date

import pytest

from app.errors import InvalidStateTransitionError, ValidationError
from app.models.enums import PullRequestSource, PullRequestStatus, ShipmentStatus
from app.models.project import Project
from app.models.pull_request import PullRequest, PullRequestItem
from app.models.shipment_load import ShipmentLoad
from app.repositories import shipment_containers as containers
from app.repositories import shipment_loads, shipping_repository
from app.services.gp_window import local_today


def _project(session, *, number=None, company="TUBC") -> Project:
    p = Project(
        id=uuid.uuid4(),
        project_id=number or f"P{uuid.uuid4().hex[:8]}",
        description="Test",
        company=company,
    )
    session.add(p)
    session.flush()
    return p


def _staged(session, project, qty=4):
    pr = PullRequest(
        id=uuid.uuid4(),
        request_number=f"SOR-{uuid.uuid4().hex[:6]}",
        project_id=project.id,
        source=PullRequestSource.SHIPPING_OUT,
        status=PullRequestStatus.COMPLETED,
        requested_by="tester",
    )
    session.add(pr)
    session.flush()
    session.add(
        PullRequestItem(
            id=uuid.uuid4(),
            pull_request_id=pr.id,
            opening_number="101",
            hardware_category="HINGE",
            product_code="HG-100",
            requested_quantity=qty,
        )
    )
    session.flush()


def _ship(session, project, *, load_id=None, pickup=None, qty=1):
    """Stage `qty`, load it on a fresh skid and confirm it."""
    _staged(session, project, qty)
    skid = containers.create_container(
        session, project.id, container_type="SKID", name=f"Skid {uuid.uuid4().hex[:4]}", created_by="tester"
    )
    containers.set_container_items(
        session,
        skid.id,
        [{"opening_number": "101", "hardware_category": "HINGE", "product_code": "HG-100", "quantity": qty}],
    )
    return containers.confirm_shipment_from_containers(
        session,
        project.id,
        [skid.id],
        shipped_by="tester",
        details={"pickup_date": pickup} if pickup else None,
        load_id=load_id,
    )


def test_a_confirm_starts_a_load_named_for_the_project_and_today(db_session):
    project = _project(db_session)
    slip = _ship(db_session, project)
    assert slip.load is not None
    assert slip.load.load_number == f"{project.project_id}-{local_today():%m%d%Y}"
    assert slip.load.lead_project_id == project.id


def test_the_pickup_date_names_the_load(db_session):
    project = _project(db_session)
    slip = _ship(db_session, project, pickup=date(2026, 10, 15))
    assert slip.load.load_number == f"{project.project_id}-10152026"
    assert slip.load.ship_date == date(2026, 10, 15)


def test_a_second_load_the_same_day_is_suffixed(db_session):
    project = _project(db_session)
    day = date(2026, 10, 15)
    first = _ship(db_session, project, pickup=day)
    second = _ship(db_session, project, pickup=day)
    third = _ship(db_session, project, pickup=day)
    base = f"{project.project_id}-10152026"
    assert [first.load.load_number, second.load.load_number, third.load.load_number] == [
        base,
        f"{base}-2",
        f"{base}-3",
    ]


def test_another_projects_slip_joins_a_load_and_the_picker_lists_both(db_session):
    lead = _project(db_session)
    other = _project(db_session)
    first = _ship(db_session, lead)
    second = _ship(db_session, other, load_id=first.load_id)
    assert second.load_id == first.load_id
    assert second.load.load_number == first.load.load_number

    listed = {load.id: load for load in shipment_loads.joinable_loads(db_session, "TUBC")}
    assert {s.id for s in listed[first.load_id].slips} == {first.id, second.id}


def test_a_load_with_a_slip_picked_up_cannot_be_joined(db_session):
    project = _project(db_session)
    first = _ship(db_session, project)
    shipping_repository.mark_shipment_picked_up(db_session, first.id, "driver")
    db_session.flush()
    assert first.load_id not in {load.id for load in shipment_loads.joinable_loads(db_session, "TUBC")}
    with pytest.raises(InvalidStateTransitionError, match="left the dock"):
        _ship(db_session, project, load_id=first.load_id)


def test_a_load_whose_only_slip_was_cancelled_cannot_be_joined(db_session):
    project = _project(db_session)
    first = _ship(db_session, project)
    first.status = ShipmentStatus.CANCELLED
    db_session.flush()
    assert first.load_id not in {load.id for load in shipment_loads.joinable_loads(db_session, "TUBC")}


def test_another_companys_load_is_refused(db_session):
    ours = _project(db_session, company="TUBC")
    theirs = _project(db_session, company="UBC")
    first = _ship(db_session, theirs)
    with pytest.raises(ValidationError, match="another company"):
        _ship(db_session, ours, load_id=first.load_id)
    assert first.load_id not in {load.id for load in shipment_loads.joinable_loads(db_session, "TUBC")}


def test_a_demo_load_is_marked_so_it_never_takes_a_real_number():
    assert shipment_loads.load_number_base("22713", date(2026, 10, 15), "DEMO") == "D-22713-10152026"
    assert shipment_loads.load_number_base("22713", date(2026, 10, 15), "UBC") == "22713-10152026"


# --- moving a slip between loads (#1723) --------------------------------------------------------


def test_a_slip_moves_onto_another_load_and_its_empty_load_goes(db_session):
    lead = _project(db_session)
    other = _project(db_session)
    first = _ship(db_session, lead)
    second = _ship(db_session, other)
    old_load_id = second.load_id

    shipment_loads.move_slip_to_load(db_session, second, first.load_id, "tester")
    assert second.load_id == first.load_id
    assert db_session.get(ShipmentLoad, old_load_id) is None


def test_a_slip_moves_off_a_shared_load_onto_a_new_one(db_session):
    lead = _project(db_session)
    other = _project(db_session)
    first = _ship(db_session, lead)
    second = _ship(db_session, other, load_id=first.load_id)

    load = shipment_loads.move_slip_to_load(db_session, second, None, "tester")
    assert load.id != first.load_id
    assert load.lead_project_id == other.id
    assert db_session.get(ShipmentLoad, first.load_id) is not None


def test_a_picked_up_slip_stays_on_its_load(db_session):
    project = _project(db_session)
    first = _ship(db_session, project)
    shipping_repository.mark_shipment_picked_up(db_session, first.id, "driver")
    with pytest.raises(InvalidStateTransitionError, match="stays on its load"):
        shipment_loads.move_slip_to_load(db_session, first, None, "tester")


def test_moving_onto_its_own_load_is_refused(db_session):
    project = _project(db_session)
    first = _ship(db_session, project)
    with pytest.raises(ValidationError, match="already on that load"):
        shipment_loads.move_slip_to_load(db_session, first, first.load_id, "tester")


# --- the shipments list (#1724) -----------------------------------------------------------------


def test_the_list_finds_a_shipment_by_its_load_number_and_keeps_a_load_together(db_session):
    lead = _project(db_session)
    other = _project(db_session)
    first = _ship(db_session, lead, pickup=date(2026, 10, 15))
    alone = _ship(db_session, lead, pickup=date(2026, 10, 16))
    joined = _ship(db_session, other, load_id=first.load_id)

    found = shipping_repository.list_packing_slips(db_session, search=first.load.load_number, company="TUBC")
    assert {s.id for s in found} >= {first.id, joined.id}
    assert alone.id not in {s.id for s in found}

    listed = [s.id for s in shipping_repository.list_packing_slips(db_session, company="TUBC", limit=200)]
    together = [listed.index(first.id), listed.index(joined.id)]
    assert abs(together[0] - together[1]) == 1


# --- the driver page (#1727) --------------------------------------------------------------------


def test_a_driver_sees_their_own_shipments_still_on_the_road_next_pickup_first(db_session):
    project = _project(db_session)
    later = _ship(db_session, project, pickup=date(2026, 10, 20))
    sooner = _ship(db_session, project, pickup=date(2026, 10, 16))
    delivered = _ship(db_session, project)
    someone_elses = _ship(db_session, project)
    for slip in (later, sooner, delivered):
        slip.driver_user_id, slip.driver_name = "u_dan", "Dan Driver"
    someone_elses.driver_user_id, someone_elses.driver_name = "u_ann", "Ann Able"
    shipping_repository.mark_shipment_picked_up(db_session, delivered.id, "Dan Driver")
    shipping_repository.mark_shipment_delivered(db_session, delivered.id, "Dan Driver")
    db_session.flush()

    mine = shipping_repository.list_driver_shipments(db_session, "u_dan", company="TUBC")
    assert [s.id for s in mine] == [sooner.id, later.id]
