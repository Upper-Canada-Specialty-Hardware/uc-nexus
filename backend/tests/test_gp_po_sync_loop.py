"""Backfill loop control for the GP PO mirror (gp-owned-po mirror). Pure async - relay + persist are
stubbed, no DB - so these run everywhere.

Covers the anti-hot-spin contract: the cursor advances only over POs that persisted, a stall is a
distinct signal so run_forever waits instead of re-reading the same page, one pass is bounded by
max_pages, and run_once forwards the caller's cap (the admin mutation passes a small one).

Also covers the throttle the twelve-company backfill forced: the env tunables and their fallbacks, the
pause between pages (never after a pass's last one), the between-pass wait that replaced run_forever's
bare `continue`, and the per-page log line that would have made the fifteen-hour drain visible.

And the two schedules run_forever drives: the open book of the most overdue mirrored company, and a
batch of history pages for the next company still draining whenever the first has nothing due and the
nightly window is open. Neither has a delay of its own - the shared read budget is the pace - and
there is no all-companies sweep on a reconnect."""

import asyncio
import logging
from datetime import datetime

import pytest

from app.errors import RelayBusyError
from app.services import gp_load, gp_po_sync, gp_window


@pytest.fixture(autouse=True)
def _no_budget_wait(monkeypatch):
    """A fresh, unlimited read budget per test. The bucket is process-wide in production on purpose
    (one SQL server, one budget), so without this a test would inherit the previous one's balance and
    the page loops here would wait out real seconds. What the budget itself does is
    tests/test_gp_load.py's job."""
    policy = gp_load.GpLoadPolicy()
    monkeypatch.setattr(gp_load, "policy", policy)
    monkeypatch.setattr(gp_load, "READ_BATCH", 25)
    # And an always-open backfill window, so the tests that are about draining pages do not depend on
    # what time of day they happen to run. The window's own tests set it explicitly.
    monkeypatch.setattr(gp_po_sync, "BACKFILL_WINDOW", gp_window.parse("", None))


def _paced(result, *, cpu_ms=None, sql_cpu_pct=None, waited=0.0, calls=None, reads=None):
    """One paced_call return. The pacing itself is gp_load's (tests/test_gp_load.py); what these tests
    care about is that the backfill loop asks for it and reports what it got."""
    if calls is not None:
        calls.append({"reads": reads})
    return {
        "result": result,
        "meta": {},
        "elapsed_ms": 12.0,
        "cpu_ms": cpu_ms,
        "sql_cpu_pct": sql_cpu_pct,
        "waited": waited,
    }


def _counts(*, stored_cursor, backfill_done, created=1):
    return {
        "created": created,
        "updated": 0,
        "skipped": 0,
        "stored_cursor": stored_cursor,
        "backfill_done": backfill_done,
    }


def _advancing_pages(monkeypatch, *, calls=None, cpu_ms=None, sql_cpu_pct=None, waited=0.0):
    """Stub a paced relay + persist pair whose cursor always advances, so a pass runs to its max_pages."""
    n = {"i": 0}
    monkeypatch.setattr(gp_po_sync, "_load_cursor", lambda c: f"C{n['i']}")

    async def fake_paced_call(company, op, payload=None, *, reads, **kwargs):
        return _paced(
            {"pos": [{"po_number": "PO"}], "next_cursor": "advance"},
            cpu_ms=cpu_ms,
            sql_cpu_pct=sql_cpu_pct,
            waited=waited,
            calls=calls,
            reads=reads,
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

    async def fake_paced_call(company, op, payload=None, *, reads, **kwargs):
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

    async def fake_paced_call(company, op, payload=None, *, reads, **kwargs):
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
    monkeypatch.delenv("GP_PO_SYNC_POLL_SECONDS", raising=False)

    assert gp_po_sync._env_number("GP_PO_SYNC_POLL_SECONDS", 900.0, float, minimum=1.0) == 900.0


def test_env_tunables_are_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("GP_PO_SYNC_POLL_SECONDS", " 120 ")
    monkeypatch.setenv("GP_PO_SYNC_BACKFILL_MAX_PAGES_PER_PASS", "40")

    assert gp_po_sync._env_number("GP_PO_SYNC_POLL_SECONDS", 900.0, float, minimum=1.0) == 120.0
    assert gp_po_sync._env_number("GP_PO_SYNC_BACKFILL_MAX_PAGES_PER_PASS", 12, int, minimum=1) == 40


@pytest.mark.parametrize("raw", ["", "   ", "abc", "5s", "-1", "nan"])
def test_garbage_env_tunables_fall_back_to_the_default(monkeypatch, raw):
    """A mistyped variable must never turn a throttle off or stop the mirror - it logs and the default
    stands. A negative delay counts as garbage; zero is a legitimate "no pause"."""
    monkeypatch.setattr(gp_po_sync, "_env_warned", set())
    monkeypatch.setenv("GP_PO_SYNC_POLL_SECONDS", raw)

    assert gp_po_sync._env_number("GP_PO_SYNC_POLL_SECONDS", 900.0, float, minimum=1.0) == 900.0


def test_a_zero_page_budget_is_rejected(monkeypatch):
    """0 pages per pass would stop the backfill dead, so it fails the minimum like any other garbage."""
    monkeypatch.setattr(gp_po_sync, "_env_warned", set())
    monkeypatch.setenv("GP_PO_SYNC_BACKFILL_MAX_PAGES_PER_PASS", "0")

    assert gp_po_sync._env_number("GP_PO_SYNC_BACKFILL_MAX_PAGES_PER_PASS", 12, int, minimum=1) == 12


def test_every_page_charges_the_budget_its_own_batch(monkeypatch):
    """The budget is charged in KEYS, not requests: a page of READ_BATCH costs READ_BATCH. There is no
    delay between pages any more - the budget is the whole pace."""
    calls: list[dict] = []
    _advancing_pages(monkeypatch, calls=calls)

    asyncio.run(gp_po_sync._run_backfill("TUBC", max_pages=3))

    assert [c["reads"] for c in calls] == [gp_load.READ_BATCH] * 3


def test_the_loop_sleeps_nothing_of_its_own_between_pages(monkeypatch):
    """Time gaps were the wrong instrument and are gone. Whatever waiting happens happens inside
    gp_load.acquire, against a fixed number of reads a minute."""
    slept: list[float] = []
    _advancing_pages(monkeypatch)

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(gp_po_sync.asyncio, "sleep", fake_sleep)

    asyncio.run(gp_po_sync._run_backfill("TUBC", max_pages=3))

    assert slept == []


def test_a_backfill_page_asks_for_no_more_than_the_batch(monkeypatch):
    """Bounded work per request is the other half of the throttle. A 300-key page was what made one
    request able to pin the server."""
    asked: list[dict] = []

    async def fake_paced_call(company, op, payload=None, *, reads, **kwargs):
        asked.append(payload)
        return _paced({"pos": [], "next_cursor": None})

    monkeypatch.setattr(gp_po_sync, "_load_cursor", lambda c: None)
    monkeypatch.setattr(gp_po_sync.gp_load, "paced_call", fake_paced_call)
    monkeypatch.setattr(
        gp_po_sync,
        "_persist_page",
        lambda company, pos, next_cursor, *, is_backfill: _counts(stored_cursor=None, backfill_done=True),
    )

    asyncio.run(gp_po_sync._run_backfill("TUBC", max_pages=1))

    assert asked[0]["page_size"] == gp_load.READ_BATCH


def test_backfill_logs_one_line_per_page(monkeypatch, caplog):
    _advancing_pages(monkeypatch, cpu_ms=812.0, sql_cpu_pct=42.0, waited=8.1)

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
    assert "waited=8.1s" in page_lines[0]
    # And one summary line for the pass on top of the per-page lines.
    assert len([m for m in messages if "backfill pass drained" in m]) == 1


# --- the two schedules -------------------------------------------------------------------------------


class _Clock:
    """A monotonic clock the fake _wait drives, so run_forever's arithmetic can be tested without real
    time passing. Safe to patch here: every await inside the loop is stubbed, so the event loop itself
    has no timer scheduled against it."""

    def __init__(self, start=10_000.0):
        self.now = start

    def __call__(self):
        return self.now


class _LoopStopped(Exception):
    """Breaks out of run_forever's `while True` once the test has seen enough turns."""


def _run_scheduler(
    monkeypatch,
    *,
    companies,
    draining,
    stalls=frozenset(),
    max_turns=6,
    wake_at=None,
    paused=False,
):
    """Drive run_forever against a fake clock and return the log of what it did, in order:
    ("all", ...) for an all-companies pass, ("backfill", company), ("incremental", company),
    ("sleep", seconds).

    `wake_at` is {turn number: seconds the interrupted sleep actually consumed} - what a wake() looks
    like from the loop's side."""
    wake_at = wake_at or {}
    clock = _Clock()
    events: list[tuple] = []
    turns = {"n": 0}

    monkeypatch.setattr(gp_po_sync.time, "monotonic", clock)
    monkeypatch.setattr(gp_po_sync, "_rotations", {})
    # A copy, so a test that seeded the queue keeps its seed and one that did not starts empty.
    monkeypatch.setattr(gp_po_sync, "_requested", set(gp_po_sync._requested))
    monkeypatch.setattr(gp_po_sync, "POLL_SECONDS", 900.0)
    monkeypatch.setattr(gp_po_sync.gp_load, "HELLO_GRACE_SECONDS", 15.0)
    monkeypatch.setattr(gp_po_sync.gp_load, "paused", lambda: paused)
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
        turns["n"] += 1
        if turns["n"] >= max_turns:
            raise _LoopStopped
        consumed = wake_at.get(turns["n"])
        clock.now += seconds if consumed is None else consumed
        return consumed is not None

    monkeypatch.setattr(gp_po_sync, "run_once", fake_run_once)
    monkeypatch.setattr(gp_po_sync, "_run_backfill", fake_backfill)
    monkeypatch.setattr(gp_po_sync, "_run_incremental", fake_incremental)
    monkeypatch.setattr(gp_po_sync, "_wait", fake_wait)

    with pytest.raises(_LoopStopped):
        asyncio.run(gp_po_sync.run_forever())
    return events


def test_a_company_is_refreshed_then_left_alone_for_the_poll_interval(monkeypatch):
    """POLL_SECONDS is the minimum gap between passes of the SAME company, not a wait between
    requests. Its first pass runs at once; the second waits out the interval."""
    events = _run_scheduler(monkeypatch, companies=["A"], draining=set(), max_turns=3)

    assert events[0] == ("incremental", "A")
    assert events[1] == ("sleep", 0.0)  # nothing owed between a pass and whatever is due next
    assert events[2] == ("sleep", 900.0)  # nothing else to do, so wait for A to age out


def test_every_mirrored_company_is_refreshed_before_any_is_refreshed_twice(monkeypatch):
    events = _run_scheduler(monkeypatch, companies=["A", "B", "C"], draining=set(), max_turns=8)

    assert [c for kind, c in events if kind == "incremental"][:3] == ["A", "B", "C"]


def test_with_nothing_to_do_the_loop_sleeps_until_the_soonest_company_is_due(monkeypatch):
    events = _run_scheduler(monkeypatch, companies=["A"], draining=set(), max_turns=4)

    assert ("sleep", 900.0) in events


def test_a_stalled_company_leaves_the_backfill_rotation(monkeypatch):
    """The old anti-hot-spin rule: a non-advancing cursor must not be re-read every turn."""
    events = _run_scheduler(monkeypatch, companies=["A", "B"], draining={"A", "B"}, stalls={"A"}, max_turns=6)

    backfills = [c for kind, c in events if kind == "backfill"]
    assert backfills[0] == "A"
    assert "A" not in backfills[1:]


def test_there_is_no_all_companies_sweep_at_startup(monkeypatch):
    """Sweeping every company is what re-issued two unbounded open-book reads minutes after the first
    had already pinned GP's CPU. Startup resumes the rotation; it does not sweep."""
    events = _run_scheduler(monkeypatch, companies=["A", "B", "C"], draining=set(), max_turns=4)

    assert not [e for e in events if e[0] == "all"]


def test_a_wake_resumes_the_rotation_rather_than_sweeping(monkeypatch):
    """A reconnect only cuts the sleep short. The rotation carries on where it was."""
    events = _run_scheduler(monkeypatch, companies=["A", "B", "C"], draining=set(), max_turns=8, wake_at={2: 1.0})

    assert not [e for e in events if e[0] == "all"]
    # And the companies still come round in order rather than all at once.
    assert [c for kind, c in events if kind == "incremental"][:3] == ["A", "B", "C"]


def test_no_read_runs_while_gp_load_says_gp_is_too_busy(monkeypatch):
    """The brake sits on top of the budget: paused means no reads at all."""
    probes = {"n": 0}

    async def fake_probe():
        probes["n"] += 1
        return False

    monkeypatch.setattr(gp_po_sync.gp_load, "probe", fake_probe)
    monkeypatch.setattr(gp_po_sync.gp_load.policy, "probe_due_at", lambda: 10_060.0)

    events = _run_scheduler(monkeypatch, companies=["A"], draining={"A"}, paused=True, max_turns=3)

    assert not [e for e in events if e[0] in ("incremental", "backfill", "all")]
    assert probes["n"] >= 1
    assert events[0] == ("sleep", 60.0)  # slept to the next probe


# --- the hello gap -----------------------------------------------------------------------------------


def test_a_connected_relay_with_no_companies_waits_only_the_grace(monkeypatch):
    """/relay-link wakes the loops at try_register, one frame BEFORE the GP company list arrives, so
    connected-with-no-companies is the state every connection passes through. Treating it as "no
    relay" and sleeping out the poll interval is what left the mirror silent for fifteen minutes."""
    events = _run_scheduler(monkeypatch, companies=[], draining=set(), max_turns=2)

    assert events[0] == ("sleep", 15.0)


def test_a_socket_that_is_genuinely_gone_still_waits_the_poll_interval(monkeypatch):
    """Only the hello gap gets the short grace. No socket at all is what the poll interval is for, and
    a reconnect wakes the loop anyway."""
    clock = _Clock()
    events: list[tuple] = []
    turns = {"n": 0}
    monkeypatch.setattr(gp_po_sync.time, "monotonic", clock)
    monkeypatch.setattr(gp_po_sync, "POLL_SECONDS", 900.0)
    monkeypatch.setattr(gp_po_sync.gp_load, "paused", lambda: False)
    monkeypatch.setattr(gp_po_sync.relay_gateway, "_socket", None)
    monkeypatch.setattr(gp_po_sync.relay_gateway, "_companies", frozenset())

    async def fake_wait(seconds):
        events.append(("sleep", round(seconds, 3)))
        turns["n"] += 1
        if turns["n"] >= 2:
            raise _LoopStopped
        clock.now += seconds
        return False

    monkeypatch.setattr(gp_po_sync, "_wait", fake_wait)

    with pytest.raises(_LoopStopped):
        asyncio.run(gp_po_sync.run_forever())

    assert events[0] == ("sleep", 900.0)


# --- run_once's own rotation ---------------------------------------------------------------------------


TWELVE = [f"C{i:02d}" for i in range(12)]


def _rotating(monkeypatch, seen: list[str]):
    """A relay serving twelve already-mirrored companies. `seen` collects what run_once QUEUED - it
    never walks a mirrored company itself."""
    monkeypatch.setattr(gp_po_sync, "_rotations", {})
    monkeypatch.setattr(gp_po_sync, "_requested", set())
    monkeypatch.setattr(gp_po_sync.relay_gateway, "_companies", frozenset(TWELVE))
    monkeypatch.setattr(gp_po_sync, "_backfill_done", lambda c: True)
    monkeypatch.setattr(gp_po_sync, "wake", lambda: None)

    async def never(company, **kwargs):
        raise AssertionError("run_once must not walk an open book inline")

    monkeypatch.setattr(gp_po_sync, "_run_incremental", never)
    monkeypatch.setattr(gp_po_sync, "request_refresh", lambda c: seen.append(c))


def test_run_once_queues_one_company_per_call_and_the_rotation_wraps(monkeypatch):
    """run_forever's routine ticks no longer come through run_once, but the admin mutation still can,
    and a single-company call still rotates rather than repeating one."""
    seen: list[str] = []
    _rotating(monkeypatch, seen)

    for _ in range(13):
        asyncio.run(gp_po_sync.run_once())

    assert seen[:12] == TWELVE  # each company exactly once, starting at the first alphabetically
    assert seen[12] == TWELVE[0]  # and then round again


def test_the_admin_button_covers_every_company_in_one_call(monkeypatch):
    """The admin Sync from GP button is the only caller left that sweeps - a person pressed it and
    expects every company looked at."""
    seen: list[str] = []
    _rotating(monkeypatch, seen)

    result = asyncio.run(gp_po_sync.run_once(all_companies=True))

    assert seen == TWELVE
    assert result["mode"] == "queued"
    assert (result["created"], result["updated"]) == (0, 0)


def test_a_mirrored_company_is_never_walked_inside_a_request(monkeypatch):
    """UBC's open book is ~94 pages, tens of minutes. Walking it in a GraphQL request times out at the
    edge, leaves the walk running in the orphaned task, and races the loop over the same cursor row -
    two walkers on one open_book_cursor lose pages. The loop is the only walker."""
    queued: list[str] = []
    monkeypatch.setattr(gp_po_sync, "_rotations", {})
    monkeypatch.setattr(gp_po_sync, "_requested", set())
    monkeypatch.setattr(gp_po_sync.relay_gateway, "_companies", frozenset({"TUBC"}))
    monkeypatch.setattr(gp_po_sync, "_backfill_done", lambda c: True)
    monkeypatch.setattr(gp_po_sync, "wake", lambda: None)
    monkeypatch.setattr(gp_po_sync, "request_refresh", lambda c: queued.append(c))

    async def never(company, **kwargs):
        raise AssertionError("run_once walked an open book inline")

    monkeypatch.setattr(gp_po_sync, "_run_incremental", never)

    result = asyncio.run(gp_po_sync.run_once(all_companies=True))

    assert queued == ["TUBC"]
    assert result["mode"] == "queued"


def test_a_backfilling_company_still_drains_inline(monkeypatch):
    """A backfill batch IS bounded - ADMIN_SYNC_BACKFILL_PAGES pages of READ_BATCH - so the button
    still returns something the person who pressed it can see."""
    monkeypatch.setattr(gp_po_sync, "_rotations", {})
    monkeypatch.setattr(gp_po_sync, "_requested", set())
    monkeypatch.setattr(gp_po_sync.relay_gateway, "_companies", frozenset({"TUBC"}))
    monkeypatch.setattr(gp_po_sync, "_backfill_done", lambda c: False)
    drained = []

    async def fake_backfill(company, *, max_pages, **kwargs):
        drained.append(max_pages)
        return {"mode": "backfill", "backfill_done": False, "stalled": False, "created": 3, "updated": 1, "pos": 4}

    monkeypatch.setattr(gp_po_sync, "_run_backfill", fake_backfill)

    result = asyncio.run(gp_po_sync.run_once(backfill_max_pages=gp_po_sync.ADMIN_SYNC_BACKFILL_PAGES))

    assert drained == [gp_po_sync.ADMIN_SYNC_BACKFILL_PAGES]
    assert result["mode"] == "backfill"
    assert result["created"] == 3


def test_the_poll_interval_default_and_env_parse(monkeypatch):
    monkeypatch.delenv("GP_PO_SYNC_POLL_SECONDS", raising=False)
    assert gp_po_sync._env_number("GP_PO_SYNC_POLL_SECONDS", 900.0, float, minimum=1.0) == 900.0

    monkeypatch.setenv("GP_PO_SYNC_POLL_SECONDS", "120")
    assert gp_po_sync._env_number("GP_PO_SYNC_POLL_SECONDS", 900.0, float, minimum=1.0) == 120.0

    # A zero or negative poll would turn the loop into a spin, so it fails the minimum.
    monkeypatch.setattr(gp_po_sync, "_env_warned", set())
    monkeypatch.setenv("GP_PO_SYNC_POLL_SECONDS", "0")
    assert gp_po_sync._env_number("GP_PO_SYNC_POLL_SECONDS", 900.0, float, minimum=1.0) == 900.0


# --- the open-book walk ------------------------------------------------------------------------------


def _open_book(monkeypatch, pages, *, stale=(), cursor=None, started_at=None):
    """Stub one company's open-book walk. `pages` is the sequence of (pos, next_cursor) GP hands back;
    `stale` is what the closure sweep will find still open locally. Returns the request log."""
    asked: list[tuple] = []
    started_at = started_at or datetime(2026, 9, 3, 12, 0, 0)
    monkeypatch.setattr(gp_po_sync, "_begin_open_pass", lambda c, s: (cursor, started_at))
    monkeypatch.setattr(gp_po_sync, "_advance_open_pass", lambda c, cur: asked.append(("cursor", cur)))
    monkeypatch.setattr(gp_po_sync, "_finish_open_pass", lambda c: asked.append(("finish", None)))
    monkeypatch.setattr(gp_po_sync, "_po_numbers_left_open", lambda c, since: list(stale))
    monkeypatch.setattr(
        gp_po_sync,
        "_persist_page",
        lambda company, pos, next_cursor, *, is_backfill: _counts(stored_cursor=None, backfill_done=False, created=0),
    )
    state = {"i": 0}

    async def fake_paced_call(company, op, payload=None, *, reads, **kwargs):
        asked.append((op, payload, reads))
        if op == "read_pos_by_number":
            return _paced({"pos": [{"po_number": n} for n in payload["po_numbers"]]})
        pos, next_cursor = pages[state["i"]]
        state["i"] += 1
        return _paced({"pos": pos, "next_cursor": next_cursor}, cpu_ms=91.0, sql_cpu_pct=12.0)

    monkeypatch.setattr(gp_po_sync.gp_load, "paced_call", fake_paced_call)
    return asked


def test_the_open_book_is_walked_in_pages_until_the_cursor_runs_out(monkeypatch):
    """One unbounded "give me every open PO" request is what pinned GP's CPU. It is a keyset walk now,
    and each page asks for at most READ_BATCH."""
    asked = _open_book(
        monkeypatch,
        [
            ([{"po_number": "PO1"}], "PO1"),
            ([{"po_number": "PO2"}], "PO2"),
            ([{"po_number": "PO3"}], None),
        ],
    )

    asyncio.run(gp_po_sync._run_incremental("TUBC"))

    reads = [a for a in asked if a[0] == "sync_pos"]
    assert len(reads) == 3
    assert all(a[1]["open_only"] is True for a in reads)
    assert all(a[1]["page_size"] == gp_load.READ_BATCH for a in reads)
    assert [a[1]["cursor"] for a in reads] == [None, "PO1", "PO2"]


def test_every_open_page_charges_the_budget_its_batch(monkeypatch):
    asked = _open_book(monkeypatch, [([{"po_number": "PO1"}], "PO1"), ([], None)])

    asyncio.run(gp_po_sync._run_incremental("TUBC"))

    assert [a[2] for a in asked if a[0] == "sync_pos"] == [gp_load.READ_BATCH, gp_load.READ_BATCH]


def test_the_walk_stores_its_cursor_after_every_page(monkeypatch):
    """A restart mid-walk must resume, not start again - UBC's open book is 94 pages, and re-reading
    its start every restart would spend the budget without ever reaching the end."""
    asked = _open_book(monkeypatch, [([{"po_number": "PO1"}], "PO1"), ([{"po_number": "PO2"}], None)])

    asyncio.run(gp_po_sync._run_incremental("TUBC"))

    assert [a[1] for a in asked if a[0] == "cursor"] == ["PO1", None]
    assert ("finish", None) in asked  # and the walk is cleared once GP runs out of pages


def test_a_resumed_walk_starts_from_the_stored_cursor(monkeypatch):
    asked = _open_book(monkeypatch, [([{"po_number": "PO9"}], None)], cursor="PO8")

    asyncio.run(gp_po_sync._run_incremental("TUBC"))

    assert [a[1]["cursor"] for a in asked if a[0] == "sync_pos"] == ["PO8"]


def test_a_cursor_that_does_not_advance_ends_the_pass(monkeypatch):
    """Otherwise the walk re-reads one page forever, spending the whole budget on it."""
    asked = _open_book(monkeypatch, [([{"po_number": "PO1"}], "PO1")], cursor="PO1")

    asyncio.run(gp_po_sync._run_incremental("TUBC"))

    assert len([a for a in asked if a[0] == "sync_pos"]) == 1


def test_what_left_the_open_table_is_re_read_by_number(monkeypatch):
    """A PO that has closed, been voided or moved to history is invisible to every open-only page, so
    without this the register would show it outstanding forever."""
    asked = _open_book(monkeypatch, [([{"po_number": "PO1"}], None)], stale=["PO7", "PO8"])

    asyncio.run(gp_po_sync._run_incremental("TUBC"))

    by_number = [a for a in asked if a[0] == "read_pos_by_number"]
    assert len(by_number) == 1
    assert by_number[0][1]["po_numbers"] == ["PO7", "PO8"]
    # Charged its real length, not a flat page size: a trailing batch of two costs two.
    assert by_number[0][2] == 2


def test_the_closure_sweep_is_batched(monkeypatch):
    monkeypatch.setattr(gp_load, "READ_BATCH", 2)
    stale = [f"PO{i}" for i in range(5)]
    asked = _open_book(monkeypatch, [([], None)], stale=stale)

    asyncio.run(gp_po_sync._run_incremental("TUBC"))

    batches = [a[1]["po_numbers"] for a in asked if a[0] == "read_pos_by_number"]
    assert batches == [["PO0", "PO1"], ["PO2", "PO3"], ["PO4"]]


def test_nothing_unseen_means_no_by_number_reads_at_all(monkeypatch):
    asked = _open_book(monkeypatch, [([{"po_number": "PO1"}], None)], stale=[])

    asyncio.run(gp_po_sync._run_incremental("TUBC"))

    assert not [a for a in asked if a[0] == "read_pos_by_number"]


def test_the_pass_logs_what_it_walked_and_what_closed(monkeypatch, caplog):
    _open_book(monkeypatch, [([{"po_number": "PO1"}], None)], stale=["PO7"])

    with caplog.at_level(logging.INFO, logger="app.services.gp_po_sync"):
        asyncio.run(gp_po_sync._run_incremental("TUCSH"))

    pages = [m for m in caplog.messages if "open page" in m]
    assert len(pages) == 1
    assert "TUCSH" in pages[0] and "cpu_ms=91.0" in pages[0] and "sql_cpu_pct=12.0" in pages[0]
    summary = [m for m in caplog.messages if "open book refreshed" in m]
    assert len(summary) == 1
    assert "1 left the open table" in summary[0]


def test_run_once_stops_at_the_first_busy_refusal_and_says_so(monkeypatch):
    """The next company would be refused by the same server for the same reason, so one refusal ends
    the pass. It is RAISED rather than folded into a 0-created result: run_forever hands over to its
    paused branch, and the admin Sync from GP button shows why nothing happened instead of a silent
    "0 new / 0 updated" that reads like success."""
    monkeypatch.setattr(gp_po_sync, "_rotations", {})
    monkeypatch.setattr(gp_po_sync.relay_gateway, "_companies", frozenset({"A", "B", "C"}))
    monkeypatch.setattr(gp_po_sync, "_backfill_done", lambda c: False)
    tried: list[str] = []

    async def refuse(company, *, max_pages, **kwargs):
        tried.append(company)
        raise RelayBusyError("busy", sql_cpu_pct=91.0, ceiling_pct=70.0)

    monkeypatch.setattr(gp_po_sync, "_run_backfill", refuse)

    with pytest.raises(RelayBusyError):
        asyncio.run(gp_po_sync.run_once(all_companies=True))

    assert len(tried) == 1


def test_the_admin_button_is_never_marked_background(monkeypatch):
    """A person is waiting on it. run_once defaults background=False so the relay serves it rather
    than refusing it, while paced_call still makes it take its turn in the read budget."""
    seen: list[bool] = []
    monkeypatch.setattr(gp_po_sync, "_rotations", {})
    monkeypatch.setattr(gp_po_sync.relay_gateway, "_companies", frozenset({"TUBC"}))
    monkeypatch.setattr(gp_po_sync, "_backfill_done", lambda c: False)

    async def fake_backfill(company, *, max_pages, background=True, **kwargs):
        seen.append(background)
        return {"mode": "backfill", "backfill_done": False, "stalled": False, "created": 0, "updated": 0, "pos": 0}

    monkeypatch.setattr(gp_po_sync, "_run_backfill", fake_backfill)

    # What app/schemas/po.py's syncGpPos mutation calls.
    asyncio.run(gp_po_sync.run_once(backfill_max_pages=gp_po_sync.ADMIN_SYNC_BACKFILL_PAGES, all_companies=True))
    assert seen == [False]

    seen.clear()
    asyncio.run(gp_po_sync.run_once(all_companies=True, background=True))
    assert seen == [True]


# --- the nightly backfill window ----------------------------------------------------------------------


DAYTIME = datetime(2026, 7, 15, 17, 0)  # 13:00 EDT - the middle of the working day
NIGHT = datetime(2026, 7, 15, 2, 0)  # 22:00 EDT the evening before


def _at(monkeypatch, instant):
    """Freeze the backend's UTC clock. The window converts it through zoneinfo itself."""

    class _FrozenDatetime(datetime):
        @classmethod
        def utcnow(cls):
            return instant

    monkeypatch.setattr(gp_po_sync, "datetime", _FrozenDatetime)


def test_the_backfill_does_not_start_a_page_outside_the_window(monkeypatch):
    """Massive sync jobs may not run during the working day, and the history drain is the massive one."""
    pages = []
    _at(monkeypatch, DAYTIME)
    monkeypatch.setattr(gp_po_sync, "BACKFILL_WINDOW", gp_window.parse("20:00-05:00", "America/Toronto"))
    monkeypatch.setattr(gp_po_sync, "_load_cursor", lambda c: None)

    async def fake_paced_call(company, op, payload=None, *, reads, **kwargs):
        pages.append(op)
        return _paced({"pos": [], "next_cursor": None})

    monkeypatch.setattr(gp_po_sync.gp_load, "paced_call", fake_paced_call)

    result = asyncio.run(gp_po_sync._run_backfill("TUBC", max_pages=5))

    assert pages == []
    assert result["backfill_done"] is False  # nothing was drained, so nothing is finished


def test_the_backfill_runs_inside_the_window(monkeypatch):
    pages = []
    _at(monkeypatch, NIGHT)
    monkeypatch.setattr(gp_po_sync, "BACKFILL_WINDOW", gp_window.parse("20:00-05:00", "America/Toronto"))
    monkeypatch.setattr(gp_po_sync, "_load_cursor", lambda c: None)
    monkeypatch.setattr(
        gp_po_sync,
        "_persist_page",
        lambda company, pos, next_cursor, *, is_backfill: _counts(stored_cursor=None, backfill_done=True),
    )

    async def fake_paced_call(company, op, payload=None, *, reads, **kwargs):
        pages.append(op)
        return _paced({"pos": [], "next_cursor": None})

    monkeypatch.setattr(gp_po_sync.gp_load, "paced_call", fake_paced_call)

    asyncio.run(gp_po_sync._run_backfill("TUBC", max_pages=5))

    assert pages == ["sync_pos"]


def test_an_empty_window_lets_the_backfill_run_in_the_afternoon(monkeypatch):
    """The switch a preview environment flips to exercise the drain during the day."""
    pages = []
    _at(monkeypatch, DAYTIME)
    monkeypatch.setattr(gp_po_sync, "BACKFILL_WINDOW", gp_window.parse("", "America/Toronto"))
    monkeypatch.setattr(gp_po_sync, "_load_cursor", lambda c: None)
    monkeypatch.setattr(
        gp_po_sync,
        "_persist_page",
        lambda company, pos, next_cursor, *, is_backfill: _counts(stored_cursor=None, backfill_done=True),
    )

    async def fake_paced_call(company, op, payload=None, *, reads, **kwargs):
        pages.append(op)
        return _paced({"pos": [], "next_cursor": None})

    monkeypatch.setattr(gp_po_sync.gp_load, "paced_call", fake_paced_call)

    asyncio.run(gp_po_sync._run_backfill("TUBC", max_pages=1))

    assert pages == ["sync_pos"]


def test_the_gate_is_per_page_so_a_pass_stops_when_the_window_shuts(monkeypatch):
    """A page in flight at 05:00 finishes and stores its cursor; the next one waits for tonight. A
    once-per-pass check would let a pass that started at 04:55 run into the morning."""
    clock = {"utc": datetime(2026, 7, 15, 8, 58)}  # 04:58 EDT, two minutes of window left
    pages = []

    class _FrozenDatetime(datetime):
        @classmethod
        def utcnow(cls):
            return clock["utc"]

    monkeypatch.setattr(gp_po_sync, "datetime", _FrozenDatetime)
    monkeypatch.setattr(gp_po_sync, "BACKFILL_WINDOW", gp_window.parse("20:00-05:00", "America/Toronto"))
    monkeypatch.setattr(gp_po_sync, "_load_cursor", lambda c: f"C{len(pages)}")

    async def fake_paced_call(company, op, payload=None, *, reads, **kwargs):
        pages.append(op)
        clock["utc"] = datetime(2026, 7, 15, 9, 1)  # 05:01 EDT - the window shut while we read
        return _paced({"pos": [{"po_number": "PO1"}], "next_cursor": "advance"})

    monkeypatch.setattr(gp_po_sync.gp_load, "paced_call", fake_paced_call)
    monkeypatch.setattr(
        gp_po_sync,
        "_persist_page",
        lambda company, pos, next_cursor, *, is_backfill: _counts(stored_cursor="advance", backfill_done=False),
    )

    result = asyncio.run(gp_po_sync._run_backfill("TUBC", max_pages=10))

    assert pages == ["sync_pos"]  # the one in flight completed; the next waited
    assert result["stalled"] is False  # and it is not a fault, just the end of the night


def test_the_open_book_refresh_ignores_the_window(monkeypatch):
    """THE point of gating only the backfill: the register has to stay live during the working day.
    The open-book walk is bounded and budgeted, so it runs at 13:00 like any other hour."""
    asked = _open_book(monkeypatch, [([{"po_number": "PO1"}], None)], stale=["PO7"])
    _at(monkeypatch, DAYTIME)
    monkeypatch.setattr(gp_po_sync, "BACKFILL_WINDOW", gp_window.parse("20:00-05:00", "America/Toronto"))

    asyncio.run(gp_po_sync._run_incremental("TUBC"))

    assert [a[0] for a in asked if a[0] in ("sync_pos", "read_pos_by_number")] == [
        "sync_pos",
        "read_pos_by_number",
    ]


def test_the_loop_sleeps_until_the_window_reopens(monkeypatch, caplog):
    """It computes the exact reopening rather than polling, capped so a config change is noticed."""
    _at(monkeypatch, DAYTIME)
    monkeypatch.setattr(gp_po_sync, "BACKFILL_WINDOW", gp_window.parse("20:00-05:00", "America/Toronto"))

    with caplog.at_level(logging.INFO, logger="app.services.gp_po_sync"):
        events = _run_scheduler(monkeypatch, companies=["DRAIN"], draining={"DRAIN"}, max_turns=3)

    assert not [e for e in events if e[0] == "backfill"]
    # It sleeps rather than draining, and never past the cap - here the loop's own poll wake is sooner
    # than the window's seven hours, and the shorter of the two is what it waits.
    assert events[0][0] == "sleep"
    assert 0 < events[0][1] <= gp_window.MAX_SLEEP_SECONDS
    asleep = [m for m in caplog.messages if "backfill outside window" in m]
    assert len(asleep) == 1  # one line per transition, not one per check
    assert "resumes at 2026-07-15T20:00" in asleep[0]


def test_the_loop_backfills_once_the_window_is_open(monkeypatch):
    _at(monkeypatch, NIGHT)
    monkeypatch.setattr(gp_po_sync, "BACKFILL_WINDOW", gp_window.parse("20:00-05:00", "America/Toronto"))

    events = _run_scheduler(monkeypatch, companies=["DRAIN"], draining={"DRAIN"}, max_turns=3)

    assert ("backfill", "DRAIN") in events


def test_the_loop_says_so_when_the_window_reopens(monkeypatch, caplog):
    """One line each way, on the transition rather than per check. Without the second one the only
    evidence the drain resumed is that pages start appearing, which is exactly the "nothing showed it
    running" problem that started all of this."""
    calls = {"n": 0}

    class _FrozenDatetime(datetime):
        @classmethod
        def utcnow(cls):
            # The loop reads the clock once a turn. Night falls after the first.
            calls["n"] += 1
            return DAYTIME if calls["n"] == 1 else NIGHT

    monkeypatch.setattr(gp_po_sync, "datetime", _FrozenDatetime)
    monkeypatch.setattr(gp_po_sync, "BACKFILL_WINDOW", gp_window.parse("20:00-05:00", "America/Toronto"))

    with caplog.at_level(logging.INFO, logger="app.services.gp_po_sync"):
        events = _run_scheduler(monkeypatch, companies=["DRAIN"], draining={"DRAIN"}, max_turns=4)

    assert len([m for m in caplog.messages if "backfill outside window" in m]) == 1
    assert len([m for m in caplog.messages if "backfill window open" in m]) == 1
    assert ("backfill", "DRAIN") in events


def test_inside_the_window_the_backfill_goes_first(monkeypatch):
    """One draining company and one due mirrored company, at 22:00. The backfill takes the turn.

    It has to. A company's open book is ~94 pages at one page per 15 seconds - roughly 24 minutes,
    longer than POLL_SECONDS - so SOME company is always due, and a refresh-first loop would never
    once reach the backfill, not even at 3am."""
    _at(monkeypatch, NIGHT)
    monkeypatch.setattr(gp_po_sync, "BACKFILL_WINDOW", gp_window.parse("20:00-05:00", "America/Toronto"))

    events = _run_scheduler(monkeypatch, companies=["DRAIN", "MIRRORED"], draining={"DRAIN"}, max_turns=3)

    assert ("backfill", "DRAIN") in events
    assert not [e for e in events if e[0] == "incremental"]


def test_outside_the_window_the_open_book_goes_first(monkeypatch):
    """By day the register has to stay live, and the drain is not allowed to run at all."""
    _at(monkeypatch, DAYTIME)
    monkeypatch.setattr(gp_po_sync, "BACKFILL_WINDOW", gp_window.parse("20:00-05:00", "America/Toronto"))

    events = _run_scheduler(monkeypatch, companies=["DRAIN", "MIRRORED"], draining={"DRAIN"}, max_turns=3)

    assert ("incremental", "MIRRORED") in events
    assert not [e for e in events if e[0] == "backfill"]


def test_the_refresh_resumes_inside_the_window_once_nothing_is_drainable(monkeypatch):
    """The backfill owns the window only while it has work. When the last history is drained the
    refresh gets the budget back, at 3am as much as at noon."""
    _at(monkeypatch, NIGHT)
    monkeypatch.setattr(gp_po_sync, "BACKFILL_WINDOW", gp_window.parse("20:00-05:00", "America/Toronto"))

    events = _run_scheduler(monkeypatch, companies=["MIRRORED"], draining=set(), max_turns=3)

    assert ("incremental", "MIRRORED") in events


def test_a_stalled_company_hands_the_window_back_to_the_refresh(monkeypatch):
    """ "Drainable" is draining minus stalled, so a company whose cursor is stuck does not hold the
    window against the refresh - and the refresh tick is what clears the stall for its next try."""
    _at(monkeypatch, NIGHT)
    monkeypatch.setattr(gp_po_sync, "BACKFILL_WINDOW", gp_window.parse("20:00-05:00", "America/Toronto"))

    events = _run_scheduler(
        monkeypatch, companies=["DRAIN", "MIRRORED"], draining={"DRAIN"}, stalls={"DRAIN"}, max_turns=4
    )

    assert events[0] == ("backfill", "DRAIN")  # tried once
    assert ("incremental", "MIRRORED") in events  # then the refresh got the turn


# --- a requested refresh -----------------------------------------------------------------------------


def test_a_requested_company_jumps_the_rotation(monkeypatch):
    monkeypatch.setattr(gp_po_sync, "_requested", {"C"})

    events = _run_scheduler(monkeypatch, companies=["A", "B", "C"], draining=set(), max_turns=3)

    assert events[0] == ("incremental", "C")


def test_a_requested_company_is_only_walked_once(monkeypatch):
    """The request is consumed by the walk, not left standing to re-walk the same company forever."""
    monkeypatch.setattr(gp_po_sync, "_requested", {"C"})

    events = _run_scheduler(monkeypatch, companies=["A", "B", "C"], draining=set(), max_turns=4)

    assert [c for kind, c in events if kind == "incremental"] == ["C", "A", "B"]


def test_request_refresh_queues_and_wakes(monkeypatch):
    """Cheap enough for any request path: a set add and a nudge, no relay call and no database."""
    monkeypatch.setattr(gp_po_sync, "_requested", set())
    woken = []
    monkeypatch.setattr(gp_po_sync, "wake", lambda: woken.append(True))

    gp_po_sync.request_refresh("TUBC")
    gp_po_sync.request_refresh("TUBC")

    assert gp_po_sync._requested == {"TUBC"}
    assert woken == [True, True]


def _open_book_with_missing(monkeypatch, stale, missing):
    """The closure sweep, where the relay reports some of the numbers as being in neither GP table."""
    asked: list[tuple] = []
    monkeypatch.setattr(gp_po_sync, "_begin_open_pass", lambda c, s: (None, datetime(2026, 9, 3, 12, 0)))
    monkeypatch.setattr(gp_po_sync, "_advance_open_pass", lambda c, cur: None)
    monkeypatch.setattr(gp_po_sync, "_finish_open_pass", lambda c: None)
    monkeypatch.setattr(gp_po_sync, "_po_numbers_left_open", lambda c, since: list(stale))
    monkeypatch.setattr(
        gp_po_sync,
        "_persist_page",
        lambda company, pos, next_cursor, *, is_backfill: _counts(stored_cursor=None, backfill_done=False, created=0),
    )

    async def fake_paced_call(company, op, payload=None, *, reads, **kwargs):
        asked.append((op, payload))
        if op == "read_pos_by_number":
            wanted = payload["po_numbers"]
            gone = [n for n in wanted if n in missing]
            return _paced({"pos": [{"po_number": n} for n in wanted if n not in gone], "missing": gone})
        return _paced({"pos": [], "next_cursor": None})

    monkeypatch.setattr(gp_po_sync.gp_load, "paced_call", fake_paced_call)
    return asked


def test_a_po_in_neither_gp_table_is_named_once_per_pass(monkeypatch, caplog):
    """Deleted outright rather than closed or moved to history. Nothing is changed - what the register
    should do with a PO that vanished from GP is a product decision - but it is said out loud, because
    the row stays in an open stage and is re-read by number on every pass until somebody decides."""
    _open_book_with_missing(monkeypatch, stale=["PO1", "PO2", "PO3"], missing={"PO2"})

    with caplog.at_level(logging.WARNING, logger="app.services.gp_po_sync"):
        asyncio.run(gp_po_sync._run_incremental("TUCSH"))

    lines = [m for m in caplog.messages if "neither GP table" in m]
    assert len(lines) == 1
    assert "TUCSH" in lines[0]
    assert "1 PO(s)" in lines[0]
    assert "PO2" in lines[0]


def test_nothing_missing_says_nothing(monkeypatch, caplog):
    _open_book_with_missing(monkeypatch, stale=["PO1"], missing=set())

    with caplog.at_level(logging.WARNING, logger="app.services.gp_po_sync"):
        asyncio.run(gp_po_sync._run_incremental("TUBC"))

    assert not [m for m in caplog.messages if "neither GP table" in m]


def test_the_missing_list_is_capped_so_it_cannot_flood_the_log(monkeypatch, caplog):
    """One line per pass, and a company with hundreds of them names twenty."""
    monkeypatch.setattr(gp_load, "READ_BATCH", 25)
    stale = [f"PO{i:03d}" for i in range(30)]
    _open_book_with_missing(monkeypatch, stale=stale, missing=set(stale))

    with caplog.at_level(logging.WARNING, logger="app.services.gp_po_sync"):
        asyncio.run(gp_po_sync._run_incremental("TUBC"))

    lines = [m for m in caplog.messages if "neither GP table" in m]
    assert len(lines) == 1
    assert "30 PO(s)" in lines[0]  # the count is the whole truth
    assert lines[0].count("PO0") + lines[0].count("PO1") + lines[0].count("PO2") == 20
    assert lines[0].endswith("...")


def test_the_missing_are_gathered_across_every_batch(monkeypatch, caplog):
    monkeypatch.setattr(gp_load, "READ_BATCH", 2)
    _open_book_with_missing(monkeypatch, stale=["A", "B", "C", "D"], missing={"A", "D"})

    with caplog.at_level(logging.WARNING, logger="app.services.gp_po_sync"):
        asyncio.run(gp_po_sync._run_incremental("TUBC"))

    lines = [m for m in caplog.messages if "neither GP table" in m]
    assert len(lines) == 1
    assert "2 PO(s)" in lines[0] and "A, D" in lines[0]


def test_a_requested_refresh_still_waits_for_the_backfill_inside_the_window(monkeypatch):
    """Following the priority rule exactly: inside the window, while anything is drainable, the
    backfill goes first - and a queued refresh is still a refresh. So an operator who presses Sync
    from GP at 10pm gets their walk when the drain runs out of work or the window shuts, not at once.

    Worth knowing rather than hidden: outside the window (the working day, when somebody is actually
    looking at the register) the request is served on the very next turn."""
    _at(monkeypatch, NIGHT)
    monkeypatch.setattr(gp_po_sync, "BACKFILL_WINDOW", gp_window.parse("20:00-05:00", "America/Toronto"))
    monkeypatch.setattr(gp_po_sync, "_requested", {"MIRRORED"})

    events = _run_scheduler(monkeypatch, companies=["DRAIN", "MIRRORED"], draining={"DRAIN"}, max_turns=3)

    assert events[0] == ("backfill", "DRAIN")
    assert not [e for e in events if e[0] == "incremental"]


def test_a_requested_refresh_is_served_at_once_during_the_working_day(monkeypatch):
    _at(monkeypatch, DAYTIME)
    monkeypatch.setattr(gp_po_sync, "BACKFILL_WINDOW", gp_window.parse("20:00-05:00", "America/Toronto"))
    monkeypatch.setattr(gp_po_sync, "_requested", {"MIRRORED"})

    events = _run_scheduler(monkeypatch, companies=["DRAIN", "MIRRORED"], draining={"DRAIN"}, max_turns=3)

    assert events[0] == ("incremental", "MIRRORED")
