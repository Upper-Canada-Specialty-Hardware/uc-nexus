"""createGpJob: admin gate, relay gating, GP error surfacing, and what gets persisted (#380).

The mutation writes to GP through the relay and only then creates the Nexus project, so these pin the
order and the failure modes rather than the happy path alone: a relay that isn't there must stop the
call before GP is touched, and a proc rejection must reach the dialog in the proc's own words - that
message ("Job cannot be created within a closed period") is the only thing telling the user what to fix.
"""

import asyncio
from datetime import date

import pytest

from app.auth import ADMIN_ROLE
from app.auth_policy import ROOT_FIELD_POLICY
from app.database import SessionLocal
from app.errors import ConflictError, RelayCallError, RelayUnavailableError, ValidationError
from app.models.project import Project as ProjectModel
from app.schemas import project as project_module
from app.schemas.inputs import CreateGpJobInput
from app.schemas.project import ProjectMutations


class _FakeInfo:
    context = {"request": None}


@pytest.fixture
def _clean_up_test_projects(_migrate_database):
    """The persist runs through the resolver's OWN SessionLocal and commits, so the db_session rollback
    fixture cannot reach it. Without this the row survives the run and the next one fails on
    adopt_gp_job's already-adopted check - invisible in CI, which starts from a fresh database."""
    yield
    with SessionLocal() as session:
        for project in session.query(ProjectModel).filter(ProjectModel.project_id.like("NEXUS-380-%")).all():
            session.delete(project)
        session.commit()


def _input(**overrides):
    fields = {
        "job_number": "NEXUS-380-T1",
        "job_name": "Test job",
        "division": "VANCOUVER",
        "customer_number": "ELL100",
        "job_address_code": "MAIN",
        "billto_address_code": "MAIN",
        "tax_schedule_id": "GST 5%",
        "created_date": date(2025, 9, 15),
    }
    fields.update(overrides)
    return CreateGpJobInput(**fields)


def _relay(monkeypatch, *, company="TUBC", result=None, raises=None):
    calls: list[tuple] = []

    async def _call(_company, op, payload=None, timeout=None):
        calls.append((_company, op, payload))
        if raises is not None:
            raise raises
        return result if result is not None else {"job_number": "NEXUS-380-T1", "job_name": "Test job"}

    monkeypatch.setattr(type(project_module.relay_gateway), "company", property(lambda self: company))
    monkeypatch.setattr(project_module.relay_gateway, "relay_call", _call)
    return calls


def _no_persist(monkeypatch):
    """Stub the Postgres write out. The tests that use this assert what goes TO GP; the project row is
    covered separately by the DB-backed test at the bottom."""

    class _FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def commit(self):
            pass

        def refresh(self, obj):
            pass

    monkeypatch.setattr(project_module, "SessionLocal", _FakeSession)
    monkeypatch.setattr(project_module.project_repository, "adopt_gp_job", lambda session, **kwargs: object())
    monkeypatch.setattr(project_module, "project_to_type", lambda project: project)


def _create(**overrides):
    return asyncio.run(ProjectMutations().create_gp_job(_FakeInfo(), _input(**overrides)))


def test_requires_an_admin():
    """Creating a job writes to the accounting system of record, so this is not an any-user mutation.

    Since #423 the gate is the policy table, applied by the schema extension before the resolver runs,
    so the requirement is asserted where it is decided. `test_resolver_auth_gates.py` covers that the
    extension enforces the table. The tests below call the resolver directly with no auth setup -
    what they pin is the guard order INSIDE the body, which is unchanged."""
    assert ROOT_FIELD_POLICY["createGpJob"] == ADMIN_ROLE


def test_refuses_when_no_relay_is_connected(monkeypatch):
    _relay(monkeypatch, company=None)

    with pytest.raises(RelayUnavailableError):
        _create()


def test_gp_rejection_surfaces_the_procs_own_message(monkeypatch):
    # The whole point of the OnlyValidate pass: GP words the objection better than we can.
    _relay(
        monkeypatch,
        raises=RelayCallError("Job cannot be created within a closed period", detail={}),
    )

    with pytest.raises(ValidationError) as e:
        _create()
    assert "closed period" in str(e.value)


def test_gp_rejection_keeps_the_relay_detail_for_the_error_alert(monkeypatch):
    # main.py publishes extensions.relayError from the raised error's .detail. A plain ValidationError
    # has no such field, so converting without carrying it over would empty the dialog's GP detail
    # table - the proc, the error state and the taErrorCode description all gone (#187).
    detail = {
        "error": "econnect_error",
        "message": "Job cannot be created within a closed period",
        "context": {"proc": "wsiJCJobMaster", "error_state": 8000},
    }
    _relay(monkeypatch, raises=RelayCallError("Job cannot be created within a closed period", detail=detail))

    with pytest.raises(ValidationError) as e:
        _create()
    assert e.value.detail == detail


def test_a_job_already_in_gp_is_adopted_rather_than_dead_ending(monkeypatch):
    """GP holds the job but Nexus does not, so make that true instead of erroring.

    This is the retry path after an ambiguous failure: the proc committed, the reply was lost, and the
    user pressed Create again. The relay's job_exists pre-check now answers job_already_exists, which
    no amount of retrying can clear - and the sync would have created the project a few minutes later
    anyway, so there is nothing to refuse."""
    _relay(
        monkeypatch,
        raises=RelayCallError("job 'NEXUS-380-T1' already exists in GP", detail={"error": "job_already_exists"}),
    )

    synced: list[bool] = []

    async def _fake_sync():
        synced.append(True)
        return (1, 1)

    monkeypatch.setattr(project_module.gp_job_sync, "run_once", _fake_sync)
    monkeypatch.setattr(project_module, "_load_project", lambda job_number: f"project:{job_number}")

    result = _create()
    assert result.project == "project:NEXUS-380-T1"
    # created=False is what stops the UI reporting a creation that never happened (#392)
    assert result.created is False
    assert synced == [True]  # the sync pass is what gives the project GP's own job name


def test_sends_every_required_field_and_omits_unset_optionals(monkeypatch):
    _no_persist(monkeypatch)
    calls = _relay(monkeypatch)

    _create()

    company, op, payload = calls[0]
    assert (company, op) == ("TUBC", "create_job")
    assert payload["job_number"] == "NEXUS-380-T1"
    assert payload["division"] == "VANCOUVER"
    assert payload["created_date"] == "2025-09-15"  # serialized for JSON transport
    # unset optionals travel as None; the relay drops them rather than sending the proc a NULL
    assert payload["estimator_id"] is None
    assert payload["schedule_start_date"] is None


def test_sends_the_optional_fields_that_were_filled_in(monkeypatch):
    _no_persist(monkeypatch)
    calls = _relay(monkeypatch)

    _create(estimator_id="EST1", use_tax_schedule="GST 5%", schedule_start_date=date(2025, 9, 20))

    payload = calls[0][2]
    assert payload["estimator_id"] == "EST1"
    assert payload["use_tax_schedule"] == "GST 5%"
    assert payload["schedule_start_date"] == "2025-09-20"


def test_the_sync_winning_the_race_is_not_an_error(monkeypatch):
    # GP committed, then gp_job_sync adopted the job before this resolver's persist ran. The row we
    # wanted exists; failing here would report a failure for a create that fully succeeded.
    _relay(monkeypatch)
    _no_persist(monkeypatch)

    def _already_there(session, **kwargs):
        raise ConflictError("GP job NEXUS-380-T1 has already been adopted as a project")

    monkeypatch.setattr(project_module.project_repository, "adopt_gp_job", _already_there)
    monkeypatch.setattr(project_module, "_load_project", lambda job_number: f"existing:{job_number}")

    result = _create()
    assert result.project == "existing:NEXUS-380-T1"
    # GP still created the job on this call; only the Nexus row was written by someone else first
    assert result.created is True


def test_persists_the_project_from_gps_own_answer(monkeypatch, _clean_up_test_projects):
    # GP's reply, not the input, is what the project is built from
    _relay(monkeypatch, result={"job_number": "NEXUS-380-T9", "job_name": "Name GP Kept"})

    result = _create(job_number="NEXUS-380-T9", job_name="What The Caller Typed")

    assert result.created is True
    assert result.project.project_id == "NEXUS-380-T9"
    assert result.project.description == "Name GP Kept"
