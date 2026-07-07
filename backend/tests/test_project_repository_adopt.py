import uuid

import pytest

from app.errors import ConflictError
from app.repositories import project_repository


def test_adopt_gp_job_creates_project_with_job_number_as_identity(db_session):
    job_number = f"JOB-{uuid.uuid4().hex[:6]}"
    project = project_repository.adopt_gp_job(db_session, job_number=job_number, job_name="123 Main St Reno")
    assert project.project_id == job_number
    assert project.description == "123 Main St Reno"
    assert project.client is None


def test_adopt_gp_job_allows_missing_job_name(db_session):
    job_number = f"JOB-{uuid.uuid4().hex[:6]}"
    project = project_repository.adopt_gp_job(db_session, job_number=job_number, job_name=None)
    assert project.project_id == job_number
    assert project.description is None


def test_adopt_gp_job_rejects_a_job_already_adopted(db_session):
    job_number = f"JOB-{uuid.uuid4().hex[:6]}"
    project_repository.adopt_gp_job(db_session, job_number=job_number, job_name="First pick")

    with pytest.raises(ConflictError):
        project_repository.adopt_gp_job(db_session, job_number=job_number, job_name="Second pick")
