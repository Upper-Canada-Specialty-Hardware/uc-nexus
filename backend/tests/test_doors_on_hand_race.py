"""Two first saves of one project's doors on hand at once (#1473).

The per-project row was read and inserted when missing, so two saves that both missed both inserted and the
loser hit uq_doors_on_hand_company_project as a masked server error. Two real sessions on separate
connections, the first holding its insert uncommitted while the second arrives.
"""

import threading
import time
import uuid

import pytest

from app.database import SessionLocal
from app.models.inventory_value import DoorsOnHand
from app.models.project import Project
from app.repositories import inventory_value_repository

COMPANY = "TUBC"


@pytest.fixture
def project_id(_migrate_database):
    with SessionLocal() as s:
        p = Project(id=uuid.uuid4(), project_id=f"DOH-{uuid.uuid4().hex[:8]}", description="Doors", company=COMPANY)
        s.add(p)
        s.commit()
        pid = p.id
    yield pid
    with SessionLocal() as s:
        s.query(DoorsOnHand).filter(DoorsOnHand.project_id == pid).delete()
        s.query(Project).filter(Project.id == pid).delete()
        s.commit()


def _save(pid, *, quantity: int, hold: float, start_after: float, errors: list):
    time.sleep(start_after)
    try:
        with SessionLocal() as s:
            inventory_value_repository.save_doors_on_hand(s, COMPANY, project_id=pid, quantity=quantity)
            time.sleep(hold)  # the other save arrives while this insert is uncommitted
            s.commit()
    except BaseException as e:  # noqa: BLE001 - the test reports whatever the race raised
        errors.append(e)


def test_two_first_saves_of_one_project_keep_one_row_and_the_later_number(project_id):
    errors: list = []
    threads = [
        threading.Thread(
            target=_save, args=(project_id,), kwargs={"quantity": 3, "hold": 1.0, "start_after": 0.0, "errors": errors}
        ),
        threading.Thread(
            target=_save, args=(project_id,), kwargs={"quantity": 5, "hold": 0.0, "start_after": 0.3, "errors": errors}
        ),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(15)

    assert errors == []
    with SessionLocal() as s:
        rows = s.query(DoorsOnHand).filter(DoorsOnHand.project_id == project_id).all()
        assert [r.quantity for r in rows] == [5]
