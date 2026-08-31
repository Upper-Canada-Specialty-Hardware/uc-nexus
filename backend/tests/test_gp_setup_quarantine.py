"""The server-side GP setup quarantine (#425).

A project whose GP job carries JC00701 cost codes pointing at GL account indexes this company does not
have can be ordered against and never received - eConnect rejects the receipt line with 4612 "Invalid
Account Index", and by then the hardware is in the building. So the sync stamps a verdict on every
project and `require_gp_setup_ok` is the wall every write action hits.

The rule that gets tested hardest here is the one that is easy to get wrong in the safe-looking
direction: **null does not quarantine**. The stamp only exists while a relay is connected, so treating
"never checked" as "broken" would let a relay outage - or a fresh database - freeze the whole of Nexus,
including the actions that never touch GP at all.
"""

import json
import uuid
from datetime import datetime

import pytest

from app.errors import GpSetupInvalidError
from app.models.project import Project as ProjectModel
from app.repositories import project_repository

pytestmark = pytest.mark.usefixtures("_migrate_database")


def _project(session, *, ok=None, detail=None, job=None):
    project = ProjectModel(
        id=uuid.uuid4(),
        project_id=job or f"QT-425-{uuid.uuid4().hex[:8]}",
        description="Quarantine fixture",
        gp_setup_ok=ok,
        gp_setup_detail=detail,
        gp_setup_checked_at=datetime.utcnow() if ok is not None else None,
        company="TUBC",
    )
    session.add(project)
    session.flush()
    return project


_BROKEN = json.dumps([{"cost_code": "210-200-2", "account_index": 1617}])


# --- require_gp_setup_ok: what blocks and what does not ---


def test_a_false_verdict_blocks(db_session):
    project = _project(db_session, ok=False, detail=_BROKEN)

    with pytest.raises(GpSetupInvalidError) as excinfo:
        project_repository.require_gp_setup_ok(db_session, project.id)

    assert excinfo.value.code == "GP_SETUP_INVALID"


def test_a_true_verdict_passes(db_session):
    project = _project(db_session, ok=True)
    project_repository.require_gp_setup_ok(db_session, project.id)  # must not raise


def test_a_null_verdict_passes(db_session):
    """Never checked is not broken. The sync only runs while a relay is connected, so quarantining on
    null would mean a relay outage froze every project in the application."""
    project = _project(db_session, ok=None)
    project_repository.require_gp_setup_ok(db_session, project.id)


def test_no_project_passes(db_session):
    # A draft PO with no project has no GP job that could be broken.
    project_repository.require_gp_setup_ok(db_session, None)


def test_an_unknown_project_passes(db_session):
    # Not this gate's job to decide a missing project is an error; the caller's own lookup says so.
    project_repository.require_gp_setup_ok(db_session, uuid.uuid4())


# --- the message has to name what accounting must fix ---


def test_the_message_names_the_cost_code_and_the_account_index(db_session):
    project = _project(db_session, ok=False, detail=_BROKEN, job="23093")

    with pytest.raises(GpSetupInvalidError) as excinfo:
        project_repository.require_gp_setup_ok(db_session, project.id)

    message = excinfo.value.message
    assert "23093" in message
    assert "210-200-2" in message
    assert "1617" in message
    assert excinfo.value.issues == [{"cost_code": "210-200-2", "account_index": 1617}]


def test_the_message_caps_the_list_and_says_how_many_were_hidden(db_session):
    # The 62 affected production jobs average 24 broken codes each; an error listing all of them is
    # one nobody reads.
    detail = json.dumps([{"cost_code": f"3{i:02d}-000-3", "account_index": 1600 + i} for i in range(10)])
    project = _project(db_session, ok=False, detail=detail)

    with pytest.raises(GpSetupInvalidError) as excinfo:
        project_repository.require_gp_setup_ok(db_session, project.id)

    assert "and 7 more" in excinfo.value.message


def test_a_broken_project_with_no_detail_still_blocks(db_session):
    project = _project(db_session, ok=False, detail=None)

    with pytest.raises(GpSetupInvalidError):
        project_repository.require_gp_setup_ok(db_session, project.id)


def test_unparseable_detail_does_not_break_the_gate(db_session):
    """gp_setup_detail is JSON text written from whatever the relay reported. Garbage in it must
    degrade to "broken, details unavailable" - it is read on every project query, so a parse error
    here would take out the project list, not just this message."""
    project = _project(db_session, ok=False, detail="{not json")

    with pytest.raises(GpSetupInvalidError) as excinfo:
        project_repository.require_gp_setup_ok(db_session, project.id)

    assert excinfo.value.issues == []


# --- parse_gp_setup_issues ---


def test_parse_handles_the_shapes_that_are_not_a_list_of_objects():
    assert project_repository.parse_gp_setup_issues(None) == []
    assert project_repository.parse_gp_setup_issues("") == []
    assert project_repository.parse_gp_setup_issues("nonsense") == []
    assert project_repository.parse_gp_setup_issues('{"cost_code": "x"}') == []
    assert project_repository.parse_gp_setup_issues('["bare string"]') == []


def test_parse_returns_the_pairs():
    assert project_repository.parse_gp_setup_issues(_BROKEN) == [{"cost_code": "210-200-2", "account_index": 1617}]


# --- stamp_gp_setup_health ---


def test_stamping_records_the_verdict_and_the_detail(db_session):
    project = _project(db_session, job=f"QT-425-{uuid.uuid4().hex[:8]}")

    project_repository.stamp_gp_setup_health(
        db_session,
        {
            project.project_id: {
                "ok": False,
                "issues": [{"cost_code": "210-200-2", "account_index": 1617}],
            }
        },
        "TUBC",
    )

    db_session.refresh(project)
    assert project.gp_setup_ok is False
    assert project.gp_setup_checked_at is not None
    assert json.loads(project.gp_setup_detail) == [{"cost_code": "210-200-2", "account_index": 1617}]


def test_a_healthy_verdict_clears_the_detail(db_session):
    """Once accounting repairs the job, the next pass has to clear the stale list of broken codes -
    leaving it would keep the banner naming codes that are now fine."""
    project = _project(db_session, ok=False, detail=_BROKEN)

    project_repository.stamp_gp_setup_health(db_session, {project.project_id: {"ok": True, "issues": []}}, "TUBC")

    db_session.refresh(project)
    assert project.gp_setup_ok is True
    assert project.gp_setup_detail is None


def test_a_project_gp_did_not_report_is_left_alone(db_session):
    """A verdict absent from the answer says nothing about the job. Blanking it would silently
    un-quarantine a broken project every time the single-job filter was used."""
    untouched = _project(db_session, ok=False, detail=_BROKEN)
    reported = _project(db_session)

    project_repository.stamp_gp_setup_health(db_session, {reported.project_id: {"ok": True, "issues": []}}, "TUBC")

    db_session.refresh(untouched)
    assert untouched.gp_setup_ok is False
    assert untouched.gp_setup_detail == _BROKEN


def test_stamping_an_empty_verdict_map_touches_nothing(db_session):
    project = _project(db_session, ok=True)
    assert project_repository.stamp_gp_setup_health(db_session, {}, "TUBC") == 0
    db_session.refresh(project)
    assert project.gp_setup_ok is True
