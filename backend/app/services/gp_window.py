"""A nightly wall-clock window, for the one GP read that is allowed to be big.

Massive sync jobs may not run during the working day. The PO backfill - the one-time drain of GP's
whole purchase-order history - is confined to a window, by default 8pm to 5am Eastern. Nothing else is
gated: the paginated open-book refresh, the by-number closure fetch and the job sync keep running all
day, because they are bounded and budgeted (app/services/gp_load.py) and the point of that budget is
that they no longer need a window.

WALL CLOCK, not UTC. "8pm Eastern" has to mean 8pm in Toronto whether or not daylight saving is on,
which is 00:00 UTC in summer and 01:00 UTC in winter - so the comparison is done by converting the
instant through zoneinfo and reading the local time off it. The Railway container runs UTC, so naive
local time is never read anywhere.

Everything here is a pure function of an instant, so the whole of it is testable without a clock.
"""

import logging
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger(__name__)

DEFAULT_WINDOW = "20:00-05:00"
DEFAULT_TZ = "America/Toronto"

# Longest the caller should sleep on one "closed" answer. The exact reopening instant is computed, but
# a config change or a clock correction should be noticed within half an hour rather than at dawn.
MAX_SLEEP_SECONDS = 1800.0


class Window:
    """A daily wall-clock window in one timezone. `start == end` and an empty spec both mean always."""

    def __init__(self, start: time | None, end: time | None, tz: ZoneInfo, label: str) -> None:
        self._start = start
        self._end = end
        self._tz = tz
        self.label = label

    @property
    def always(self) -> bool:
        return self._start is None or self._end is None or self._start == self._end

    def local(self, now: datetime) -> datetime:
        """`now` in the window's own timezone. A naive instant is read as UTC, which is what the
        container's clock is - never as local time, which it never is."""
        if now.tzinfo is None:
            now = now.replace(tzinfo=ZoneInfo("UTC"))
        return now.astimezone(self._tz)

    def allows(self, now: datetime) -> bool:
        """Is the window open at this instant?

        A window that wraps midnight (20:00-05:00) is open at or after the start OR before the end; one
        that does not (02:00-05:00) is open between them. The end is exclusive so 05:00 sharp is shut,
        which is what "until 5am" means to the person who asked for it."""
        if self.always:
            return True
        current = self.local(now).time()
        if self._start < self._end:
            return self._start <= current < self._end
        return current >= self._start or current < self._end

    def next_open(self, now: datetime) -> datetime:
        """The next instant the window opens, in local time. `now` itself when it is already open.

        Built by putting the start time on today's local date and, if that has passed, tomorrow's -
        rather than by adding a fixed 24 hours, which would be an hour out across a DST change."""
        local_now = self.local(now)
        if self.always or self.allows(now):
            return local_now
        candidate = datetime.combine(local_now.date(), self._start, tzinfo=self._tz)
        if candidate <= local_now:
            candidate = datetime.combine(local_now.date() + timedelta(days=1), self._start, tzinfo=self._tz)
        return candidate

    def seconds_until_open(self, now: datetime) -> float:
        """How long to sleep before looking again. Capped at MAX_SLEEP_SECONDS so a config or clock
        change is picked up without polling every few seconds.

        Both sides are converted to UTC before subtracting. Python subtracts two aware datetimes that
        share a tzinfo in WALL-CLOCK terms, not elapsed time, so a DST transition falling between now
        and the opening would otherwise put this an hour out - 24 hours where 23 had actually passed."""
        if self.always or self.allows(now):
            return 0.0
        utc = ZoneInfo("UTC")
        delta = (self.next_open(now).astimezone(utc) - self.local(now).astimezone(utc)).total_seconds()
        return max(0.0, min(delta, MAX_SLEEP_SECONDS))


_ALWAYS = Window(None, None, ZoneInfo("UTC"), "always")


def _parse_time(raw: str) -> time:
    hour, _, minute = raw.strip().partition(":")
    parsed = time(int(hour), int(minute or 0))
    if not raw.strip() or int(hour) > 23:
        raise ValueError(raw)
    return parsed


def parse(spec: str | None, tz_name: str | None, *, warned: set[str] | None = None) -> Window:
    """Build a Window from "HH:MM-HH:MM" and an IANA zone name.

    An EMPTY spec means no window at all - backfill allowed at any hour. That is deliberate and is the
    switch a preview environment flips to exercise the backfill during the day.

    Anything UNPARSEABLE falls back to the DEFAULT window, never to always-allowed, and says so at
    ERROR. The safe failure for a typo is less load on GP, not more: a mistyped window that silently
    became "any time" would put the history drain back into the working day, which is the one thing
    this exists to prevent."""
    spec = (spec or "").strip()
    tz_name = (tz_name or "").strip() or DEFAULT_TZ
    if not spec:
        return _ALWAYS

    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        _complain(warned, "GP_PO_SYNC_BACKFILL_WINDOW_TZ", tz_name, DEFAULT_TZ)
        tz_name = DEFAULT_TZ
        tz = ZoneInfo(DEFAULT_TZ)

    start_raw, sep, end_raw = spec.partition("-")
    try:
        if not sep:
            raise ValueError(spec)
        start, end = _parse_time(start_raw), _parse_time(end_raw)
    except (TypeError, ValueError):
        _complain(warned, "GP_PO_SYNC_BACKFILL_WINDOW", spec, DEFAULT_WINDOW)
        start_raw, _, end_raw = DEFAULT_WINDOW.partition("-")
        start, end = _parse_time(start_raw), _parse_time(end_raw)
        spec = DEFAULT_WINDOW

    return Window(start, end, tz, f"{spec} {tz_name}")


def _complain(warned: set[str] | None, name: str, raw: str, fallback: str) -> None:
    """Once per variable. A misconfigured window is worth an ERROR - somebody meant to set it and it
    is not doing what they think - but not one line per check."""
    seen = warned if warned is not None else set()
    if name in seen:
        return
    seen.add(name)
    logger.error(
        "gp po sync: %s=%r is not usable; falling back to %r. The backfill stays confined to that "
        "window rather than running at any hour.",
        name,
        raw,
        fallback,
    )
