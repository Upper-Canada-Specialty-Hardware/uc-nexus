import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from app.models.enums import POStatus
from app.models.purchase_order import POLineItem, PurchaseOrder
from app.models.vendor import Vendor
from app.repositories import po_repository


def _make_vendor(session, name: str = "Acme") -> Vendor:
    v = Vendor(id=uuid.uuid4(), name=f"{name}-{uuid.uuid4().hex[:6]}")
    session.add(v)
    session.flush()
    return v


def _make_po(
    session,
    *,
    vendor_id: uuid.UUID,
    status: POStatus = POStatus.DRAFT,
    deleted_at: datetime | None = None,
) -> PurchaseOrder:
    po = PurchaseOrder(
        id=uuid.uuid4(),
        request_number=f"PO-REQ-{uuid.uuid4().hex[:8]}",
        vendor_id=vendor_id,
        status=status,
        deleted_at=deleted_at,
    )
    session.add(po)
    session.flush()
    return po


def _make_line_item(
    session,
    *,
    po_id: uuid.UUID,
    product_code: str = "ABC",
    order_as: str | None = None,
    updated_at: datetime | None = None,
) -> POLineItem:
    kwargs = {
        "id": uuid.uuid4(),
        "po_id": po_id,
        "hardware_category": "HINGE",
        "product_code": product_code,
        "ordered_quantity": 1,
        "unit_cost": Decimal("1.00"),
        "order_as": order_as,
    }
    if updated_at is not None:
        kwargs["updated_at"] = updated_at
    li = POLineItem(**kwargs)
    session.add(li)
    session.flush()
    return li


def test_returns_distinct_values_ranked_recent_first(db_session):
    vendor = _make_vendor(db_session)
    po1 = _make_po(db_session, vendor_id=vendor.id)
    po2 = _make_po(db_session, vendor_id=vendor.id)
    older = datetime.utcnow() - timedelta(days=2)
    newer = datetime.utcnow()
    _make_line_item(db_session, po_id=po1.id, product_code="P1", order_as="OLD-SKU", updated_at=older)
    _make_line_item(db_session, po_id=po2.id, product_code="P1", order_as="NEW-SKU", updated_at=newer)

    result = po_repository.get_prior_order_as_values(db_session, vendor.id, ["P1"])
    assert result == {"P1": ["NEW-SKU", "OLD-SKU"]}


def test_excludes_cancelled_pos(db_session):
    vendor = _make_vendor(db_session)
    cancelled_po = _make_po(
        db_session,
        vendor_id=vendor.id,
        status=POStatus.CANCELLED,
        deleted_at=datetime.utcnow(),
    )
    _make_line_item(db_session, po_id=cancelled_po.id, product_code="P2", order_as="CANCELLED-SKU")
    assert po_repository.get_prior_order_as_values(db_session, vendor.id, ["P2"]) == {}


def test_excludes_soft_deleted_pos(db_session):
    vendor = _make_vendor(db_session)
    soft_deleted_po = _make_po(
        db_session,
        vendor_id=vendor.id,
        status=POStatus.DRAFT,
        deleted_at=datetime.utcnow(),
    )
    _make_line_item(db_session, po_id=soft_deleted_po.id, product_code="P3", order_as="DELETED-SKU")
    assert po_repository.get_prior_order_as_values(db_session, vendor.id, ["P3"]) == {}


def test_excludes_empty_and_whitespace_order_as(db_session):
    vendor = _make_vendor(db_session)
    po = _make_po(db_session, vendor_id=vendor.id)
    _make_line_item(db_session, po_id=po.id, product_code="P4", order_as=None)
    _make_line_item(db_session, po_id=po.id, product_code="P4", order_as="")
    _make_line_item(db_session, po_id=po.id, product_code="P4", order_as="   ")
    _make_line_item(db_session, po_id=po.id, product_code="P4", order_as="REAL-SKU")

    assert po_repository.get_prior_order_as_values(db_session, vendor.id, ["P4"]) == {"P4": ["REAL-SKU"]}


def test_scoped_by_vendor(db_session):
    vendor_a = _make_vendor(db_session, name="VendorA")
    vendor_b = _make_vendor(db_session, name="VendorB")
    po_a = _make_po(db_session, vendor_id=vendor_a.id)
    po_b = _make_po(db_session, vendor_id=vendor_b.id)
    _make_line_item(db_session, po_id=po_a.id, product_code="P5", order_as="A-SKU")
    _make_line_item(db_session, po_id=po_b.id, product_code="P5", order_as="B-SKU")

    assert po_repository.get_prior_order_as_values(db_session, vendor_a.id, ["P5"]) == {"P5": ["A-SKU"]}
    assert po_repository.get_prior_order_as_values(db_session, vendor_b.id, ["P5"]) == {"P5": ["B-SKU"]}


def test_dedupes_same_value_keeps_most_recent(db_session):
    vendor = _make_vendor(db_session)
    po1 = _make_po(db_session, vendor_id=vendor.id)
    po2 = _make_po(db_session, vendor_id=vendor.id)
    older = datetime.utcnow() - timedelta(days=5)
    middle = datetime.utcnow() - timedelta(days=3)
    newer = datetime.utcnow() - timedelta(days=1)
    _make_line_item(db_session, po_id=po1.id, product_code="P6", order_as="DUP", updated_at=older)
    _make_line_item(db_session, po_id=po2.id, product_code="P6", order_as="DUP", updated_at=newer)
    _make_line_item(db_session, po_id=po1.id, product_code="P6", order_as="OTHER", updated_at=middle)

    assert po_repository.get_prior_order_as_values(db_session, vendor.id, ["P6"]) == {"P6": ["DUP", "OTHER"]}


def test_buckets_by_product_code(db_session):
    vendor = _make_vendor(db_session)
    po = _make_po(db_session, vendor_id=vendor.id)
    _make_line_item(db_session, po_id=po.id, product_code="P7", order_as="P7-SKU")
    _make_line_item(db_session, po_id=po.id, product_code="P8", order_as="P8-SKU")

    result = po_repository.get_prior_order_as_values(db_session, vendor.id, ["P7", "P8"])
    assert result == {"P7": ["P7-SKU"], "P8": ["P8-SKU"]}


def test_returns_empty_for_empty_product_codes(db_session):
    vendor = _make_vendor(db_session)
    assert po_repository.get_prior_order_as_values(db_session, vendor.id, []) == {}


def test_returns_empty_for_unknown_product_code(db_session):
    vendor = _make_vendor(db_session)
    po = _make_po(db_session, vendor_id=vendor.id)
    _make_line_item(db_session, po_id=po.id, product_code="REAL", order_as="SKU")
    assert po_repository.get_prior_order_as_values(db_session, vendor.id, ["NOPE"]) == {}
