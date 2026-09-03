"""Adaptive pacing for background GP reads (app/services/gp_load.py).

The rule under test: neither Nexus nor its relay may contribute to an overload of the GP SQL server.
Everything that decides anything is a pure function over numbers, so all of it runs with no relay, no
database and no clock - which is the point of the split.
"""

import asyncio
import logging
from datetime import datetime, timedelta

import pytest

from app.errors import RelayBusyError, RelayOpUnsupportedError
from app.services import gp_load


@pytest.fixture(autouse=True)
def _fresh_policy(monkeypatch):
    """A policy per test. It is process-wide in production on purpose (one SQL server, one budget), so
    the tests have to reset it rather than construct their own."""
    policy = gp_load.GpLoadPolicy()
    monkeypatch.setattr(gp_load, "policy", policy)
    return policy


def _sample(cpu=10.0, runnable=0, source=gp_load.RING_BUFFER, age_seconds=0.0):
    """A server sample as the relay sends it. `sampled_at` is a real timestamp because freshness is
    now part of every pause decision - a reading too old to describe the server counts as no reading."""
    return {
        "sql_cpu_pct": cpu,
        "other_cpu_pct": 5.0,
        "runnable_tasks": runnable,
        "sampled_at": (datetime.utcnow() - timedelta(seconds=age_seconds)).isoformat(),
        "source": source,
    }


# --- budget ------------------------------------------------------------------------------------------


def test_spacing_is_the_wall_clock_the_cpu_cost_averages_out_over():
    """400 ms of CPU at a tenth of a core is 4 s of wall clock. That identity IS the budget."""
    assert gp_load.spacing_ms(400.0, budget_cores=0.10) == pytest.approx(4000.0)
    assert gp_load.spacing_ms(800.0, budget_cores=0.10) == pytest.approx(8000.0)
    assert gp_load.spacing_ms(400.0, budget_cores=0.20) == pytest.approx(2000.0)


def test_no_reported_cost_claims_no_spacing():
    """An older relay reports no cost block. Pacing then falls back to the floor, not to zero waits and
    not to a made-up number."""
    assert gp_load.spacing_ms(None) == 0.0
    assert gp_load.spacing_ms(0) == 0.0
    assert gp_load.pace_seconds(floor_seconds=5.0, cpu_ms=None, elapsed_ms=200.0) == 5.0


def test_a_zero_budget_cannot_become_an_infinite_wait():
    """The floor exists so a mistyped budget throttles hard rather than deadlocking the mirror."""
    assert gp_load.spacing_ms(100.0, budget_cores=0.0) == pytest.approx(100.0 / 0.01)


def test_the_pause_owed_is_spacing_minus_the_time_already_spent():
    """A slow op has already provided some of the quiet its cost bought; only the remainder is owed."""
    # 800 ms cpu at 0.10 cores = 8000 ms spacing, of which the op itself consumed 3000.
    assert gp_load.pace_seconds(floor_seconds=1.0, cpu_ms=800.0, elapsed_ms=3000.0, budget_cores=0.10) == pytest.approx(
        5.0
    )


def test_the_configured_delay_is_a_floor_the_budget_can_raise_but_not_undercut():
    cheap = gp_load.pace_seconds(floor_seconds=5.0, cpu_ms=10.0, elapsed_ms=50.0, budget_cores=0.10)
    assert cheap == 5.0  # 100 ms of spacing does not buy less than the floor
    dear = gp_load.pace_seconds(floor_seconds=5.0, cpu_ms=4000.0, elapsed_ms=1000.0, budget_cores=0.10)
    assert dear == pytest.approx(39.0)  # 40 s of spacing minus the 1 s the op took


# --- pressure ----------------------------------------------------------------------------------------


def test_pressure_is_an_op_far_slower_than_that_op_normally_is():
    assert gp_load.is_under_pressure(3100.0, 1000.0) is True
    assert gp_load.is_under_pressure(2900.0, 1000.0) is False
    # No median yet, or no reading: no signal, never a false positive.
    assert gp_load.is_under_pressure(9999.0, None) is False
    assert gp_load.is_under_pressure(None, 1000.0) is False


def test_pressure_doubles_the_wait_and_is_capped_at_ten_floors():
    assert gp_load.pace_seconds(floor_seconds=5.0, cpu_ms=None, elapsed_ms=1.0, under_pressure=True) == 10.0
    # 5 s floor, 30 s base from the budget: doubling would be 60, the cap holds it at 10 x floor.
    capped = gp_load.pace_seconds(
        floor_seconds=5.0, cpu_ms=3100.0, elapsed_ms=100.0, under_pressure=True, budget_cores=0.10
    )
    assert capped == pytest.approx(50.0)


def test_the_cap_never_shrinks_a_wait_the_budget_itself_demands():
    """The cap limits what PRESSURE may add, not the total. A genuinely expensive op keeps its spacing -
    shrinking it would break the budget the cap exists to protect."""
    base = gp_load.pace_seconds(floor_seconds=1.0, cpu_ms=8000.0, elapsed_ms=0.0, budget_cores=0.10)
    pressured = gp_load.pace_seconds(
        floor_seconds=1.0, cpu_ms=8000.0, elapsed_ms=0.0, under_pressure=True, budget_cores=0.10
    )
    assert base == pytest.approx(80.0)
    assert pressured == pytest.approx(80.0)  # 10 x floor is 10 s, well under the budget's own demand


def test_the_median_is_not_trusted_until_it_has_seen_enough_ops(_fresh_policy):
    """Two samples make a median a third normal reading can beat by 3x on noise alone."""
    for _ in range(gp_load.MEDIAN_MIN_SAMPLES - 1):
        _fresh_policy.observe("TUBC", "sync_pos", 1000.0)
    assert _fresh_policy.median_ms("TUBC", "sync_pos") is None
    _fresh_policy.observe("TUBC", "sync_pos", 1000.0)
    assert _fresh_policy.median_ms("TUBC", "sync_pos") == 1000.0


def test_medians_are_kept_per_company_and_op(_fresh_policy):
    for _ in range(6):
        _fresh_policy.observe("TUBC", "sync_pos", 1000.0)
        _fresh_policy.observe("UCSH", "sync_pos", 50.0)
    assert _fresh_policy.median_ms("TUBC", "sync_pos") == 1000.0
    assert _fresh_policy.median_ms("UCSH", "sync_pos") == 50.0
    assert _fresh_policy.median_ms("TUBC", "list_jobs") is None


def test_the_rolling_window_forgets_old_ops(_fresh_policy):
    for _ in range(gp_load.MEDIAN_WINDOW):
        _fresh_policy.observe("TUBC", "sync_pos", 10.0)
    for _ in range(gp_load.MEDIAN_WINDOW):
        _fresh_policy.observe("TUBC", "sync_pos", 500.0)
    assert _fresh_policy.median_ms("TUBC", "sync_pos") == 500.0


# --- pause / resume ----------------------------------------------------------------------------------


def test_pause_on_server_cpu():
    assert gp_load.pause_reason(_sample(cpu=70.0)) is not None
    assert gp_load.pause_reason(_sample(cpu=69.9)) is None


def test_pause_on_a_backed_up_runnable_queue():
    """CPU pressure the averaged percentage can miss: tasks queued for a scheduler mean the server is
    already behind."""
    assert gp_load.pause_reason(_sample(cpu=10.0, runnable=8)) is not None
    assert gp_load.pause_reason(_sample(cpu=10.0, runnable=7)) is None


def test_a_sample_that_is_not_a_real_reading_never_pauses():
    """An unavailable sample is not evidence the server is fine, but it is not evidence it is not -
    and pausing on no evidence would stop the mirror forever on every relay without VIEW SERVER STATE."""
    assert gp_load.pause_reason(None) is None
    assert gp_load.pause_reason(_sample(cpu=99.0, source=gp_load.UNAVAILABLE)) is None


def test_resume_needs_both_numbers_back_under_their_thresholds():
    assert gp_load.may_resume(_sample(cpu=49.0, runnable=0)) is True
    assert gp_load.may_resume(_sample(cpu=50.0, runnable=0)) is False  # still at the resume line
    assert gp_load.may_resume(_sample(cpu=10.0, runnable=8)) is False  # cpu fine, queue is not


def test_the_hysteresis_band_is_where_a_paused_policy_stays_paused(_fresh_policy):
    """Between resume and pause the answer to both questions is no, which is the whole point: a server
    sitting at 60% neither pauses a running policy nor resumes a paused one."""
    mid = _sample(cpu=60.0)
    assert gp_load.pause_reason(mid) is None
    assert gp_load.may_resume(mid) is False


def test_a_missing_sample_never_resumes():
    """The policy paused on evidence and needs evidence to un-pause. A probe that could not read the
    server simply runs again."""
    assert gp_load.may_resume(None) is False
    assert gp_load.may_resume(_sample(cpu=1.0, source=gp_load.UNAVAILABLE)) is False


def test_a_sample_over_the_ceiling_pauses_the_policy(_fresh_policy):
    _fresh_policy.note_sample(_sample(cpu=85.0))
    assert _fresh_policy.paused is True
    assert "85" in _fresh_policy.paused_reason


def test_a_recovered_sample_resumes_it(_fresh_policy):
    _fresh_policy.note_sample(_sample(cpu=85.0))
    _fresh_policy.note_sample(_sample(cpu=20.0))
    assert _fresh_policy.paused is False


def test_a_sample_inside_the_band_does_not_resume(_fresh_policy):
    _fresh_policy.note_sample(_sample(cpu=85.0))
    _fresh_policy.note_sample(_sample(cpu=60.0))
    assert _fresh_policy.paused is True


def test_a_busy_refusal_pauses_and_takes_the_relay_s_retry_advice(_fresh_policy, monkeypatch):
    clock = {"now": 1000.0}
    monkeypatch.setattr(gp_load.time, "monotonic", lambda: clock["now"])
    error = RelayBusyError("busy", sql_cpu_pct=91.0, ceiling_pct=70.0, retry_after_seconds=12.0)

    _fresh_policy.note_busy(error)

    assert _fresh_policy.paused is True
    # The relay is closer to the server than we are, so its advice beats the configured interval.
    assert _fresh_policy.probe_due_at() == pytest.approx(1012.0)


def test_a_busy_refusal_without_advice_falls_back_to_the_probe_interval(_fresh_policy, monkeypatch):
    clock = {"now": 1000.0}
    monkeypatch.setattr(gp_load.time, "monotonic", lambda: clock["now"])

    _fresh_policy.note_busy(RelayBusyError("busy"))

    assert _fresh_policy.probe_due_at() == pytest.approx(1000.0 + gp_load.SERVER_PROBE_SECONDS)


def test_the_missing_permission_is_warned_about_once_per_process(_fresh_policy, caplog):
    with caplog.at_level(logging.WARNING, logger="app.services.gp_load"):
        for _ in range(5):
            _fresh_policy.note_sample(_sample(source=gp_load.UNAVAILABLE))

    warnings = [m for m in caplog.messages if "VIEW SERVER STATE" in m]
    assert len(warnings) == 1
    assert "paced on op cost and elapsed time only" in warnings[0]


def test_pacing_still_works_with_an_unavailable_sample(_fresh_policy):
    """No server permissions: cost and elapsed time alone, and nothing pauses."""
    pace = _fresh_policy.note_op(
        "TUBC",
        "sync_pos",
        {"cost": {"cpu_ms": 800.0, "elapsed_ms": 1000.0}, "server": _sample(cpu=99.0, source=gp_load.UNAVAILABLE)},
        1000.0,
        floor_seconds=5.0,
    )
    assert _fresh_policy.paused is False
    assert pace == pytest.approx(7.0)  # 8 s of spacing, 1 s of which the op already spent


# --- note_op bookkeeping -----------------------------------------------------------------------------


def test_note_op_prefers_the_server_s_own_elapsed_over_our_round_trip(_fresh_policy):
    pace = _fresh_policy.note_op(
        "TUBC", "sync_pos", {"cost": {"cpu_ms": 1000.0, "elapsed_ms": 2000.0}}, 9999.0, floor_seconds=1.0
    )
    assert pace == pytest.approx(8.0)  # 10 s spacing minus the server's 2 s, not our 9.999 s


def test_note_op_falls_back_to_our_round_trip_when_the_relay_reports_none(_fresh_policy):
    pace = _fresh_policy.note_op("TUBC", "sync_pos", {"cost": {"cpu_ms": 1000.0}}, 2000.0, floor_seconds=1.0)
    assert pace == pytest.approx(8.0)


def test_note_op_sets_when_the_next_background_op_may_run(_fresh_policy, monkeypatch):
    clock = {"now": 500.0}
    monkeypatch.setattr(gp_load.time, "monotonic", lambda: clock["now"])

    _fresh_policy.note_op("TUBC", "sync_pos", {"cost": {"cpu_ms": 1000.0}}, 0.0, floor_seconds=1.0)

    assert _fresh_policy.next_op_at() == pytest.approx(510.0)
    assert _fresh_policy.wait_seconds() == pytest.approx(10.0)
    clock["now"] = 515.0
    assert _fresh_policy.wait_seconds() == 0.0


def test_a_slow_op_doubles_the_next_wait_once_a_median_exists(_fresh_policy):
    for _ in range(gp_load.MEDIAN_MIN_SAMPLES):
        _fresh_policy.note_op("TUBC", "sync_pos", {"cost": {"elapsed_ms": 100.0}}, 100.0, floor_seconds=5.0)

    pace = _fresh_policy.note_op("TUBC", "sync_pos", {"cost": {"elapsed_ms": 5000.0}}, 5000.0, floor_seconds=5.0)

    assert pace == pytest.approx(10.0)


def test_a_pacing_decision_above_the_floor_says_why(_fresh_policy, caplog):
    with caplog.at_level(logging.INFO, logger="app.services.gp_load"):
        _fresh_policy.note_op("TUBC", "sync_pos", {"cost": {"cpu_ms": 2000.0}}, 100.0, floor_seconds=5.0)

    lines = [m for m in caplog.messages if "paced" in m]
    assert len(lines) == 1
    assert "cpu_ms=2000" in lines[0] and "floor 5.0s" in lines[0]


def test_a_pace_at_the_floor_says_nothing(_fresh_policy, caplog):
    """One line per decision that DIFFERS from the floor. The ordinary case is silent, or the log is
    just the delay written out longhand."""
    with caplog.at_level(logging.INFO, logger="app.services.gp_load"):
        _fresh_policy.note_op("TUBC", "sync_pos", {"cost": {"cpu_ms": 1.0}}, 10.0, floor_seconds=5.0)

    assert not [m for m in caplog.messages if "paced" in m]


# --- probing -----------------------------------------------------------------------------------------


def test_the_probe_only_runs_when_one_is_due(_fresh_policy, monkeypatch):
    clock = {"now": 1000.0}
    monkeypatch.setattr(gp_load.time, "monotonic", lambda: clock["now"])
    calls = {"n": 0}

    async def fake_call(company, op, payload=None, **kwargs):
        calls["n"] += 1
        return None, {"cost": None, "server": _sample(cpu=5.0)}

    monkeypatch.setattr(gp_load.relay_gateway, "relay_call_with_meta", fake_call)
    _fresh_policy.note_busy(RelayBusyError("busy", retry_after_seconds=30.0))

    assert asyncio.run(gp_load.probe()) is False
    assert calls["n"] == 0  # not due yet

    clock["now"] = 1031.0
    assert asyncio.run(gp_load.probe()) is True
    assert calls["n"] == 1
    assert _fresh_policy.paused is False


def test_a_probe_that_still_finds_the_server_busy_stays_paused(_fresh_policy, monkeypatch):
    clock = {"now": 1000.0}
    monkeypatch.setattr(gp_load.time, "monotonic", lambda: clock["now"])

    async def fake_call(company, op, payload=None, **kwargs):
        return None, {"cost": None, "server": _sample(cpu=88.0)}

    monkeypatch.setattr(gp_load.relay_gateway, "relay_call_with_meta", fake_call)
    _fresh_policy.note_sample(_sample(cpu=88.0))
    clock["now"] = 1000.0 + gp_load.SERVER_PROBE_SECONDS + 1

    assert asyncio.run(gp_load.probe()) is False
    assert _fresh_policy.paused is True


def test_a_probe_that_cannot_reach_the_relay_does_not_resume(_fresh_policy, monkeypatch):
    """Resuming because we could not ask is precisely the wrong failure."""
    clock = {"now": 1000.0}
    monkeypatch.setattr(gp_load.time, "monotonic", lambda: clock["now"])

    async def boom(company, op, payload=None, **kwargs):
        raise RuntimeError("socket gone")

    monkeypatch.setattr(gp_load.relay_gateway, "relay_call_with_meta", boom)
    _fresh_policy.note_sample(_sample(cpu=88.0))
    clock["now"] = 1000.0 + gp_load.SERVER_PROBE_SECONDS + 1

    assert asyncio.run(gp_load.probe()) is False
    assert _fresh_policy.paused is True


# --- paced_call --------------------------------------------------------------------------------------


def test_paced_call_waits_out_what_the_previous_op_earned(_fresh_policy, monkeypatch):
    slept: list[float] = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    async def fake_call(company, op, payload=None, **kwargs):
        return {"pos": []}, {"cost": {"cpu_ms": 500.0, "elapsed_ms": 100.0}, "server": _sample()}

    monkeypatch.setattr(gp_load.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(gp_load.relay_gateway, "relay_call_with_meta", fake_call)
    monkeypatch.setattr(gp_load.time, "monotonic", lambda: 1000.0)
    _fresh_policy.note_op("TUBC", "sync_pos", {"cost": {"cpu_ms": 1000.0}}, 0.0, floor_seconds=1.0)

    call = asyncio.run(gp_load.paced_call("TUBC", "sync_pos", floor_seconds=5.0))

    assert slept == [pytest.approx(10.0)]  # the previous op's 1000 ms of cpu at 0.10 cores
    assert call["result"] == {"pos": []}
    assert call["cpu_ms"] == 500.0
    assert call["sql_cpu_pct"] == 10.0
    assert call["pace"] == pytest.approx(5.0)  # 5 s of spacing is under the floor


def test_paced_call_enters_the_pause_on_a_busy_refusal(_fresh_policy, monkeypatch):
    async def refuse(company, op, payload=None, **kwargs):
        raise RelayBusyError("busy", sql_cpu_pct=91.0, ceiling_pct=70.0, retry_after_seconds=45.0)

    monkeypatch.setattr(gp_load.relay_gateway, "relay_call_with_meta", refuse)

    with pytest.raises(RelayBusyError):
        asyncio.run(gp_load.paced_call("TUBC", "sync_pos", floor_seconds=5.0))

    # Paused where the error was raised, so no caller can forget to - but still raised, because the
    # caller's pass genuinely did not happen.
    assert _fresh_policy.paused is True


def test_paced_call_records_the_sample_even_from_an_op_that_is_not_about_load(_fresh_policy, monkeypatch):
    async def fake_call(company, op, payload=None, **kwargs):
        return None, {"cost": None, "server": _sample(cpu=95.0)}

    monkeypatch.setattr(gp_load.asyncio, "sleep", lambda s: asyncio.sleep(0))
    monkeypatch.setattr(gp_load.relay_gateway, "relay_call_with_meta", fake_call)

    asyncio.run(gp_load.paced_call("TUBC", "list_jobs", floor_seconds=1.0))

    assert _fresh_policy.paused is True


def test_a_relay_downgraded_mid_pause_does_not_wedge_the_mirror(_fresh_policy, monkeypatch, caplog):
    """The only probe failure that resumes. A workstation that rolled back to a build without the op
    can never answer, so staying paused would stop background reads forever - and that relay reports
    no samples either, which is exactly the cost-only mode this falls back to."""
    clock = {"now": 1000.0}
    monkeypatch.setattr(gp_load.time, "monotonic", lambda: clock["now"])

    async def too_old(company, op, payload=None, **kwargs):
        raise RelayOpUnsupportedError(op)

    monkeypatch.setattr(gp_load.relay_gateway, "relay_call_with_meta", too_old)
    _fresh_policy.note_sample(_sample(cpu=88.0))
    clock["now"] = 1000.0 + gp_load.SERVER_PROBE_SECONDS + 1

    with caplog.at_level(logging.WARNING, logger="app.services.gp_load"):
        resumed = asyncio.run(gp_load.probe())

    assert resumed is True
    assert _fresh_policy.paused is False
    assert [m for m in caplog.messages if "cannot report server load" in m]


# --- sample freshness ---------------------------------------------------------------------------------


def test_a_stale_sample_decides_nothing():
    """A user-facing op's reply can carry a reading the relay took minutes ago. Pausing the mirror on a
    server that has since gone quiet, or resuming on one taken before the load arrived, is deciding on
    a number that no longer describes anything."""
    old_and_busy = _sample(cpu=95.0, age_seconds=gp_load.SAMPLE_MAX_AGE_SECONDS + 1)
    old_and_quiet = _sample(cpu=5.0, age_seconds=gp_load.SAMPLE_MAX_AGE_SECONDS + 1)

    assert gp_load.pause_reason(old_and_busy) is None
    assert gp_load.may_resume(old_and_quiet) is False


def test_a_sample_inside_the_freshness_window_still_counts():
    assert gp_load.pause_reason(_sample(cpu=95.0, age_seconds=gp_load.SAMPLE_MAX_AGE_SECONDS - 5)) is not None
    assert gp_load.may_resume(_sample(cpu=5.0, age_seconds=gp_load.SAMPLE_MAX_AGE_SECONDS - 5)) is True


def test_an_undateable_sample_counts_as_no_reading():
    """The rule is to judge by sampled_at. Without one there is nothing to judge, so it decides
    nothing - neither pausing a running policy nor resuming a paused one."""
    no_stamp = {"sql_cpu_pct": 95.0, "runnable_tasks": 0, "source": gp_load.RING_BUFFER}
    assert gp_load.pause_reason(no_stamp) is None
    assert gp_load.may_resume({**no_stamp, "sql_cpu_pct": 5.0}) is False
    assert gp_load.pause_reason({**no_stamp, "sampled_at": "not a timestamp"}) is None


def test_the_age_of_a_sample_is_read_off_its_own_stamp():
    assert gp_load.sample_age_seconds(_sample(age_seconds=30.0)) == pytest.approx(30.0, abs=2.0)
    assert gp_load.sample_age_seconds(None) is None
    assert gp_load.sample_age_seconds({"sampled_at": ""}) is None


def test_a_stale_sample_does_not_release_a_pause(_fresh_policy):
    """The dangerous direction. A quiet reading from three minutes ago is not evidence the server is
    quiet now, and treating it as such is what would put the mirror back onto a still-loaded server."""
    _fresh_policy.note_sample(_sample(cpu=95.0))
    assert _fresh_policy.paused is True

    _fresh_policy.note_sample(_sample(cpu=5.0, age_seconds=gp_load.SAMPLE_MAX_AGE_SECONDS + 30))

    assert _fresh_policy.paused is True


def test_a_fresh_quiet_sample_does_release_it(_fresh_policy):
    _fresh_policy.note_sample(_sample(cpu=95.0))
    _fresh_policy.note_sample(_sample(cpu=5.0, age_seconds=1.0))
    assert _fresh_policy.paused is False


def test_paced_call_defaults_to_marking_the_read_background(_fresh_policy, monkeypatch):
    """Everything routed through gp_load is timer-driven unless a caller says otherwise."""
    seen = {}

    async def fake_call(company, op, payload=None, *, background=False, **kwargs):
        seen["background"] = background
        return None, {"cost": None, "server": None}

    monkeypatch.setattr(gp_load.relay_gateway, "relay_call_with_meta", fake_call)

    asyncio.run(gp_load.paced_call("TUBC", "sync_pos", floor_seconds=0.0))
    assert seen["background"] is True

    asyncio.run(gp_load.paced_call("TUBC", "sync_pos", floor_seconds=0.0, background=False))
    assert seen["background"] is False


def test_the_probe_goes_out_with_no_company_and_is_not_background(_fresh_policy, monkeypatch):
    """server_load is exempt from the channel pin and never refused, so it needs no company and must
    not be marked background - being refused is the one thing the way out of a pause cannot be."""
    seen = {}
    clock = {"now": 1000.0}
    monkeypatch.setattr(gp_load.time, "monotonic", lambda: clock["now"])

    async def fake_call(company, op, payload=None, *, background=False, **kwargs):
        seen.update({"company": company, "op": op, "background": background})
        return None, {"cost": None, "server": _sample(cpu=5.0)}

    monkeypatch.setattr(gp_load.relay_gateway, "relay_call_with_meta", fake_call)
    _fresh_policy.note_sample(_sample(cpu=95.0))
    clock["now"] += gp_load.SERVER_PROBE_SECONDS + 1

    assert asyncio.run(gp_load.probe()) is True
    assert seen == {"company": "", "op": "server_load", "background": False}
