"""createGpJob: admin gate, relay gating, GP error surfacing, and what gets persisted (#380).

The mutation writes to GP through the relay and only then creates the Nexus project, so these pin the
order and the failure modes rather than the happy path alone: a relay that isn't there must stop the
call before GP is touched, and a proc rejection must reach the dialog in the proc's own words - that
message ("Job cannot be created within a closed period") is the only thing telling the user what to fix.
"""

import asyncio
from datetime import date

import pytest

from app.auth import AuthError
from app.errors import RelayCallError, RelayUnavailableError, ValidationError
from app.schemas import project as project_module
from app.schemas.inputs import CreateGpJobInput
from app.schemas.project import ProjectMutations


class _FakeInfo:
    context = {"request": None}


def _as_admin(monkeypatch):
    monkeypatch.setattr(project_module, "require_admin", lambda info: {"user_id": "user_1", "roles": ["Admin"]})


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


def test_requires_an_admin(monkeypatch):
    # Creating a job writes to the accounting system of record, so this is not an any-user mutation.
    def _deny(info):
        raise AuthError("Admin role required")

    monkeypatch.setattr(project_module, "require_admin", _deny)

    async def _never(*a, **k):
        raise AssertionError("the relay must not be called for a non-admin")

    monkeypatch.setattr(project_module.relay_gateway, "relay_call", _never)

    with pytest.raises(AuthError):
        _create()


def test_refuses_when_no_relay_is_connected(monkeypatch):
    _as_admin(monkeypatch)
    _relay(monkeypatch, company=None)

    with pytest.raises(RelayUnavailableError):
        _create()


def test_gp_rejection_surfaces_the_procs_own_message(monkeypatch):
    # The whole point of the OnlyValidate pass: GP words the objection better than we can.
    _as_admin(monkeypatch)
    _relay(
        monkeypatch,
        raises=RelayCallError("Job cannot be created within a closed period", detail={}),
    )

    with pytest.raises(ValidationError) as e:
        _create()
    assert "closed period" in str(e.value)


def test_job_already_in_gp_surfaces_as_a_validation_error(monkeypatch):
    _as_admin(monkeypatch)
    _relay(monkeypatch, raises=RelayCallError("job 'NEXUS-380-T1' already exists in GP company TUBC", detail={}))

    with pytest.raises(ValidationError) as e:
        _create()
    assert "already exists" in str(e.value)


def test_sends_every_required_field_and_omits_unset_optionals(monkeypatch):
    _as_admin(monkeypatch)
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
    _as_admin(monkeypatch)
    _no_persist(monkeypatch)
    calls = _relay(monkeypatch)

    _create(estimator_id="EST1", use_tax_schedule="GST 5%", schedule_start_date=date(2025, 9, 20))

    payload = calls[0][2]
    assert payload["estimator_id"] == "EST1"
    assert payload["use_tax_schedule"] == "GST 5%"
    assert payload["schedule_start_date"] == "2025-09-20"


def test_persists_the_project_from_gps_own_answer(monkeypatch, _migrate_database):
    _as_admin(monkeypatch)
    # GP's reply, not the input, is what the project is built from
    _relay(monkeypatch, result={"job_number": "NEXUS-380-T9", "job_name": "Name GP Kept"})

    project = _create(job_number="NEXUS-380-T9", job_name="What The Caller Typed")

    assert project.project_id == "NEXUS-380-T9"
    assert project.description == "Name GP Kept"
