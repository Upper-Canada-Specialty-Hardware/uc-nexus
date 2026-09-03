"""Backfill loop control for the GP PO mirror (gp-owned-po mirror). Pure async - relay + persist are
stubbed, no DB - so these run everywhere.

Covers the anti-hot-spin contract: the cursor advances only over POs that persisted, a stall is a
distinct signal so run_forever waits instead of re-reading the same page, one pass is bounded by
max_pages, and run_once forwards the caller's cap (the admin mutation passes a small one).

Also covers the throttle the twelve-company backfill forced: the env tunables and their fallbacks, the
pause between pages (never after a pass's last one), the between-pass wait that replaced run_forever's
bare `continue`, and the per-page log line that would have made the fifteen-hour drain visible.

And the two schedules run_forever drives: a backfill batch every BACKFILL_PASS_DELAY_SECONDS for the
next company still draining, an incremental pass every POLL_SECONDS for the next company already
mirrored, each on its own rotation and deadline, with the wake() path (reconnect, admin button) still
covering every company at once."""

import asyncio
import logging

import pytest

from app.errors import RelayBusyError
from app.services import gp_po_sync


@pytest.fixture(autouse=True)
def _no_page_delay(monkeypatch):
    """Every test here drains pages back to back; the real 5s pause between them is the one thing
    nothing wants to wait for. The delay's own tests set it explicitly."""
    monkeypatch.setattr(gp_po_sync, "PAGE_DELAY_SECONDS", 0.0)


def _paced(result, *, cpu_ms=None, sql_cpu_pct=None, pace=0.0, calls=None, floor_seconds=None):
    """One paced_call return. The pacing itself is gp_load's (tests/test_gp_load.py); what these tests
    care about is that the backfill loop asks for it and reports what it got."""
    if calls is not None:
        calls.append({"floor_seconds": floor_seconds})
    return {
        "result": result,
        "meta": {},
        "elapsed_ms": 12.0,
        "cpu_ms": cpu_ms,
        "sql_cpu_pct": sql_cpu_pct,
        "pace": pace,
    }


def _counts(*, stored_cursor, backfill_done, created=1):
    return {
        "created": created,
        "updated": 0,
        "skipped": 0,
        "stored_cursor": stored_cursor,
        "backfill_done": backfill_done,
    }


def _advancing_pages(monkeypatch, *, calls=None, cpu_ms=None, sql_cpu_pct=None, pace=0.0):
    """Stub a paced relay + persist pair whose cursor always advances, so a pass runs to its max_pages."""
    n = {"i": 0}
    monkeypatch.setattr(gp_po_sync, "_load_cursor", lambda c: f"C{n['i']}")

    async def fake_paced_call(company, op, payload=None, *, floor_seconds, **kwargs):
        return _paced(
            {"pos": [{"po_number": "PO"}], "next_cursor": "advance"},
            cpu_ms=cpu_ms,
            sql_cpu_pct=sql_cpu_pct,
            pace=pace,
            calls=calls,
            floor_seconds=floor_seconds,
        )

    monkeypatch.setattr(gp_po_sync.gp_load, "paced_call", fake_paced_call)

    def fake_persist(company, pos, next_cursor, *, is_backfill):
        n["i"] += 1
        return _counts(stored_cursor=f"C{n['i']}", backfill_done=False)

    monkeypatch.setattr(gp_po_sync, "_persist_page", fake_persist)
    return n


def test_backfill_stalls_when_cursor_does_not_advance(monkeypatch):
    calls = {"relay": 0}
    monkeypatch.setattr(gp_po_sync, "_load_cursor", lambda c: "C1")

    async def fake_paced_call(company, op, payload=None, *, floor_seconds, **kwargs):
        calls["relay"] += 1
        return _paced({"pos": [{"po_number": "PO1"}], "next_cursor": "C1"})

    monkeypatch.setattr(gp_po_sync.gp_load, "paced_call", fake_paced_call)
    # Cursor did not move (stored_cursor None) -> the page could not advance.
    monkeypatch.setattr(
        gp_po_sync,
        "_persist_page",
        lambda company, pos, next_cursor, *, is_backfill: _counts(stored_cursor=None, backfill_done=False),
    )

    result = asyncio.run(gp_po_sync._run_backfill("TUBC", max_pages=50))

    assert result["stalled"] is True
    assert result["backfill_done"] is False
    assert calls["relay"] == 1  # stopped after one page rather than hot-spinning


def test_backfill_drains_until_a_short_page_marks_it_done(monkeypatch):
    pages = [
        {"pos": [{"po_number": "PO1"}], "next_cursor": "C1"},
        {"pos": [{"po_number": "PO2"}], "next_cursor": None},  # short page = history drained
    ]
    state = {"i": 0, "cursor": None}
    monkeypatch.setattr(gp_po_sync, "_load_cursor", lambda c: state["cursor"])

    async def fake_paced_call(company, op, payload=None, *, floor_seconds, **kwargs):
        return _paced(pages[state["i"]])

    monkeypatch.setattr(gp_po_sync.gp_load, "paced_call", fake_paced_call)

    def fake_persist(company, pos, next_cursor, *, is_backfill):
        state["i"] += 1
        if next_cursor is None:
            return _counts(stored_cursor=None, backfill_done=True)
        state["cursor"] = next_cursor
        return _counts(stored_cursor=next_cursor, backfill_done=False)

    monkeypatch.setattr(gp_po_sync, "_persist_page", fake_persist)

    result = asyncio.run(gp_po_sync._run_backfill("TUBC", max_pages=50))

    assert result["backfill_done"] is True
    assert result["stalled"] is False
    assert result["created"] == 2


def test_backfill_is_bounded_by_max_pages(monkeypatch):
    n = _advancing_pages(monkeypatch)

    result = asyncio.run(gp_po_sync._run_backfill("TUBC", max_pages=3))

    assert result["backfill_done"] is False
    assert result["stalled"] is False
    assert n["i"] == 3  # exactly max_pages pages drained, not more


@pytest.fixture
def _one_company(monkeypatch):
    monkeypatch.setattr(gp_po_sync, "_rotations", {})
    monkeypatch.setattr(gp_po_sync.relay_gateway, "_companies", frozenset({"TUBC"}))


def test_run_once_forwards_the_backfill_cap(monkeypatch, _one_company):
    monkeypatch.setattr(gp_po_sync, "_backfill_done", lambda c: False)
    captured = {}

    async def fake_run_backfill(company, *, max_pages, **kwargs):
        captured["max_pages"] = max_pages
        return {"mode": "backfill", "backfill_done": False, "stalled": False}

    monkeypatch.setattr(gp_po_sync, "_run_backfill", fake_run_backfill)

    asyncio.run(gp_po_sync.run_once(backfill_max_pages=gp_po_sync.ADMIN_SYNC_BACKFILL_PAGES))

    assert captured["max_pages"] == gp_po_sync.ADMIN_SYNC_BACKFILL_PAGES


def test_run_once_defaults_to_the_configured_page_budget(monkeypatch, _one_company):
    """No cap from the caller means the env-derived budget, read at call time rather than frozen into
    the signature's default."""
    monkeypatch.setattr(gp_po_sync, "_backfill_done", lambda c: False)
    monkeypatch.setattr(gp_po_sync, "BACKFILL_MAX_PAGES_PER_PASS", 7)
    captured = {}

    async def fake_run_backfill(company, *, max_pages, **kwargs):
        captured["max_pages"] = max_pages
        return {"mode": "backfill", "backfill_done": False, "stalled": False}

    monkeypatch.setattr(gp_po_sync, "_run_backfill", fake_run_backfill)

    asyncio.run(gp_po_sync.run_once())

    assert captured["max_pages"] == 7


# --- throttle ----------------------------------------------------------------------------------------


def test_env_tunables_use_their_default_when_unset(monkeypatch):
    monkeypatch.delenv("GP_PO_SYNC_PAGE_DELAY_SECONDS", raising=False)

    assert gp_po_sync._env_number("GP_PO_SYNC_PAGE_DELAY_SECONDS", 5.0, float, minimum=0.0) == 5.0


def test_env_tunables_are_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("GP_PO_SYNC_PAGE_DELAY_SECONDS", " 0.25 ")
    monkeypatch.setenv("GP_PO_SYNC_BACKFILL_MAX_PAGES_PER_PASS", "40")

    assert gp_po_sync._env_number("GP_PO_SYNC_PAGE_DELAY_SECONDS", 5.0, float, minimum=0.0) == 0.25
    assert gp_po_sync._env_number("GP_PO_SYNC_BACKFILL_MAX_PAGES_PER_PASS", 12, int, minimum=1) == 40


@pytest.mark.parametrize("raw", ["", "   ", "abc", "5s", "-1", "nan"])
def test_garbage_env_tunables_fall_back_to_the_default(monkeypatch, raw):
    """A mistyped variable must never turn a throttle off or stop the mirror - it logs and the default
    stands. A negative delay counts as garbage; zero is a legitimate "no pause"."""
    monkeypatch.setattr(gp_po_sync, "_env_warned", set())
    monkeypatch.setenv("GP_PO_SYNC_PAGE_DELAY_SECONDS", raw)

    assert gp_po_sync._env_number("GP_PO_SYNC_PAGE_DELAY_SECONDS", 5.0, float, minimum=0.0) == 5.0


def test_a_zero_page_budget_is_rejected(monkeypatch):
    """0 pages per pass would stop the backfill dead, so it fails the minimum like any other garbage."""
    monkeypatch.setattr(gp_po_sync, "_env_warned", set())
    monkeypatch.setenv("GP_PO_SYNC_BACKFILL_MAX_PAGES_PER_PASS", "0")

    assert gp_po_sync._env_number("GP_PO_SYNC_BACKFILL_MAX_PAGES_PER_PASS", 12, int, minimum=1) == 12


def test_every_page_asks_gp_load_to_pace_it_with_the_page_delay_as_the_floor(monkeypatch):
    """The fixed delay is a FLOOR now, not the gap. paced_call waits out whatever the previous page
    actually cost GP before issuing the next one; the loop's job is only to hand it the floor."""
    calls: list[dict] = []
    _advancing_pages(monkeypatch, calls=calls)
    monkeypatch.setattr(gp_po_sync, "PAGE_DELAY_SECONDS", 1.5)

    asyncio.run(gp_po_sync._run_backfill("TUBC", max_pages=3))

    assert [c["floor_seconds"] for c in calls] == [1.5, 1.5, 1.5]


def test_the_loop_no_longer_sleeps_a_fixed_delay_of_its_own(monkeypatch):
    """Waiting BEFORE the next op rather than after the last one is what removes the "not after the
    final page" special case: a pass that ends still leaves its debt on the policy, and whoever runs
    the next op pays it - including across a pass boundary."""
    slept: list[float] = []
    _advancing_pages(monkeypatch)
    monkeypatch.setattr(gp_po_sync, "PAGE_DELAY_SECONDS", 1.5)

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(gp_po_sync.asyncio, "sleep", fake_sleep)

    asyncio.run(gp_po_sync._run_backfill("TUBC", max_pages=3))

    assert slept == []


def test_backfill_logs_one_line_per_page(monkeypatch, caplog):
    _advancing_pages(monkeypatch, cpu_ms=812.0, sql_cpu_pct=42.0, pace=8.1)

    with caplog.at_level(logging.INFO, logger="app.services.gp_po_sync"):
        asyncio.run(gp_po_sync._run_backfill("TUCSH", max_pages=2))

    messages = [r.getMessage() for r in caplog.records]
    page_lines = [m for m in messages if "backfill page" in m]
    assert len(page_lines) == 2
    for field in ("TUCSH", "cursor=", "pos=", "created=", "updated=", "skipped=", "stored_cursor=", "relay_ms="):
        assert field in page_lines[0], page_lines[0]
    assert "persist_ms=" in page_lines[0]
    # What the read cost GP, and what the server looked like while it ran - the two numbers that make
    # the pacing decision legible after the fact.
    assert "cpu_ms=812.0" in page_lines[0]
    assert "sql_cpu_pct=42.0" in page_lines[0]
    assert "next_pace=8.1s" in page_lines[0]
    # And one summary line for the pass on top of the per-page lines.
    assert len([m for m in messages if "backfill pass drained" in m]) == 1


# --- the two schedules -------------------------------------------------------------------------------


class _Clock:
    """A monotonic clock the fake _wait drives, so run_forever's deadline arithmetic can be tested
    without real time passing. Patching time.monotonic is safe in these tests: every await inside the
    loop is stubbed out, so the event loop itself has no timer scheduled against it."""

    def __init__(self, start=10_000.0):
        self.now = start

    def __call__(self):
        return self.now


class _LoopStopped(Exception):
    """Breaks out of run_forever's `while True` once the test has seen enough ticks."""


def _run_scheduler(monkeypatch, *, companies, draining, stalls=frozenset(), max_ticks=34, wake_at=None):
    """Drive run_forever against a fake clock and return the log of what it did, in order:
    ("all", True) for an all-companies pass, ("backfill", company), ("incremental", company),
    ("sleep", seconds).

    `wake_at` is {tick number: seconds the interrupted sleep actually consumed}, which is what a wake()
    looks like from the loop's side - the sleep returns True having burned less than it asked for. The
    consumed time is what the all-companies min gap is measured against, so it has to be controllable."""
    wake_at = wake_at or {}
    clock = _Clock()
    events: list[tuple] = []
    ticks = {"n": 0}

    monkeypatch.setattr(gp_po_sync.time, "monotonic", clock)
    monkeypatch.setattr(gp_po_sync, "_rotations", {})
    monkeypatch.setattr(gp_po_sync, "POLL_SECONDS", 900.0)
    monkeypatch.setattr(gp_po_sync, "BACKFILL_PASS_DELAY_SECONDS", 30.0)
    monkeypatch.setattr(gp_po_sync, "ALL_COMPANIES_MIN_GAP_SECONDS", 300.0)
    monkeypatch.setattr(gp_po_sync.relay_gateway, "_socket", object())
    monkeypatch.setattr(gp_po_sync.relay_gateway, "_companies", frozenset(companies))
    monkeypatch.setattr(
        gp_po_sync,
        "_backfill_phase",
        lambda cs: ([c for c in cs if c in draining], [c for c in cs if c not in draining]),
    )

    async def fake_run_once(*, all_companies=False, **kwargs):
        events.append(("all", all_companies))
        return {"mode": "incremental", "backfill_done": True, "stalled": False, "created": 0, "updated": 0}

    async def fake_backfill(company, *, max_pages, **kwargs):
        events.append(("backfill", company))
        return {
            "mode": "backfill",
            "backfill_done": False,
            "stalled": company in stalls,
            "created": 0,
            "updated": 0,
            "pos": 0,
        }

    async def fake_incremental(company, **kwargs):
        events.append(("incremental", company))
        return {"mode": "incremental", "backfill_done": True, "created": 0, "updated": 0, "skipped": 0, "pos": 0}

    async def fake_wait(seconds):
        events.append(("sleep", round(seconds, 3)))
        ticks["n"] += 1
        if ticks["n"] >= max_ticks:
            raise _LoopStopped
        consumed = wake_at.get(ticks["n"])
        clock.now += seconds if consumed is None else consumed
        return consumed is not None

    monkeypatch.setattr(gp_po_sync, "run_once", fake_run_once)
    monkeypatch.setattr(gp_po_sync, "_run_backfill", fake_backfill)
    monkeypatch.setattr(gp_po_sync, "_run_incremental", fake_incremental)
    monkeypatch.setattr(gp_po_sync, "_wait", fake_wait)

    with pytest.raises(_LoopStopped):
        asyncio.run(gp_po_sync.run_forever())
    return events


def test_the_two_schedules_run_on_their_own_cadences(monkeypatch):
    """Three companies, one already mirrored. The backfill takes a batch every 30s and only ever picks
    from the two still draining; the mirrored one waits out the full 900s for its incremental. Sharing
    one rotation is what made the tail of a backfill crawl - the last draining company only came round
    once every N poll intervals."""
    events = _run_scheduler(monkeypatch, companies=["A", "B", "DONE"], draining={"A", "B"}, max_ticks=34)

    backfills = [c for kind, c in events if kind == "backfill"]
    incrementals = [c for kind, c in events if kind == "incremental"]

    assert events[0] == ("all", True)  # startup covers everything
    assert backfills[:4] == ["A", "B", "A", "B"]  # the two draining companies, in turn
    assert "DONE" not in backfills
    assert incrementals == ["DONE"]  # and the incremental only ever takes the mirrored one
    first_incremental = next(i for i, e in enumerate(events) if e[0] == "incremental")
    # 900s of poll interval at one 30s batch each: thirty batches land before it comes due.
    assert len([1 for e in events[:first_incremental] if e[0] == "backfill"]) == 30
    assert {seconds for kind, seconds in events if kind == "sleep"} == {30.0}


def test_with_nothing_left_to_backfill_only_the_incremental_tick_runs(monkeypatch):
    events = _run_scheduler(monkeypatch, companies=["A", "B", "C"], draining=set(), max_ticks=8)

    assert not [1 for kind, _ in events if kind == "backfill"]
    assert [c for kind, c in events if kind == "incremental"] == ["A", "B", "C"]
    # And the backfill schedule stops probing on its own cadence rather than querying every 30s forever.
    assert 870.0 in {seconds for kind, seconds in events if kind == "sleep"}


def test_a_stalled_company_leaves_the_backfill_rotation_until_the_poll_tick(monkeypatch):
    """The old anti-hot-spin rule, now per company: a non-advancing cursor must not be re-read every
    pass delay, but it must not stop the companies that ARE advancing either."""
    events = _run_scheduler(monkeypatch, companies=["A", "B"], draining={"A", "B"}, stalls={"A"}, max_ticks=35)

    backfills = [c for kind, c in events if kind == "backfill"]
    assert backfills[0] == "A"  # tried once
    assert "A" not in backfills[1:30]  # then held out while B keeps draining
    assert set(backfills[1:30]) == {"B"}
    assert "A" in backfills[30:]  # and let back in once the incremental tick clears the stall


def test_a_wake_promotes_the_next_pass_to_all_companies(monkeypatch):
    """_wait reports whether wake() cut it short; that is what promotes the next pass. Startup counts
    as one too - nothing has been mirrored this process yet."""
    events = _run_scheduler(monkeypatch, companies=["A", "B"], draining={"A"}, max_ticks=4, wake_at={2: 400.0})

    assert [e for e in events if e[0] == "all"] == [("all", True), ("all", True)]


def test_a_wake_inside_the_min_gap_is_downgraded_to_the_due_ticks(monkeypatch, caplog):
    """Two wakes ten seconds apart. The first is served in full; the second lands inside the min gap
    and runs the ticks that are due instead of sweeping every company again. A relay that drops and
    re-dials within minutes (#384) would otherwise hand the mirror back the exact load this removes."""
    with caplog.at_level(logging.INFO, logger="app.services.gp_po_sync"):
        events = _run_scheduler(
            monkeypatch,
            companies=["A", "B"],
            draining={"A"},
            max_ticks=6,
            wake_at={1: 400.0, 2: 10.0},
        )

    # Startup plus the first wake. The second wake did NOT add one.
    assert [e for e in events if e[0] == "all"] == [("all", True), ("all", True)]
    assert len([1 for m in caplog.messages if "running the due ticks instead" in m]) == 1
    # Downgraded, not dropped: both schedules were marked due, so the ticks ran on the next turn.
    after = events[[e[0] for e in events].index("backfill") :]
    assert after[0] == ("backfill", "A")
    assert ("incremental", "B") in after


def test_wakes_further_apart_than_the_min_gap_each_get_their_sweep(monkeypatch):
    events = _run_scheduler(
        monkeypatch,
        companies=["A", "B"],
        draining={"A"},
        max_ticks=5,
        wake_at={1: 400.0, 2: 400.0},
    )

    # Startup plus one sweep per wake.
    assert [e for e in events if e[0] == "all"] == [("all", True)] * 3


# --- run_once's own rotation ---------------------------------------------------------------------------


TWELVE = [f"C{i:02d}" for i in range(12)]


def _rotating(monkeypatch, seen: list[str]):
    monkeypatch.setattr(gp_po_sync, "_rotations", {})
    monkeypatch.setattr(gp_po_sync.relay_gateway, "_companies", frozenset(TWELVE))
    monkeypatch.setattr(gp_po_sync, "_backfill_done", lambda c: True)

    async def fake_incremental(company, **kwargs):
        seen.append(company)
        return {"mode": "incremental", "backfill_done": True, "created": 0, "updated": 0, "skipped": 0, "pos": 0}

    monkeypatch.setattr(gp_po_sync, "_run_incremental", fake_incremental)


def test_run_once_takes_one_company_per_call_and_the_rotation_wraps(monkeypatch):
    """run_forever's routine ticks no longer come through run_once, but the admin mutation and any
    other caller still can, and a single-company call still rotates rather than repeating one."""
    seen: list[str] = []
    _rotating(monkeypatch, seen)

    for _ in range(13):
        asyncio.run(gp_po_sync.run_once())

    assert seen[:12] == TWELVE  # each company exactly once, starting at the first alphabetically
    assert seen[12] == TWELVE[0]  # and then round again


def test_the_wake_path_covers_every_company_in_one_call(monkeypatch):
    """A relay reconnect and the admin button both mean "look at all of them now"."""
    seen: list[str] = []
    _rotating(monkeypatch, seen)

    asyncio.run(gp_po_sync.run_once(all_companies=True))

    assert seen == TWELVE


def test_the_poll_interval_default_and_env_parse(monkeypatch):
    monkeypatch.delenv("GP_PO_SYNC_POLL_SECONDS", raising=False)
    assert gp_po_sync._env_number("GP_PO_SYNC_POLL_SECONDS", 900.0, float, minimum=1.0) == 900.0

    monkeypatch.setenv("GP_PO_SYNC_POLL_SECONDS", "120")
    assert gp_po_sync._env_number("GP_PO_SYNC_POLL_SECONDS", 900.0, float, minimum=1.0) == 120.0

    # A zero or negative poll would turn the loop into a spin, so it fails the minimum.
    monkeypatch.setattr(gp_po_sync, "_env_warned", set())
    monkeypatch.setenv("GP_PO_SYNC_POLL_SECONDS", "0")
    assert gp_po_sync._env_number("GP_PO_SYNC_POLL_SECONDS", 900.0, float, minimum=1.0) == 900.0


def test_the_incremental_pass_logs_one_line(monkeypatch, caplog):
    monkeypatch.setattr(gp_po_sync, "_load_watermark", lambda c: None)

    async def fake_paced_call(company, op, payload=None, *, floor_seconds, **kwargs):
        return _paced(
            {
                "pos": [
                    {"po_number": "PO1", "source_table": "work"},
                    {"po_number": "PO2", "source_table": "work"},
                    {"po_number": "PO3", "source_table": "history"},
                ]
            },
            cpu_ms=91.0,
            sql_cpu_pct=12.0,
            pace=3.0,
        )

    monkeypatch.setattr(gp_po_sync.gp_load, "paced_call", fake_paced_call)
    monkeypatch.setattr(
        gp_po_sync,
        "_persist_page",
        lambda company, pos, next_cursor, *, is_backfill: _counts(stored_cursor=None, backfill_done=False),
    )

    with caplog.at_level(logging.INFO, logger="app.services.gp_po_sync"):
        asyncio.run(gp_po_sync._run_incremental("TUCSH"))

    lines = [r.getMessage() for r in caplog.records if "incremental pass" in r.getMessage()]
    assert len(lines) == 1
    assert "TUCSH" in lines[0]
    assert "open=2" in lines[0] and "history_since=1" in lines[0]
    assert "created=1" in lines[0] and "updated=0" in lines[0]
    assert "relay_ms=" in lines[0] and "persist_ms=" in lines[0]
    assert "cpu_ms=91.0" in lines[0] and "sql_cpu_pct=12.0" in lines[0]


# --- adaptive pacing ---------------------------------------------------------------------------------


def _quiet_load(monkeypatch, *, paused=False, probe_at=0.0, resumes=False):
    """Stub gp_load's verdicts. The policy itself is tested in tests/test_gp_load.py; here the only
    question is what run_forever does when it is told GP is busy."""
    state = {"paused": paused, "probes": 0}

    def fake_paused():
        return state["paused"]

    async def fake_probe():
        state["probes"] += 1
        if resumes:
            state["paused"] = False
        return not state["paused"]

    monkeypatch.setattr(gp_po_sync.gp_load, "paused", fake_paused)
    monkeypatch.setattr(gp_po_sync.gp_load, "probe", fake_probe)
    monkeypatch.setattr(gp_po_sync.gp_load.policy, "probe_due_at", lambda: probe_at)
    return state


def test_no_tick_runs_while_gp_load_says_gp_is_too_busy(monkeypatch):
    """The ruling this exists for: Nexus must never add to an overloaded GP. While paused the loop
    does exactly one thing - ask the server how it is doing."""
    clock = _Clock()
    events: list[tuple] = []
    ticks = {"n": 0}
    monkeypatch.setattr(gp_po_sync.time, "monotonic", clock)
    monkeypatch.setattr(gp_po_sync.relay_gateway, "_socket", object())
    monkeypatch.setattr(gp_po_sync.relay_gateway, "_companies", frozenset({"TUBC"}))
    load = _quiet_load(monkeypatch, paused=True, probe_at=clock.now + 60.0)

    async def fake_run_once(**kwargs):
        events.append(("all", True))
        return {"mode": "incremental", "backfill_done": True, "stalled": False, "created": 0, "updated": 0}

    async def boom(*args, **kwargs):
        raise AssertionError("a tick ran while paused")

    async def fake_wait(seconds):
        events.append(("sleep", round(seconds, 3)))
        ticks["n"] += 1
        if ticks["n"] >= 3:
            raise _LoopStopped
        clock.now += seconds
        return False

    monkeypatch.setattr(gp_po_sync, "run_once", fake_run_once)
    monkeypatch.setattr(gp_po_sync, "_run_backfill", boom)
    monkeypatch.setattr(gp_po_sync, "_run_incremental", boom)
    monkeypatch.setattr(gp_po_sync, "_wait", fake_wait)

    with pytest.raises(_LoopStopped):
        asyncio.run(gp_po_sync.run_forever())

    assert not [e for e in events if e[0] == "all"]  # not even the startup sweep
    assert load["probes"] >= 1
    assert events[0] == ("sleep", 60.0)  # slept to the next probe, not to a tick


def test_the_pending_sweep_survives_the_pause_and_runs_on_resume(monkeypatch):
    """run_all is not consumed while paused: the sweep it promises still has to happen once the server
    recovers, or a reconnect that landed during a busy spell would never sweep at all."""
    clock = _Clock()
    events: list[tuple] = []
    ticks = {"n": 0}
    monkeypatch.setattr(gp_po_sync.time, "monotonic", clock)
    monkeypatch.setattr(gp_po_sync.relay_gateway, "_socket", object())
    monkeypatch.setattr(gp_po_sync.relay_gateway, "_companies", frozenset({"TUBC"}))
    _quiet_load(monkeypatch, paused=True, probe_at=clock.now, resumes=True)
    monkeypatch.setattr(gp_po_sync, "_backfill_phase", lambda cs: ([], list(cs)))

    async def fake_incremental(company, **kwargs):
        events.append(("incremental", company))
        return {"mode": "incremental", "backfill_done": True, "created": 0, "updated": 0, "skipped": 0, "pos": 0}

    monkeypatch.setattr(gp_po_sync, "_run_incremental", fake_incremental)

    async def fake_run_once(*, all_companies=False, **kwargs):
        events.append(("all", all_companies))
        return {"mode": "incremental", "backfill_done": True, "stalled": False, "created": 0, "updated": 0}

    async def fake_wait(seconds):
        events.append(("sleep", round(seconds, 3)))
        ticks["n"] += 1
        if ticks["n"] >= 3:
            raise _LoopStopped
        clock.now += seconds
        return False

    monkeypatch.setattr(gp_po_sync, "run_once", fake_run_once)
    monkeypatch.setattr(gp_po_sync, "_wait", fake_wait)

    with pytest.raises(_LoopStopped):
        asyncio.run(gp_po_sync.run_forever())

    assert ("all", True) in events


# --- the hello gap -----------------------------------------------------------------------------------


def _hello_pending_loop(monkeypatch, *, wake_on_hello):
    """run_forever against a relay whose socket is up but whose hello has not been read yet, with the
    company list appearing during the first sleep. Returns the event log."""
    clock = _Clock()
    events: list[tuple] = []
    ticks = {"n": 0}
    monkeypatch.setattr(gp_po_sync.time, "monotonic", clock)
    monkeypatch.setattr(gp_po_sync, "POLL_SECONDS", 900.0)
    monkeypatch.setattr(gp_po_sync, "BACKFILL_PASS_DELAY_SECONDS", 30.0)
    monkeypatch.setattr(gp_po_sync.gp_load, "HELLO_GRACE_SECONDS", 15.0)
    monkeypatch.setattr(gp_po_sync.gp_load, "paused", lambda: False)
    monkeypatch.setattr(gp_po_sync.relay_gateway, "_socket", object())
    # Connected, but GP has not told the relay its companies yet - the state EVERY connection passes
    # through, because /relay-link wakes this loop at try_register.
    monkeypatch.setattr(gp_po_sync.relay_gateway, "_companies", frozenset())
    # The routine ticks that follow the sweep must not reach for Postgres.
    monkeypatch.setattr(gp_po_sync, "_backfill_phase", lambda cs: ([], list(cs)))

    async def fake_incremental(company, **kwargs):
        events.append(("incremental", company, clock.now))
        return {"mode": "incremental", "backfill_done": True, "created": 0, "updated": 0, "skipped": 0, "pos": 0}

    monkeypatch.setattr(gp_po_sync, "_run_incremental", fake_incremental)

    async def fake_run_once(*, all_companies=False, **kwargs):
        events.append(("all", all_companies, clock.now))
        return {"mode": "incremental", "backfill_done": True, "stalled": False, "created": 0, "updated": 0}

    async def fake_wait(seconds):
        events.append(("sleep", round(seconds, 3)))
        ticks["n"] += 1
        if ticks["n"] >= 4:
            raise _LoopStopped
        clock.now += seconds
        if ticks["n"] == 1:
            # The hello lands. main.py's read loop wake()s both sync loops here.
            gp_po_sync.relay_gateway._companies = frozenset({"TUBC"})
            return wake_on_hello
        return False

    monkeypatch.setattr(gp_po_sync, "run_once", fake_run_once)
    monkeypatch.setattr(gp_po_sync, "_wait", fake_wait)

    with pytest.raises(_LoopStopped):
        asyncio.run(gp_po_sync.run_forever())
    return events, clock


def test_a_wake_before_the_hello_waits_the_grace_not_the_poll_interval(monkeypatch):
    """The 2026-09-03 regression. /relay-link calls wake() at try_register, one frame BEFORE the GP
    company list arrives, so the loop woke to connected=true and companies empty, read that as "no
    relay", and parked on POLL_SECONDS with its sweep still pending - silent for over ten minutes
    after a 17:36 reconnect."""
    events, _ = _hello_pending_loop(monkeypatch, wake_on_hello=True)

    assert events[0] == ("sleep", 15.0)
    sweeps = [e for e in events if e[0] == "all"]
    assert sweeps and sweeps[0][1] is True


def test_the_hello_driven_wake_runs_the_sweep_at_once(monkeypatch):
    """The read loop's second wake is what makes it immediate rather than merely soon."""
    events, _ = _hello_pending_loop(monkeypatch, wake_on_hello=True)

    sweep_at = next(e[2] for e in events if e[0] == "all")
    assert sweep_at == pytest.approx(10_015.0)  # the one grace sleep, cut short by the hello wake


def test_the_grace_alone_still_gets_there_without_a_wake(monkeypatch):
    """A relay build that never sends a hello, or a wake that gets lost: the sweep still happens a
    grace period later instead of a poll interval later."""
    events, _ = _hello_pending_loop(monkeypatch, wake_on_hello=False)

    sweeps = [e for e in events if e[0] == "all"]
    assert sweeps and sweeps[0][2] == pytest.approx(10_015.0)


def test_a_socket_that_is_genuinely_gone_still_waits_the_poll_interval(monkeypatch):
    """Only the hello gap gets the short grace. No socket at all is the case the poll interval is for,
    and a reconnect wakes the loop anyway."""
    clock = _Clock()
    events: list[tuple] = []
    ticks = {"n": 0}
    monkeypatch.setattr(gp_po_sync.time, "monotonic", clock)
    monkeypatch.setattr(gp_po_sync, "POLL_SECONDS", 900.0)
    monkeypatch.setattr(gp_po_sync.gp_load, "paused", lambda: False)
    monkeypatch.setattr(gp_po_sync.relay_gateway, "_socket", None)
    monkeypatch.setattr(gp_po_sync.relay_gateway, "_companies", frozenset())

    async def fake_wait(seconds):
        events.append(("sleep", round(seconds, 3)))
        ticks["n"] += 1
        if ticks["n"] >= 2:
            raise _LoopStopped
        clock.now += seconds
        return False

    monkeypatch.setattr(gp_po_sync, "_wait", fake_wait)

    with pytest.raises(_LoopStopped):
        asyncio.run(gp_po_sync.run_forever())

    assert events[0] == ("sleep", 900.0)


def test_run_once_stops_at_the_first_busy_refusal_and_says_so(monkeypatch):
    """The next company would be refused by the same server for the same reason, so one refusal ends
    the pass. It is RAISED rather than folded into a 0-created result: run_forever hands over to its
    paused branch, and the admin Sync from GP button shows why nothing happened instead of a silent
    "0 new / 0 updated" that reads like success."""
    monkeypatch.setattr(gp_po_sync, "_rotations", {})
    monkeypatch.setattr(gp_po_sync.relay_gateway, "_companies", frozenset({"A", "B", "C"}))
    monkeypatch.setattr(gp_po_sync, "_backfill_done", lambda c: True)
    tried: list[str] = []

    async def refuse(company, **kwargs):
        tried.append(company)
        raise RelayBusyError("busy", sql_cpu_pct=91.0, ceiling_pct=70.0)

    monkeypatch.setattr(gp_po_sync, "_run_incremental", refuse)

    with pytest.raises(RelayBusyError):
        asyncio.run(gp_po_sync.run_once(all_companies=True))

    assert len(tried) == 1


def test_the_timer_driven_pages_are_marked_background(monkeypatch):
    """The relay refuses background reads when GP is above its ceiling, and keys that on the flag
    rather than the op name - so the mirror's own pages have to carry it."""
    seen: list[bool] = []
    monkeypatch.setattr(gp_po_sync, "_load_cursor", lambda c: None)
    monkeypatch.setattr(gp_po_sync, "_load_watermark", lambda c: None)
    monkeypatch.setattr(
        gp_po_sync,
        "_persist_page",
        lambda company, pos, next_cursor, *, is_backfill: _counts(stored_cursor=None, backfill_done=True),
    )

    async def fake_paced_call(company, op, payload=None, *, floor_seconds, background=True, **kwargs):
        seen.append(background)
        return _paced({"pos": [], "next_cursor": None})

    monkeypatch.setattr(gp_po_sync.gp_load, "paced_call", fake_paced_call)

    asyncio.run(gp_po_sync._run_backfill("TUBC", max_pages=1))
    assert seen == [True]

    seen.clear()
    asyncio.run(gp_po_sync._run_incremental("TUBC"))
    assert seen == [True]


def test_the_admin_button_is_never_marked_background(monkeypatch):
    """A person is waiting on it. run_once defaults background=False so the relay serves it rather
    than refusing it, while paced_call still makes it take its turn in the CPU budget."""
    seen: list[bool] = []
    monkeypatch.setattr(gp_po_sync, "_rotations", {})
    monkeypatch.setattr(gp_po_sync.relay_gateway, "_companies", frozenset({"TUBC"}))
    monkeypatch.setattr(gp_po_sync, "_backfill_done", lambda c: True)

    async def fake_incremental(company, *, background=True):
        seen.append(background)
        return {"mode": "incremental", "backfill_done": True, "created": 0, "updated": 0, "skipped": 0, "pos": 0}

    monkeypatch.setattr(gp_po_sync, "_run_incremental", fake_incremental)

    # What app/schemas/po.py's syncGpPos mutation calls.
    asyncio.run(gp_po_sync.run_once(backfill_max_pages=gp_po_sync.ADMIN_SYNC_BACKFILL_PAGES, all_companies=True))
    assert seen == [False]

    seen.clear()
    asyncio.run(gp_po_sync.run_once(all_companies=True, background=True))
    assert seen == [True]
