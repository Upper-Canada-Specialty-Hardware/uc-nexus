"""Where a shipping-out request sits on the ladder, and the note a cancelled pull leaves on it (#613).

The stage answers the same question `shop_assembly_repository.get_request_stages` does, and the
return-note the same one its `get_return_notes` does - but the two derivations diverged at #646,
because a shop-assembly request has many pulls (one per batch) and no `pull_request_id` of its own.
This file is the shipping-out half, off `app.repositories.request_return_notes`; the shop-assembly
half is in test_accept_requests.py and test_pick_flow.py. Both are read by the accept board so a
request that reappears there after a cancel explains itself instead of looking like a bug.
"""

import uuid
from datetime import datetime

from app.models.enums import PullRequestStatus, ShippingOutRequestStatus
from app.models.inventory import InventoryLocation
from app.models.project import Project
from app.models.stock_item import StockItem
from app.repositories import (
    import_repository,
    shipping_repository,
    warehouse_admin_repository,
)
from app.repositories import warehouse as warehouse_repository
from tests.pick_helpers import pick_pull


def _make_project(session) -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:8]}", description="Test", company="TUBC")
    session.add(p)
    session.flush()
    return p


def _seed_inventory(session, project_id, *, category="HINGE", code="HG-100", quantity):
    warehouse_id = warehouse_admin_repository.get_primary_warehouse_id(session)
    stock = StockItem(
        id=uuid.uuid4(),
        warehouse_id=warehouse_id,
        hardware_category=category,
        product_code=code,
        quantity=0,
        deficient_quantity=0,
        received_at=datetime.utcnow(),
    )
    session.add(stock)
    session.flush()
    il = InventoryLocation(
        id=uuid.uuid4(),
        project_id=project_id,
        stock_item_id=stock.id,
        warehouse_id=warehouse_id,
        hardware_category=category,
        product_code=code,
        quantity=quantity,
        deficient_quantity=0,
        received_at=datetime.utcnow(),
    )
    session.add(il)
    session.flush()
    return il


def _finalize_shipping(session, project, *, code="HG-100", qty=2, opening_number="A01"):
    return import_repository.finalize_import_session(
        session,
        {
            "project_id": str(project.id),
            "openings": [{"opening_number": opening_number}],
            "hardware_items": [],
            "shipping_out_pr_drafts": [
                {
                    "request_number": f"SHIP-{uuid.uuid4().hex[:6]}",
                    "requested_by": "importer",
                    "items": [
                        {
                            "opening_number": opening_number,
                            "hardware_category": "HINGE",
                            "product_code": code,
                            "requested_quantity": qty,
                        }
                    ],
                }
            ],
        },
    )


def _stage_of(session, req):
    return shipping_repository.get_request_stages(session, [req])[req.id]


def test_shipping_request_stage_walks_the_ladder(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=10)
    req = _finalize_shipping(db_session, project, qty=2)["shipping_out_requests"][0]
    db_session.flush()

    assert _stage_of(db_session, req) == "REQUESTED"  # PENDING, no pull yet

    shipping_repository.accept_shipping_out_request(db_session, req.id, "acceptor")
    db_session.flush()
    assert _stage_of(db_session, req) == "ACCEPTED"  # pull PENDING

    pr = warehouse_repository.get_pull_request_details(db_session, req.pull_request_id)
    warehouse_repository.start_pull_request_pick(db_session, pr.id, "picker")
    db_session.flush()
    assert _stage_of(db_session, req) == "PULLING"  # pull IN_PROGRESS

    pick_pull(db_session, pr.id, "picker")
    warehouse_repository.complete_pull_request(db_session, pr.id, completed_by="picker")
    db_session.flush()
    assert _stage_of(db_session, req) == "DONE"  # pull COMPLETED


def test_rejected_shipping_request_is_off_the_ladder(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=5)
    req = _finalize_shipping(db_session, project, qty=2)["shipping_out_requests"][0]
    db_session.flush()
    shipping_repository.reject_shipping_out_request(db_session, req.id, "rejector", "no")
    db_session.flush()
    assert _stage_of(db_session, req) == "REJECTED"


def test_cancel_returns_the_request_to_pending_and_keeps_its_pull_pointer(db_session):
    """The return-note keys off a PENDING request still pointing at its now-CANCELLED pull, so the
    cancel must leave that pointer in place rather than null it."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=5)
    req = _finalize_shipping(db_session, project, qty=2)["shipping_out_requests"][0]
    db_session.flush()
    shipping_repository.accept_shipping_out_request(db_session, req.id, "acceptor")
    db_session.flush()
    pr_id = req.pull_request_id
    pick_pull(db_session, pr_id, "picker")

    warehouse_repository.cancel_pull_request(db_session, pr_id, "manager", "wrong pull")
    db_session.flush()

    assert req.status == ShippingOutRequestStatus.PENDING
    assert req.pull_request_id == pr_id  # kept pointing at the cancelled pull
    cancelled = warehouse_repository.get_pull_request_details(db_session, pr_id)
    assert cancelled.status == PullRequestStatus.CANCELLED


def test_return_note_is_derived_only_for_a_returned_request(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=5)

    returned = _finalize_shipping(db_session, project, qty=2, opening_number="A01")["shipping_out_requests"][0]
    fresh = _finalize_shipping(db_session, project, qty=2, opening_number="A02")["shipping_out_requests"][0]
    db_session.flush()

    shipping_repository.accept_shipping_out_request(db_session, returned.id, "acceptor")
    db_session.flush()
    pick_pull(db_session, returned.pull_request_id, "picker")
    warehouse_repository.cancel_pull_request(db_session, returned.pull_request_id, "Alex", "wrong pull")
    db_session.flush()

    notes = shipping_repository.get_return_notes(db_session, [returned, fresh])
    assert notes[fresh.id] is None  # never accepted, never cancelled
    assert notes[returned.id] is not None
    assert "Returned to Pending" in notes[returned.id]
    assert "Alex" in notes[returned.id]
    assert "wrong pull" in notes[returned.id]
