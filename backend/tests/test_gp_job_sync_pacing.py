"""Adaptive pacing as the job sync sees it: no pass while GP is busy, a paced read per company, and
the hello gap that used to be mistaken for an absent relay.

Separate from test_gp_job_sync.py because that file is entirely DB-gated (it adopts real projects)
and none of this needs a database."""

import asyncio

import pytest

from app.errors import RelayBusyError
from app.services import gp_job_sync

# --- adaptive pacing ---------------------------------------------------------------------------------


class _LoopStopped(Exception):
    """Breaks out of run_forever's `while True` once the test has seen enough turns."""


def _drive_loop(monkeypatch, *, connected, companies, paused, max_turns=1):
    """Run gp_job_sync.run_forever for a couple of turns and report what it waited and what it ran."""
    waits: list[float] = []
    ran: list[str] = []
    probes = {"n": 0}
    turns = {"n": 0}

    monkeypatch.setattr(gp_job_sync.relay_gateway, "_socket", object() if connected else None)
    monkeypatch.setattr(gp_job_sync.relay_gateway, "_companies", frozenset(companies))
    monkeypatch.setattr(gp_job_sync.gp_load, "paused", lambda: paused)

    async def fake_probe():
        probes["n"] += 1
        return not paused

    async def fake_run_once(**kwargs):
        ran.append("pass")
        return (0, 0)

    async def fake_wait_for(awaitable, timeout=None):
        waits.append(timeout)
        turns["n"] += 1
        awaitable.close()
        if turns["n"] >= max_turns:
            raise _LoopStopped
        raise TimeoutError

    monkeypatch.setattr(gp_job_sync.gp_load, "probe", fake_probe)
    monkeypatch.setattr(gp_job_sync, "run_once", fake_run_once)
    monkeypatch.setattr(gp_job_sync.asyncio, "wait_for", fake_wait_for)

    with pytest.raises(_LoopStopped):
        asyncio.run(gp_job_sync.run_forever())
    return {"waits": waits, "ran": ran, "probes": probes["n"]}


def test_the_job_sync_runs_no_pass_while_gp_is_too_busy(monkeypatch):
    """Adopting jobs can wait; not adding load to an overloaded GP cannot."""
    out = _drive_loop(monkeypatch, connected=True, companies=["TUBC"], paused=True)

    assert out["ran"] == []
    assert out["probes"] >= 1
    assert out["waits"][0] == gp_job_sync.gp_load.SERVER_PROBE_SECONDS


def test_the_job_sync_runs_its_pass_when_the_server_is_fine(monkeypatch):
    out = _drive_loop(monkeypatch, connected=True, companies=["TUBC"], paused=False)

    assert out["ran"] == ["pass"]
    assert out["probes"] == 0
    assert out["waits"][0] == gp_job_sync.POLL_SECONDS


def test_the_job_sync_waits_only_the_grace_while_the_hello_is_pending(monkeypatch):
    """Same shape as the PO mirror had, and the same fix: connected with no companies is a hello that
    has not been read yet, not an absent relay."""
    out = _drive_loop(monkeypatch, connected=True, companies=[], paused=False)

    assert out["ran"] == []
    assert out["waits"][0] == gp_job_sync.gp_load.HELLO_GRACE_SECONDS


def test_the_job_sync_still_waits_the_poll_interval_with_no_socket(monkeypatch):
    out = _drive_loop(monkeypatch, connected=False, companies=[], paused=False)

    assert out["ran"] == []
    assert out["waits"][0] == gp_job_sync.POLL_SECONDS


def test_a_busy_refusal_ends_the_pass_instead_of_working_through_the_list(monkeypatch):
    """The next company would be refused by the same server for the same reason, so collecting one
    refusal per company is pure extra load for no information. Raised rather than counted as a
    failure, or the all-companies-failed branch would blame the relay for a busy server."""
    monkeypatch.setattr(gp_job_sync.relay_gateway, "_companies", frozenset({"TUBC", "UCSH", "UBC"}))
    tried: list[str] = []

    async def refuse(company, op, payload=None, *, floor_seconds, **kwargs):
        tried.append(company)
        raise RelayBusyError("busy", sql_cpu_pct=91.0, ceiling_pct=70.0)

    monkeypatch.setattr(gp_job_sync.gp_load, "paced_call", refuse)

    with pytest.raises(RelayBusyError):
        asyncio.run(gp_job_sync.run_once())

    assert len(tried) == 1  # stopped at the first refusal


def test_the_timer_driven_pass_is_marked_background_and_the_admin_one_is_not(monkeypatch):
    """The relay keys its busy gate on the flag, not the op - so the loop's pass carries it and the
    admin Sync from GP button (and /admin/reset-data, which calls run_once with no arguments) does
    not, and is therefore served rather than refused."""
    monkeypatch.setattr(gp_job_sync.relay_gateway, "_companies", frozenset({"TUBC"}))
    seen: list[bool] = []

    async def fake_paced_call(company, op, payload=None, *, floor_seconds, background=True, **kwargs):
        seen.append(background)
        return {"result": {"jobs": []}, "meta": {}, "elapsed_ms": 1.0, "cpu_ms": None, "sql_cpu_pct": None, "pace": 0.0}

    monkeypatch.setattr(gp_job_sync.gp_load, "paced_call", fake_paced_call)
    monkeypatch.setattr(gp_job_sync, "_persist_missing", lambda jobs, company: (0, 0))
    monkeypatch.setattr(gp_job_sync, "_persist_health", lambda jobs, company: 0)

    asyncio.run(gp_job_sync.run_once())
    assert seen == [False, False]  # list_jobs and job_setup_health, neither marked

    seen.clear()
    asyncio.run(gp_job_sync.run_once(background=True))
    assert seen == [True, True]


def test_each_company_read_is_paced(monkeypatch):
    """Spacing the companies apart is the same mechanism as spacing the pages apart - one budget."""
    monkeypatch.setattr(gp_job_sync.relay_gateway, "_companies", frozenset({"TUBC", "UCSH"}))
    floors: list[float] = []

    async def fake_paced_call(company, op, payload=None, *, floor_seconds, **kwargs):
        floors.append(floor_seconds)
        return {"result": {"jobs": []}, "meta": {}, "elapsed_ms": 1.0, "cpu_ms": None, "sql_cpu_pct": None, "pace": 0.0}

    monkeypatch.setattr(gp_job_sync.gp_load, "paced_call", fake_paced_call)
    monkeypatch.setattr(gp_job_sync, "_persist_missing", lambda jobs, company: (0, 0))
    monkeypatch.setattr(gp_job_sync, "_persist_health", lambda jobs, company: 0)

    asyncio.run(gp_job_sync.run_once())

    # list_jobs and job_setup_health, for each of the two companies.
    assert floors == [gp_job_sync.COMPANY_FLOOR_SECONDS] * 4
