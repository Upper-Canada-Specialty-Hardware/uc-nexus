import uuid

import pytest

from app.errors import NotFoundError
from app.models.project import Project as ProjectModel
from app.repositories import project_repository


def _make_project(session) -> ProjectModel:
    project = project_repository.adopt_gp_job(
        session,
        job_number=f"PRJ-{uuid.uuid4().hex[:6]}",
        job_name="orig desc",
        company="TUBC",
    )
    project.client = "orig client"
    session.flush()
    return project


def test_update_project_sets_editable_fields(db_session):
    project = _make_project(db_session)
    updated = project_repository.update_project(
        db_session,
        project.id,
        description="new desc",
        client="new client",
        job_site_name="Main St Site",
        address="123 Main St",
        city="Townsville",
        state="CA",
        zip="90210",
        contractor="BuildCo",
        project_manager="Jane PM",
        application="Commercial",
        gc_contact_name="Bob GC",
        gc_phone="555-1234",
        gc_email="bob@gc.com",
        off_site_storage_agreement=True,
    )
    db_session.refresh(updated)
    assert updated.description == "new desc"
    assert updated.client == "new client"
    assert updated.job_site_name == "Main St Site"
    assert updated.address == "123 Main St"
    assert updated.city == "Townsville"
    assert updated.state == "CA"
    assert updated.zip == "90210"
    assert updated.contractor == "BuildCo"
    assert updated.project_manager == "Jane PM"
    assert updated.application == "Commercial"
    assert updated.gc_contact_name == "Bob GC"
    assert updated.gc_phone == "555-1234"
    assert updated.gc_email == "bob@gc.com"
    assert updated.off_site_storage_agreement is True


def test_new_project_defaults_off_site_storage_agreement_false(db_session):
    project = _make_project(db_session)
    db_session.refresh(project)
    assert project.off_site_storage_agreement is False


def test_update_project_none_args_leave_other_fields_unchanged(db_session):
    project = _make_project(db_session)
    project_repository.update_project(db_session, project.id, off_site_storage_agreement=True)
    db_session.refresh(project)
    assert project.description == "orig desc"
    assert project.client == "orig client"
    assert project.off_site_storage_agreement is True


def test_update_project_does_not_change_project_id(db_session):
    project = _make_project(db_session)
    original_pid = project.project_id
    project_repository.update_project(db_session, project.id, description="changed")
    db_session.refresh(project)
    assert project.project_id == original_pid


def test_update_project_clears_text_field_with_empty_string(db_session):
    project = _make_project(db_session)
    project_repository.update_project(db_session, project.id, description="")
    db_session.refresh(project)
    assert project.description == ""


def test_update_project_unknown_id_raises_not_found(db_session):
    with pytest.raises(NotFoundError):
        project_repository.update_project(db_session, uuid.uuid4(), description="x")
