"""The primary-warehouse flag is per company (#919).

`get_primary_warehouse_id` reads the flag within one company, but marking a warehouse primary used to
clear the flag on every company's buildings - so giving UBC a primary would silently un-primary TUBC's.
DB-backed: skips locally, runs in CI.
"""

import uuid

from app.models.warehouse import Warehouse
from app.repositories import warehouse_admin_repository


def _make(session, company: str, *, primary: bool) -> Warehouse:
    tag = uuid.uuid4().hex[:6]
    return warehouse_admin_repository.create_warehouse(
        session, name=f"WH {company} {tag}", code=f"{company[:3]}{tag}", company=company, is_primary=primary
    )


def test_creating_a_primary_leaves_another_companys_primary_alone(db_session):
    tubc = _make(db_session, "TUBC", primary=True)
    ubc = _make(db_session, "UBC", primary=True)
    db_session.flush()
    db_session.refresh(tubc)

    assert tubc.is_primary is True
    assert ubc.is_primary is True


def test_creating_a_primary_still_replaces_the_same_companys_primary(db_session):
    first = _make(db_session, "TUBC", primary=True)
    second = _make(db_session, "TUBC", primary=True)
    db_session.flush()
    db_session.refresh(first)

    assert first.is_primary is False
    assert second.is_primary is True


def test_making_one_primary_on_update_only_touches_its_own_company(db_session):
    tubc = _make(db_session, "TUBC", primary=True)
    ubc_old = _make(db_session, "UBC", primary=True)
    ubc_new = _make(db_session, "UBC", primary=False)
    db_session.flush()

    warehouse_admin_repository.update_warehouse(db_session, ubc_new.id, is_primary=True)
    db_session.flush()
    for wh in (tubc, ubc_old, ubc_new):
        db_session.refresh(wh)

    assert tubc.is_primary is True
    assert ubc_old.is_primary is False
    assert ubc_new.is_primary is True
