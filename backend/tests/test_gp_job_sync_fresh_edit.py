"""A job sync pass can't revert a project edit saved after it read GP (#1573).

The pass reads GP's job list, then overwrites every existing project from it. An edit saved in between -
written to GP first, GP's read-back kept - was put back to GP's older copy until the next pass."""

import uuid
from datetime import datetime, timedelta

from app.models.project import Project as ProjectModel
from app.services import gp_job_sync


def _project(session, name: str) -> ProjectModel:
    project = ProjectModel(id=uuid.uuid4(), project_id=f"J1573{uuid.uuid4().hex[:8]}", description=name, company="TUBC")
    session.add(project)
    session.flush()
    return project


def test_a_project_saved_after_the_pass_read_gp_is_left_for_the_next_pass(db_session):
    pass_started_at = datetime.utcnow()
    untouched = _project(db_session, "Old name")
    edited = _project(db_session, "New name, saved after the read")
    untouched.updated_at = pass_started_at - timedelta(minutes=5)
    edited.updated_at = pass_started_at + timedelta(seconds=2)
    db_session.flush()
    seen = {
        untouched.project_id: {"job_number": untouched.project_id, "job_name": "From GP"},
        edited.project_id: {"job_number": edited.project_id, "job_name": "Stale name from the read"},
    }

    gp_job_sync._overwrite_existing(db_session, "TUBC", seen, set(seen), pass_started_at)

    assert untouched.description == "From GP"
    assert edited.description == "New name, saved after the read"
