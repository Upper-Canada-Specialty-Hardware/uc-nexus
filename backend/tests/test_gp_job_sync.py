"""The GP job sync: every job in GP becomes a project, exactly once (#380).

This is what replaced the manual Adopt GP Job dialog, so it has to be safe to run repeatedly and on a
timer: a second pass must adopt nothing, a job racing a concurrent createGpJob must not blow up the
pass, and one unusable job must not cost the others. A sync that dies quietly is invisible until
somebody asks why a job is missing from Nexus.
"""

import asyncio

import pytest

from app.database import SessionLocal
from app.errors import RelayUnavailableError
from app.models.project import Project as ProjectModel
from app.repositories import project_repository
from app.services import gp_job_sync

pytestmark = pytest.mark.usefixtures("_migrate_database")

JOBS = [
    {"job_number": "SYNC-380-A", "job_name": "First job"},
    {"job_number": "SYNC-380-B", "job_name": "Second job"},
]


@pytest.fixture(autouse=True)
def _clean_up_test_projects(_migrate_database):
    """These write through the service's own sessions, so the db_session rollback fixture can't cover
    them - remove what the test created instead.

    Takes _migrate_database explicitly so the no-DATABASE_URL skip fires during ITS setup. Left autouse
    alone, this fixture's teardown would still run after a skipped test and open a session anyway."""
    yield
    with SessionLocal() as session:
        for project in session.query(ProjectModel).filter(ProjectModel.project_id.like("SYNC-380-%")).all():
            session.delete(project)
        session.commit()


def _relay(monkeypatch, *, company="TUBC", jobs=None, raises=None):
    calls: list[tuple] = []

    async def _call(_company, op, payload=None, timeout=None):
        calls.append((_company, op, payload))
        if raises is not None:
            raise raises
        return {"jobs": JOBS if jobs is None else jobs}

    monkeypatch.setattr(type(gp_job_sync.relay_gateway), "company", property(lambda self: company))
    monkeypatch.setattr(type(gp_job_sync.relay_gateway), "connected", property(lambda self: company is not None))
    monkeypatch.setattr(gp_job_sync.relay_gateway, "relay_call", _call)
    return calls


def _projects(prefix="SYNC-380-"):
    with SessionLocal() as session:
        return {
            p.project_id: p.description
            for p in session.query(ProjectModel).filter(ProjectModel.project_id.like(f"{prefix}%")).all()
        }


def test_creates_a_project_for_every_gp_job(monkeypatch):
    _relay(monkeypatch)

    total, adopted = asyncio.run(gp_job_sync.run_once())

    assert (total, adopted) == (2, 2)
    assert _projects() == {"SYNC-380-A": "First job", "SYNC-380-B": "Second job"}


def test_a_second_pass_adopts_nothing(monkeypatch):
    _relay(monkeypatch)
    asyncio.run(gp_job_sync.run_once())

    total, adopted = asyncio.run(gp_job_sync.run_once())

    assert (total, adopted) == (2, 0)  # still counted, just not re-created
    assert len(_projects()) == 2


def test_adopts_only_the_jobs_that_are_missing(monkeypatch):
    with SessionLocal() as session:
        project_repository.adopt_gp_job(session, job_number="SYNC-380-A", job_name="Already here")
        session.commit()
    _relay(monkeypatch)

    total, adopted = asyncio.run(gp_job_sync.run_once())

    assert (total, adopted) == (2, 1)
    # the existing project keeps its own snapshot; the sync does not restate names
    assert _projects()["SYNC-380-A"] == "Already here"


def test_survives_a_job_it_cannot_adopt(monkeypatch):
    """One unusable job must not cost the others in the same pass.

    The failure is injected rather than provoked with bad data: project_id has no length cap, so an
    absurd job number adopts perfectly well, and there is no input the sync can be handed that is
    reliably rejected. What matters is the handling, so raise from the write itself."""
    _relay(monkeypatch, jobs=[{"job_number": "SYNC-380-A", "job_name": "Fine"}, {"job_number": "SYNC-380-BAD"}])
    real_adopt = project_repository.adopt_gp_job

    def _explode(session, *, job_number, job_name):
        if job_number == "SYNC-380-BAD":
            raise RuntimeError("whatever the database refuses this row for")
        return real_adopt(session, job_number=job_number, job_name=job_name)

    monkeypatch.setattr(gp_job_sync.project_repository, "adopt_gp_job", _explode)

    total, adopted = asyncio.run(gp_job_sync.run_once())

    assert (total, adopted) == (2, 1)
    assert "SYNC-380-A" in _projects()
    assert "SYNC-380-BAD" not in _projects()


def test_ignores_blank_and_duplicate_job_numbers(monkeypatch):
    _relay(
        monkeypatch,
        jobs=[
            {"job_number": "SYNC-380-A", "job_name": "First job"},
            {"job_number": "  ", "job_name": "Nothing"},
            {"job_number": "SYNC-380-A", "job_name": "Same again"},
        ],
    )

    total, adopted = asyncio.run(gp_job_sync.run_once())

    assert (total, adopted) == (1, 1)


def test_refuses_when_no_relay_is_connected(monkeypatch):
    _relay(monkeypatch, company=None)

    with pytest.raises(RelayUnavailableError):
        asyncio.run(gp_job_sync.run_once())


def test_a_relay_error_does_not_kill_the_loop(monkeypatch):
    # One failed pass must leave the service running; the next one retries.
    _relay(monkeypatch, raises=RuntimeError("relay exploded"))
    monkeypatch.setattr(gp_job_sync, "POLL_SECONDS", 0.01)

    async def _one_iteration():
        task = asyncio.create_task(gp_job_sync.run_forever())
        await asyncio.sleep(0.05)
        still_running = not task.done()
        task.cancel()
        return still_running

    assert asyncio.run(_one_iteration()) is True


def test_kill_switch_reads_the_environment(monkeypatch):
    monkeypatch.delenv("GP_JOB_SYNC_ENABLED", raising=False)
    assert gp_job_sync.enabled() is True
    monkeypatch.setenv("GP_JOB_SYNC_ENABLED", "false")
    assert gp_job_sync.enabled() is False


def test_wake_is_safe_before_the_loop_has_started(monkeypatch):
    monkeypatch.setattr(gp_job_sync, "_wake_event", None)
    gp_job_sync.wake()  # must not raise - /relay-link calls this on every registration
