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
from app.models.project_product_classification import ProjectProductClassification
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


def _list(session, project, code, cls) -> None:
    """Put a product on the project's classification list (#1443) directly."""
    session.add(
        ProjectProductClassification(
            project_id=project.id, hardware_category=CAT, product_code=code, classification=cls
        )
    )
    session.flush()


def _listed(session, project) -> dict[str, tuple[Classification, str | None]]:
    return {
        r.product_code: (r.classification, r.updated_by)
        for r in session.scalars(
            select(ProjectProductClassification).where(ProjectProductClassification.project_id == project.id)
        )
    }


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
    assert all(r["on_schedule"] for r in rows.values())


def test_the_list_holds_a_listed_products_choice_and_its_dropped_products(db_session):
    """#1443: a listed product reads as the list says, whatever its rows hold, and a product only on the
    list - one a newer schedule dropped - is still shown, off the schedule with nothing on it."""
    project = _project(db_session)
    _item(db_session, project, _opening(db_session, project), "HG-1", cls=Classification.SITE_HARDWARE)
    _list(db_session, project, "HG-1", Classification.SHOP_HARDWARE)
    _list(db_session, project, "GONE-1", Classification.SITE_HARDWARE)

    rows = {r["product_code"]: r for r in repo.list_product_classifications(db_session, project.id)}

    assert rows["HG-1"]["choice"] == C.UCH_SHOP and rows["HG-1"]["on_schedule"] is True
    assert rows["GONE-1"] == {
        "hardware_category": CAT,
        "product_code": "GONE-1",
        "quantity": 0,
        "opening_count": 0,
        "choice": C.UCH_SITE,
        "on_schedule": False,
    }


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
    # #1443: the page writes the project's classification list too, and says who did.
    assert _listed(db_session, project) == {"HG-1": (Classification.SHOP_HARDWARE, "Greg")}


def test_a_product_only_on_the_list_can_be_changed(db_session):
    """#1443: a product a newer schedule dropped is still the project's to classify; with no rows, the list
    is all the change writes."""
    project = _project(db_session)
    _list(db_session, project, "GONE-1", Classification.SITE_HARDWARE)

    [plan] = repo.plan_product_classifications(db_session, project.id, [(CAT, "GONE-1", C.UCH_SHOP)])
    assert (plan["blocks"], plan["adjusts"], plan["went_out"]) == ([], [], [])

    written = repo.set_product_classifications(db_session, project.id, [(CAT, "GONE-1", C.UCH_SHOP)], changed_by="Greg")

    assert [(w.from_choice, w.to_choice) for w in written] == [("UCH_SITE", "UCH_SHOP")]
    assert _listed(db_session, project) == {"GONE-1": (Classification.SHOP_HARDWARE, "Greg")}
    assert _choices(db_session, project) == {"GONE-1": C.UCH_SHOP}


def test_a_product_only_on_the_list_cannot_go_to_by_others(db_session):
    """#1392 holds for a listed product off the schedule: it is classified."""
    project = _project(db_session)
    _list(db_session, project, "GONE-1", Classification.SITE_HARDWARE)

    with pytest.raises(ConflictError) as err:
        repo.set_product_classifications(db_session, project.id, [(CAT, "GONE-1", C.BY_OTHERS)], changed_by="Greg")

    assert "GONE-1" in err.value.message and "can't be changed to By Others" in err.value.message
    assert _listed(db_session, project) == {"GONE-1": (Classification.SITE_HARDWARE, None)}


def test_by_others_and_back_writes_and_removes_the_exclusion(db_session):
    """An unclassified product may go to By Others (#1392 refuses only a classified one) and come back."""
    project = _project(db_session)
    _item(db_session, project, _opening(db_session, project), "HG-1")

    repo.set_product_classifications(db_session, project.id, [(CAT, "HG-1", C.BY_OTHERS)], changed_by="Greg")
    assert _choices(db_session, project)["HG-1"] == C.BY_OTHERS
    assert _listed(db_session, project) == {}

    repo.set_product_classifications(db_session, project.id, [(CAT, "HG-1", C.UCH_SITE)], changed_by="Greg")
    assert _choices(db_session, project)["HG-1"] == C.UCH_SITE
    assert _listed(db_session, project) == {"HG-1": (Classification.SITE_HARDWARE, "Greg")}
    assert (
        db_session.scalars(select(ProjectExcludedItem).where(ProjectExcludedItem.project_id == project.id)).all() == []
    )


def test_setting_the_value_a_product_already_has_writes_nothing(db_session):
    project = _project(db_session)
    _item(db_session, project, _opening(db_session, project), "HG-1", cls=Classification.SHOP_HARDWARE)

    assert (
        repo.set_product_classifications(db_session, project.id, [(CAT, "HG-1", C.UCH_SHOP)], changed_by="Greg") == []
    )


def _shipment(session, project, code, status):
    from datetime import datetime

    from app.models.shipping import PackingSlip, PackingSlipItem

    slip = PackingSlip(
        id=uuid.uuid4(),
        packing_slip_number=f"PS-{uuid.uuid4().hex[:6]}",
        project_id=project.id,
        shipped_by="shipper",
        shipped_at=datetime.utcnow(),
        status=status,
    )
    session.add(slip)
    session.flush()
    session.add(
        PackingSlipItem(
            id=uuid.uuid4(),
            packing_slip_id=slip.id,
            opening_number="A01",
            product_code=code,
            hardware_category=CAT,
            quantity=1,
        )
    )
    session.flush()
    return slip


def test_hardware_that_went_to_the_shop_no_longer_locks_and_the_log_keeps_where_it_went(db_session):
    """#1050: the #977 lock is gone - the change applies to what is still owed, and the log row records
    that some of the hardware had already gone to the shop under the old classification."""
    project = _project(db_session)
    _item(db_session, project, _opening(db_session, project), "HG-1", cls=Classification.SHOP_HARDWARE)
    batch = _batch(db_session, project, "HG-1", PullRequestStatus.COMPLETED)

    written = repo.set_product_classifications(db_session, project.id, [(CAT, "HG-1", C.UCH_SITE)], changed_by="Greg")

    assert _choices(db_session, project)["HG-1"] == C.UCH_SITE
    assert f"went to the shop on {batch.batch_number}" in written[0].note
    # And back again - the 80001 case: put it back to the classification it went to the shop under.
    repo.set_product_classifications(db_session, project.id, [(CAT, "HG-1", C.UCH_SHOP)], changed_by="Greg")
    assert _choices(db_session, project)["HG-1"] == C.UCH_SHOP


def test_hardware_that_shipped_no_longer_locks(db_session):
    from app.models.enums import ShipmentStatus

    project = _project(db_session)
    _item(db_session, project, _opening(db_session, project), "HG-1", cls=Classification.SITE_HARDWARE)
    slip = _shipment(db_session, project, "HG-1", ShipmentStatus.DELIVERED)

    written = repo.set_product_classifications(db_session, project.id, [(CAT, "HG-1", C.UCH_SHOP)], changed_by="Greg")

    assert _choices(db_session, project)["HG-1"] == C.UCH_SHOP
    assert f"shipped on {slip.packing_slip_number}" in written[0].note


def test_a_cancelled_shipment_is_not_history(db_session):
    """A cancelled shipment never left (#973), so the log does not say the hardware went anywhere."""
    from app.models.enums import ShipmentStatus

    project = _project(db_session)
    _item(db_session, project, _opening(db_session, project), "HG-1", cls=Classification.SITE_HARDWARE)
    _shipment(db_session, project, "HG-1", ShipmentStatus.CANCELLED)

    written = repo.set_product_classifications(db_session, project.id, [(CAT, "HG-1", C.UCH_SHOP)], changed_by="Greg")

    assert _choices(db_session, project)["HG-1"] == C.UCH_SHOP
    assert written[0].note is None


# --- refusals -----------------------------------------------------------------------------------


def test_shop_to_site_takes_the_product_off_a_waiting_shop_request_and_tells_the_manager(db_session):
    """#1050: a waiting opening holds nothing yet, so the product comes off it. The opening, left with
    nothing, is dismissed; the request, left with nothing waiting, closes out; the manager is told."""
    from app.models.notification import Notification

    project = _project(db_session)
    _item(db_session, project, _opening(db_session, project), "HG-1", cls=Classification.SHOP_HARDWARE)
    req = _shop_request(db_session, project, "HG-1")

    written = repo.set_product_classifications(db_session, project.id, [(CAT, "HG-1", C.UCH_SITE)], changed_by="Greg")
    db_session.refresh(req)

    assert _choices(db_session, project)["HG-1"] == C.UCH_SITE
    assert req.items == []
    assert [o.status for o in req.openings] == [ShopAssemblyOpeningStatus.DISMISSED]
    assert req.status == ShopAssemblyRequestStatus.APPROVED
    assert req.request_number in written[0].note
    notices = db_session.scalars(select(Notification).where(Notification.project_id == project.id)).all()
    assert [n.type.value for n in notices] == ["CLASSIFICATION_CHANGED"]
    assert req.request_number in notices[0].message


def test_a_change_locks_the_projects_pending_shop_requests_before_planning(db_session, monkeypatch):
    """#1156: the plan is built under the same request lock batch, dismiss, reject and discard take, so a
    batch landing at the same moment waits instead of racing it."""
    from app.services import locking

    project = _project(db_session)
    _item(db_session, project, _opening(db_session, project), "HG-1", cls=Classification.SHOP_HARDWARE)
    req = _shop_request(db_session, project, "HG-1")
    calls: list[str] = []
    real_lock = locking.lock_rows
    real_plan = repo.plan_product_classifications

    def lock_spy(session, model_class, ids):
        calls.append(f"lock {model_class.__name__} {sorted(ids)}")
        return real_lock(session, model_class, ids)

    def plan_spy(*args, **kwargs):
        calls.append("plan")
        return real_plan(*args, **kwargs)

    monkeypatch.setattr(locking, "lock_rows", lock_spy)
    monkeypatch.setattr(repo, "plan_product_classifications", plan_spy)

    repo.set_product_classifications(db_session, project.id, [(CAT, "HG-1", C.UCH_SITE)], changed_by="Greg")

    assert calls[:2] == [f"lock ShopAssemblyRequest {[req.id]}", "plan"]


def test_an_opening_keeping_other_hardware_stays_waiting(db_session):
    project = _project(db_session)
    a01 = _opening(db_session, project)
    _item(db_session, project, a01, "HG-1", cls=Classification.SHOP_HARDWARE)
    _item(db_session, project, a01, "HG-2", cls=Classification.SHOP_HARDWARE)
    req = _shop_request(db_session, project, "HG-1")
    db_session.add(
        ShopAssemblyRequestItem(
            id=uuid.uuid4(),
            shop_assembly_request_id=req.id,
            opening_number="A01",
            hardware_category=CAT,
            product_code="HG-2",
            requested_quantity=1,
        )
    )
    db_session.flush()

    repo.set_product_classifications(db_session, project.id, [(CAT, "HG-1", C.UCH_SITE)], changed_by="Greg")
    db_session.refresh(req)

    assert [i.product_code for i in req.items] == ["HG-2"]
    assert [o.status for o in req.openings] == [ShopAssemblyOpeningStatus.PENDING]
    assert req.status == ShopAssemblyRequestStatus.PENDING


def test_a_save_reads_the_pending_shop_requests_once_for_every_product_leaving_the_shop(db_session, monkeypatch):
    """#1892: two products leaving the shop off two requests read the pending requests once, not once per
    product, and each product's pass still sees what the one before it did: the first leaves each opening
    the second product, and the second leaves it nothing, so it is dismissed and the request closes out."""
    from app.models.notification import Notification

    project = _project(db_session)
    a01 = _opening(db_session, project)
    _item(db_session, project, a01, "HG-1", cls=Classification.SHOP_HARDWARE)
    _item(db_session, project, a01, "HG-2", cls=Classification.SHOP_HARDWARE)
    requests = [_shop_request(db_session, project, "HG-1") for _ in range(2)]
    for req in requests:
        db_session.add(
            ShopAssemblyRequestItem(
                id=uuid.uuid4(),
                shop_assembly_request_id=req.id,
                opening_number="A01",
                hardware_category=CAT,
                product_code="HG-2",
                requested_quantity=1,
            )
        )
    db_session.flush()
    reads: list[uuid.UUID] = []
    real_read = repo._pending_shop_requests

    def read_spy(session, project_id):
        reads.append(project_id)
        return real_read(session, project_id)

    monkeypatch.setattr(repo, "_pending_shop_requests", read_spy)

    repo.set_product_classifications(
        db_session, project.id, [(CAT, "HG-1", C.UCH_SITE), (CAT, "HG-2", C.UCH_SITE)], changed_by="Greg"
    )

    assert reads == [project.id]
    for req in requests:
        db_session.refresh(req)
        assert req.items == []
        # Dismissed by whichever product's pass came second, the one that left the opening empty.
        assert [o.status for o in req.openings] == [ShopAssemblyOpeningStatus.DISMISSED]
        assert req.openings[0].dismissal_reason.startswith("Nothing left for the shop: HG-")
        assert req.status == ShopAssemblyRequestStatus.APPROVED
    notices = db_session.scalars(select(Notification).where(Notification.project_id == project.id)).all()
    assert len(notices) == 4


def test_shop_to_site_is_refused_while_an_active_batch_pull_is_unfinished(db_session):
    project = _project(db_session)
    _item(db_session, project, _opening(db_session, project), "HG-1", cls=Classification.SHOP_HARDWARE)
    batch = _batch(db_session, project, "HG-1", PullRequestStatus.IN_PROGRESS)

    with pytest.raises(ConflictError) as err:
        repo.set_product_classifications(db_session, project.id, [(CAT, "HG-1", C.UCH_SITE)], changed_by="Greg")

    assert batch.batch_number in err.value.message


def test_a_batch_whose_pull_has_not_started_is_pointed_at_discard_not_cancel(db_session):
    """#1956: a pull that hasn't started can't be cancelled, so the block says to discard the batch - and a
    started one keeps the cancel wording."""
    project = _project(db_session)
    a01 = _opening(db_session, project)
    _item(db_session, project, a01, "HG-1", cls=Classification.SHOP_HARDWARE)
    _item(db_session, project, a01, "HG-2", cls=Classification.SHOP_HARDWARE)
    unstarted = _batch(db_session, project, "HG-1", PullRequestStatus.PENDING)
    started = _batch(db_session, project, "HG-2", PullRequestStatus.IN_PROGRESS)

    plans = repo.plan_product_classifications(
        db_session, project.id, [(CAT, "HG-1", C.UCH_SITE), (CAT, "HG-2", C.UCH_SITE)]
    )

    blocks = {plan["product_code"]: plan["blocks"] for plan in plans}
    assert blocks["HG-1"] == [
        f"on shop assembly batch {unstarted.batch_number}, whose pull hasn't started - discard batch "
        f"{unstarted.batch_number} on the Shop Assembly page first"
    ]
    assert blocks["HG-2"] == [
        f"on shop assembly batch {started.batch_number}, still being pulled - finish or cancel the pull first"
    ]


def test_by_others_on_a_po_is_allowed_and_the_rows_stop_counting_as_ordered(db_session):
    """#1050 ruling: the PO does not depend on the classification - it is shown as unaffected, and the
    schedule rows lose their ordered link. Only an unclassified product can get here since #1392."""
    project = _project(db_session)
    _item(db_session, project, _opening(db_session, project), "HG-1", state=HardwareItemState.IN_PO)

    plan = repo.plan_product_classifications(db_session, project.id, [(CAT, "HG-1", C.BY_OTHERS)])
    assert plan[0]["blocks"] == []
    assert any("unaffected" in u for u in plan[0]["unaffected"])

    repo.set_product_classifications(db_session, project.id, [(CAT, "HG-1", C.BY_OTHERS)], changed_by="Greg")

    assert _choices(db_session, project)["HG-1"] == C.BY_OTHERS
    states = set(db_session.scalars(select(HardwareItem.state).where(HardwareItem.project_id == project.id)))
    assert states == {HardwareItemState.AVAILABLE}


def test_by_others_with_a_pending_shipping_request_is_allowed_and_leaves_the_request(db_session):
    project = _project(db_session)
    _item(db_session, project, _opening(db_session, project), "HG-1")
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

    plan = repo.plan_product_classifications(db_session, project.id, [(CAT, "HG-1", C.BY_OTHERS)])
    assert any(req.request_number in u for u in plan[0]["unaffected"])

    repo.set_product_classifications(db_session, project.id, [(CAT, "HG-1", C.BY_OTHERS)], changed_by="Greg")

    assert _choices(db_session, project)["HG-1"] == C.BY_OTHERS
    assert db_session.scalars(
        select(ShippingOutRequestItem).where(ShippingOutRequestItem.shipping_out_request_id == req.id)
    ).all()


@pytest.mark.parametrize(
    "classes",
    [
        [Classification.SITE_HARDWARE],
        [Classification.SHOP_HARDWARE],
        [Classification.SITE_HARDWARE, Classification.SHOP_HARDWARE],
    ],
    ids=["site", "shop", "mixed"],
)
def test_a_classified_product_cannot_go_to_by_others(db_session, classes):
    """#1392 ruling: a product that already has a classification can't be changed to By Others. The
    preview shows why; the save refuses and changes nothing."""
    project = _project(db_session)
    opening = _opening(db_session, project)
    for cls in classes:
        _item(db_session, project, opening, "HG-1", cls=cls, state=HardwareItemState.IN_PO)
    before = _choices(db_session, project)["HG-1"]

    [plan] = repo.plan_product_classifications(db_session, project.id, [(CAT, "HG-1", C.BY_OTHERS)])
    assert len(plan["blocks"]) == 1 and "can't be changed to By Others" in plan["blocks"][0]
    assert plan["adjusts"] == [] and plan["unaffected"] == []

    with pytest.raises(ConflictError) as err:
        repo.set_product_classifications(db_session, project.id, [(CAT, "HG-1", C.BY_OTHERS)], changed_by="Greg")
    assert "HG-1" in err.value.message

    assert _choices(db_session, project)["HG-1"] == before
    excluded = db_session.scalars(select(ProjectExcludedItem).where(ProjectExcludedItem.project_id == project.id))
    assert excluded.all() == []
    states = set(db_session.scalars(select(HardwareItem.state).where(HardwareItem.project_id == project.id)))
    assert states == {HardwareItemState.IN_PO}


def test_the_plan_writes_nothing(db_session):
    project = _project(db_session)
    _item(db_session, project, _opening(db_session, project), "HG-1", cls=Classification.SHOP_HARDWARE)
    _shop_request(db_session, project, "HG-1")

    plan = repo.plan_product_classifications(db_session, project.id, [(CAT, "HG-1", C.UCH_SITE)])

    assert plan[0]["adjusts"] and plan[0]["blocks"] == []
    assert _choices(db_session, project)["HG-1"] == C.UCH_SHOP


def test_a_bulk_change_with_one_blocked_product_changes_nothing(db_session):
    project = _project(db_session)
    a01 = _opening(db_session, project)
    _item(db_session, project, a01, "HG-1", cls=Classification.SHOP_HARDWARE)
    _item(db_session, project, a01, "HG-2", cls=Classification.SHOP_HARDWARE)
    _batch(db_session, project, "HG-2", PullRequestStatus.IN_PROGRESS)

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
