"""The shippingStats rollup feeds the Shipping landing's pipeline gauges (#589).

The resolver-level test mirrors test_warehouse_dashboard's: it runs the real query through the real
schema and compares field-for-field against the repository dict, so a field added to ShippingStats
but dropped from the resolver's constructor fails here without the test ever being edited - the
exact gap that shipped a broken warehouse dashboard in #474.
"""

import asyncio
import uuid
from datetime import datetime

from app import auth
from app.models.enums import (
    ShipmentContainerType,
    ShipmentStatus,
    ShippingOutRequestStatus,
)
from app.models.project import Project
from app.models.shipment_container import ShipmentContainer
from app.models.shipping import PackingSlip
from app.models.shipping_out_request import ShippingOutRequest
from app.repositories import dashboard_repository, user_repository
from app.schemas import dashboard as dashboard_schema_module
from main import schema


def _make_project(session) -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:8]}", description="Test")
    session.add(p)
    session.flush()
    return p


def _slip(session, project_id, status: ShipmentStatus) -> PackingSlip:
    slip = PackingSlip(
        id=uuid.uuid4(),
        packing_slip_number=f"PS-{uuid.uuid4().hex[:8]}",
        project_id=project_id,
        shipped_by="tester",
        shipped_at=datetime.utcnow(),
        status=status,
    )
    session.add(slip)
    session.flush()
    return slip


def test_shipping_stats_count_each_pipeline_stage(db_session):
    session = db_session
    baseline = dashboard_repository.get_shipping_stats(session)
    project = _make_project(session)

    # Requests: one PENDING counts, one APPROVED must not.
    session.add(
        ShippingOutRequest(
            id=uuid.uuid4(),
            request_number=f"SR-{uuid.uuid4().hex[:8]}",
            project_id=project.id,
            status=ShippingOutRequestStatus.PENDING,
            created_by="tester",
        )
    )
    session.add(
        ShippingOutRequest(
            id=uuid.uuid4(),
            request_number=f"SR-{uuid.uuid4().hex[:8]}",
            project_id=project.id,
            status=ShippingOutRequestStatus.APPROVED,
            created_by="tester",
        )
    )

    # A shipped slip, so a shipped (closed) container has something to point at and must not count as
    # staging.
    delivered = _slip(session, project.id, ShipmentStatus.DELIVERED)

    # Containers: one open (staging) counts, one already on a slip must not.
    session.add(
        ShipmentContainer(
            id=uuid.uuid4(),
            project_id=project.id,
            container_type=ShipmentContainerType.SKID,
            name="Skid 1",
            packing_slip_id=None,
            created_by="tester",
        )
    )
    session.add(
        ShipmentContainer(
            id=uuid.uuid4(),
            project_id=project.id,
            container_type=ShipmentContainerType.BOX,
            name="Box 1",
            packing_slip_id=delivered.id,
            created_by="tester",
        )
    )

    # Shipments: one SCHEDULED, one PICKED_UP; the DELIVERED one above counts toward neither.
    _slip(session, project.id, ShipmentStatus.SCHEDULED)
    _slip(session, project.id, ShipmentStatus.PICKED_UP)
    session.flush()

    stats = dashboard_repository.get_shipping_stats(session)
    assert stats["pending_request_count"] == baseline["pending_request_count"] + 1
    assert stats["staging_container_count"] == baseline["staging_container_count"] + 1
    assert stats["scheduled_shipment_count"] == baseline["scheduled_shipment_count"] + 1
    assert stats["in_transit_shipment_count"] == baseline["in_transit_shipment_count"] + 1


class _FakeRequest:
    def __init__(self, token: str):
        self.headers = {"authorization": f"Bearer {token}"}


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(w.capitalize() for w in rest)


def test_the_resolver_carries_every_field_the_repository_returns(db_session, monkeypatch):
    monkeypatch.setattr(auth, "verify_clerk_token", lambda token: {"sub": "u_shipping"})
    monkeypatch.setattr(user_repository, "get_user_roles", lambda user_id: [])

    class _BorrowedSession:
        def __enter__(self):
            return db_session

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(dashboard_schema_module, "SessionLocal", _BorrowedSession)

    field_names = list(schema._schema.type_map["ShippingStats"].fields)
    query = f"query {{ shippingStats {{ {' '.join(field_names)} }} }}"
    result = asyncio.run(schema.execute(query, context_value={"request": _FakeRequest("tok")}))

    assert result.errors is None, result.errors
    expected = dashboard_repository.get_shipping_stats(db_session)
    assert result.data["shippingStats"] == {_camel(k): v for k, v in expected.items()}
