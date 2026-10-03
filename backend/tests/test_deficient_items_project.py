"""The deficient-items review names each row's project off the project itself (#1252)."""

import uuid

from app.auth import NEXUS_ADMIN_ROLE
from app.models.project import Project

from .inventory_fixtures import make_il


class _AdminInfo:
    """An unscoped admin caller, seeded into the role memo so `tenant_scope` answers None."""

    context = {"request": None, "_auth_roles": [NEXUS_ADMIN_ROLE]}


def test_an_archived_projects_deficient_row_is_named(monkeypatch, db_session):
    from app.schemas import stock as stock_module

    class _Borrowed:
        def __enter__(self):
            return db_session

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(stock_module, "SessionLocal", _Borrowed)
    project = Project(
        id=uuid.uuid4(), company="TUBC", project_id=f"J-{uuid.uuid4().hex[:6]}", description="Old Library"
    )
    project.archived = True
    db_session.add(project)
    db_session.flush()
    make_il(db_session, project, quantity=4, deficient=2)

    rows = stock_module.StockQueries().deficient_items(_AdminInfo(), project_id=str(project.id))

    assert [(r.project_number, r.project_description) for r in rows] == [(project.project_id, "Old Library")]
