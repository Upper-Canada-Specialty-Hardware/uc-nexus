"""get_audit_log offset pagination (warehouse/audit.py).

The query gained an `offset` argument (default 0) so the auditLog resolver can page past the first
`limit` rows. Entries are ordered created_at desc, so the fixtures stamp explicit timestamps to make
the page boundaries deterministic.
"""

import uuid
from datetime import datetime, timedelta

from app.models.audit_log import InventoryAuditLog
from app.models.enums import AuditAction, AuditEntityType
from app.repositories import warehouse as warehouse_repository

from .inventory_fixtures import make_project


def _seed(session, project, n):
    """n audit rows for one project, oldest first. Returns their ids newest-first (query order)."""
    base = datetime(2026, 1, 1, 12, 0, 0)
    ids = []
    for i in range(n):
        entry = InventoryAuditLog(
            id=uuid.uuid4(),
            project_id=project.id,
            entity_type=AuditEntityType.INVENTORY_LOCATION,
            entity_id=uuid.uuid4(),
            action=AuditAction.ADJUSTMENT,
            detail={"i": i},
            performed_by="tester",
            created_at=base + timedelta(minutes=i),
        )
        session.add(entry)
        ids.append(entry.id)
    session.flush()
    return list(reversed(ids))  # created_at desc -> newest (highest i) first


def test_offset_pages_past_the_first_rows(db_session):
    project = make_project(db_session)
    newest_first = _seed(db_session, project, 6)

    page1 = warehouse_repository.get_audit_log(db_session, project_id=project.id, limit=2, offset=0)
    page2 = warehouse_repository.get_audit_log(db_session, project_id=project.id, limit=2, offset=2)
    page3 = warehouse_repository.get_audit_log(db_session, project_id=project.id, limit=2, offset=4)

    assert [e.id for e in page1] == newest_first[0:2]
    assert [e.id for e in page2] == newest_first[2:4]
    assert [e.id for e in page3] == newest_first[4:6]


def test_offset_defaults_to_zero(db_session):
    project = make_project(db_session)
    newest_first = _seed(db_session, project, 3)

    default_page = warehouse_repository.get_audit_log(db_session, project_id=project.id, limit=10)

    assert [e.id for e in default_page] == newest_first


def test_offset_past_the_end_returns_empty(db_session):
    project = make_project(db_session)
    _seed(db_session, project, 3)

    page = warehouse_repository.get_audit_log(db_session, project_id=project.id, limit=10, offset=5)

    assert page == []


def test_limit_still_caps_the_page(db_session):
    project = make_project(db_session)
    _seed(db_session, project, 6)

    page = warehouse_repository.get_audit_log(db_session, project_id=project.id, limit=3, offset=0)

    assert len(page) == 3
