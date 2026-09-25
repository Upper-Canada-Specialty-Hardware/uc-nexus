"""#735: correcting a product's classification after import, and what refuses it.

Site hardware cannot be pulled into the shop, so a product may not leave shop while a live shop
assembly request holds it. By Others is not UC Hardware's to order or ship, so a product may not become
By Others while it is on a PO or a pending shipping request. Everything else is allowed, a bulk change
is all or nothing, and every change is logged.
"""

import uuid

import pytest
from sqlalchemy import select

from app.errors import ConflictError, ValidationError
from app.models.enums import (
    Classification,
    HardwareItemState,
    PullRequestSource,
    PullRequestStatus,
    ShippingOutRequestStatus,
    ShopAssemblyBatchStatus,
    ShopAssemblyOpeningStatus,
    ShopAssemblyRequestStatus,
)
from app.models.enums import HardwareClassificationChoice as C
from app.models.hardware import HardwareItem
from app.models.hardware_classification_change import HardwareClassificationChange
from app.models.project import Opening, Project
from app.models.project_excluded_item import ProjectExcludedItem
from app.models.pull_request import PullRequest
from app.models.shipping_out_request import ShippingOutRequest, ShippingOutRequestItem
from app.models.shop_assembly import (
    ShopAssemblyBatch,
    ShopAssemblyBatchItem,
    ShopAssemblyRequest,
    ShopAssemblyRequestItem,
    ShopAssemblyRequestOpening,
)
from app.repositories import classification_override_repository as repo

CAT = "HINGE"


def _project(session) -> Project:
    p = Project(id=uuid.uuid4(), company="TUBC", project_id=f"CO-{uuid.uuid4().hex[:8]}", description="Job")
    session.add(p)
    session.flush()
    return p


def _opening(session, project, number="A01") -> Opening:
    o = Opening(id=uuid.uuid4(), project_id=project.id, opening_number=number)
    session.add(o)
    session.flush()
    return o


def _item(session, project, opening, code, *, cls=None, qty=2, state=HardwareItemState.AVAILABLE, cost=None):
    session.add(
        HardwareItem(
            id=uuid.uuid4(),
            project_id=project.id,
            opening_id=opening.id,
            hardware_category=CAT,
            product_code=code,
            item_quantity=qty,
            classification=cls,
            state=state,
            unit_cost=cost,
        )
    )
    session.flush()


def _choices(session, project) -> dict[str, C]:
    return {r["product_code"]: r["choice"] for r in repo.list_product_classifications(session, project.id)}


def _shop_request(session, project, code, *, opening_status=ShopAssemblyOpeningStatus.PENDING):
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
            id=uuid.uuid4(), shop_assembly_request_id=req.id, opening_number="A01", status=opening_status
        )
    )
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


def _batch(session, project, code, pull_status):
    req = _shop_request(session, project, code, opening_status=ShopAssemblyOpeningStatus.BATCHED)
    pull = PullRequest(
        id=uuid.uuid4(),
        request_number=f"PR-{uuid.uuid4().hex[:6]}",
        project_id=project.id,
        source=PullRequestSource.SHOP_ASSEMBLY,
        status=pull_status,
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
    return batch


# --- reading ------------------------------------------------------------------------------------


def test_each_product_reads_as_the_import_choice_it_holds(db_session):
    project = _project(db_session)
    a01, a02 = _opening(db_session, project), _opening(db_session, project, "A02")
    _item(db_session, project, a01, "SHOP-1", cls=Classification.SHOP_HARDWARE)
    _item(db_session, project, a02, "SHOP-1", cls=Classification.SHOP_HARDWARE, qty=3)
    _item(db_session, project, a01, "SITE-1", cls=Classification.SITE_HARDWARE)
    _item(db_session, project, a01, "NONE-1")
    _item(db_session, project, a01, "MIX-1", cls=Classification.SHOP_HARDWARE, cost=1)
    _item(db_session, project, a02, "MIX-1", cls=Classification.SITE_HARDWARE, cost=2)
    _item(db_session, project, a01, "OTHER-1", cls=Classification.SITE_HARDWARE)
    db_session.add(
        ProjectExcludedItem(id=uuid.uuid4(), project_id=project.id, hardware_category=CAT, product_code="OTHER-1")
    )
    db_session.flush()

    rows = {r["product_code"]: r for r in repo.list_product_classifications(db_session, project.id)}

    assert {code: r["choice"] for code, r in rows.items()} == {
        "SHOP-1": C.UCH_SHOP,
        "SITE-1": C.UCH_SITE,
        "NONE-1": C.UNCLASSIFIED,
        "MIX-1": C.MIXED,
        "OTHER-1": C.BY_OTHERS,
    }
    assert (rows["SHOP-1"]["quantity"], rows["SHOP-1"]["opening_count"]) == (5, 2)


# --- allowed moves ------------------------------------------------------------------------------


def test_site_to_shop_writes_every_row_and_logs_it(db_session):
    project = _project(db_session)
    a01, a02 = _opening(db_session, project), _opening(db_session, project, "A02")
    _item(db_session, project, a01, "HG-1", cls=Classification.SITE_HARDWARE)
    _item(db_session, project, a02, "HG-1", cls=Classification.SITE_HARDWARE)

    written = repo.set_product_classifications(db_session, project.id, [(CAT, "HG-1", C.UCH_SHOP)], changed_by="Greg")

    classes = set(db_session.scalars(select(HardwareItem.classification).where(HardwareItem.project_id == project.id)))
    assert classes == {Classification.SHOP_HARDWARE}
    assert [(w.from_choice, w.to_choice, w.changed_by) for w in written] == [("UCH_SITE", "UCH_SHOP", "Greg")]
    assert repo.list_changes(db_session, project.id)[0].product_code == "HG-1"


def test_by_others_and_back_writes_and_removes_the_exclusion(db_session):
    project = _project(db_session)
    _item(db_session, project, _opening(db_session, project), "HG-1", cls=Classification.SITE_HARDWARE)

    repo.set_product_classifications(db_session, project.id, [(CAT, "HG-1", C.BY_OTHERS)], changed_by="Greg")
    assert _choices(db_session, project)["HG-1"] == C.BY_OTHERS

    repo.set_product_classifications(db_session, project.id, [(CAT, "HG-1", C.UCH_SITE)], changed_by="Greg")
    assert _choices(db_session, project)["HG-1"] == C.UCH_SITE
    assert (
        db_session.scalars(select(ProjectExcludedItem).where(ProjectExcludedItem.project_id == project.id)).all() == []
    )


def test_setting_the_value_a_product_already_has_writes_nothing(db_session):
    project = _project(db_session)
    _item(db_session, project, _opening(db_session, project), "HG-1", cls=Classification.SHOP_HARDWARE)

    assert (
        repo.set_product_classifications(db_session, project.id, [(CAT, "HG-1", C.UCH_SHOP)], changed_by="Greg") == []
    )


def test_a_finished_shop_pull_does_not_hold_the_product(db_session):
    project = _project(db_session)
    _item(db_session, project, _opening(db_session, project), "HG-1", cls=Classification.SHOP_HARDWARE)
    _batch(db_session, project, "HG-1", PullRequestStatus.COMPLETED)

    repo.set_product_classifications(db_session, project.id, [(CAT, "HG-1", C.UCH_SITE)], changed_by="Greg")

    assert _choices(db_session, project)["HG-1"] == C.UCH_SITE


# --- refusals -----------------------------------------------------------------------------------


def test_shop_to_site_is_refused_while_a_waiting_shop_request_holds_it(db_session):
    project = _project(db_session)
    _item(db_session, project, _opening(db_session, project), "HG-1", cls=Classification.SHOP_HARDWARE)
    req = _shop_request(db_session, project, "HG-1")

    with pytest.raises(ConflictError) as err:
        repo.set_product_classifications(db_session, project.id, [(CAT, "HG-1", C.UCH_SITE)], changed_by="Greg")

    assert req.request_number in err.value.message
    assert _choices(db_session, project)["HG-1"] == C.UCH_SHOP


def test_shop_to_site_is_refused_while_an_active_batch_pull_is_unfinished(db_session):
    project = _project(db_session)
    _item(db_session, project, _opening(db_session, project), "HG-1", cls=Classification.SHOP_HARDWARE)
    batch = _batch(db_session, project, "HG-1", PullRequestStatus.IN_PROGRESS)

    with pytest.raises(ConflictError) as err:
        repo.set_product_classifications(db_session, project.id, [(CAT, "HG-1", C.UCH_SITE)], changed_by="Greg")

    assert batch.batch_number in err.value.message


def test_by_others_is_refused_while_the_product_is_on_a_po(db_session):
    project = _project(db_session)
    _item(
        db_session,
        project,
        _opening(db_session, project),
        "HG-1",
        cls=Classification.SITE_HARDWARE,
        state=HardwareItemState.IN_PO,
    )

    with pytest.raises(ConflictError, match="on a PO"):
        repo.set_product_classifications(db_session, project.id, [(CAT, "HG-1", C.BY_OTHERS)], changed_by="Greg")


def test_by_others_is_refused_while_a_pending_shipping_request_asks_for_it(db_session):
    project = _project(db_session)
    _item(db_session, project, _opening(db_session, project), "HG-1", cls=Classification.SITE_HARDWARE)
    req = ShippingOutRequest(
        id=uuid.uuid4(),
        request_number=f"SO-{uuid.uuid4().hex[:6]}",
        project_id=project.id,
        status=ShippingOutRequestStatus.PENDING,
        created_by="pm",
    )
    db_session.add(req)
    db_session.flush()
    db_session.add(
        ShippingOutRequestItem(
            id=uuid.uuid4(),
            shipping_out_request_id=req.id,
            opening_number="A01",
            hardware_category=CAT,
            product_code="HG-1",
            requested_quantity=1,
        )
    )
    db_session.flush()

    with pytest.raises(ConflictError) as err:
        repo.set_product_classifications(db_session, project.id, [(CAT, "HG-1", C.BY_OTHERS)], changed_by="Greg")

    assert req.request_number in err.value.message


def test_a_bulk_change_with_one_blocked_product_changes_nothing(db_session):
    project = _project(db_session)
    a01 = _opening(db_session, project)
    _item(db_session, project, a01, "HG-1", cls=Classification.SHOP_HARDWARE)
    _item(db_session, project, a01, "HG-2", cls=Classification.SHOP_HARDWARE)
    _shop_request(db_session, project, "HG-2")

    with pytest.raises(ConflictError) as err:
        repo.set_product_classifications(
            db_session, project.id, [(CAT, "HG-1", C.UCH_SITE), (CAT, "HG-2", C.UCH_SITE)], changed_by="Greg"
        )

    assert "HG-2" in err.value.message and "HG-1 " not in err.value.message
    assert _choices(db_session, project) == {"HG-1": C.UCH_SHOP, "HG-2": C.UCH_SHOP}
    assert (
        db_session.scalars(
            select(HardwareClassificationChange).where(HardwareClassificationChange.project_id == project.id)
        ).all()
        == []
    )


def test_only_the_three_import_choices_can_be_set(db_session):
    project = _project(db_session)
    _item(db_session, project, _opening(db_session, project), "HG-1")

    with pytest.raises(ValidationError):
        repo.set_product_classifications(db_session, project.id, [(CAT, "HG-1", C.MIXED)], changed_by="Greg")


def test_a_product_not_on_the_schedule_is_refused(db_session):
    project = _project(db_session)

    with pytest.raises(ValidationError):
        repo.set_product_classifications(db_session, project.id, [(CAT, "NOPE", C.UCH_SHOP)], changed_by="Greg")
