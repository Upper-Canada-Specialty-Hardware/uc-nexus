"""What a return gives back, what a manual line is not, and the Shipments list a page at a time (#1107).

The request composer offers each opening `owed - sent - claimed`. `sent` used to count every unit a
slip ever carried, so hardware that came back to the project - or never left, on a cancelled slip -
was never offered again, and a manual spare that shared a product code read as the opening's
hardware having shipped.
"""

import uuid

import pytest

from app.errors import ValidationError
from app.models.enums import PullRequestSource, PullRequestStatus, ReturnDisposition, ShipmentStatus
from app.models.project import Project
from app.models.pull_request import PullRequest, PullRequestItem
from app.repositories import request_composer, shipping_repository, warehouse_admin_repository
from app.schemas.converters import packing_slip_to_type

KEY = ("HINGE", "HG-100")


def _project(session) -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:8]}", description="Test", company="TUBC")
    session.add(p)
    session.flush()
    return p


def _staged(session, project, *, qty=4, opening="101"):
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
            opening_number=opening,
            hardware_category=KEY[0],
            product_code=KEY[1],
            requested_quantity=qty,
        )
    )
    session.flush()


def _ship(session, project, *, qty=4, opening="101", manual=False):
    return shipping_repository.confirm_shipment(
        session,
        project.id,
        "shipper",
        [
            {
                "opening_number": opening,
                "hardware_category": KEY[0],
                "product_code": KEY[1],
                "quantity": qty,
                "is_manual": manual,
            }
        ],
    )


def _return(session, slip, qty, disposition):
    session.flush()
    session.refresh(slip)
    shipping_repository.create_shipment_return(
        session,
        packing_slip_id=slip.id,
        warehouse_id=warehouse_admin_repository.get_primary_warehouse_id(session),
        returned_by="tester",
        reference=None,
        items=[{"packing_slip_item_id": slip.items[0].id, "quantity": qty, "disposition": disposition}],
    )
    session.flush()


def _shipped(session, project, opening="101") -> int:
    sent = request_composer._sent_quantities(session, project.id, [opening])
    return sent.get(opening, {}).get(KEY, {}).get("shipped", 0)


# --- B4: returns re-offered --------------------------------------------------------------------


def test_hardware_returned_to_the_project_is_no_longer_counted_as_sent(db_session):
    project = _project(db_session)
    _staged(db_session, project, qty=4)
    slip = _ship(db_session, project, qty=4)
    assert _shipped(db_session, project) == 4

    _return(db_session, slip, 2, ReturnDisposition.RETURN_TO_PROJECT)

    assert _shipped(db_session, project) == 2


def test_a_cancelled_slip_never_left(db_session):
    """Everything came back before pickup (#973), so the opening is owed all of it again, whatever
    the disposition."""
    project = _project(db_session)
    _staged(db_session, project, qty=4)
    slip = _ship(db_session, project, qty=4)

    _return(db_session, slip, 4, ReturnDisposition.NON_STOCK)

    assert slip.status == ShipmentStatus.CANCELLED
    assert _shipped(db_session, project) == 0


def test_a_return_into_stock_off_a_shipment_that_went_out_stays_sent(db_session):
    """The site no longer has it, but the project does not hold it either - the ruling re-offers what
    came back to the project, not what went to stock."""
    project = _project(db_session)
    _staged(db_session, project, qty=4)
    slip = _ship(db_session, project, qty=4)
    shipping_repository.mark_shipment_picked_up(db_session, slip.id, "driver")

    _return(db_session, slip, 1, ReturnDisposition.NON_STOCK)

    assert _shipped(db_session, project) == 4


# --- B5: manual lines are not the opening's hardware --------------------------------------------


def test_a_manual_line_sharing_a_product_code_is_not_coverage(db_session):
    project = _project(db_session)
    _ship(db_session, project, qty=3, manual=True)

    assert _shipped(db_session, project) == 0


# --- B6 / U4: a slip carries what came back off each line ---------------------------------------


def test_a_slip_read_carries_the_returned_quantity_per_line(db_session):
    project = _project(db_session)
    _staged(db_session, project, qty=4)
    slip = _ship(db_session, project, qty=4)
    _return(db_session, slip, 3, ReturnDisposition.RETURN_TO_PROJECT)

    read = packing_slip_to_type(shipping_repository.get_packing_slip(db_session, slip.id))

    assert [(i.quantity, i.returned_quantity) for i in read.items] == [(4, 3)]


# --- U7: the Shipments list a page at a time ----------------------------------------------------


def _slips(session, project, n):
    _staged(session, project, qty=n)
    return [_ship(session, project, qty=1) for _ in range(n)]


def test_the_list_returns_one_page_newest_first_and_counts_the_rest(db_session):
    project = _project(db_session)
    slips = _slips(db_session, project, 3)
    db_session.flush()

    page = shipping_repository.list_packing_slips(db_session, project.id, limit=2)

    assert len(page) == 2
    assert shipping_repository.count_packing_slips(db_session, project.id) == 3
    rest = shipping_repository.list_packing_slips(db_session, project.id, limit=2, offset=2)
    assert {s.id for s in page} | {s.id for s in rest} == {s.id for s in slips}


def test_the_list_searches_the_slip_number_on_the_server(db_session):
    project = _project(db_session)
    slips = _slips(db_session, project, 2)
    db_session.flush()
    wanted = slips[1].packing_slip_number

    found = shipping_repository.list_packing_slips(db_session, project.id, search=wanted)

    assert [s.packing_slip_number for s in found] == [wanted]
    assert shipping_repository.count_packing_slips(db_session, project.id, search=wanted) == 1


def test_a_search_for_a_like_wildcard_matches_it_literally(db_session):
    project = _project(db_session)
    _slips(db_session, project, 1)
    db_session.flush()

    assert shipping_repository.list_packing_slips(db_session, project.id, search="%") == []


def test_no_caller_can_ask_for_the_whole_history_at_once(db_session):
    project = _project(db_session)
    with pytest.raises(ValidationError, match="limit"):
        shipping_repository.list_packing_slips(
            db_session, project.id, limit=shipping_repository.PACKING_SLIP_PAGE_MAX + 1
        )
