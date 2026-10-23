"""An archived project is read off the record itself, not the picker list (#1877).

`projects` leaves archived jobs out, and three screens looked a project up there: PO detail showed
"Project -" for an archived job's PO, receiving skipped the quarantine warning and the closed-job block
for one, and the shipping requests picker read blank when a link scoped it to one. The PO now carries
its own project, and a project can be read by its id, archived included."""

import json
import uuid
from datetime import date

from sqlalchemy import event

from app.auth import NEXUS_ADMIN_ROLE
from app.models.enums import GpJobState, POStatus
from app.models.project import Opening, Project
from app.models.purchase_order import PurchaseOrder
from app.schemas import po as po_module
from app.schemas import project as project_module
from app.schemas import warehouse as warehouse_module


class _AdminInfo:
    """An unscoped admin caller, seeded into the role memo so `tenant_scope` answers None."""

    context = {"request": None, "_auth_roles": [NEXUS_ADMIN_ROLE]}


def _borrow(monkeypatch, db_session, *modules):
    class _Borrowed:
        def __enter__(self):
            return db_session

        def __exit__(self, *exc):
            return False

    for module in modules:
        monkeypatch.setattr(module, "SessionLocal", _Borrowed)


def _archived_project(session, **values) -> Project:
    project = Project(
        id=uuid.uuid4(), company="TUBC", project_id=f"J-{uuid.uuid4().hex[:6]}", description="Old Library", **values
    )
    project.archived = True
    session.add(project)
    session.flush()
    return project


def _po(session, project) -> PurchaseOrder:
    po = PurchaseOrder(
        id=uuid.uuid4(),
        company="TUBC",
        po_number=f"PO-{uuid.uuid4().hex[:8]}",
        request_number=None,
        project_id=project.id if project is not None else None,
        status=POStatus.GP_REGISTERED,
        gp_company="TUBC",
        vendor_name_snapshot="Acme",
        ordered_at=date.today(),
    )
    session.add(po)
    session.flush()
    return po


def test_the_po_type_publishes_its_project():
    from main import schema

    fields = schema._schema.type_map["PurchaseOrder"].fields
    assert str(fields["project"].type) == "PurchaseOrderProject"
    project_fields = schema._schema.type_map["PurchaseOrderProject"].fields
    assert {"id", "projectId", "description", "archived", "gpJobState", "gpSetupOk", "gpSetupIssues"} <= set(
        project_fields
    )


def test_an_archived_projects_po_names_its_project(monkeypatch, db_session):
    _borrow(monkeypatch, db_session, po_module)
    project = _archived_project(db_session)
    po = _po(db_session, project)

    result = po_module.POQueries().purchase_order(_AdminInfo(), id=str(po.id))

    assert (result.project.project_id, result.project.description, result.project.archived) == (
        project.project_id,
        "Old Library",
        True,
    )


def test_receiving_reads_an_archived_projects_job_state_and_setup(monkeypatch, db_session):
    _borrow(monkeypatch, db_session, warehouse_module)
    project = _archived_project(
        db_session,
        gp_job_state=GpJobState.CLOSED,
        gp_setup_ok=False,
        gp_setup_detail=json.dumps([{"cost_code": "210-200-2", "account_index": 1617}]),
    )
    po = _po(db_session, project)

    result = warehouse_module.WarehouseQueries().po_receiving_details(_AdminInfo(), po_id=str(po.id))

    assert result.project.gp_job_state == GpJobState.CLOSED
    assert result.project.gp_setup_ok is False
    assert [(i.cost_code, i.account_index) for i in result.project.gp_setup_issues] == [("210-200-2", 1617)]


def test_a_stock_po_has_no_project(monkeypatch, db_session):
    _borrow(monkeypatch, db_session, po_module)
    po = _po(db_session, None)

    assert po_module.POQueries().purchase_order(_AdminInfo(), id=str(po.id)).project is None


def test_a_po_list_reads_its_projects_in_one_query(monkeypatch, db_session):
    """No N+1 (CLAUDE.md perf rules): the list resolver reads every PO's project in one batch."""
    _borrow(monkeypatch, db_session, po_module)
    project = _archived_project(db_session)
    other = _archived_project(db_session)
    for p in (project, project, other):
        _po(db_session, p)
    db_session.expire_all()

    statements: list[str] = []

    def _count(conn, cursor, statement, *args):
        if "FROM projects" in statement:
            statements.append(statement)

    engine = db_session.get_bind().engine
    event.listen(engine, "before_cursor_execute", _count)
    try:
        rows = po_module.POQueries().purchase_orders(_AdminInfo())
    finally:
        event.remove(engine, "before_cursor_execute", _count)

    named = {r.project.project_id for r in rows if r.project is not None}
    assert {project.project_id, other.project_id} <= named
    assert len(statements) == 1


def test_a_project_is_read_by_id_archived_included(monkeypatch, db_session):
    _borrow(monkeypatch, db_session, project_module)
    project = _archived_project(db_session)
    db_session.add(Opening(id=uuid.uuid4(), project_id=project.id, opening_number="A01"))
    db_session.flush()

    result = project_module.ProjectQueries().project(_AdminInfo(), id=str(project.id))

    assert (result.project_id, result.archived, result.opening_count, result.openings) == (
        project.project_id,
        True,
        1,
        [],
    )


def test_a_project_by_id_is_scoped_to_the_callers_company(monkeypatch, db_session):
    _borrow(monkeypatch, db_session, project_module)
    project = _archived_project(db_session)
    monkeypatch.setattr(project_module, "tenant_scope", lambda info: "UCSH")

    assert project_module.ProjectQueries().project(_AdminInfo(), id=str(project.id)) is None
