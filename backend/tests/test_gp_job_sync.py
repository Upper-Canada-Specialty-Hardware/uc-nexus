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


def _relay(monkeypatch, *, company="TUBC", jobs=None, raises=None, health=None, health_raises=None):
    """Fake the relay socket. `health` is the job_setup_health answer (#425); left None it echoes the
    job list as all-healthy, so the existing adoption tests are unaffected by the health pass."""
    calls: list[tuple] = []

    async def _call(_company, op, payload=None, timeout=None):
        calls.append((_company, op, payload))
        if op == "job_setup_health":
            if health_raises is not None:
                raise health_raises
            if health is not None:
                return {"jobs": health}
            reported = JOBS if jobs is None else jobs
            return {"jobs": [{"job_number": j.get("job_number"), "ok": True, "issues": []} for j in reported]}
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


# --- GP setup health stamping (#425) ---------------------------------------------------------------
# Every pass also asks GP whether each job's cost codes point at accounts this company actually has,
# and stamps the answer on the project. A job replicated from UCSH before 2023 carries UCSH account
# indexes, which makes a PO on it registerable and permanently unreceivable - the stamp is how Nexus
# finds out before somebody spends a PO on it.


def _stamps(prefix="SYNC-380-"):
    with SessionLocal() as session:
        return {
            p.project_id: (p.gp_setup_ok, p.gp_setup_detail, p.gp_setup_checked_at is not None)
            for p in session.query(ProjectModel).filter(ProjectModel.project_id.like(f"{prefix}%")).all()
        }


def test_stamps_the_setup_verdict_on_every_reported_job(monkeypatch):
    _relay(
        monkeypatch,
        health=[
            {"job_number": "SYNC-380-A", "ok": True, "issues": []},
            {
                "job_number": "SYNC-380-B",
                "ok": False,
                "issues": [{"cost_code": "210-200-2", "account_index": 1617}],
            },
        ],
    )

    asyncio.run(gp_job_sync.run_once())

    stamps = _stamps()
    assert stamps["SYNC-380-A"][0] is True
    assert stamps["SYNC-380-A"][1] is None  # a healthy job carries no stale detail
    assert stamps["SYNC-380-B"][0] is False
    assert "210-200-2" in stamps["SYNC-380-B"][1]
    assert "1617" in stamps["SYNC-380-B"][1]
    assert all(checked for _, _, checked in stamps.values())


def test_a_job_adopted_this_pass_is_stamped_on_the_same_pass(monkeypatch):
    """The health read runs AFTER adoption on purpose - a job GP has only just started reporting gets
    its project and its verdict together rather than a whole poll interval apart."""
    _relay(monkeypatch, health=[{"job_number": "SYNC-380-A", "ok": False, "issues": []}])

    total, adopted = asyncio.run(gp_job_sync.run_once())

    assert adopted == 2
    assert _stamps()["SYNC-380-A"][0] is False


def test_a_failed_health_call_does_not_break_job_adoption(monkeypatch):
    """The verdict is an annotation; adoption is the invariant this service exists for. A relay too
    old for the op, or a GP read that times out, must cost the pass nothing."""
    _relay(monkeypatch, health_raises=RuntimeError("relay too old for job_setup_health"))

    total, adopted = asyncio.run(gp_job_sync.run_once())

    assert (total, adopted) == (2, 2)
    assert set(_projects()) == {"SYNC-380-A", "SYNC-380-B"}
    assert all(ok is None for ok, _, _ in _stamps().values())  # nothing stamped, nothing invented


def test_a_failed_health_call_leaves_an_existing_stamp_alone(monkeypatch):
    """Blanking on failure would un-quarantine a broken project on a transient relay blip. A stale
    verdict is still a verdict."""
    _relay(monkeypatch, health=[{"job_number": "SYNC-380-A", "ok": False, "issues": []}])
    asyncio.run(gp_job_sync.run_once())

    _relay(monkeypatch, health_raises=RuntimeError("relay went away"))
    asyncio.run(gp_job_sync.run_once())

    assert _stamps()["SYNC-380-A"][0] is False


def test_the_health_op_is_asked_for_the_whole_company(monkeypatch):
    # No job filter on the sync pass: one sweep for ~900 jobs, not 900 round trips.
    calls = _relay(monkeypatch)

    asyncio.run(gp_job_sync.run_once())

    health_calls = [c for c in calls if c[1] == "job_setup_health"]
    assert len(health_calls) == 1
    assert health_calls[0][2] in (None, {})


def test_the_live_single_job_check_filters_to_that_job(monkeypatch):
    calls = _relay(monkeypatch, health=[{"job_number": "SYNC-380-B", "ok": False, "issues": []}])

    verdict = asyncio.run(gp_job_sync.check_job_setup_live("TUBC", "SYNC-380-B"))

    assert verdict["ok"] is False
    assert calls[0] == ("TUBC", "job_setup_health", {"job": "SYNC-380-B"})


def test_the_live_check_returns_none_when_it_cannot_run(monkeypatch):
    """None is "could not check", not "healthy". register_po_in_gp falls back to the stamped verdict
    on None rather than refusing - a relay blip must not brick PO registration."""
    _relay(monkeypatch, health_raises=RuntimeError("relay unavailable"))

    assert asyncio.run(gp_job_sync.check_job_setup_live("TUBC", "SYNC-380-A")) is None


def test_the_live_check_returns_none_for_a_job_gp_does_not_report(monkeypatch):
    _relay(monkeypatch, health=[])

    assert asyncio.run(gp_job_sync.check_job_setup_live("TUBC", "GHOST")) is None
