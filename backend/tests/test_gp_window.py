"""The nightly window the PO history drain is confined to (app/services/gp_window.py).

Massive sync jobs may not run during the working day. Only the BACKFILL is gated - the paginated
open-book refresh, the by-number closure fetch and the job sync are bounded and budgeted and keep
running all day, which is what makes gating just this one read safe.

Every instant here is written as UTC, because that is what the container's clock reads, and asserted
through the Toronto wall clock, because that is what the rule is about. Both an EDT date (UTC-4) and
an EST date (UTC-5) are covered: the whole reason this is not a fixed offset is that 8pm Eastern is
00:00 UTC in July and 01:00 UTC in January.
"""

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.services import gp_window

TORONTO = ZoneInfo("America/Toronto")


def _utc(iso: str) -> datetime:
    return datetime.fromisoformat(iso).replace(tzinfo=ZoneInfo("UTC"))


def _window(spec="20:00-05:00", tz="America/Toronto"):
    return gp_window.parse(spec, tz)


# --- the wrapping window, on an EDT date (Toronto is UTC-4) -------------------------------------------


@pytest.mark.parametrize(
    ("utc_instant", "local", "open_"),
    [
        ("2026-07-14T23:59:00", "19:59", False),  # a minute before it opens
        ("2026-07-15T00:00:00", "20:00", True),  # 8pm sharp: open
        ("2026-07-15T04:00:00", "00:00", True),  # midnight, the wrap itself
        ("2026-07-15T08:59:00", "04:59", True),  # a minute before it shuts
        ("2026-07-15T09:00:00", "05:00", False),  # 5am sharp: shut, the end is exclusive
        ("2026-07-15T17:00:00", "13:00", False),  # the middle of the working day
    ],
)
def test_the_window_in_summer(utc_instant, local, open_):
    window = _window()
    now = _utc(utc_instant)
    assert window.local(now).strftime("%H:%M") == local
    assert window.allows(now) is open_


@pytest.mark.parametrize(
    ("utc_instant", "local", "open_"),
    [
        ("2026-01-15T00:59:00", "19:59", False),
        ("2026-01-15T01:00:00", "20:00", True),
        ("2026-01-15T09:59:00", "04:59", True),
        ("2026-01-15T10:00:00", "05:00", False),
    ],
)
def test_the_window_in_winter(utc_instant, local, open_):
    """The same wall-clock rule, an hour later in UTC. A fixed UTC-5 would have opened the drain at
    7pm all summer and shut it at 4am - an hour of the working day, every day, for half the year."""
    window = _window()
    now = _utc(utc_instant)
    assert window.local(now).strftime("%H:%M") == local
    assert window.allows(now) is open_


def test_a_naive_instant_is_read_as_utc_never_as_local_time():
    """The Railway container runs UTC. Reading a naive clock as local time would shift the window by
    the offset and put the drain into the afternoon."""
    window = _window()
    assert window.allows(datetime(2026, 7, 15, 0, 0)) is True  # 20:00 EDT
    assert window.allows(datetime(2026, 7, 15, 17, 0)) is False  # 13:00 EDT


# --- other shapes -------------------------------------------------------------------------------------


def test_a_window_that_does_not_wrap_midnight():
    window = _window("02:00-05:00")
    assert window.allows(_utc("2026-07-15T05:59:00")) is False  # 01:59 EDT
    assert window.allows(_utc("2026-07-15T06:00:00")) is True  # 02:00 EDT
    assert window.allows(_utc("2026-07-15T08:59:00")) is True  # 04:59 EDT
    assert window.allows(_utc("2026-07-15T09:00:00")) is False  # 05:00 EDT
    # And the hours a wrapping window would have allowed are shut.
    assert window.allows(_utc("2026-07-15T02:00:00")) is False  # 22:00 EDT


def test_an_empty_window_allows_every_hour():
    """The switch a preview environment flips to exercise the drain in the afternoon."""
    window = _window("")
    assert window.always is True
    assert window.allows(_utc("2026-07-15T17:00:00")) is True
    assert window.seconds_until_open(_utc("2026-07-15T17:00:00")) == 0.0


def test_a_window_whose_ends_meet_allows_every_hour():
    window = _window("05:00-05:00")
    assert window.always is True
    assert window.allows(_utc("2026-07-15T17:00:00")) is True


# --- bad configuration --------------------------------------------------------------------------------


@pytest.mark.parametrize("spec", ["nonsense", "20:00", "25:00-05:00", "20:00-", "-05:00", "8pm-5am"])
def test_an_unusable_window_falls_back_to_the_default_not_to_always(spec):
    """The safe failure for a typo is LESS load on GP, not more. A mistyped window that silently
    became "any hour" would put the history drain back into the working day, which is the one thing
    this exists to prevent."""
    window = gp_window.parse(spec, "America/Toronto", warned=set())

    assert window.always is False
    assert window.allows(_utc("2026-07-15T17:00:00")) is False  # 13:00 EDT, still shut
    assert window.allows(_utc("2026-07-15T02:00:00")) is True  # 22:00 EDT, still open


def test_a_bad_window_says_so_once(caplog):
    warned: set[str] = set()
    with caplog.at_level(logging.ERROR, logger="app.services.gp_window"):
        for _ in range(4):
            gp_window.parse("nonsense", "America/Toronto", warned=warned)

    errors = [m for m in caplog.messages if "GP_PO_SYNC_BACKFILL_WINDOW" in m]
    assert len(errors) == 1
    assert "falling back" in errors[0]


def test_an_unusable_timezone_falls_back_to_toronto(caplog):
    with caplog.at_level(logging.ERROR, logger="app.services.gp_window"):
        window = gp_window.parse("20:00-05:00", "Mars/Olympus_Mons", warned=set())

    assert window.allows(_utc("2026-07-15T00:00:00")) is True  # 20:00 Toronto
    assert "America/Toronto" in window.label
    assert [m for m in caplog.messages if "WINDOW_TZ" in m]


def test_the_label_names_the_window_and_the_zone():
    assert _window().label == "20:00-05:00 America/Toronto"


# --- when it reopens ----------------------------------------------------------------------------------


def test_the_next_opening_is_computed_not_polled_for():
    """13:00 on a July Wednesday: the drain resumes at 20:00 that same evening."""
    window = _window()
    nxt = window.next_open(_utc("2026-07-15T17:00:00"))

    assert nxt.astimezone(TORONTO).strftime("%Y-%m-%d %H:%M") == "2026-07-15 20:00"


def test_the_next_opening_rolls_to_tomorrow_after_the_window_has_passed():
    """06:00 local - the window shut an hour ago, so the next one is tonight, not this morning."""
    window = _window()
    nxt = window.next_open(_utc("2026-07-15T10:00:00"))

    assert nxt.astimezone(TORONTO).strftime("%Y-%m-%d %H:%M") == "2026-07-15 20:00"


def test_the_next_opening_is_built_on_a_local_date_not_by_adding_a_day():
    """Across the spring-forward Sunday, adding a fixed 24 hours would land an hour out. 2026-03-08 is
    the DST change; the window still opens at 20:00 wall clock on each side of it."""
    window = _window()
    before = window.next_open(_utc("2026-03-07T18:00:00"))  # 13:00 EST on the Saturday
    after = window.next_open(_utc("2026-03-08T17:00:00"))  # 13:00 EDT on the Sunday

    assert before.astimezone(TORONTO).strftime("%H:%M") == "20:00"
    assert after.astimezone(TORONTO).strftime("%H:%M") == "20:00"
    # And the two openings really are 23 hours apart in ELAPSED time, not 24. Note the conversion to
    # UTC before subtracting: Python subtracts two aware datetimes sharing a tzinfo in wall-clock
    # terms, so the naive version of this assertion reads 24 hours and hides the very thing it checks.
    utc = ZoneInfo("UTC")
    assert (after.astimezone(utc) - before.astimezone(utc)).total_seconds() == pytest.approx(23 * 3600)


def test_an_open_window_is_due_now():
    window = _window()
    now = _utc("2026-07-15T02:00:00")
    assert window.next_open(now) == window.local(now)
    assert window.seconds_until_open(now) == 0.0


def test_the_sleep_is_capped_so_a_config_change_is_noticed():
    """The exact reopening is computed, but sleeping seven hours on it would mean a changed window or
    a corrected clock went unnoticed until dawn."""
    window = _window()
    seconds = window.seconds_until_open(_utc("2026-07-15T17:00:00"))  # 13:00 EDT, seven hours to go

    assert seconds == gp_window.MAX_SLEEP_SECONDS


def test_a_short_wait_is_reported_exactly():
    window = _window()
    seconds = window.seconds_until_open(_utc("2026-07-14T23:50:00"))  # 19:50 EDT, ten minutes to go

    assert seconds == pytest.approx(600.0)


def test_the_wait_never_goes_negative():
    window = _window("02:00-05:00")
    assert window.seconds_until_open(_utc("2026-07-15T09:00:00")) >= 0.0
    assert window.seconds_until_open(_utc("2026-07-15T09:00:00")) <= gp_window.MAX_SLEEP_SECONDS


def test_every_minute_of_the_day_is_either_open_or_shut_and_reopens_within_a_day():
    """A sweep of the whole day, so no shape of the rule can leave an instant with no answer or with a
    reopening that never comes."""
    window = _window()
    start = _utc("2026-07-15T00:00:00")
    for minutes in range(0, 24 * 60, 7):
        now = start + timedelta(minutes=minutes)
        assert isinstance(window.allows(now), bool)
        if not window.allows(now):
            utc = ZoneInfo("UTC")
            ahead = (window.next_open(now).astimezone(utc) - now.astimezone(utc)).total_seconds()
            assert 0 < ahead <= 24 * 3600
