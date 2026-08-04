"""The SHIP_READY leaf fixture, and the gate in front of it (#470).

The fixture fabricates assembled door leaves - rows the rest of the system treats as physical objects
in a warehouse - without any of the pull cycle that normally produces one. That is the only way to
reach a skid's thirty-leaf ceiling, and it is also why the gate matters as much as the behaviour:
on anything holding real data, a leaf minted here is an invented door.

The auth half mirrors `test_testing_sign_in_auth.py`, because it is literally the same gate.
"""

import hashlib
import uuid

import pytest
from fastapi.testclient import TestClient

from app.errors import NotFoundError, ValidationError
from app.models.enums import OpeningItemState
from app.models.opening_item import OpeningItem
from app.models.project import Project
from app.repositories import shipment_containers as containers
from app.services import testing_fixtures

_SECRET = "correct-horse-battery-staple"
_SECRET_HASH = hashlib.sha256(_SECRET.encode("utf-8")).hexdigest()
_ROUTE = "/testing/seed-ship-ready-leaves"


@pytest.fixture
def client(monkeypatch):
    """The environment gate open and the secret configured, so the tests below land on the AUTH gate.
    Attributes are patched on `app.config` rather than reimporting `main`, which would rebuild the
    app and the relay gateway singleton underneath the rest of the suite."""
    import app.config
    import main

    monkeypatch.setattr(app.config, "TESTING_ENABLED", True, raising=False)
    monkeypatch.setattr(app.config, "TESTING_SIGN_IN_SECRET_HASH", _SECRET_HASH, raising=False)
    return TestClient(main.app)


def _project(session) -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:8]}", description="Test")
    session.add(p)
    session.flush()
    return p


# --- the gate ------------------------------------------------------------------------------------


def test_seeding_is_refused_when_testing_is_disabled(monkeypatch):
    """Checked before auth, so a production deployment refuses outright rather than leaking whether
    the caller's credential would have been good enough."""
    import app.config
    import main

    monkeypatch.setattr(app.config, "TESTING_ENABLED", False, raising=False)
    resp = TestClient(main.app).post(_ROUTE, params={"project_id": str(uuid.uuid4())})

    assert resp.status_code == 403
    assert "not enabled" in resp.json()["error"].lower()


def test_seeding_is_refused_without_any_credential(client):
    resp = client.post(_ROUTE, params={"project_id": str(uuid.uuid4())})

    assert resp.status_code == 401
    assert resp.json()["code"] == "UNAUTHENTICATED"


def test_seeding_is_refused_with_the_wrong_secret(client):
    resp = client.post(
        _ROUTE,
        params={"project_id": str(uuid.uuid4())},
        headers={"X-Testing-Secret": "not-it"},
    )

    assert resp.status_code == 401
    assert resp.json()["code"] == "UNAUTHENTICATED"


def test_secret_path_is_disabled_when_no_hash_is_configured(client, monkeypatch):
    """A blank TESTING_SIGN_IN_SECRET_HASH must fail CLOSED: any presented secret falls through to
    the admin path rather than comparing equal to nothing."""
    import app.config

    monkeypatch.setattr(app.config, "TESTING_SIGN_IN_SECRET_HASH", "", raising=False)
    resp = client.post(_ROUTE, params={"project_id": str(uuid.uuid4())}, headers={"X-Testing-Secret": _SECRET})

    assert resp.status_code == 401
    assert resp.json()["code"] == "UNAUTHENTICATED"


def test_the_secret_opens_it(client):
    """Past the gate and into the body, shown by the route reaching its own argument check. A
    malformed project id is refused at 400 before any database work, so this needs no DB."""
    resp = client.post(_ROUTE, params={"project_id": "not-a-uuid"}, headers={"X-Testing-Secret": _SECRET})

    assert resp.status_code == 400
    assert "not a project id" in resp.json()["error"]


# --- what it seeds -------------------------------------------------------------------------------


def test_seeded_leaves_land_in_the_staging_pool(db_session):
    """The point of the fixture: straight to SHIP_READY and unplaced, with no pull cycle behind it."""
    project = _project(db_session)

    result = testing_fixtures.seed_ship_ready_leaves(db_session, project.id, 3)

    assert result["created"] == 3
    pool = containers.build_staged_pool(db_session, project.id)
    assert len(pool["leaves"]) == 3
    assert all(holder is None for holder in pool["leaves"].values())
    assert {uuid.UUID(leaf["opening_item_id"]) for leaf in result["leaves"]} == set(pool["leaves"])


def test_seeded_leaves_are_ship_ready_and_belong_to_the_project(db_session):
    project = _project(db_session)

    testing_fixtures.seed_ship_ready_leaves(db_session, project.id, 2)

    rows = db_session.query(OpeningItem).filter(OpeningItem.project_id == project.id).all()
    assert len(rows) == 2
    assert all(row.state == OpeningItemState.SHIP_READY for row in rows)
    assert all(row.leaf == 1 for row in rows)
    assert all(len(row.installed_hardware) == 1 for row in rows)


def test_a_second_call_adds_rather_than_colliding(db_session):
    """`uq_opening_items_live_leaf` is one live unit per project/opening/leaf, so re-running the
    fixture has to issue fresh opening numbers rather than repeat the first run's."""
    project = _project(db_session)

    first = testing_fixtures.seed_ship_ready_leaves(db_session, project.id, 2)
    second = testing_fixtures.seed_ship_ready_leaves(db_session, project.id, 2)

    numbers = [leaf["opening_number"] for leaf in first["leaves"] + second["leaves"]]
    assert len(set(numbers)) == 4
    assert len(containers.build_staged_pool(db_session, project.id)["leaves"]) == 4


def test_seeding_enough_to_fill_a_skid_and_be_refused_the_next_one(db_session):
    """The state the whole fixture exists for. `test_a_skid_stops_at_thirty_leaves` proves the
    ceiling on a hand-built pool; this proves the fixture can actually reach it."""
    from app.models.enums import ShipmentContainerType

    project = _project(db_session)
    result = testing_fixtures.seed_ship_ready_leaves(db_session, project.id, 31)
    leaf_ids = [leaf["opening_item_id"] for leaf in result["leaves"]]

    skid = containers.create_container(
        db_session, project.id, container_type=ShipmentContainerType.SKID, name="Skid 1", created_by="tester"
    )
    items = [
        {"item_type": "OPENING_ITEM", "opening_item_id": oi_id, "hardware_category": "", "product_code": ""}
        for oi_id in leaf_ids[:30]
    ]
    containers.set_container_items(db_session, skid.id, items)
    assert len(skid.items) == 30

    items.append(
        {
            "item_type": "OPENING_ITEM",
            "opening_item_id": leaf_ids[30],
            "hardware_category": "",
            "product_code": "",
        }
    )
    with pytest.raises(ValidationError, match="at most 30"):
        containers.set_container_items(db_session, skid.id, items)


def test_an_unknown_project_is_refused(db_session):
    with pytest.raises(NotFoundError):
        testing_fixtures.seed_ship_ready_leaves(db_session, uuid.uuid4(), 1)


@pytest.mark.parametrize("count", [0, -1, testing_fixtures.MAX_SEEDED_LEAVES + 1])
def test_the_count_is_bounded(db_session, count):
    """Open-ended would mean a typo on a query string can mint a hundred thousand doors."""
    project = _project(db_session)

    with pytest.raises(ValidationError):
        testing_fixtures.seed_ship_ready_leaves(db_session, project.id, count)
