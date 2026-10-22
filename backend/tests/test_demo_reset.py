"""Anybody in demo mode resets the demo, and everybody else is told (#1697).

Run through the real schema with the request memos `app.auth` would fill from Clerk, against the stored
build record, which each test writes and the fixture puts back.
"""

import asyncio

import pytest

from app.auth import remember_display_name
from app.services import demo_build

_IN_DEMO = {"request": None, "_auth_user_id": "u_resetter", "_auth_roles": [], "_auth_company": "UBC"}


def _as(user_id: str, *, demo: bool = True) -> dict:
    return {**_IN_DEMO, "_auth_user_id": user_id, "_auth_demo_mode": demo}


def _run(document: str, context: dict):
    from main import schema

    return asyncio.run(schema.execute(document, context_value=context))


_STATUS = "{ demoResetStatus { building buildStartedBy notice { resetAt resetBy } } }"


@pytest.fixture
def stored(_migrate_database):
    """The build record and the seen record, saved before and put back after."""
    from app.database import SessionLocal
    from app.repositories import demo_mirror_state_repository as state

    keys = (state.BUILD, state.RESET_SEEN)
    with SessionLocal() as session:
        kept = {k: state.get(session, k) for k in keys}

    def write(build: dict | None, seen: dict | None = None) -> None:
        with SessionLocal() as session:
            state.put(session, state.BUILD, build or {})
            state.put(session, state.RESET_SEEN, seen or {})
            session.commit()

    for user_id, name in (("u_resetter", "Rhea Resetter"), ("u_other", "Otto Other")):
        remember_display_name(user_id, name)
    yield write
    with SessionLocal() as session:
        for k, v in kept.items():
            state.put(session, k, v or {})
        session.commit()


def _finished(**overrides) -> dict:
    return {
        "started_at": "2026-10-16T18:40:00",
        "finished_at": "2026-10-16T18:41:52",
        "started_by": "Rhea Resetter",
        "started_by_id": "u_resetter",
        "kind": demo_build.DEMO_RESET,
        "running": False,
        "error": None,
        **overrides,
    }


# --- resetting ---------------------------------------------------------------------------------


def test_reset_is_refused_outside_demo_mode(stored, monkeypatch):
    started = []
    monkeypatch.setattr(demo_build, "start_rebuild", lambda *a, **kw: started.append(kw))

    result = _run("mutation { resetDemo { building } }", _as("u_other", demo=False))

    assert result.errors and "demo mode" in result.errors[0].message
    assert started == []


def test_anybody_in_demo_mode_resets_it(stored, monkeypatch):
    stored(_finished())
    started = []
    monkeypatch.setattr(demo_build, "start_rebuild", lambda name, **kw: started.append((name, kw)))

    result = _run("mutation { resetDemo { building } }", _as("u_other"))

    assert result.errors is None, result.errors
    assert started == [("Otto Other", {"started_by_id": "u_other", "kind": demo_build.DEMO_RESET})]


def test_a_reset_is_refused_while_the_nightly_runs_and_no_tab_is_told_of_one(monkeypatch):
    """#1831: refused up front, not accepted and failed on the lock; and the nightly only adds, so the
    demo tabs, which read `building()`, are not put behind the reset dialog."""
    from app.errors import ConflictError

    monkeypatch.setattr(demo_build, "_nightly_running", True)

    with pytest.raises(ConflictError, match="nightly"):
        demo_build.start_rebuild("Otto Other", started_by_id="u_other", kind=demo_build.DEMO_RESET)
    assert demo_build.building() is False


# --- being told --------------------------------------------------------------------------------


def test_everybody_else_is_told_who_reset_it_and_when(stored):
    stored(_finished())

    result = _run(_STATUS, _as("u_other"))

    assert result.errors is None, result.errors
    assert result.data["demoResetStatus"]["notice"] == {"resetAt": "2026-10-16T18:41:52", "resetBy": "Rhea Resetter"}


def test_they_are_told_once(stored):
    stored(_finished())

    ack = _run("mutation { acknowledgeDemoReset { notice { resetBy } } }", _as("u_other"))

    assert ack.errors is None, ack.errors
    assert ack.data["acknowledgeDemoReset"]["notice"] is None
    assert _run(_STATUS, _as("u_other")).data["demoResetStatus"]["notice"] is None


def test_a_reset_still_running_is_not_marked_seen(stored):
    """#1814: a "Got it" on the last reset while the next one runs must not count for the next one."""
    stored(_finished(started_at="2026-10-17T09:00:00", finished_at=None, running=True), {"u_other": "x"})

    _run("mutation { acknowledgeDemoReset { notice { resetBy } } }", _as("u_other"))

    from app.database import SessionLocal
    from app.repositories import demo_mirror_state_repository as state

    with SessionLocal() as session:
        assert state.get(session, state.RESET_SEEN) == {"u_other": "x"}


def test_a_later_reset_is_told_again(stored):
    stored(
        _finished(started_at="2026-10-17T09:00:00", finished_at="2026-10-17T09:02:00"),
        {"u_other": "2026-10-16T18:40:00"},
    )

    assert _run(_STATUS, _as("u_other")).data["demoResetStatus"]["notice"]["resetAt"] == "2026-10-17T09:02:00"


def test_the_person_who_reset_it_is_not_told(stored):
    stored(_finished())

    assert _run(_STATUS, _as("u_resetter")).data["demoResetStatus"]["notice"] is None


def test_the_first_build_is_nobodys_reset(stored):
    stored(_finished(kind=demo_build.FIRST_BUILD, started_by_id=None))

    assert _run(_STATUS, _as("u_other")).data["demoResetStatus"]["notice"] is None


def test_a_failed_build_tells_nobody(stored):
    stored(_finished(error="boom"))

    assert _run(_STATUS, _as("u_other")).data["demoResetStatus"]["notice"] is None


def test_a_running_reset_is_answered_with_who_started_it(stored, monkeypatch):
    stored({"started_at": "2026-10-16T18:40:00", "started_by": "Rhea Resetter", "running": True})
    monkeypatch.setattr(demo_build, "building", lambda: True)

    result = _run(_STATUS, _as("u_other"))

    assert result.errors is None, result.errors
    assert result.data["demoResetStatus"] == {"building": True, "buildStartedBy": "Rhea Resetter", "notice": None}


def test_reading_resets_needs_demo_mode(stored):
    stored(_finished())

    assert _run(_STATUS, _as("u_other", demo=False)).errors


def test_an_admin_rebuild_records_who_started_it(stored, monkeypatch):
    started = []
    monkeypatch.setattr(demo_build, "start_rebuild", lambda name, **kw: started.append(kw))
    admin = {"request": None, "_auth_user_id": "u_admin", "_auth_roles": ["UC Nexus Admin"], "_auth_company": None}
    remember_display_name("u_admin", "Ada Admin")

    _run("mutation { rebuildDemo { building } }", admin)

    assert started == [{"started_by_id": "u_admin", "kind": demo_build.ADMIN_REBUILD}]
