"""Server-minted pull-request numbers (#493).

The numbers used to be typed by hand on two wizard steps, which made a uniqueness constraint the
user's problem: two people raising requests on the same project at once collided, and nothing tied
a number to the job it belonged to.
"""

import uuid

import pytest

from app.models.project import Project
from app.repositories.request_numbers import mint_request_number


def _project(session, project_id: str) -> Project:
    p = Project(id=uuid.uuid4(), project_id=project_id, description="Test", company="TUBC")
    session.add(p)
    session.flush()
    return p


def test_mints_sequentially_from_one(db_session):
    project = _project(db_session, "23093")

    assert mint_request_number(db_session, project.id) == "23093-001"
    assert mint_request_number(db_session, project.id) == "23093-002"
    assert mint_request_number(db_session, project.id) == "23093-003"


def test_each_project_has_its_own_sequence(db_session):
    a = _project(db_session, "23093")
    b = _project(db_session, "24001")

    assert mint_request_number(db_session, a.id) == "23093-001"
    assert mint_request_number(db_session, b.id) == "24001-001"
    assert mint_request_number(db_session, a.id) == "23093-002"


def test_pads_to_three_digits_then_grows(db_session):
    """The format is a floor, not a ceiling: a project past 999 requests keeps counting rather than
    wrapping into a number it has already used."""
    project = _project(db_session, "23093")
    from app.models.project_request_counter import ProjectRequestCounter

    db_session.add(ProjectRequestCounter(project_id=project.id, next_value=999))
    db_session.flush()

    assert mint_request_number(db_session, project.id) == "23093-999"
    assert mint_request_number(db_session, project.id) == "23093-1000"


def test_refuses_an_unknown_project(db_session):
    with pytest.raises(ValueError):
        mint_request_number(db_session, uuid.uuid4())
