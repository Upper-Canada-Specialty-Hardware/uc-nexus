"""A PO line that came from the non-schedule item catalog, and what that means for Order As.

Order As is a hardware schedule item's field: the schedule's name for a product can differ from the
vendor's, and Order As is where that translation lives. A catalog item (#454) is already written the
way the vendor sells it, so the field does not apply - the line records which catalog entry it came
from and saves no Order As whatever the caller sends.

DB-backed (db_session). The schema half runs through the built Strawberry schema with the caller's
company stubbed, the way the other schema tests stub it (#637).
"""

import asyncio
import uuid

import pytest
from sqlalchemy import select

from app import auth
from app.models.inventory_item_type import CustomInventoryItem, InventoryItemType
from app.models.project import Project
from app.models.purchase_order import POLineItem
from app.repositories import po_repository, user_repository
from main import schema

COMPANY = "TUBC"


@pytest.fixture
def project(db_session):
    p = Project(id=uuid.uuid4(), project_id=f"J-{uuid.uuid4().hex[:6]}", description="Job", company=COMPANY)
    db_session.add(p)
    db_session.flush()
    return p


@pytest.fixture
def catalog_item(db_session):
    item_type = InventoryItemType(
        id=uuid.uuid4(),
        company=COMPANY,
        code=f"FRAME{uuid.uuid4().hex[:4].upper()}",
        name=f"Frames {uuid.uuid4().hex[:4]}",
    )
    db_session.add(item_type)
    db_session.flush()
    item = CustomInventoryItem(id=uuid.uuid4(), type_id=item_type.id, product_code="FR-101")
    db_session.add(item)
    db_session.flush()
    return item


def _line_item(**overrides) -> dict:
    base = {
        "hardware_category": "HINGE",
        "product_code": "HG-100",
        "ordered_quantity": 2,
        "unit_cost": 12.5,
        "classification": None,
        "order_as": "ML2010",
    }
    base.update(overrides)
    return base


def _lines(session, po):
    return session.scalars(select(POLineItem).where(POLineItem.po_id == po.id)).all()


def test_a_draft_line_records_the_catalog_entry_it_came_from(db_session, project, catalog_item):
    po = po_repository.create_po(
        db_session,
        line_items=[
            _line_item(
                hardware_category="FRAME",
                product_code="FR-101",
                custom_inventory_item_id=str(catalog_item.id),
            ),
            _line_item(),
        ],
        project_id=project.id,
    )
    db_session.flush()

    by_code = {li.product_code: li for li in _lines(db_session, po)}
    assert by_code["FR-101"].custom_inventory_item_id == catalog_item.id
    # A catalog line has no Order As, even though one was sent.
    assert by_code["FR-101"].order_as is None
    # The hardware schedule line keeps its own.
    assert by_code["HG-100"].custom_inventory_item_id is None
    assert by_code["HG-100"].order_as == "ML2010"


def test_registering_carries_the_catalog_entry_onto_kept_and_added_lines(db_session, project, catalog_item):
    po = po_repository.create_po(db_session, line_items=[_line_item()], project_id=project.id)
    db_session.flush()
    existing = _lines(db_session, po)[0]

    po_repository.register_po_in_gp(
        db_session,
        po.id,
        gp_vendor_id="GPV1",
        vendor_name_snapshot="GP Vendor",
        po_number=f"PO{uuid.uuid4().hex[:8].upper()}",
        gp_company=COMPANY,
        line_items=[
            # the draft's own line, turned into a catalog line in the register dialog
            _line_item(
                id=str(existing.id),
                hardware_category="FRAME",
                product_code="FR-101",
                custom_inventory_item_id=str(catalog_item.id),
            ),
            # and one added from the catalog at register time
            _line_item(
                hardware_category="FRAME",
                product_code="FR-101",
                custom_inventory_item_id=str(catalog_item.id),
            ),
        ],
    )
    db_session.flush()

    lines = _lines(db_session, po)
    assert len(lines) == 2
    assert all(li.custom_inventory_item_id == catalog_item.id for li in lines)
    assert all(li.order_as is None for li in lines)


# --- what the schema publishes -----------------------------------------------------------------------


class _FakeRequest:
    def __init__(self, token: str = "tok"):
        self.headers = {"authorization": f"Bearer {token}"}


def _context():
    return {
        "request": _FakeRequest(),
        "_auth_user_id": "u_test",
        "_auth_roles": [],
        "_auth_company": COMPANY,
    }


def _execute(query: str, variables: dict | None = None):
    return asyncio.run(schema.execute(query, variable_values=variables or {}, context_value=_context()))


@pytest.fixture
def signed_in(monkeypatch, db_session):
    from app.schemas import po as po_module

    monkeypatch.setattr(auth, "verify_clerk_token", lambda token: {"sub": "u_test"})
    monkeypatch.setattr(user_repository, "get_user_roles", lambda user_id: [])
    monkeypatch.setattr(user_repository, "get_user_company", lambda user_id: COMPANY)

    class _Borrowed:
        def __enter__(self):
            return db_session

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(po_module, "SessionLocal", _Borrowed)
    return db_session


_QUERY = "query($id: ID!){ purchaseOrder(id: $id){ lineItems { productCode customInventoryItemId orderAs } } }"


def test_the_schema_publishes_the_catalog_entry_on_the_line(signed_in, db_session, project, catalog_item):
    po = po_repository.create_po(
        db_session,
        line_items=[
            _line_item(
                hardware_category="FRAME",
                product_code="FR-101",
                custom_inventory_item_id=str(catalog_item.id),
            ),
            _line_item(),
        ],
        project_id=project.id,
    )
    db_session.flush()

    result = _execute(_QUERY, {"id": str(po.id)})

    assert result.errors is None, result.errors
    by_code = {li["productCode"]: li for li in result.data["purchaseOrder"]["lineItems"]}
    assert by_code["FR-101"]["customInventoryItemId"] == str(catalog_item.id)
    assert by_code["FR-101"]["orderAs"] is None
    assert by_code["HG-100"]["customInventoryItemId"] is None
    assert by_code["HG-100"]["orderAs"] == "ML2010"
