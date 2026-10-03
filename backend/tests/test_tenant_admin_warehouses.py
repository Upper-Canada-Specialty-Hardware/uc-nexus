"""Tenant-admin rules for warehouses and accounts (#1253, #1254, #1255, #1256).

- A cancelled pull that has to re-create a project inventory row puts it in the project's own
  company's primary building, never the oldest primary across every tenant.
- The primary warehouse is always active, and the primary lookup prefers an active building.
- Moving an account off a company gives its GP buyer id back.
- Warehouse names and codes are unique per company.

The account tests run without a database. The warehouse ones are DB-backed: they skip locally and run
in CI. Each DB test works in companies of its own, so rows other suites leave behind never decide it.
"""

import uuid

import pytest

from app.errors import ConflictError, ValidationError
from app.models.project import Project
from app.repositories import user_repository, warehouse_admin_repository


def _company() -> str:
    return f"T{uuid.uuid4().hex[:6].upper()}"


def _warehouse(session, company, *, primary=False, active=True, name=None, code=None):
    tag = uuid.uuid4().hex[:6]
    return warehouse_admin_repository.create_warehouse(
        session,
        name=name or f"WH {tag}",
        code=code or f"W{tag}",
        company=company,
        is_primary=primary,
        is_active=active,
    )


# --- #1255: a company move gives the buyer id back ---------------------------------------------------


def _capture(monkeypatch, current: dict) -> dict:
    written: dict = {}
    monkeypatch.setattr(
        user_repository,
        "_merge_public_metadata",
        lambda user_id, patch: written.update(patch) or {"id": user_id},
    )
    monkeypatch.setattr(user_repository, "_public_metadata", lambda user_id: current)
    return written


def test_moving_an_account_to_another_company_clears_its_buyer_id(monkeypatch):
    written = _capture(monkeypatch, {"company": "TUBC", "gpBuyerId": "JSMITH"})

    user_repository.update_user_company("u_1", "UBC")

    assert written == {"company": "UBC", "gpBuyerId": None}


def test_clearing_the_company_clears_the_buyer_id_too(monkeypatch):
    written = _capture(monkeypatch, {"company": "TUBC", "gpBuyerId": "JSMITH"})

    user_repository.update_user_company("u_1", None)

    assert written == {"company": None, "gpBuyerId": None}


def test_a_first_company_assignment_keeps_the_buyer_id(monkeypatch):
    written = _capture(monkeypatch, {"gpBuyerId": "JSMITH"})

    user_repository.update_user_company("u_1", "TUBC")

    assert written == {"company": "TUBC"}


def test_re_sending_the_same_company_keeps_the_buyer_id(monkeypatch):
    written = _capture(monkeypatch, {"company": "TUBC", "gpBuyerId": "JSMITH"})

    user_repository.update_user_company("u_1", " tubc ")

    assert written == {"company": "TUBC"}


# --- #1254: the primary warehouse stays active -----------------------------------------------------


def test_creating_an_inactive_primary_is_refused(db_session):
    with pytest.raises(ValidationError) as exc:
        _warehouse(db_session, _company(), primary=True, active=False)
    assert exc.value.field == "is_active"


def test_deactivating_the_primary_is_refused(db_session):
    wh = _warehouse(db_session, _company(), primary=True)

    with pytest.raises(ValidationError) as exc:
        warehouse_admin_repository.update_warehouse(db_session, wh.id, is_active=False)
    assert exc.value.field == "is_active"


def test_a_warehouse_no_longer_primary_can_be_deactivated(db_session):
    wh = _warehouse(db_session, _company(), primary=True)

    warehouse_admin_repository.update_warehouse(db_session, wh.id, is_primary=False, is_active=False)

    assert wh.is_primary is False
    assert wh.is_active is False


def test_the_primary_lookup_prefers_an_active_building(db_session):
    company = _company()
    active = _warehouse(db_session, company)
    retired_primary = _warehouse(db_session, company, primary=True)
    # A retired primary from before the guard: written directly, as the guard now refuses it.
    retired_primary.is_active = False
    db_session.flush()

    assert warehouse_admin_repository.get_primary_warehouse_id(db_session, company=company) == active.id


def test_the_active_primary_still_wins(db_session):
    company = _company()
    _warehouse(db_session, company)
    primary = _warehouse(db_session, company, primary=True)

    assert warehouse_admin_repository.get_primary_warehouse_id(db_session, company=company) == primary.id


# --- #1256: names and codes are unique per company ---------------------------------------------------


def test_two_companies_can_use_the_same_name_and_code(db_session):
    tag = uuid.uuid4().hex[:6]
    _warehouse(db_session, _company(), name=f"Main {tag}", code=f"M{tag}")
    other = _warehouse(db_session, _company(), name=f"Main {tag}", code=f"M{tag}")
    db_session.flush()

    assert other.id is not None


def test_a_name_is_still_unique_within_a_company(db_session):
    company = _company()
    tag = uuid.uuid4().hex[:6]
    _warehouse(db_session, company, name=f"Main {tag}")

    with pytest.raises(ConflictError):
        _warehouse(db_session, company, name=f"main {tag}")


def test_a_code_is_still_unique_within_a_company(db_session):
    company = _company()
    tag = uuid.uuid4().hex[:6]
    _warehouse(db_session, company, code=f"M{tag}")

    with pytest.raises(ConflictError):
        _warehouse(db_session, company, code=f"m{tag}")


def test_moving_a_warehouse_rechecks_its_name_in_the_new_company(db_session):
    tag = uuid.uuid4().hex[:6]
    source, target = _company(), _company()
    _warehouse(db_session, target, name=f"Main {tag}")
    moving = _warehouse(db_session, source, name=f"Main {tag}")

    with pytest.raises(ConflictError):
        warehouse_admin_repository.update_warehouse(db_session, moving.id, company=target)


# --- #1253: a restored row lands in the project's own company ----------------------------------------


def test_a_restored_inventory_row_lands_in_the_projects_company(db_session):
    from app.repositories.warehouse.pull_requests import _return_units_to_project_inventory

    home, elsewhere = _company(), _company()
    # The other company's primary is the older one, which an unscoped lookup would pick.
    _warehouse(db_session, elsewhere, primary=True)
    home_primary = _warehouse(db_session, home, primary=True)
    project = Project(id=uuid.uuid4(), company=home, project_id=f"RS-{uuid.uuid4().hex[:8]}", description="restore")
    db_session.add(project)
    db_session.flush()

    row = _return_units_to_project_inventory(db_session, project.id, "Hinges", "HG-100", 2)

    assert row.warehouse_id == home_primary.id


# --- #1282: a stock receive with no warehouse stays in a named company --------------------------------


def _receive(session, **kw):
    from datetime import datetime

    from app.repositories import stock as stock_repository

    return stock_repository.receive_into_stock(
        session,
        hardware_category="HINGE",
        product_code=f"SR-{uuid.uuid4().hex[:6]}",
        quantity=2,
        deficient_quantity=0,
        aisle=None,
        row=None,
        bay=None,
        received_at=datetime.utcnow(),
        received_by="warehouse",
        po_number=None,
        **kw,
    )


def test_a_stock_receive_with_no_warehouse_lands_in_the_named_companys_primary(db_session):
    home, elsewhere = _company(), _company()
    _warehouse(db_session, elsewhere, primary=True)
    home_primary = _warehouse(db_session, home, primary=True)

    row = _receive(db_session, company=home)

    assert row.warehouse_id == home_primary.id


def test_a_stock_receive_with_no_warehouse_and_no_company_is_refused(db_session):
    with pytest.raises(ValidationError) as exc:
        _receive(db_session)
    assert exc.value.field == "warehouse_id"
