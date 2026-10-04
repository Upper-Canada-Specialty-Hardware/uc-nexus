"""Three races #1402 closed: an overlapping receive retry, a project's first request numbers, and
names or codes that differ only by case.

Each test reproduces the window the pre-check used to leave open (by hiding the pre-check, or with
two real sessions) and pins that the database rule or the locked re-check now answers it.
"""

import threading
import time
import uuid

import pytest

from app.database import SessionLocal
from app.errors import ConflictError
from app.models.project import Project
from app.models.project_request_counter import ProjectRequestCounter
from app.models.receive_draft import ReceiveDraft
from app.repositories import custom_items_repository, warehouse_admin_repository
from app.repositories import warehouse as warehouse_repository
from app.repositories.request_numbers import mint_request_number
from app.repositories.warehouse import receive_drafts
from tests.test_receive_drafts import AUTHOR, AUTHOR_NAME, _lines, _make_po, _make_project, _packing_slip

# --- an overlapping receive retry gets its own draft back -----------------------------------------


def test_a_retry_overlapping_the_first_submit_returns_its_draft(db_session, monkeypatch):
    project = _make_project(db_session)
    po, li = _make_po(db_session, project.id)
    slip = _packing_slip(db_session, po)

    def submit():
        return warehouse_repository.create_receive_draft(
            db_session,
            po.id,
            _lines(li, 3),
            AUTHOR,
            AUTHOR_NAME,
            idempotency_key="k-overlap",
            packing_slip_document_id=slip.id,
        )

    first = submit()
    db_session.flush()

    # The retry's unlocked first look ran before the first submit committed, so it saw nothing; only
    # the look under the PO lock can find the draft.
    real = receive_drafts._draft_for_create_key
    calls = {"n": 0}

    def first_look_misses(session, key):
        calls["n"] += 1
        return None if calls["n"] == 1 else real(session, key)

    monkeypatch.setattr(receive_drafts, "_draft_for_create_key", first_look_misses)
    second = submit()

    assert second.id == first.id
    assert calls["n"] == 2
    assert db_session.query(ReceiveDraft).filter(ReceiveDraft.po_id == po.id).count() == 1


# --- the first two request numbers on a project ------------------------------------------------------


@pytest.mark.usefixtures("_migrate_database")
def test_the_first_two_requests_at_once_on_a_project_both_get_a_number():
    with SessionLocal() as s:
        project = Project(id=uuid.uuid4(), project_id=f"P{uuid.uuid4().hex[:6]}", description="race", company="TUBC")
        s.add(project)
        s.commit()
        project_id = project.id

    numbers: list[str] = []
    errors: list[BaseException] = []

    def mint(hold: float, start_after: float):
        time.sleep(start_after)
        try:
            with SessionLocal() as s:
                numbers.append(mint_request_number(s, project_id))
                time.sleep(hold)  # keep the counter row's lock while the other one arrives
                s.commit()
        except BaseException as e:  # noqa: BLE001 - the test reports whatever the race raised
            errors.append(e)

    try:
        a = threading.Thread(target=mint, args=(1.0, 0.0))
        b = threading.Thread(target=mint, args=(0.0, 0.3))
        a.start()
        b.start()
        a.join(10)
        b.join(10)
        assert errors == []
        assert sorted(n.rsplit("-", 1)[1] for n in numbers) == ["001", "002"]
    finally:
        with SessionLocal() as s:
            s.query(ProjectRequestCounter).filter(ProjectRequestCounter.project_id == project_id).delete()
            s.query(Project).filter(Project.id == project_id).delete()
            s.commit()


# --- names and codes are unique regardless of case ---------------------------------------------------


def _company() -> str:
    return f"T{uuid.uuid4().hex[:6].upper()}"


def test_a_warehouse_name_differing_only_by_case_is_refused_by_the_database(db_session, monkeypatch):
    company = _company()
    warehouse_admin_repository.create_warehouse(db_session, name="Main", code="MAIN", company=company)
    # Two saves racing both passed the unlocked check; the index is what answers now.
    monkeypatch.setattr(warehouse_admin_repository, "_check_name_unique", lambda *a, **k: None)
    with pytest.raises(ConflictError, match="named 'main' already exists"):
        warehouse_admin_repository.create_warehouse(db_session, name="main", code="OTHER", company=company)


def test_a_warehouse_code_differing_only_by_case_is_refused_by_the_database(db_session, monkeypatch):
    company = _company()
    warehouse_admin_repository.create_warehouse(db_session, name="North", code="NORTH", company=company)
    monkeypatch.setattr(warehouse_admin_repository, "_check_code_unique", lambda *a, **k: None)
    with pytest.raises(ConflictError, match="code 'north' already exists"):
        warehouse_admin_repository.create_warehouse(db_session, name="North two", code="north", company=company)


def test_a_rename_into_another_warehouses_name_is_refused_by_the_database(db_session, monkeypatch):
    company = _company()
    warehouse_admin_repository.create_warehouse(db_session, name="Main", code="MAIN", company=company)
    other = warehouse_admin_repository.create_warehouse(db_session, name="Annex", code="ANNEX", company=company)
    monkeypatch.setattr(warehouse_admin_repository, "_check_name_unique", lambda *a, **k: None)
    with pytest.raises(ConflictError, match="already exists"):
        warehouse_admin_repository.update_warehouse(db_session, other.id, name="MAIN")


def test_an_item_type_name_differing_only_by_case_is_refused_by_the_database(db_session, monkeypatch):
    company = _company()
    custom_items_repository.create_item_type(db_session, name="Door Sweeps", code="SWEEPS_A", company=company)
    monkeypatch.setattr(custom_items_repository, "_check_type_name_free", lambda *a, **k: None)
    with pytest.raises(ConflictError) as exc:
        custom_items_repository.create_item_type(db_session, name="door sweeps", code="SWEEPS_B", company=company)
    assert exc.value.field == "name"


def test_an_attribute_name_differing_only_by_case_is_refused_by_the_database(db_session, monkeypatch):
    company = _company()
    item_type = custom_items_repository.create_item_type(db_session, name="Frames", code="FRAMES_X", company=company)
    custom_items_repository.create_attribute(db_session, type_id=item_type.id, name="Fire Rating")
    monkeypatch.setattr(custom_items_repository, "_check_attribute_name_free", lambda *a, **k: None)
    with pytest.raises(ConflictError) as exc:
        custom_items_repository.create_attribute(db_session, type_id=item_type.id, name="fire rating")
    assert exc.value.field == "name"


def test_names_that_differ_only_by_case_in_different_companies_are_both_fine(db_session):
    warehouse_admin_repository.create_warehouse(db_session, name="Main", code="MAIN", company=_company())
    warehouse_admin_repository.create_warehouse(db_session, name="main", code="main", company=_company())
