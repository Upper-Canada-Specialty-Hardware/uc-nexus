"""#1443: a schedule import doesn't change the classification of a product the project already has.

The product owner ruled that a product's UCH Shop / UCH Site lives on the project's own classification
list, not on whichever schedule was imported last. A finalize that answers a listed product differently is
refused whole and changes nothing - the change is made on the Hardware Classifications page, which plans
what it does first. A new product takes its first value from the finalize and is listed, and a product a
newer schedule drops stays listed. #1442's safeguards remain for a Mixed product - never listed, its rows
disagree - that a finalize settles on one value: it is held to the page's plan and logged like the page.
A shop batch also refuses a product that is no longer shop work, whatever path changed it.
"""

import uuid

import pytest
from sqlalchemy import delete, select, update

from app.errors import ConflictError, ValidationError
from app.models.enums import (
    Classification,
    HardwareClassificationChoice,
    HardwareItemState,
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
from app.models.project import Opening, Project
from app.models.project_product_classification import ProjectProductClassification
from app.models.pull_request import PullRequest
from app.models.shop_assembly import (
    ShopAssemblyBatch,
    ShopAssemblyBatchItem,
    ShopAssemblyRequest,
    ShopAssemblyRequestItem,
    ShopAssemblyRequestOpening,
)
from app.repositories import classification_override_repository, import_repository, shop_assembly_repository

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


def _listed(session, project) -> dict[str, Classification]:
    return {
        code: classification
        for (_category, code), classification in classification_override_repository.listed_classifications(
            session, project.id
        ).items()
    }


def _item_in_po(session, project, code: str, classification: Classification) -> None:
    opening = session.scalars(select(Opening).where(Opening.project_id == project.id)).first()
    session.add(
        HardwareItem(
            id=uuid.uuid4(),
            project_id=project.id,
            opening_id=opening.id,
            hardware_category=CAT,
            product_code=code,
            leaf=2,
            item_quantity=1,
            classification=classification,
            state=HardwareItemState.IN_PO,
        )
    )
    session.flush()


def test_a_first_classification_is_listed(db_session):
    project = _project(db_session)
    import_repository.finalize_import_session(
        db_session,
        {"project_id": str(project.id), "openings": [_opening("A01")], "hardware_items": [_item("A01", "HG-100")]},
    )
    db_session.flush()
    assert _listed(db_session, project) == {}

    _finalize(db_session, project, {"HG-100": Classification.SITE_HARDWARE})

    assert _classes(db_session, project, "HG-100") == {Classification.SITE_HARDWARE}
    assert _listed(db_session, project) == {"HG-100": Classification.SITE_HARDWARE}
    assert _changes(db_session, project) == []


def test_a_replace_cannot_change_a_listed_products_classification(db_session):
    project = _project(db_session)
    _finalize(db_session, project, {"HG-100": Classification.SHOP_HARDWARE, "HG-200": Classification.SHOP_HARDWARE})
    req = _waiting_request(db_session, project, ["HG-100"])

    with pytest.raises(ValidationError) as exc:
        _finalize(
            db_session,
            project,
            {"HG-100": Classification.SITE_HARDWARE, "HG-200": Classification.SHOP_HARDWARE},
            replace=True,
        )

    assert exc.value.field == "classifications"
    assert "HG-100 (HINGE) is UCH Shop" in exc.value.message
    assert "Hardware Classifications page" in exc.value.message
    assert "HG-200" not in exc.value.message
    assert _classes(db_session, project, "HG-100") == {Classification.SHOP_HARDWARE}
    assert _listed(db_session, project)["HG-100"] == Classification.SHOP_HARDWARE
    db_session.refresh(req)
    assert [i.product_code for i in req.items] == ["HG-100"]
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


def test_a_listed_product_given_no_classification_takes_the_lists(db_session):
    project = _project(db_session)
    _finalize(db_session, project, {"HG-100": Classification.SITE_HARDWARE})

    import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [_opening("A01")],
            "hardware_items": [_item("A01", "HG-100", qty=4)],
            "replace_schedule": True,
        },
    )
    db_session.flush()

    assert _classes(db_session, project, "HG-100") == {Classification.SITE_HARDWARE}


def test_a_product_a_newer_schedule_drops_stays_listed_and_comes_back_as_it_was(db_session):
    project = _project(db_session)
    _finalize(db_session, project, {"HG-100": Classification.SHOP_HARDWARE, "HG-200": Classification.SITE_HARDWARE})

    _finalize(db_session, project, {"HG-200": Classification.SITE_HARDWARE}, replace=True)

    assert _classes(db_session, project, "HG-100") == set()
    assert _listed(db_session, project) == {
        "HG-100": Classification.SHOP_HARDWARE,
        "HG-200": Classification.SITE_HARDWARE,
    }
    rows = {
        r["product_code"]: r
        for r in classification_override_repository.list_product_classifications(db_session, project.id)
    }
    assert rows["HG-100"]["on_schedule"] is False
    assert (rows["HG-100"]["quantity"], rows["HG-100"]["opening_count"]) == (0, 0)
    assert rows["HG-100"]["choice"] == HardwareClassificationChoice.UCH_SHOP
    assert rows["HG-200"]["on_schedule"] is True

    # Back on a later schedule with no answer for it: it takes the classification Nexus remembered.
    import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [_opening("A01")],
            "hardware_items": [_item("A01", "HG-100"), _item("A01", "HG-200")],
            "classifications": [_classified("HG-200", Classification.SITE_HARDWARE)],
            "replace_schedule": True,
        },
    )
    db_session.flush()
    assert _classes(db_session, project, "HG-100") == {Classification.SHOP_HARDWARE}


def test_a_product_given_different_answers_at_different_costs_is_not_listed(db_session):
    project = _project(db_session)
    import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [_opening("A01"), _opening("A02")],
            "hardware_items": [_item("A01", "HG-100"), {**_item("A02", "HG-100"), "unit_cost": 20.0}],
            "classifications": [
                _classified("HG-100", Classification.SHOP_HARDWARE),
                {**_classified("HG-100", Classification.SITE_HARDWARE), "unit_cost": 20.0},
            ],
        },
    )
    db_session.flush()

    assert _listed(db_session, project) == {}
    assert _classes(db_session, project, "HG-100") == {Classification.SHOP_HARDWARE, Classification.SITE_HARDWARE}


def test_a_mixed_products_rows_put_back_keep_the_classification_they_had(db_session):
    """#1919: a Mixed product is on no list, so a finalize that doesn't pick it (a shop request, a PO
    finalize that left it alone) put its wiped unordered rows back with no classification at all."""
    project = _project(db_session)
    items = [_item("A01", "HG-100"), {**_item("A02", "HG-100"), "unit_cost": 20.0}]
    import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [_opening("A01"), _opening("A02")],
            "hardware_items": items,
            "classifications": [
                _classified("HG-100", Classification.SHOP_HARDWARE),
                {**_classified("HG-100", Classification.SITE_HARDWARE), "unit_cost": 20.0},
            ],
        },
    )
    db_session.flush()

    import_repository.finalize_import_session(
        db_session,
        {"project_id": str(project.id), "openings": [_opening("A01"), _opening("A02")], "hardware_items": items},
    )
    db_session.flush()

    rows = db_session.execute(
        select(Opening.opening_number, HardwareItem.classification)
        .join(Opening, HardwareItem.opening_id == Opening.id)
        .where(HardwareItem.project_id == project.id, HardwareItem.product_code == "HG-100")
    ).all()
    assert sorted(rows) == [("A01", Classification.SHOP_HARDWARE), ("A02", Classification.SITE_HARDWARE)]
    assert _listed(db_session, project) == {}


def _mixed(session, project, codes: list[str]) -> None:
    """Each code on A01 as Shop, plus one ordered row of it as Site: a Mixed product, never listed - the
    state a product whose rows disagreed was left in by the #1443 backfill."""
    _finalize(session, project, {code: Classification.SHOP_HARDWARE for code in codes})
    session.execute(delete(ProjectProductClassification).where(ProjectProductClassification.project_id == project.id))
    for code in codes:
        _item_in_po(session, project, code, Classification.SITE_HARDWARE)
        assert _classes(session, project, code) == {Classification.SHOP_HARDWARE, Classification.SITE_HARDWARE}


def test_a_mixed_product_not_yet_listed_takes_its_single_value_and_is_listed(db_session):
    project = _project(db_session)
    _mixed(db_session, project, ["HG-100"])

    _finalize(db_session, project, {"HG-100": Classification.SHOP_HARDWARE}, replace=True)

    assert _classes(db_session, project, "HG-100") == {Classification.SHOP_HARDWARE}
    assert _listed(db_session, project) == {"HG-100": Classification.SHOP_HARDWARE}
    (change,) = _changes(db_session, project)
    assert (change.from_choice, change.to_choice, change.changed_by) == ("MIXED", "UCH_SHOP", "Pat PM")


def test_a_mixed_product_moved_to_site_comes_off_a_waiting_shop_request(db_session):
    """#1442, kept for a Mixed product (#1443): settling it on Site takes it off the openings still waiting
    on a pending shop request, the manager is told, and the change is logged."""
    project = _project(db_session)
    _mixed(db_session, project, ["HG-100"])
    req = _waiting_request(db_session, project, ["HG-100"])

    _finalize(db_session, project, {"HG-100": Classification.SITE_HARDWARE}, replace=True)

    db_session.refresh(req)
    assert req.items == []
    assert req.openings[0].status == ShopAssemblyOpeningStatus.DISMISSED
    # Nothing left waiting, so the request closes out, and the manager is told.
    assert req.status == ShopAssemblyRequestStatus.APPROVED
    assert _notices(db_session, project) == 1
    assert _classes(db_session, project, "HG-100") == {Classification.SITE_HARDWARE}
    assert _listed(db_session, project) == {"HG-100": Classification.SITE_HARDWARE}
    (change,) = _changes(db_session, project)
    assert (change.from_choice, change.to_choice, change.changed_by) == ("MIXED", "UCH_SITE", "Pat PM")


def test_the_rest_of_a_waiting_request_stays_when_a_mixed_product_moves_to_site(db_session):
    project = _project(db_session)
    _mixed(db_session, project, ["HG-100"])
    req = _waiting_request(db_session, project, ["HG-100"])
    db_session.add(
        ShopAssemblyRequestItem(
            id=uuid.uuid4(),
            shop_assembly_request_id=req.id,
            opening_number="A01",
            hardware_category=CAT,
            product_code="HG-200",
            requested_quantity=1,
        )
    )
    db_session.flush()

    _finalize(db_session, project, {"HG-100": Classification.SITE_HARDWARE}, replace=True)

    db_session.refresh(req)
    assert [i.product_code for i in req.items] == ["HG-200"]
    assert req.openings[0].status == ShopAssemblyOpeningStatus.PENDING
    assert req.status == ShopAssemblyRequestStatus.PENDING
    assert [c.product_code for c in _changes(db_session, project)] == ["HG-100"]


def test_a_mixed_product_on_a_batch_being_pulled_is_refused(db_session):
    project = _project(db_session)
    _mixed(db_session, project, ["HG-100"])
    _batch_being_pulled(db_session, project, "HG-100")

    with pytest.raises(ConflictError) as exc:
        _finalize(db_session, project, {"HG-100": Classification.SITE_HARDWARE}, replace=True)

    assert "still being pulled" in str(exc.value)
    assert _classes(db_session, project, "HG-100") == {Classification.SHOP_HARDWARE, Classification.SITE_HARDWARE}
    assert _listed(db_session, project) == {}
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
    # #1540: the screen has no per-opening dismiss, so the refusal only says what the manager can do there.
    assert "Take the line off the batch." in str(exc.value)
    assert "Dismiss the opening" not in str(exc.value)


def test_the_batch_review_flags_a_line_that_is_no_longer_shop_work(db_session):
    """#1540: the review reads the batch's own rule, so the line's Send box is off with the reason rather
    than the batch being refused after it is composed. A line still shop work carries no reason."""
    project = _project(db_session)
    _finalize(db_session, project, {"HG-100": Classification.SHOP_HARDWARE, "HG-200": Classification.SHOP_HARDWARE})
    req = _waiting_request(db_session, project, ["HG-100", "HG-200"])
    db_session.execute(
        update(HardwareItem)
        .where(HardwareItem.project_id == project.id, HardwareItem.product_code == "HG-100")
        .values(classification=Classification.SITE_HARDWARE)
    )
    db_session.flush()

    review = shop_assembly_repository.get_allocation_review(db_session, req.id)

    reasons = {line["product_code"]: line["not_shop_work_reason"] for line in review["openings"][0]["lines"]}
    assert reasons["HG-200"] is None
    assert reasons["HG-100"] is not None and "not shop hardware" in reasons["HG-100"]


def _hg100_line(quantity: int) -> list[dict]:
    return [
        {"opening_number": "A01", "hardware_category": CAT, "product_code": "HG-100", "allocated_quantity": quantity}
    ]


def test_a_line_the_reupload_took_off_a_kept_opening_is_off_the_schedule(db_session):
    """#1954: the re-upload keeps A01, so the request keeps its HG-100 line - but A01's schedule no longer
    lists HG-100. The review says so and offers it nothing, and the batch refuses it."""
    project = _project(db_session)
    _finalize(db_session, project, {"HG-100": Classification.SHOP_HARDWARE, "HG-200": Classification.SHOP_HARDWARE})
    req = _waiting_request(db_session, project, ["HG-100", "HG-200"])

    _finalize(db_session, project, {"HG-200": Classification.SHOP_HARDWARE}, replace=True)

    review = shop_assembly_repository.get_allocation_review(db_session, req.id)
    reasons = {line["product_code"]: line["not_shop_work_reason"] for line in review["openings"][0]["lines"]}
    assert reasons["HG-200"] is None
    assert reasons["HG-100"] == shop_assembly_repository.OFF_SCHEDULE_REASON

    with pytest.raises(ValidationError) as exc:
        shop_assembly_repository.create_shop_assembly_batch(db_session, req.id, _hg100_line(2), created_by="manager")
    assert exc.value.field == "lines"
    assert "no longer on this opening's schedule" in str(exc.value)


def test_a_line_is_capped_at_what_the_openings_schedule_lists_now(db_session):
    """#1954: the request was raised owing 2, and the re-upload lowered A01 to 1. The review offers 1 and the
    batch refuses 2, rather than pulling a unit the schedule no longer asks for."""
    project = _project(db_session)
    _finalize(db_session, project, {"HG-100": Classification.SHOP_HARDWARE})
    req = _waiting_request(db_session, project, ["HG-100"])

    import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [_opening("A01")],
            "hardware_items": [_item("A01", "HG-100", qty=1)],
            "classifications": [_classified("HG-100", Classification.SHOP_HARDWARE)],
            "replace_schedule": True,
        },
        created_by="Pat PM",
    )
    db_session.flush()

    review = shop_assembly_repository.get_allocation_review(db_session, req.id)
    (line,) = review["openings"][0]["lines"]
    assert (line["requested_quantity"], line["not_shop_work_reason"]) == (1, None)

    with pytest.raises(ValidationError) as exc:
        shop_assembly_repository.create_shop_assembly_batch(db_session, req.id, _hg100_line(2), created_by="manager")
    assert exc.value.field == "allocated_quantity"
    assert "schedule now gives it 1" in str(exc.value)


def _replace_with_by_others(session, project, codes: list[str], by_others: list[str]):
    import_repository.finalize_import_session(
        session,
        {
            "project_id": str(project.id),
            "openings": [_opening("A01")],
            "hardware_items": [_item("A01", code) for code in codes],
            "excluded_items": [{"hardware_category": CAT, "product_code": code} for code in by_others],
            "replace_schedule": True,
        },
        created_by="Pat PM",
    )
    session.flush()


def _excluded(session, project) -> set[str]:
    from app.models.project_excluded_item import ProjectExcludedItem

    return set(
        session.scalars(select(ProjectExcludedItem.product_code).where(ProjectExcludedItem.project_id == project.id))
    )


def test_a_replace_cannot_take_a_classified_product_to_by_others(db_session):
    """#1392 ruling: a product the project already has as Shop / Site can't become By Others through a
    schedule replace either. Nothing is written."""
    project = _project(db_session)
    _finalize(db_session, project, {"HG-1": Classification.SITE_HARDWARE})

    with pytest.raises(ValidationError) as err:
        _replace_with_by_others(db_session, project, ["HG-1"], ["HG-1"])

    assert "HG-1" in err.value.message and "can't be changed to By Others" in err.value.message
    assert _excluded(db_session, project) == set()


def test_a_new_product_may_still_be_by_others_at_import(db_session):
    project = _project(db_session)
    _finalize(db_session, project, {"HG-1": Classification.SITE_HARDWARE})

    _replace_with_by_others(db_session, project, ["HG-1", "HG-NEW"], ["HG-NEW"])

    assert _excluded(db_session, project) == {"HG-NEW"}
