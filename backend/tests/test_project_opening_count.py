"""The project page and a project save carry the real openings count (#1874).

Both build the project without its openings, and `project_to_type` reads 0 when no count is passed -
so the tenant-owner project page's Openings tile always read 0, and a save wrote 0 into the client's
normalized Project cache over the figure the grid had."""

import uuid

from app.auth import NEXUS_ADMIN_ROLE
from app.models.project import Opening, Project
from app.schemas import project as project_module
from app.schemas.inputs import UpdateProjectInput


class _AdminInfo:
    """An unscoped admin caller, seeded into the role memo so `tenant_scope` answers None."""

    context = {"request": None, "_auth_roles": [NEXUS_ADMIN_ROLE]}


def _borrow(monkeypatch, db_session):
    class _Borrowed:
        def __enter__(self):
            return db_session

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(project_module, "SessionLocal", _Borrowed)


def _project_with_openings(session, count: int) -> Project:
    project = Project(id=uuid.uuid4(), company="TUBC", project_id=f"J-{uuid.uuid4().hex[:6]}", description="Job")
    session.add(project)
    session.flush()
    for n in range(count):
        session.add(Opening(id=uuid.uuid4(), project_id=project.id, opening_number=f"A{n:02d}"))
    session.flush()
    return project


def test_the_project_page_carries_the_openings_count(monkeypatch, db_session):
    _borrow(monkeypatch, db_session)
    project = _project_with_openings(db_session, 3)

    detail = project_module.ProjectQueries().admin_project_detail(_AdminInfo(), id=str(project.id))

    assert detail.project.opening_count == 3
    assert detail.project.openings == []


def test_a_project_save_carries_the_count_and_builds_no_openings(monkeypatch, db_session):
    _borrow(monkeypatch, db_session)
    project = _project_with_openings(db_session, 2)

    saved = project_module._save_project_edit(project.id, UpdateProjectInput(contractor="Acme"), None)

    assert saved.opening_count == 2
    assert saved.openings == []
    assert saved.contractor == "Acme"


def test_archiving_carries_the_count(monkeypatch, db_session):
    _borrow(monkeypatch, db_session)
    project = _project_with_openings(db_session, 4)

    archived = project_module.ProjectMutations().set_project_archived(_AdminInfo(), id=str(project.id), archived=True)

    assert archived.opening_count == 4
    assert archived.archived is True
