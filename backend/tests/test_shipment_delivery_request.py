"""The Delivery Request a shipment carries, and the lifecycle it travels through (#447).

A packing slip stopped being a single moment. It is now the paper form the shipping department fills
in, which outlives its own creation: written days before a truck comes, taken by the driver, signed
for on site. What these tests hold down is the part of that which is not obvious from the columns -
that the header can be emptied as well as filled, that it seals the moment the paper leaves the
building, and that the states are a ladder rather than a set of flags.

Nothing here asserts about inventory, and that is the point: the lifecycle documents the truck's
journey, not the hardware's. `confirm_shipment` is still the only thing in this file that touches
stock, and it does exactly what it did before.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

import pytest

from app.errors import InvalidStateTransitionError, ValidationError
from app.models.enums import PullRequestSource, PullRequestStatus, ShipmentStatus
from app.models.project import Project
from app.models.shipping import PackingSlip
from app.repositories import shipping_repository

# A filled-in form, one value per field, so a test that asserts on the whole header fails by name.
FULL_DETAILS = {
    "pickup_date": date(2026, 8, 3),
    "delivery_date": date(2026, 8, 5),
    "shipper_email": "shipping@example.com",
    "shipper_phone": "555-0100",
    "pickup_location": "UC Hardware\n12 Depot Rd\nToronto ON M1M 1M1",
    "shipment_method": "Our truck",
    "carrier_tag_bol": "BOL-4471",
    "weight_lbs": 812.5,
    "delivery_address": "40 Site Blvd\nMississauga ON",
    "special_instructions": "Call ahead.\nNo weekend deliveries.",
    "gate_number": "Gate 4",
    "forklift_onsite": "Yes until 3pm",
    "material_coming_back": "No",
    "site_material_included": "Yes",
    "construction_temp_keys": "Yes - 6 sets",
    "extra_frame_anchors": "No",
    "contractor_contact_name": "Dave Site",
    "contractor_contact_phone": "555-0111",
    "ucsh_contact_name": "Pat Office",
    "ucsh_contact_phone": "555-0122",
    "sales_order_number": "SO-9001",
}


def _make_project(session) -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:8]}", description="Test", company="TUBC")
    session.add(p)
    session.flush()
    return p


def _make_slip(session, project_id, *, status=ShipmentStatus.SCHEDULED, **header) -> PackingSlip:
    ps = PackingSlip(
        id=uuid.uuid4(),
        packing_slip_number=f"PS-{uuid.uuid4().hex[:8]}",
        project_id=project_id,
        shipped_by="shipper",
        shipped_at=datetime.utcnow(),
        status=status,
        **header,
    )
    session.add(ps)
    session.flush()
    return ps


def _stage(session, project_id, *, qty=1, opening="DR1"):
    """Put stock in the staging pool the confirm draws from: a COMPLETED shipping-out pull."""
    from app.models.pull_request import PullRequest, PullRequestItem

    pr = PullRequest(
        id=uuid.uuid4(),
        request_number=f"SOR-{uuid.uuid4().hex[:6]}",
        project_id=project_id,
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
            opening_number=opening,
            hardware_category="HINGE",
            product_code="HG-100",
            requested_quantity=qty,
        )
    )
    session.flush()


def _shipped_line(**placement) -> dict:
    return {
        "opening_number": "DR1",
        "hardware_category": "HINGE",
        "product_code": "HG-100",
        "quantity": 1,
        **placement,
    }


def _header(ps) -> dict:
    return {field: getattr(ps, field) for field in shipping_repository.DELIVERY_REQUEST_FIELDS}


def _round_trip(session, ps) -> None:
    """Push the write to Postgres and forget everything in memory, so what is asserted on next is
    what the database actually holds rather than what was assigned to the object."""
    session.flush()
    session.expire(ps)


# --- confirm ------------------------------------------------------------------------------------


def test_confirm_shipment_starts_scheduled_carrying_its_delivery_request(db_session):
    """A slip is born SCHEDULED with the form the shipping department filled in already on it.

    SCHEDULED rather than shipped-and-done because the paper is written before the truck arrives -
    the whole reason the header is editable at all is that there is a window between cutting the
    Delivery Request and anyone collecting it."""
    project = _make_project(db_session)
    _stage(db_session, project.id)

    slip = shipping_repository.confirm_shipment(
        db_session,
        project_id=project.id,
        shipped_by="shipper",
        items=[_shipped_line()],
        details=FULL_DETAILS,
    )
    _round_trip(db_session, slip)

    assert slip.status == ShipmentStatus.SCHEDULED
    assert (slip.picked_up_at, slip.picked_up_by, slip.delivered_at, slip.delivered_by) == (None, None, None, None)
    stored = _header(slip)
    assert stored.pop("weight_lbs") == Decimal("812.50")
    assert stored == {k: v for k, v in FULL_DETAILS.items() if k != "weight_lbs"}


def test_confirm_shipment_takes_no_delivery_request_at_all(db_session):
    """Every header field is optional, and a shipment with none of them is a valid shipment.

    The form is filled in against whatever the site has told the shipping department. Refusing to
    let hardware leave because nobody knew the gate number would be paperwork blocking a truck."""
    project = _make_project(db_session)
    _stage(db_session, project.id)

    slip = shipping_repository.confirm_shipment(
        db_session,
        project_id=project.id,
        shipped_by="shipper",
        items=[_shipped_line()],
    )
    _round_trip(db_session, slip)

    assert slip.status == ShipmentStatus.SCHEDULED
    assert set(_header(slip).values()) == {None}


def test_confirm_shipment_snapshots_where_the_hardware_was_going(db_session):
    """The slip records the placement, not just the opening number (#452).

    The Delivery Request cut at confirm time prints building / floor / location after the opening
    number. Without these columns the reprint rebuilt its material lines from the stored items and
    dropped that suffix, so one shipment produced two different documents - and the reprint is the
    copy pulled up in a site dispute.

    Snapshotted rather than looked up at print time: the schedule row it came from can be rewritten
    by a re-upload years after the truck left, and the paper the site signed has to keep saying
    where the hardware was headed on the day it went."""
    project = _make_project(db_session)
    _stage(db_session, project.id)

    slip = shipping_repository.confirm_shipment(
        db_session,
        project_id=project.id,
        shipped_by="shipper",
        items=[_shipped_line(building="A", floor="1", location="Rm 101")],
    )
    _round_trip(db_session, slip)

    (item,) = slip.items
    assert (item.building, item.floor, item.location) == ("A", "1", "Rm 101")


# --- editing the header -------------------------------------------------------------------------


def test_update_shipment_details_rewrites_the_whole_header(db_session):
    project = _make_project(db_session)
    slip = _make_slip(db_session, project.id, gate_number="Gate 1", sales_order_number="SO-0001")

    shipping_repository.update_shipment_details(db_session, slip.id, FULL_DETAILS)
    _round_trip(db_session, slip)

    stored = _header(slip)
    assert stored.pop("weight_lbs") == Decimal("812.50")
    assert stored == {k: v for k, v in FULL_DETAILS.items() if k != "weight_lbs"}


def test_update_shipment_details_clears_a_field_sent_as_null(db_session):
    """The half of full-replace that a merge-style update could never do.

    A phone number typed against the wrong shipment has to come back off it. If an absent or null
    field meant "leave it alone", the form could be corrected but never emptied."""
    project = _make_project(db_session)
    slip = _make_slip(db_session, project.id, gate_number="Gate 1", contractor_contact_phone="555-9999")

    shipping_repository.update_shipment_details(
        db_session,
        slip.id,
        {**FULL_DETAILS, "gate_number": None, "contractor_contact_phone": "   "},
    )
    _round_trip(db_session, slip)

    assert slip.gate_number is None
    # Whitespace is not an answer either - blank has one representation, so the printed form does
    # not render an invisible one.
    assert slip.contractor_contact_phone is None
    assert slip.sales_order_number == "SO-9001"


@pytest.mark.parametrize("status", [ShipmentStatus.PICKED_UP, ShipmentStatus.DELIVERED])
def test_update_shipment_details_refused_once_the_paper_has_left(db_session, status):
    """Editable only while SCHEDULED. From the pickup onward a driver holds a printed copy, and the
    site signs that copy - a stored record that disagrees with it is worse than one with a typo."""
    project = _make_project(db_session)
    slip = _make_slip(db_session, project.id, status=status, gate_number="Gate 1")

    with pytest.raises(InvalidStateTransitionError):
        shipping_repository.update_shipment_details(db_session, slip.id, FULL_DETAILS)

    assert slip.gate_number == "Gate 1"


# --- the weight bound ---------------------------------------------------------------------------


def test_confirm_shipment_refuses_a_weight_the_column_cannot_hold(db_session):
    """weight_lbs is Numeric(10, 2), so eight digits is the ceiling. Caught in the repository because
    the alternative is a raw Postgres numeric overflow at commit, which rolls back the confirm - a
    fat-fingered weight would abort the whole shipment instead of pointing at the box it came from."""
    project = _make_project(db_session)
    _stage(db_session, project.id)

    with pytest.raises(ValidationError) as exc:
        shipping_repository.confirm_shipment(
            db_session,
            project_id=project.id,
            shipped_by="shipper",
            items=[_shipped_line()],
            details={**FULL_DETAILS, "weight_lbs": 100000000.0},
        )

    assert exc.value.field == "weight_lbs"


@pytest.mark.parametrize("weight", [100000000.0, -1.0])
def test_update_shipment_details_refuses_a_weight_out_of_range(db_session, weight):
    """Both ends. Too big overflows the column; negative is not a weight at all, and a load recorded
    at minus a ton is the kind of number that reaches a carrier's invoice."""
    project = _make_project(db_session)
    slip = _make_slip(db_session, project.id, gate_number="Gate 1")

    with pytest.raises(ValidationError) as exc:
        shipping_repository.update_shipment_details(db_session, slip.id, {**FULL_DETAILS, "weight_lbs": weight})

    assert exc.value.field == "weight_lbs"
    # Refused before anything was written, so the rest of the header is untouched.
    assert slip.gate_number == "Gate 1"


def test_the_largest_weight_the_column_holds_is_accepted(db_session):
    """The boundary is inclusive on the legal side. The check exists to stop an overflow, not to
    second-guess a heavy load, so the largest value Numeric(10, 2) can store goes through."""
    project = _make_project(db_session)
    slip = _make_slip(db_session, project.id)

    shipping_repository.update_shipment_details(db_session, slip.id, {**FULL_DETAILS, "weight_lbs": 99999999.99})
    _round_trip(db_session, slip)

    assert slip.weight_lbs == Decimal("99999999.99")


# --- the lifecycle ------------------------------------------------------------------------------


def test_mark_picked_up_stamps_who_and_when(db_session):
    project = _make_project(db_session)
    slip = _make_slip(db_session, project.id)
    before = datetime.utcnow()

    shipping_repository.mark_shipment_picked_up(db_session, slip.id, "Carrier Clerk")
    _round_trip(db_session, slip)

    assert slip.status == ShipmentStatus.PICKED_UP
    assert slip.picked_up_by == "Carrier Clerk"
    assert slip.picked_up_at is not None and slip.picked_up_at >= before
    assert (slip.delivered_at, slip.delivered_by) == (None, None)


def test_mark_picked_up_refused_when_it_already_has_been(db_session):
    """One-way, and not idempotent: a second pickup would overwrite the record of the first one with
    a later time and a different name, which is a statement about a physical event that never
    happened twice."""
    project = _make_project(db_session)
    slip = _make_slip(db_session, project.id, status=ShipmentStatus.PICKED_UP)

    with pytest.raises(InvalidStateTransitionError):
        shipping_repository.mark_shipment_picked_up(db_session, slip.id, "Someone Else")


def test_mark_delivered_stamps_who_and_when(db_session):
    project = _make_project(db_session)
    slip = _make_slip(db_session, project.id, status=ShipmentStatus.PICKED_UP)
    before = datetime.utcnow()

    shipping_repository.mark_shipment_delivered(db_session, slip.id, "Site Clerk")
    _round_trip(db_session, slip)

    assert slip.status == ShipmentStatus.DELIVERED
    assert slip.delivered_by == "Site Clerk"
    assert slip.delivered_at is not None and slip.delivered_at >= before


def test_a_scheduled_shipment_cannot_jump_straight_to_delivered(db_session):
    """The ladder is strict. A load cannot arrive somewhere it was never collected for, and allowing
    the jump would quietly lose the fact that no pickup was ever recorded."""
    project = _make_project(db_session)
    slip = _make_slip(db_session, project.id)

    with pytest.raises(InvalidStateTransitionError):
        shipping_repository.mark_shipment_delivered(db_session, slip.id, "Site Clerk")

    assert slip.status == ShipmentStatus.SCHEDULED
    assert slip.delivered_at is None


def test_a_delivered_shipment_cannot_be_delivered_again(db_session):
    project = _make_project(db_session)
    slip = _make_slip(db_session, project.id, status=ShipmentStatus.DELIVERED)

    with pytest.raises(InvalidStateTransitionError):
        shipping_repository.mark_shipment_delivered(db_session, slip.id, "Site Clerk")
