"""The shipping department's list of how a load travels (#451).

Small surface, and the tests are almost entirely about the two things that make it a *list* rather
than a free-text box: one spelling per carrier, and a retired method that still reads correctly on
the shipments it already carried.
"""

import uuid
from datetime import datetime

import pytest

from app.errors import ConflictError, NotFoundError, ValidationError
from app.models.enums import ShipmentStatus
from app.models.project import Project
from app.models.shipping import PackingSlip
from app.repositories import shipment_method_repository as methods


def _project(session) -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:8]}", description="Test")
    session.add(p)
    session.flush()
    return p


def test_created_methods_come_back_in_dropdown_order(db_session):
    methods.create_shipment_method(db_session, name="Courier", sort_order=2)
    methods.create_shipment_method(db_session, name="Our truck", sort_order=1)
    methods.create_shipment_method(db_session, name="Customer pickup", sort_order=1)

    # sort_order first, then name - so the department's most-used method leads and ties stay stable.
    assert [m.name for m in methods.get_shipment_methods(db_session)] == [
        "Customer pickup",
        "Our truck",
        "Courier",
    ]


def test_a_name_is_taken_case_insensitively(db_session):
    methods.create_shipment_method(db_session, name="Flatbed")
    with pytest.raises(ConflictError):
        methods.create_shipment_method(db_session, name="flatbed")


def test_a_blank_name_is_refused(db_session):
    with pytest.raises(ValidationError):
        methods.create_shipment_method(db_session, name="   ")


def test_names_are_trimmed(db_session):
    method = methods.create_shipment_method(db_session, name="  Our truck  ")
    assert method.name == "Our truck"


def test_retiring_keeps_the_row_and_takes_it_out_of_the_form_list(db_session):
    method = methods.create_shipment_method(db_session, name="Courier")
    methods.update_shipment_method(db_session, method.id, is_active=False)

    # The management screen still sees it, so retirement is not a one-way door...
    assert [m.name for m in methods.get_shipment_methods(db_session)] == ["Courier"]
    # ...while the Delivery Request form does not offer it.
    assert methods.get_shipment_methods(db_session, active_only=True) == []


def test_a_retired_method_can_be_brought_back(db_session):
    method = methods.create_shipment_method(db_session, name="Courier")
    methods.update_shipment_method(db_session, method.id, is_active=False)
    methods.update_shipment_method(db_session, method.id, is_active=True)
    assert [m.name for m in methods.get_shipment_methods(db_session, active_only=True)] == ["Courier"]


def test_renaming_onto_another_name_is_refused(db_session):
    methods.create_shipment_method(db_session, name="Courier")
    other = methods.create_shipment_method(db_session, name="Our truck")
    with pytest.raises(ConflictError):
        methods.update_shipment_method(db_session, other.id, name="courier")


def test_renaming_to_the_same_name_is_not_a_conflict_with_itself(db_session):
    method = methods.create_shipment_method(db_session, name="Courier")
    methods.update_shipment_method(db_session, method.id, name="Courier", sort_order=5)
    assert method.sort_order == 5


def test_only_the_fields_sent_are_changed(db_session):
    method = methods.create_shipment_method(db_session, name="Courier", sort_order=3)
    methods.update_shipment_method(db_session, method.id, is_active=False)
    assert (method.name, method.sort_order, method.is_active) == ("Courier", 3, False)


def test_renaming_does_not_touch_a_shipment_already_sent_under_the_old_name(db_session):
    # The whole reason packing_slips.shipment_method is a string and not a foreign key: a reprint is
    # the copy pulled up in a site dispute, and it has to keep saying what the driver was told.
    project = _project(db_session)
    method = methods.create_shipment_method(db_session, name="Courier")
    slip = PackingSlip(
        id=uuid.uuid4(),
        packing_slip_number=f"PS-{uuid.uuid4().hex[:8]}",
        project_id=project.id,
        shipped_by="shipper",
        shipped_at=datetime.utcnow(),
        status=ShipmentStatus.SCHEDULED,
        shipment_method=method.name,
    )
    db_session.add(slip)
    db_session.flush()

    methods.update_shipment_method(db_session, method.id, name="Overnight courier")
    db_session.refresh(slip)
    assert slip.shipment_method == "Courier"


def test_deleting_leaves_a_shipment_that_used_it_readable(db_session):
    project = _project(db_session)
    method = methods.create_shipment_method(db_session, name="Courier")
    slip = PackingSlip(
        id=uuid.uuid4(),
        packing_slip_number=f"PS-{uuid.uuid4().hex[:8]}",
        project_id=project.id,
        shipped_by="shipper",
        shipped_at=datetime.utcnow(),
        status=ShipmentStatus.SCHEDULED,
        shipment_method=method.name,
    )
    db_session.add(slip)
    db_session.flush()

    methods.delete_shipment_method(db_session, method.id)
    db_session.refresh(slip)
    assert slip.shipment_method == "Courier"
    assert methods.get_shipment_methods(db_session) == []


def test_updating_or_deleting_something_that_is_not_there(db_session):
    missing = uuid.uuid4()
    with pytest.raises(NotFoundError):
        methods.update_shipment_method(db_session, missing, name="Courier")
    with pytest.raises(NotFoundError):
        methods.delete_shipment_method(db_session, missing)
