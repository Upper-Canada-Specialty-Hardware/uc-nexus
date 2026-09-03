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
def clock(monkeypatch):
    """A monotonic clock the test moves by hand. The bucket refills off elapsed time, so this is the
    whole of what makes its arithmetic testable. Autouse and declared FIRST so the policy's bucket is
    built against it - a bucket stamped with the real clock never refills against a fake one."""
    now = {"t": 1000.0}
    monkeypatch.setattr(gp_load.time, "monotonic", lambda: now["t"])
    return now


@pytest.fixture(autouse=True)
def _fresh_policy(monkeypatch, clock):
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


# --- the read budget ---------------------------------------------------------------------------------


def test_a_fresh_bucket_holds_one_minute_of_reads(clock):
    bucket = gp_load.TokenBucket(100)
    assert bucket.tokens() == pytest.approx(100.0)
    assert bucket.capacity == pytest.approx(100.0)


def test_taking_tokens_spends_them(clock):
    bucket = gp_load.TokenBucket(100)
    bucket.take(25)
    assert bucket.tokens() == pytest.approx(75.0)


def test_tokens_refill_continuously_not_in_steps(clock):
    """Continuous refill is what removes the edge a burst could line up on: after a quarter of the
    interval a quarter of the tokens are back, not none of them."""
    bucket = gp_load.TokenBucket(60)  # one a second
    bucket.take(60)
    assert bucket.tokens() == pytest.approx(0.0)
    clock["t"] += 0.5
    assert bucket.tokens() == pytest.approx(0.5)
    clock["t"] += 9.5
    assert bucket.tokens() == pytest.approx(10.0)


def test_refill_stops_at_capacity(clock):
    """An idle process may burst a minute's worth and no more - the budget is not bankable."""
    bucket = gp_load.TokenBucket(100)
    clock["t"] += 3600
    assert bucket.tokens() == pytest.approx(100.0)


def test_the_wait_for_a_batch_is_the_shortfall_at_the_refill_rate(clock):
    bucket = gp_load.TokenBucket(100)  # 100/min = 1.667/s
    bucket.take(100)
    # 25 tokens at 100 a minute is 15 seconds. This IS the documented arithmetic.
    assert bucket.wait_for(25) == pytest.approx(15.0)
    clock["t"] += 15.0
    assert bucket.wait_for(25) == pytest.approx(0.0)


def test_nothing_is_owed_when_the_tokens_are_already_there(clock):
    assert gp_load.TokenBucket(100).wait_for(25) == 0.0


def test_a_request_larger_than_the_whole_budget_is_clamped_not_deadlocked(clock):
    """A misconfigured batch should slow the sync, never wedge it."""
    bucket = gp_load.TokenBucket(10)
    bucket.take(10)
    assert bucket.wait_for(1000) == pytest.approx(60.0)  # one capacity, not a hundred minutes


def test_a_penalty_can_drive_the_balance_negative(clock):
    """The pressure brake has to be felt. Charged against a full bucket a penalty would otherwise be
    absorbed and change nothing."""
    bucket = gp_load.TokenBucket(100)
    bucket.penalise(25)
    assert bucket.tokens() == pytest.approx(75.0)
    bucket.take(75)
    bucket.penalise(50)
    assert bucket.tokens() == pytest.approx(-50.0)
    # And it is bounded, so one pathological reading cannot mute the sync for an hour.
    bucket.penalise(10_000)
    assert bucket.tokens() == pytest.approx(-100.0)


def test_acquire_returns_at_once_when_the_budget_is_there(_fresh_policy, clock, monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(gp_load.asyncio, "sleep", _recorder(slept))

    waited = asyncio.run(_fresh_policy.acquire(25))

    assert waited == 0.0
    assert slept == []
    assert _fresh_policy.bucket.tokens() == pytest.approx(gp_load.READS_PER_MINUTE - 25)


def test_acquire_waits_out_the_shortfall_then_spends(_fresh_policy, clock, monkeypatch):
    slept: list[float] = []

    async def fake_sleep(seconds):
        slept.append(seconds)
        clock["t"] += seconds

    monkeypatch.setattr(gp_load.asyncio, "sleep", fake_sleep)
    _fresh_policy.bucket.take(gp_load.READS_PER_MINUTE)  # drain it

    waited = asyncio.run(_fresh_policy.acquire(25))

    assert waited == pytest.approx(15.0)
    assert slept == [pytest.approx(15.0)]


def test_a_paused_policy_acquires_nothing(_fresh_policy, clock):
    """The brake sits on top of the budget: paused means no reads at all, not reads at a lower rate."""
    _fresh_policy.note_sample(_sample(cpu=95.0))

    with pytest.raises(RelayBusyError):
        asyncio.run(_fresh_policy.acquire(1))

    assert _fresh_policy.bucket.tokens() == pytest.approx(gp_load.READS_PER_MINUTE)


def test_the_budget_is_charged_in_keys_not_requests(_fresh_policy, clock, monkeypatch):
    """A page of 25 costs 25. Otherwise a caller could have all of GP for the price of one request by
    asking for it in one request."""
    monkeypatch.setattr(gp_load.asyncio, "sleep", _recorder([]))

    asyncio.run(_fresh_policy.acquire(25))
    asyncio.run(_fresh_policy.acquire(3))

    assert _fresh_policy.bucket.tokens() == pytest.approx(gp_load.READS_PER_MINUTE - 28)


def _recorder(into):
    async def fake_sleep(seconds):
        into.append(seconds)

    return fake_sleep


# --- pressure ----------------------------------------------------------------------------------------


def test_pressure_is_an_op_far_slower_than_that_op_normally_is():
    assert gp_load.is_under_pressure(3100.0, 1000.0) is True
    assert gp_load.is_under_pressure(2900.0, 1000.0) is False
    # No median yet, or no reading: no signal, never a false positive.
    assert gp_load.is_under_pressure(9999.0, None) is False
    assert gp_load.is_under_pressure(None, 1000.0) is False


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


def test_a_slow_op_charges_the_budget_rather_than_adding_a_delay(_fresh_policy, clock):
    """Pressure spends budget instead of pausing. A pressure PAUSE could deadlock - resuming needs a
    server sample, and the relay that cannot read server load is exactly the one this signal is for."""
    for _ in range(gp_load.MEDIAN_MIN_SAMPLES):
        _fresh_policy.note_op("TUBC", "sync_pos", {"cost": {"elapsed_ms": 100.0}}, 100.0, reads=1)
    before = _fresh_policy.bucket.tokens()

    _fresh_policy.note_op("TUBC", "sync_pos", {"cost": {"elapsed_ms": 5000.0}}, 5000.0, reads=1)

    assert _fresh_policy.bucket.tokens() == pytest.approx(before - gp_load.READ_BATCH)
    assert _fresh_policy.paused is False


def test_an_ordinary_op_charges_no_penalty(_fresh_policy, clock):
    for _ in range(gp_load.MEDIAN_MIN_SAMPLES):
        _fresh_policy.note_op("TUBC", "sync_pos", {"cost": {"elapsed_ms": 100.0}}, 100.0, reads=1)
    before = _fresh_policy.bucket.tokens()

    _fresh_policy.note_op("TUBC", "sync_pos", {"cost": {"elapsed_ms": 120.0}}, 120.0, reads=1)

    assert _fresh_policy.bucket.tokens() == pytest.approx(before)


def test_note_op_prefers_the_server_s_own_elapsed_over_our_round_trip(_fresh_policy):
    for _ in range(gp_load.MEDIAN_MIN_SAMPLES):
        _fresh_policy.note_op("TUBC", "sync_pos", {"cost": {"elapsed_ms": 100.0}}, 100.0, reads=1)
    before = _fresh_policy.bucket.tokens()

    # Our round trip looks terrible; the server says the statement itself was normal. Believe the
    # server - the difference is our own queueing, not GP's load.
    _fresh_policy.note_op("TUBC", "sync_pos", {"cost": {"elapsed_ms": 110.0}}, 9999.0, reads=1)

    assert _fresh_policy.bucket.tokens() == pytest.approx(before)


def test_note_op_falls_back_to_our_round_trip_when_the_relay_reports_none(_fresh_policy):
    for _ in range(gp_load.MEDIAN_MIN_SAMPLES):
        _fresh_policy.note_op("TUBC", "sync_pos", None, 100.0, reads=1)
    before = _fresh_policy.bucket.tokens()

    _fresh_policy.note_op("TUBC", "sync_pos", None, 5000.0, reads=1)

    assert _fresh_policy.bucket.tokens() == pytest.approx(before - gp_load.READ_BATCH)


def test_every_read_logs_what_it_cost_and_what_is_left(_fresh_policy, caplog):
    with caplog.at_level(logging.INFO, logger="app.services.gp_load"):
        _fresh_policy.note_op("TUBC", "sync_pos", {"cost": {"cpu_ms": 812.0}}, 1500.0, reads=25)

    lines = [m for m in caplog.messages if "reads=25" in m]
    assert len(lines) == 1
    assert "cpu_ms=812.0" in lines[0]
    assert "budget_left=" in lines[0]


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


def test_the_budget_still_paces_with_an_unavailable_sample(_fresh_policy):
    """No server permissions: nothing pauses, and the budget alone decides the rate. That is the whole
    degraded mode - a fixed number of reads a minute needs no VIEW SERVER STATE."""
    _fresh_policy.note_op(
        "TUBC",
        "sync_pos",
        {"cost": {"cpu_ms": 800.0}, "server": _sample(cpu=99.0, source=gp_load.UNAVAILABLE)},
        1000.0,
        reads=25,
    )

    assert _fresh_policy.paused is False
    assert _fresh_policy.bucket.tokens() == pytest.approx(gp_load.READS_PER_MINUTE)  # note_op spends nothing


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


def test_paced_call_spends_the_budget_before_the_request_goes_out(_fresh_policy, monkeypatch):
    """Charged on work REQUESTED, not on work that turned out to be expensive afterwards. By the time
    a read has cost the server something it is too late to have not asked for it."""
    seen = {}

    async def fake_call(company, op, payload=None, *, background=False, **kwargs):
        seen["tokens_at_call"] = _fresh_policy.bucket.tokens()
        return {"pos": []}, {"cost": {"cpu_ms": 500.0}, "server": _sample()}

    monkeypatch.setattr(gp_load.relay_gateway, "relay_call_with_meta", fake_call)

    call = asyncio.run(gp_load.paced_call("TUBC", "sync_pos", reads=25))

    assert seen["tokens_at_call"] == pytest.approx(gp_load.READS_PER_MINUTE - 25)
    assert call["result"] == {"pos": []}
    assert call["cpu_ms"] == 500.0
    assert call["sql_cpu_pct"] == 10.0
    assert call["waited"] == 0.0


def test_paced_call_waits_when_the_budget_is_spent(_fresh_policy, clock, monkeypatch):
    slept: list[float] = []

    async def fake_sleep(seconds):
        slept.append(seconds)
        clock["t"] += seconds

    async def fake_call(company, op, payload=None, *, background=False, **kwargs):
        return None, {"cost": None, "server": None}

    monkeypatch.setattr(gp_load.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(gp_load.relay_gateway, "relay_call_with_meta", fake_call)
    _fresh_policy.bucket.take(gp_load.READS_PER_MINUTE)

    call = asyncio.run(gp_load.paced_call("TUBC", "sync_pos", reads=25))

    assert slept == [pytest.approx(15.0)]
    assert call["waited"] == pytest.approx(15.0)


def test_paced_call_enters_the_pause_on_a_busy_refusal(_fresh_policy, monkeypatch):
    async def refuse(company, op, payload=None, *, background=False, **kwargs):
        raise RelayBusyError("busy", sql_cpu_pct=91.0, ceiling_pct=70.0, retry_after_seconds=45.0)

    monkeypatch.setattr(gp_load.relay_gateway, "relay_call_with_meta", refuse)

    with pytest.raises(RelayBusyError):
        asyncio.run(gp_load.paced_call("TUBC", "sync_pos", reads=25))

    # Paused where the error was raised, so no caller can forget to - but still raised, because the
    # caller's pass genuinely did not happen.
    assert _fresh_policy.paused is True


def test_paced_call_refuses_outright_once_paused(_fresh_policy, monkeypatch):
    """While the brake is on nothing is acquired and nothing is sent - the refusal happens here, with
    no round trip at all."""
    sent = []

    async def fake_call(company, op, payload=None, *, background=False, **kwargs):
        sent.append(op)
        return None, {"cost": None, "server": None}

    monkeypatch.setattr(gp_load.relay_gateway, "relay_call_with_meta", fake_call)
    _fresh_policy.note_sample(_sample(cpu=95.0))

    with pytest.raises(RelayBusyError):
        asyncio.run(gp_load.paced_call("TUBC", "sync_pos", reads=25))

    assert sent == []


def test_paced_call_records_the_sample_even_from_an_op_that_is_not_about_load(_fresh_policy, monkeypatch):
    async def fake_call(company, op, payload=None, *, background=False, **kwargs):
        return None, {"cost": None, "server": _sample(cpu=95.0)}

    monkeypatch.setattr(gp_load.relay_gateway, "relay_call_with_meta", fake_call)

    asyncio.run(gp_load.paced_call("TUBC", "list_jobs", reads=gp_load.JOBS_PER_READ))

    assert _fresh_policy.paused is True


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

    asyncio.run(gp_load.paced_call("TUBC", "sync_pos", reads=1))
    assert seen["background"] is True

    asyncio.run(gp_load.paced_call("TUBC", "sync_pos", reads=1, background=False))
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


def test_a_relay_downgraded_mid_pause_does_not_wedge_the_mirror(_fresh_policy, clock, monkeypatch, caplog):
    """The only probe failure that resumes. A workstation that rolled back to a build without the op
    can never answer, so staying paused would stop background reads forever - and that relay reports
    no samples either, which is exactly the budget-only mode this falls back to."""

    async def too_old(company, op, payload=None, **kwargs):
        raise RelayOpUnsupportedError(op)

    monkeypatch.setattr(gp_load.relay_gateway, "relay_call_with_meta", too_old)
    _fresh_policy.note_sample(_sample(cpu=88.0))
    clock["t"] += gp_load.SERVER_PROBE_SECONDS + 1

    with caplog.at_level(logging.WARNING, logger="app.services.gp_load"):
        resumed = asyncio.run(gp_load.probe())

    assert resumed is True
    assert _fresh_policy.paused is False
    assert [m for m in caplog.messages if "cannot report server load" in m]
