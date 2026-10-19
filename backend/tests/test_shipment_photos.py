"""Shipment photos (#1728): containers as loaded, loads as delivered.

Pinned: a photo is filed under the thing it shows - a loading photo under its container, and with it
onto the slip once the container ships; a delivery photo only under a shipment that has left the dock -
and only images are taken. Storage is stubbed; what matters is which object a row points at.
"""

import base64
import uuid

import pytest
from sqlalchemy import func, select

from app.errors import InvalidStateTransitionError, ValidationError
from app.models.enums import PullRequestSource, PullRequestStatus, ShipmentPhotoKind
from app.models.project import Project
from app.models.pull_request import PullRequest, PullRequestItem
from app.models.shipment_photo import ShipmentPhoto
from app.repositories import shipment_containers as containers
from app.repositories import shipment_photos, shipping_repository
from app.services import storage

JPEG = base64.b64encode(b"\xff\xd8\xff\xe0fake-jpeg").decode()


@pytest.fixture
def stored(monkeypatch):
    objects: dict[str, bytes] = {}
    monkeypatch.setattr(storage, "upload_file", lambda key, data, ct, **kw: objects.__setitem__(key, data) or key)
    monkeypatch.setattr(storage, "delete_file", lambda key: objects.pop(key, None))
    return objects


def _project(session) -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"P{uuid.uuid4().hex[:8]}", description="Test", company="TUBC")
    session.add(p)
    session.flush()
    return p


def _loaded_skid(session, project):
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
            requested_quantity=1,
        )
    )
    session.flush()
    skid = containers.create_container(session, project.id, container_type="SKID", name="Skid 1", created_by="t")
    containers.set_container_items(
        session,
        skid.id,
        [{"opening_number": "101", "hardware_category": "HINGE", "product_code": "HG-100", "quantity": 1}],
    )
    return skid


def _add(session, **kw):
    defaults = dict(
        container_id=None,
        packing_slip_id=None,
        file_name="IMG_0001.jpg",
        content_type="image/jpeg",
        file_data_base64=JPEG,
        taken_by="Loader",
        taken_by_user_id="u_loader",
    )
    return shipment_photos.add_photo(session, **{**defaults, **kw})


def test_a_loading_photo_rides_its_container_onto_the_slip(db_session, stored):
    project = _project(db_session)
    skid = _loaded_skid(db_session, project)
    photo = _add(db_session, kind=ShipmentPhotoKind.LOADING, container_id=skid.id)
    assert photo.s3_key in stored
    assert photo.packing_slip_id is None

    slip = containers.confirm_shipment_from_containers(
        db_session, project.id, [skid.id], shipped_by="tester", details=None
    )
    db_session.refresh(photo)
    assert photo.packing_slip_id == slip.id
    assert [p.id for p in shipping_repository.get_packing_slip(db_session, slip.id).photos] == [photo.id]


def test_a_delivery_photo_needs_a_shipment_that_has_left_the_dock(db_session, stored):
    project = _project(db_session)
    skid = _loaded_skid(db_session, project)
    slip = containers.confirm_shipment_from_containers(
        db_session, project.id, [skid.id], shipped_by="tester", details=None
    )
    with pytest.raises(InvalidStateTransitionError, match="has not left the dock"):
        _add(db_session, kind=ShipmentPhotoKind.DELIVERY, packing_slip_id=slip.id)
    assert stored == {}

    shipping_repository.mark_shipment_picked_up(db_session, slip.id, "driver")
    photo = _add(db_session, kind=ShipmentPhotoKind.DELIVERY, packing_slip_id=slip.id)
    assert photo.container_id is None and photo.packing_slip_id == slip.id


def test_only_images_are_taken(db_session, stored):
    project = _project(db_session)
    skid = _loaded_skid(db_session, project)
    with pytest.raises(ValidationError, match="Only photos"):
        _add(db_session, kind=ShipmentPhotoKind.LOADING, container_id=skid.id, content_type="application/pdf")
    assert stored == {}


def test_a_photo_must_be_of_the_right_thing(db_session, stored):
    project = _project(db_session)
    skid = _loaded_skid(db_session, project)
    with pytest.raises(ValidationError, match="delivery photo is of a shipment"):
        _add(db_session, kind=ShipmentPhotoKind.DELIVERY, container_id=skid.id)


def test_breaking_a_container_down_takes_its_photos_with_it(db_session, stored):
    project = _project(db_session)
    skid = _loaded_skid(db_session, project)
    photo = _add(db_session, kind=ShipmentPhotoKind.LOADING, container_id=skid.id)
    photo_id, key = photo.id, photo.s3_key
    keys = containers.delete_container(db_session, skid.id)
    assert keys == [key]
    # Gone by the foreign key's cascade, so asked of the table rather than of the session's copy.
    assert db_session.scalar(select(func.count(ShipmentPhoto.id)).where(ShipmentPhoto.id == photo_id)) == 0
