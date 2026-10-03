"""Rows that only carry a project id name it from the project itself, archived or not (#1196)."""

import uuid
from types import SimpleNamespace

from app.models.project import Project
from app.repositories.project_labels import project_labels
from app.schemas.converters import open_po_summary_to_type


def _project(session, *, archived=False, description="Old Library") -> Project:
    p = Project(
        id=uuid.uuid4(),
        project_id=f"J-{uuid.uuid4().hex[:6]}",
        description=description,
        company="TUBC",
        archived=archived,
    )
    session.add(p)
    session.flush()
    return p


def test_an_archived_project_is_labelled(db_session):
    live = _project(db_session, description="New Wing")
    archived = _project(db_session, archived=True)

    labels = project_labels(db_session, [live.id, archived.id, None])

    assert labels == {
        live.id: (live.project_id, "New Wing"),
        archived.id: (archived.project_id, "Old Library"),
    }


def test_no_ids_runs_no_query(db_session):
    assert project_labels(db_session, [None]) == {}


def test_the_open_po_row_carries_the_label_and_a_stock_po_carries_none():
    from app.models.enums import POOrigin, POStatus

    project_id = uuid.uuid4()
    base = dict(
        po_number="PO-1",
        pool_kind=None,
        status=POStatus.GP_REGISTERED,
        origin=POOrigin.NEXUS,
        gp_vendor_id=None,
        vendor_name_snapshot=None,
        notes=None,
        ordered_at=None,
        expected_delivery_date=None,
    )
    labels = {project_id: ("23093", "Cowichan District Hospital")}

    row = open_po_summary_to_type(SimpleNamespace(id=uuid.uuid4(), project_id=project_id, **base), 0, 0, labels=labels)
    stock = open_po_summary_to_type(SimpleNamespace(id=uuid.uuid4(), project_id=None, **base), 0, 0, labels=labels)

    assert (row.project_number, row.project_description) == ("23093", "Cowichan District Hospital")
    assert (stock.project_number, stock.project_description) == (None, None)
