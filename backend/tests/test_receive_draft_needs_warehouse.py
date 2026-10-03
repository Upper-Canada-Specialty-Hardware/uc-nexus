"""#1344: a receive draft is refused at submission when its company has no active warehouse.

A draft with no warehouse falls back to the company's default building at approval. With no active
building at all that approval can never succeed, so the person counting is told up front instead of
the manager finding out afterwards.
"""

import uuid
from decimal import Decimal

import pytest

from app.errors import ValidationError
from app.models.enums import POStatus
from app.models.project import Project
from app.models.purchase_order import POLineItem, PurchaseOrder
from app.models.warehouse import Warehouse
from app.repositories import warehouse as warehouse_repository

from .test_receive_drafts import _lines, _packing_slip


def _po_in(session, company):
    project = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:8]}", description="T", company=company)
    session.add(project)
    session.flush()
    po = PurchaseOrder(
        id=uuid.uuid4(),
        request_number=f"REQ-{uuid.uuid4().hex[:8]}",
        project_id=project.id,
        status=POStatus.GP_REGISTERED,
        po_number=f"PO{uuid.uuid4().hex[:6]}",
        gp_company="TEST",
        vendor_name_snapshot="Acme",
        company=company,
    )
    session.add(po)
    session.flush()
    li = POLineItem(
        id=uuid.uuid4(),
        po_id=po.id,
        hardware_category="HINGE",
        product_code="HG-100",
        ordered_quantity=10,
        received_quantity=0,
        unit_cost=Decimal("1.00"),
        gp_line_ord=16384,
    )
    session.add(li)
    session.flush()
    return po, li


def _submit(session, po, li):
    return warehouse_repository.create_receive_draft(
        session,
        po.id,
        _lines(li, 3),
        "u_author",
        "Wendy Warehouse",
        packing_slip_document_id=_packing_slip(session, po).id,
    )


def test_a_company_with_no_warehouse_cannot_submit_a_receive(db_session):
    po, li = _po_in(db_session, "NOWH")

    with pytest.raises(ValidationError) as excinfo:
        _submit(db_session, po, li)

    assert excinfo.value.field == "warehouse_id"
    assert "No active warehouse" in excinfo.value.message


def test_only_inactive_warehouses_still_refuses(db_session):
    db_session.add(
        Warehouse(
            id=uuid.uuid4(),
            name=f"Retired {uuid.uuid4().hex[:6]}",
            code=f"R{uuid.uuid4().hex[:5]}",
            company="NOWH",
            is_active=False,
        )
    )
    db_session.flush()
    po, li = _po_in(db_session, "NOWH")

    with pytest.raises(ValidationError):
        _submit(db_session, po, li)


def test_a_company_with_an_active_warehouse_can_submit(db_session):
    db_session.add(
        Warehouse(
            id=uuid.uuid4(),
            name=f"Main {uuid.uuid4().hex[:6]}",
            code=f"M{uuid.uuid4().hex[:5]}",
            company="HASWH",
            is_active=True,
        )
    )
    db_session.flush()
    po, li = _po_in(db_session, "HASWH")

    draft = _submit(db_session, po, li)

    assert draft.warehouse_id is None
