"""#1442: a finalize that changes a product's Site/Shop is held to the override page's plan.

Step 5a writes the classification a finalize was given onto every row of the product (#1264) - the
same change the override page makes - so it gets the same safeguards: refused while a shop batch for the
product is still being pulled, and a product leaving the shop comes off the openings still waiting on a
pending shop request. Who may make the change is a separate decision (#1443) and is not touched here.
A shop batch also refuses a product that is no longer shop work, whatever path changed it.
"""

import uuid

import pytest
from sqlalchemy import select, update

from app.errors import ConflictError, ValidationError
from app.models.enums import (
    Classification,
    NotificationType,
    PullRequestSource,
    PullRequestStatus,
    ShopAssemblyBatchStatus,
    ShopAssemblyOpeningStatus,
    ShopAssemblyRequestStatus,
)
from app.models.hardware import HardwareItem
from app.models.hardware_classification_change import HardwareClassificationChange
from app.models.notification import Notification
from app.models.project import Project
from app.models.pull_request import PullRequest
from app.models.shop_assembly import (
    ShopAssemblyBatch,
    ShopAssemblyBatchItem,
    ShopAssemblyRequest,
    ShopAssemblyRequestItem,
    ShopAssemblyRequestOpening,
)
from app.repositories import import_repository, shop_assembly_repository

CAT = "HINGE"


def _project(session) -> Project:
    p = Project(id=uuid.uuid4(), company="TUBC", project_id=f"RC-{uuid.uuid4().hex[:8]}", description="Job")
    session.add(p)
    session.flush()
    return p


def _opening(number: str) -> dict:
    return {"opening_number": number}


def _item(opening: str, code: str, qty: int = 2) -> dict:
    return {
        "opening_number": opening,
        "product_code": code,
        "hardware_category": CAT,
        "item_quantity": qty,
        "unit_cost": 10.0,
    }


def _classified(code: str, classification: Classification) -> dict:
    return {"hardware_category": CAT, "product_code": code, "unit_cost": 10.0, "classification": classification.value}


def _finalize(session, project, classes: dict[str, Classification], *, replace: bool = False):
    import_repository.finalize_import_session(
        session,
        {
            "project_id": str(project.id),
            "openings": [_opening("A01")],
            "hardware_items": [_item("A01", code) for code in classes],
            "classifications": [_classified(code, cls) for code, cls in classes.items()],
            "replace_schedule": replace,
        },
        created_by="Pat PM",
    )
    session.flush()


def _waiting_request(session, project, codes: list[str]) -> ShopAssemblyRequest:
    req = ShopAssemblyRequest(
        id=uuid.uuid4(),
        request_number=f"SAR-{uuid.uuid4().hex[:6]}",
        project_id=project.id,
        status=ShopAssemblyRequestStatus.PENDING,
        created_by="pm",
    )
    session.add(req)
    session.flush()
    session.add(
        ShopAssemblyRequestOpening(
            id=uuid.uuid4(),
            shop_assembly_request_id=req.id,
            opening_number="A01",
            status=ShopAssemblyOpeningStatus.PENDING,
        )
    )
    for code in codes:
        session.add(
            ShopAssemblyRequestItem(
                id=uuid.uuid4(),
                shop_assembly_request_id=req.id,
                opening_number="A01",
                hardware_category=CAT,
                product_code=code,
                requested_quantity=2,
            )
        )
    session.flush()
    return req


def _batch_being_pulled(session, project, code: str) -> None:
    req = _waiting_request(session, project, [code])
    req.openings[0].status = ShopAssemblyOpeningStatus.BATCHED
    pull = PullRequest(
        id=uuid.uuid4(),
        request_number=f"PR-{uuid.uuid4().hex[:6]}",
        project_id=project.id,
        source=PullRequestSource.SHOP_ASSEMBLY,
        status=PullRequestStatus.IN_PROGRESS,
        requested_by="manager",
    )
    session.add(pull)
    session.flush()
    batch = ShopAssemblyBatch(
        id=uuid.uuid4(),
        shop_assembly_request_id=req.id,
        sequence=1,
        batch_number=f"B-{uuid.uuid4().hex[:6]}",
        status=ShopAssemblyBatchStatus.ACTIVE,
        created_by="manager",
        pull_request_id=pull.id,
    )
    session.add(batch)
    session.flush()
    session.add(
        ShopAssemblyBatchItem(
            id=uuid.uuid4(),
            shop_assembly_batch_id=batch.id,
            opening_number="A01",
            hardware_category=CAT,
            product_code=code,
            allocated_quantity=2,
        )
    )
    session.flush()


def _classes(session, project, code: str) -> set:
    return set(
        session.scalars(
            select(HardwareItem.classification).where(
                HardwareItem.project_id == project.id, HardwareItem.product_code == code
            )
        )
    )


def _changes(session, project) -> list[HardwareClassificationChange]:
    return list(
        session.scalars(
            select(HardwareClassificationChange).where(HardwareClassificationChange.project_id == project.id)
        )
    )


def _notices(session, project) -> int:
    return len(
        session.scalars(
            select(Notification).where(
                Notification.project_id == project.id,
                Notification.type == NotificationType.CLASSIFICATION_CHANGED,
            )
        ).all()
    )


def test_a_replace_moving_a_product_to_site_takes_it_off_a_waiting_shop_request(db_session):
    project = _project(db_session)
    _finalize(db_session, project, {"HG-100": Classification.SHOP_HARDWARE})
    req = _waiting_request(db_session, project, ["HG-100"])

    _finalize(db_session, project, {"HG-100": Classification.SITE_HARDWARE}, replace=True)

    db_session.refresh(req)
    assert req.items == []
    assert req.openings[0].status == ShopAssemblyOpeningStatus.DISMISSED
    # Nothing left waiting, so the request closes out, and the manager is told.
    assert req.status == ShopAssemblyRequestStatus.APPROVED
    assert _notices(db_session, project) == 1
    assert _classes(db_session, project, "HG-100") == {Classification.SITE_HARDWARE}
    (change,) = _changes(db_session, project)
    assert (change.from_choice, change.to_choice, change.changed_by) == ("UCH_SHOP", "UCH_SITE", "Pat PM")


def test_the_rest_of_a_waiting_request_stays_when_one_product_moves_to_site(db_session):
    project = _project(db_session)
    _finalize(db_session, project, {"HG-100": Classification.SHOP_HARDWARE, "HG-200": Classification.SHOP_HARDWARE})
    req = _waiting_request(db_session, project, ["HG-100", "HG-200"])

    _finalize(
        db_session,
        project,
        {"HG-100": Classification.SITE_HARDWARE, "HG-200": Classification.SHOP_HARDWARE},
        replace=True,
    )

    db_session.refresh(req)
    assert [i.product_code for i in req.items] == ["HG-200"]
    assert req.openings[0].status == ShopAssemblyOpeningStatus.PENDING
    assert req.status == ShopAssemblyRequestStatus.PENDING
    assert [c.product_code for c in _changes(db_session, project)] == ["HG-100"]


def test_a_replace_moving_a_product_on_a_batch_being_pulled_is_refused(db_session):
    project = _project(db_session)
    _finalize(db_session, project, {"HG-100": Classification.SHOP_HARDWARE})
    _batch_being_pulled(db_session, project, "HG-100")

    with pytest.raises(ConflictError) as exc:
        _finalize(db_session, project, {"HG-100": Classification.SITE_HARDWARE}, replace=True)

    assert "still being pulled" in str(exc.value)
    assert _classes(db_session, project, "HG-100") == {Classification.SHOP_HARDWARE}
    assert _changes(db_session, project) == []


def test_a_finalize_that_keeps_the_classification_changes_nothing(db_session):
    project = _project(db_session)
    _finalize(db_session, project, {"HG-100": Classification.SHOP_HARDWARE})
    req = _waiting_request(db_session, project, ["HG-100"])
    _batch_being_pulled(db_session, project, "HG-100")

    # Same answer again: not a change, so neither the waiting request nor the live batch matters.
    _finalize(db_session, project, {"HG-100": Classification.SHOP_HARDWARE}, replace=True)

    db_session.refresh(req)
    assert [i.product_code for i in req.items] == ["HG-100"]
    assert req.status == ShopAssemblyRequestStatus.PENDING
    assert _changes(db_session, project) == []
    assert _notices(db_session, project) == 0


def test_a_first_classification_is_not_a_change(db_session):
    project = _project(db_session)
    import_repository.finalize_import_session(
        db_session,
        {"project_id": str(project.id), "openings": [_opening("A01")], "hardware_items": [_item("A01", "HG-100")]},
    )
    db_session.flush()

    _finalize(db_session, project, {"HG-100": Classification.SITE_HARDWARE})

    assert _classes(db_session, project, "HG-100") == {Classification.SITE_HARDWARE}
    assert _changes(db_session, project) == []


def test_a_shop_batch_refuses_a_product_that_is_no_longer_shop_hardware(db_session):
    project = _project(db_session)
    _finalize(db_session, project, {"HG-100": Classification.SHOP_HARDWARE})
    req = _waiting_request(db_session, project, ["HG-100"])
    # A path that changes the rows without taking the product off waiting requests.
    db_session.execute(
        update(HardwareItem)
        .where(HardwareItem.project_id == project.id)
        .values(classification=Classification.SITE_HARDWARE)
    )
    db_session.flush()

    with pytest.raises(ValidationError) as exc:
        shop_assembly_repository.create_shop_assembly_batch(
            db_session,
            req.id,
            [{"opening_number": "A01", "hardware_category": CAT, "product_code": "HG-100", "allocated_quantity": 2}],
            created_by="manager",
        )

    assert exc.value.field == "lines"
    assert "not shop hardware" in str(exc.value)
