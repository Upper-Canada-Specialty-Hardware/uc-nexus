"""adoptGpJob must verify the job against GP before creating a Nexus project (#314).

GP owns jobs: a Nexus project with no GP counterpart is invalid state, and POs, inventory, assembly
and shipping all hang off it. The resolver previously took no `info` at all - no auth, no GP check -
so a direct GraphQL call could adopt a fabricated job number. These pin the guard at the resolver,
which is the layer a direct call reaches; the dialog only ever offered real jobs by convention.
"""

import asyncio

import pytest

from app.auth import AuthError
from app.errors import RelayUnavailableError, ValidationError
from app.schemas import project as project_module
from app.schemas.inputs import AdoptGpJobInput
from app.schemas.project import ProjectMutations


class _FakeInfo:
    context = {"request": None}


def _as_user(monkeypatch):
    monkeypatch.setattr(project_module, "require_user", lambda info: {"user_id": "user_1", "roles": []})


def _relay(monkeypatch, *, company="TUBC", jobs=None):
    """Point the resolver at a fake connected relay serving `jobs` from list_jobs."""

    async def _call(_company, op, payload=None, timeout=None):
        assert op == "list_jobs"
        return {"jobs": jobs or []}

    monkeypatch.setattr(type(project_module.relay_gateway), "company", property(lambda self: company))
    monkeypatch.setattr(project_module.relay_gateway, "relay_call", _call)


def _adopt(job_number, job_name=None):
    return asyncio.run(
        ProjectMutations().adopt_gp_job(_FakeInfo(), AdoptGpJobInput(job_number=job_number, job_name=job_name))
    )


def test_rejects_a_job_number_gp_has_never_heard_of(monkeypatch):
    # The reproduction on #314: adopting a fabricated number used to create a Nexus-only project.
    _as_user(monkeypatch)
    _relay(monkeypatch, jobs=[{"job_number": "80001", "job_name": "Cowichan Dist Hospital"}])

    with pytest.raises(ValidationError) as e:
        _adopt("99999")
    assert "99999" in str(e.value)


def test_refuses_to_adopt_at_all_when_the_relay_is_down(monkeypatch):
    # "Cannot verify" must not degrade to "assume it is fine" - that is the whole hole.
    _as_user(monkeypatch)
    _relay(monkeypatch, company=None)

    with pytest.raises(RelayUnavailableError):
        _adopt("80001")


def test_requires_a_signed_in_caller(monkeypatch):
    # The resolver took no `info` parameter at all, so there was nothing to gate on.
    def _deny(info):
        raise AuthError("Authentication required")

    monkeypatch.setattr(project_module, "require_user", _deny)
    _relay(monkeypatch, jobs=[{"job_number": "80001"}])

    with pytest.raises(AuthError):
        _adopt("80001")


def test_rejects_a_blank_job_number_before_touching_the_relay(monkeypatch):
    _as_user(monkeypatch)

    async def _never(*a, **k):
        raise AssertionError("the relay must not be called for a blank job number")

    monkeypatch.setattr(type(project_module.relay_gateway), "company", property(lambda self: "TUBC"))
    monkeypatch.setattr(project_module.relay_gateway, "relay_call", _never)

    with pytest.raises(ValidationError):
        _adopt("   ")


def test_matches_the_gp_job_ignoring_surrounding_whitespace_and_case(monkeypatch, _migrate_database):
    _as_user(monkeypatch)
    _relay(monkeypatch, jobs=[{"job_number": " 80001 ", "job_name": "Cowichan Dist Hospital"}])

    project = _adopt("  80001  ")

    assert project.project_id == "80001"


def test_snapshots_gps_own_job_name_not_the_callers(monkeypatch, _migrate_database):
    # A direct call can put anything in job_name; GP's name is the one worth keeping.
    _as_user(monkeypatch)
    _relay(monkeypatch, jobs=[{"job_number": "80002", "job_name": "Real GP Name"}])

    project = _adopt("80002", job_name="Whatever The Caller Said")

    assert project.description == "Real GP Name"
