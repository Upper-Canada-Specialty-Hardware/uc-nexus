"""Tests for the downstream accept gate (#293 workstream B).

Start-a-Task mints request entities (ShopAssemblyRequest / ShippingOutRequest) PENDING; a signed-in
user accepts them, which mints the existing warehouse PullRequest (PENDING). These exercise the
repository layer directly (the resolvers only add require_user + commit on top).
"""

import uuid
from datetime import datetime

import pytest
from sqlalchemy import select

from app.errors import InventoryShortfallError, ValidationError
from app.models.enums import (
    OpeningItemState,
    PullRequestItemType,
    PullRequestSource,
    PullRequestStatus,
    ShippingOutRequestStatus,
    ShopAssemblyRequestStatus,
)
from app.models.inventory import InventoryLocation
from app.models.opening_item import OpeningItem
from app.models.project import Opening, Project
from app.models.pull_request import PullRequest, PullRequestItem
from app.models.shop_assembly import ShopAssemblyOpening
from app.models.stock_item import StockItem
from app.repositories import (
    import_repository,
    shipping_repository,
    shop_assembly_repository,
    warehouse_admin_repository,
)


def _make_project(session) -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:8]}", description="Test")
    session.add(p)
    session.flush()
    return p


def _seed_inventory(session, project_id, *, category="HINGE", code="HG-100", quantity):
    warehouse_id = warehouse_admin_repository.get_primary_warehouse_id(session)
    si = StockItem(
        id=uuid.uuid4(),
        warehouse_id=warehouse_id,
        hardware_category=category,
        product_code=code,
        quantity=quantity,
        deficient_quantity=0,
        received_at=datetime.utcnow(),
    )
    session.add(si)
    session.flush()
    il = InventoryLocation(
        id=uuid.uuid4(),
        project_id=project_id,
        stock_item_id=si.id,
        warehouse_id=warehouse_id,
        hardware_category=category,
        product_code=code,
        quantity=quantity,
        deficient_quantity=0,
        aisle="A",
        row="1",
        bay="1",
        received_at=datetime.utcnow(),
    )
    session.add(il)
    session.flush()
    return il


def _finalize_shop_assembly(session, project, *, code="HG-100", qty=2, opening_number="A01"):
    return import_repository.finalize_import_session(
        session,
        {
            "project_id": str(project.id),
            "openings": [{"opening_number": opening_number, "building": "B1", "floor": "F2", "location": "Lobby"}],
            "hardware_items": [],
            "include_shop_assembly_request": True,
            "shop_assembly_request_number": f"SA-{uuid.uuid4().hex[:6]}",
            "shop_assembly_openings": [
                {
                    "opening_number": opening_number,
                    "items": [{"hardware_category": "HINGE", "product_code": code, "quantity": qty}],
                },
            ],
        },
    )


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
                            "item_type": "LOOSE",
                            "opening_number": opening_number,
                            "opening_item_id": None,
                            "hardware_category": "HINGE",
                            "product_code": code,
                            "requested_quantity": qty,
                        }
                    ],
                }
            ],
        },
    )


# --- shop-assembly accept / reject -----------------------------------------------------------


def test_accept_shop_assembly_mints_pr_and_repoints_openings(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=5)
    result = _finalize_shop_assembly(db_session, project, qty=2)
    sar = result["shop_assembly_request"]
    db_session.flush()

    returned = shop_assembly_repository.accept_shop_assembly_request(db_session, sar.id, "acceptor")
    db_session.flush()

    assert returned.status == ShopAssemblyRequestStatus.APPROVED
    assert returned.approved_by == "acceptor"
    assert returned.approved_at is not None

    # A SHOP_ASSEMBLY PullRequest is minted PENDING with the SAR's request number.
    pr = db_session.scalar(select(PullRequest).where(PullRequest.request_number == sar.request_number))
    assert pr is not None
    assert pr.source == PullRequestSource.SHOP_ASSEMBLY
    assert pr.status == PullRequestStatus.PENDING
    assert pr.requested_by == "acceptor"

    # The SAR's openings are repointed at the new PR.
    sao = db_session.scalar(select(ShopAssemblyOpening).where(ShopAssemblyOpening.shop_assembly_request_id == sar.id))
    assert sao.pull_request_id == pr.id

    # One LOOSE PR item per opening item, so the unchanged warehouse approve deducts FIFO.
    pr_items = db_session.scalars(select(PullRequestItem).where(PullRequestItem.pull_request_id == pr.id)).all()
    assert len(pr_items) == 1
    assert pr_items[0].item_type == PullRequestItemType.LOOSE
    assert pr_items[0].opening_number == "A01"
    assert pr_items[0].product_code == "HG-100"
    assert pr_items[0].requested_quantity == 2


def test_accept_shop_assembly_blocks_on_shortfall(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=1)  # need 2
    result = _finalize_shop_assembly(db_session, project, qty=2)
    sar_id = result["shop_assembly_request"].id
    db_session.flush()

    with pytest.raises(InventoryShortfallError):
        shop_assembly_repository.accept_shop_assembly_request(db_session, sar_id, "acceptor")

    db_session.rollback()
    # No PR minted.
    assert (
        db_session.scalars(select(PullRequest).where(PullRequest.source == PullRequestSource.SHOP_ASSEMBLY)).all() == []
    )


def test_reject_shop_assembly_request(db_session):
    project = _make_project(db_session)
    result = _finalize_shop_assembly(db_session, project, qty=2)
    sar = result["shop_assembly_request"]
    db_session.flush()

    returned = shop_assembly_repository.reject_shop_assembly_request(db_session, sar.id, "rejector", "not needed")
    db_session.flush()

    assert returned.status == ShopAssemblyRequestStatus.REJECTED
    assert returned.rejected_by == "rejector"
    assert returned.rejection_reason == "not needed"
    assert returned.rejected_at is not None
    # No PR minted on reject.
    assert db_session.scalar(select(PullRequest).where(PullRequest.request_number == sar.request_number)) is None


# --- shipping-out accept / reject ------------------------------------------------------------


def test_accept_shipping_out_mints_pr_and_copies_items(db_session):
    project = _make_project(db_session)
    result = _finalize_shipping(db_session, project, qty=2)
    req = result["shipping_out_requests"][0]
    req_number = req.request_number
    db_session.flush()

    returned = shipping_repository.accept_shipping_out_request(db_session, req.id, "acceptor")
    db_session.flush()

    assert returned.status == ShippingOutRequestStatus.APPROVED
    assert returned.approved_by == "acceptor"
    assert returned.pull_request_id is not None

    # A SHIPPING_OUT PR is minted PENDING with the request's number and copied items.
    pr = db_session.scalar(select(PullRequest).where(PullRequest.request_number == req_number))
    assert pr is not None
    assert pr.source == PullRequestSource.SHIPPING_OUT
    assert pr.status == PullRequestStatus.PENDING
    assert returned.pull_request_id == pr.id

    pr_items = db_session.scalars(select(PullRequestItem).where(PullRequestItem.pull_request_id == pr.id)).all()
    assert len(pr_items) == 1
    assert pr_items[0].item_type == PullRequestItemType.LOOSE
    assert pr_items[0].opening_number == "A01"
    assert pr_items[0].product_code == "HG-100"
    assert pr_items[0].requested_quantity == 2


def test_reject_shipping_out_request(db_session):
    project = _make_project(db_session)
    result = _finalize_shipping(db_session, project, qty=2)
    req = result["shipping_out_requests"][0]
    req_number = req.request_number
    db_session.flush()

    returned = shipping_repository.reject_shipping_out_request(db_session, req.id, "rejector", "  cancelled  ")
    db_session.flush()

    assert returned.status == ShippingOutRequestStatus.REJECTED
    assert returned.rejected_by == "rejector"
    assert returned.rejection_reason == "cancelled"  # trimmed
    assert returned.pull_request_id is None
    assert db_session.scalar(select(PullRequest).where(PullRequest.request_number == req_number)) is None


# --- REQ-5 assembled-opening guard -----------------------------------------------------------


def test_start_task_rejects_already_assembled_opening(db_session):
    project = _make_project(db_session)
    db_session.flush()
    # Persist opening A01 first.
    import_repository.finalize_import_session(
        db_session,
        {"project_id": str(project.id), "openings": [{"opening_number": "A01"}], "hardware_items": []},
    )
    db_session.flush()
    a01 = db_session.scalar(select(Opening).where(Opening.project_id == project.id, Opening.opening_number == "A01"))

    # An assembled OpeningItem for A01 (state != SHIPPED_OUT) blocks sending it to shop assembly.
    db_session.add(
        OpeningItem(
            id=uuid.uuid4(),
            project_id=project.id,
            opening_id=a01.id,
            warehouse_id=warehouse_admin_repository.get_primary_warehouse_id(db_session),
            opening_number="A01",
            quantity=1,
            assembly_completed_at=datetime.utcnow(),
            state=OpeningItemState.IN_INVENTORY,
        )
    )
    db_session.flush()

    with pytest.raises(ValidationError) as excinfo:
        _finalize_shop_assembly(db_session, project, opening_number="A01")
    assert "A01" in excinfo.value.message
    assert "already assembled" in excinfo.value.message


def test_start_task_allows_shipped_out_opening(db_session):
    """A SHIPPED_OUT OpeningItem does NOT block a new shop-assembly task for the same opening."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=5)
    db_session.flush()
    import_repository.finalize_import_session(
        db_session,
        {"project_id": str(project.id), "openings": [{"opening_number": "A01"}], "hardware_items": []},
    )
    db_session.flush()
    a01 = db_session.scalar(select(Opening).where(Opening.project_id == project.id, Opening.opening_number == "A01"))
    db_session.add(
        OpeningItem(
            id=uuid.uuid4(),
            project_id=project.id,
            opening_id=a01.id,
            warehouse_id=warehouse_admin_repository.get_primary_warehouse_id(db_session),
            opening_number="A01",
            quantity=1,
            assembly_completed_at=datetime.utcnow(),
            state=OpeningItemState.SHIPPED_OUT,
        )
    )
    db_session.flush()

    result = _finalize_shop_assembly(db_session, project, opening_number="A01")
    db_session.flush()
    assert result["shop_assembly_request"] is not None
