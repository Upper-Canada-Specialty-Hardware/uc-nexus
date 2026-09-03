"""Adaptive pacing for every background read Nexus makes against GP.

The rule this serves: neither Nexus nor its relay may ever contribute to an overload of the GP SQL
server. The fixed waits the PO mirror shipped with (#672) were a guess - right for the server as it was
that afternoon, wrong the moment somebody runs a month-end close - so they stay only as FLOORS. What
actually paces the reads is the server's own live state, which the relay now reports on every reply:

  - `cost` {cpu_ms, logical_reads, elapsed_ms}: what the op it just ran cost, by SQL Server's own
    accounting for that session. This is the number a CPU budget can be enforced against.
  - `server` {sql_cpu_pct, other_cpu_pct, runnable_tasks, sampled_at, source}: a sample of the whole
    instance, from the scheduler-monitor ring buffer. `source: "unavailable"` when the relay's SQL
    login lacks VIEW SERVER STATE, in which case pacing runs on cost and elapsed time alone.

Three mechanisms, in increasing order of bluntness:

  1. BUDGET. Nexus's background reads get GP_SYNC_CPU_BUDGET_CORES of CPU on average. An op that cost
     cpu_ms must be followed by cpu_ms / budget of quiet before the next one, so the long-run average
     stays under budget no matter how expensive the individual reads turn out to be. At the 0.10
     default an 800 ms page buys an 8 second gap.
  2. PRESSURE. Per (company, op) rolling median of elapsed_ms. An op that took more than 3x its own
     median is the server telling us it is busy, and it is the only such signal available without
     VIEW SERVER STATE - so it doubles the next wait.
  3. PAUSE. With a real server sample, CPU at or above the pause threshold (or the runnable-task queue
     backed up) stops background reads outright, and a `server_busy` refusal from the relay does the
     same. Resume needs BOTH numbers back under their (lower) resume thresholds, so a server hovering
     at the line does not flap in and out of paused.

The state lives in one process-wide POLICY shared by the PO mirror and the job sync, because the thing
being protected is one SQL server and two independent budgets would each politely stay under half of a
limit neither of them owns. Everything that decides anything is a pure function taking numbers and
returning numbers, so the policy is testable without a relay, a database, or a clock.
"""

import asyncio
import logging
import math
import os
import statistics
import time
from collections import defaultdict, deque
from datetime import datetime

from app.errors import RelayBusyError, RelayOpUnsupportedError
from app.services.relay_gateway import gateway as relay_gateway

logger = logging.getLogger(__name__)

_env_warned: set[str] = set()


def env_number(name: str, default, cast, *, minimum, warned: set[str] | None = None, prefix: str = "gp load"):
    """One numeric tunable from the environment, falling back to `default` on anything unparseable or
    below `minimum`, and logging that fallback once per variable.

    Shared rather than duplicated: gp_po_sync had this first and still owns its own `warned` set and
    log prefix, which is why both are arguments. A mistyped variable must never stop a sync or, worse,
    turn a throttle off, so the fallback is silent-safe rather than fatal."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = cast(raw.strip())
    except (TypeError, ValueError):
        value = None
    # isfinite before the comparison: float("nan") parses happily and every comparison against it is
    # False, so a NaN would sail past a bare `< minimum` and become the throttle.
    if value is None or not math.isfinite(value) or value < minimum:
        seen = _env_warned if warned is None else warned
        if name not in seen:
            seen.add(name)
            logger.warning("%s: ignoring unusable %s=%r; using %s", prefix, name, raw, default)
        return default
    return value


# How much CPU Nexus's background reads may average on the GP server, in cores. 0.10 is a tenth of one
# core - small enough to be invisible on any box that runs GP, large enough that a backfill still
# finishes. The floor is 0.01 rather than 0: a zero budget is an infinite wait, which is not a throttle
# but a deadlock.
CPU_BUDGET_CORES = env_number("GP_SYNC_CPU_BUDGET_CORES", 0.10, float, minimum=0.01)
# Pause/resume band for the live sample. The gap between them is the hysteresis: resuming at the same
# number that paused would flap once per probe on a server sitting at the line.
SERVER_CPU_PAUSE_PCT = env_number("GP_SYNC_SERVER_CPU_PAUSE_PCT", 70.0, float, minimum=1.0)
SERVER_CPU_RESUME_PCT = env_number("GP_SYNC_SERVER_CPU_RESUME_PCT", 50.0, float, minimum=1.0)
# Runnable tasks is CPU pressure the percentage can miss: a queue of tasks waiting for a scheduler
# means the server is already behind, whatever the averaged CPU says.
SERVER_RUNNABLE_PAUSE = env_number("GP_SYNC_SERVER_RUNNABLE_PAUSE", 8, int, minimum=1)
# How often a paused policy asks the server how it is doing. The probe is the `server_load` op, which
# reads the ring buffer and nothing else.
SERVER_PROBE_SECONDS = env_number("GP_SYNC_SERVER_PROBE_SECONDS", 60.0, float, minimum=1.0)

# How long a sync loop waits when the relay socket is up but its hello frame - which carries the GP
# company list - has not been read yet. /relay-link wakes the loops the instant try_register succeeds,
# which is BEFORE that frame arrives, so every connection passes through a moment where `connected` is
# true and `companies` is empty. Treating that as "no relay" and sleeping out the poll interval is what
# left the mirror silent for fifteen minutes after the 2026-09-03 17:36 reconnect. The read loop wakes
# the loops again on the hello, so this is only the backstop for a relay that never sends one.
HELLO_GRACE_SECONDS = env_number("GP_SYNC_HELLO_GRACE_SECONDS", 15.0, float, minimum=1.0)

# An op slower than this multiple of its own median is treated as the server being under pressure.
PRESSURE_MULTIPLE = 3.0
# What pressure alone may do to a wait: double it, but never past this multiple of the floor.
PRESSURE_MAX_FLOOR_MULTIPLE = 10.0
# Rolling window per (company, op), and the count below which the median is not trusted. Two samples
# make a median that a third normal reading can exceed by 3x on noise alone.
MEDIAN_WINDOW = 20
MEDIAN_MIN_SAMPLES = 5

# How old a sample may be and still decide anything. A user-facing op's reply can carry a `server`
# block the relay sampled some time ago, and pausing the mirror on a two-minute-old reading of a
# server that has since gone quiet - or, worse, resuming on one taken before the load arrived - is
# deciding on a number that no longer describes anything. Stale reads as absent.
SAMPLE_MAX_AGE_SECONDS = 120.0

# The op that asks for nothing but a sample of the server. Company-agnostic and exempt from the
# relay's channel pin, so it goes out with an empty company and is never refused - which is what lets
# a paused policy recover even when no hello has landed and no company is known.
SERVER_LOAD_OP = "server_load"

RING_BUFFER = "ring_buffer"
UNAVAILABLE = "unavailable"


# --- pure decisions ----------------------------------------------------------------------------------


def spacing_ms(cpu_ms: float | None, *, budget_cores: float | None = None) -> float:
    """Quiet time one op earns, in ms: the wall clock over which its CPU cost averages out to the
    budget. 400 ms of CPU at a 0.10-core budget is 4 s of wall clock. No cost reported (an older relay,
    or an op the server did not account for) means no budget claim, hence no spacing."""
    budget = CPU_BUDGET_CORES if budget_cores is None else budget_cores
    if not cpu_ms or cpu_ms <= 0:
        return 0.0
    return cpu_ms / max(budget, 0.01)


def is_under_pressure(elapsed_ms: float | None, median_ms: float | None) -> bool:
    """Did this op take dramatically longer than the same op normally takes? The one load signal that
    needs no server permissions at all."""
    if not elapsed_ms or not median_ms or median_ms <= 0:
        return False
    return elapsed_ms > median_ms * PRESSURE_MULTIPLE


def pace_seconds(
    *,
    floor_seconds: float,
    cpu_ms: float | None,
    elapsed_ms: float | None,
    under_pressure: bool = False,
    budget_cores: float | None = None,
) -> float:
    """How long to stay quiet before the next background op.

    The budget claim is spacing minus the time the op already spent - waiting is only owed for the
    quiet the op has not already provided by being slow. The floor is the configured fixed delay, which
    this can raise but never undercut.

    Pressure doubles the result, capped at PRESSURE_MAX_FLOOR_MULTIPLE x the floor. The cap is on what
    PRESSURE may add, not on the total: a genuinely expensive op whose budget spacing already exceeds
    that cap keeps its spacing, because shrinking it would break the budget the cap exists to protect."""
    spacing = spacing_ms(cpu_ms, budget_cores=budget_cores)
    owed = (spacing - (elapsed_ms or 0.0)) / 1000.0
    base = max(floor_seconds, owed)
    if not under_pressure:
        return base
    return max(base, min(base * 2, floor_seconds * PRESSURE_MAX_FLOOR_MULTIPLE))


def sample_age_seconds(sample: dict | None, *, now: datetime | None = None) -> float | None:
    """How long ago the relay took this reading, or None when it cannot be told. `sampled_at` is the
    relay's own clock, so this is approximate across a workstation-to-Railway clock skew - which is
    fine for a 120-second freshness gate and is the reason the gate is not tighter."""
    stamp = (sample or {}).get("sampled_at")
    if not stamp:
        return None
    try:
        taken = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    reference = now or (datetime.now(taken.tzinfo) if taken.tzinfo else datetime.utcnow())
    return (reference - taken).total_seconds()


def is_usable(sample: dict | None) -> bool:
    """A real ring-buffer reading, recent enough to still describe the server. Everything else -
    absent, `unavailable`, undateable, or older than SAMPLE_MAX_AGE_SECONDS - is treated as no reading
    at all, which neither pauses a running policy nor resumes a paused one."""
    if not sample or sample.get("source") != RING_BUFFER:
        return False
    age = sample_age_seconds(sample)
    if age is None:
        # Undateable: the one field that decides freshness is missing or unparseable, so its age
        # cannot be judged - and the rule is to judge by sampled_at.
        return False
    return age <= SAMPLE_MAX_AGE_SECONDS


def pause_reason(sample: dict | None) -> str | None:
    """Why background reads should stop, or None to keep going. Only a real ring-buffer sample can
    decide this: an absent or `unavailable` sample is not evidence that the server is fine, but it is
    also not evidence that it is not, and pausing on no evidence would stop the mirror forever on every
    relay whose login lacks VIEW SERVER STATE. A reading too old to describe the server now is in the
    same category as one that was never taken."""
    if not is_usable(sample):
        return None
    cpu = sample.get("sql_cpu_pct")
    runnable = sample.get("runnable_tasks")
    if cpu is not None and cpu >= SERVER_CPU_PAUSE_PCT:
        return f"sql cpu {cpu}% at or above the {SERVER_CPU_PAUSE_PCT}% ceiling"
    if runnable is not None and runnable >= SERVER_RUNNABLE_PAUSE:
        return f"{runnable} runnable tasks at or above {SERVER_RUNNABLE_PAUSE}"
    return None


def may_resume(sample: dict | None) -> bool:
    """Both numbers back under their resume thresholds. A sample that is missing or unavailable does
    NOT resume: the policy paused on evidence and needs evidence to un-pause, and the probe that
    produced no reading simply runs again. A stale sample is no evidence - resuming on a reading taken
    before the load arrived is exactly the wrong failure."""
    if not is_usable(sample):
        return False
    cpu = sample.get("sql_cpu_pct")
    runnable = sample.get("runnable_tasks")
    if cpu is None or cpu >= SERVER_CPU_RESUME_PCT:
        return False
    if runnable is not None and runnable >= SERVER_RUNNABLE_PAUSE:
        return False
    return True


# --- the policy --------------------------------------------------------------------------------------


class GpLoadPolicy:
    """The shared pacing state: rolling medians, the next moment a background op may run, and the
    pause state machine. One instance per process (`policy` below) because one SQL server is what is
    being protected."""

    def __init__(self) -> None:
        self._elapsed: dict[tuple[str, str], deque] = defaultdict(lambda: deque(maxlen=MEDIAN_WINDOW))
        # Monotonic instant the next background op may start. In the past means "go now".
        self._next_op_at: float = 0.0
        self._paused_reason: str | None = None
        self._probe_at: float = 0.0
        self._unavailable_warned = False

    # -- medians ---------------------------------------------------------------------------------

    def observe(self, company: str, op: str, elapsed_ms: float | None) -> None:
        if elapsed_ms and elapsed_ms > 0:
            self._elapsed[(company, op)].append(float(elapsed_ms))

    def median_ms(self, company: str, op: str) -> float | None:
        samples = self._elapsed.get((company, op))
        if not samples or len(samples) < MEDIAN_MIN_SAMPLES:
            return None
        return statistics.median(samples)

    # -- pause state -----------------------------------------------------------------------------

    @property
    def paused(self) -> bool:
        return self._paused_reason is not None

    @property
    def paused_reason(self) -> str | None:
        return self._paused_reason

    def probe_due_at(self) -> float:
        """Monotonic instant of the next probe. Meaningless unless paused."""
        return self._probe_at

    def enter_pause(self, reason: str, *, retry_after_seconds: float | None = None) -> None:
        """Stop background reads. Re-entering an existing pause only pushes the next probe out, which
        is what a second refusal while already paused should do."""
        first = not self.paused
        self._paused_reason = reason
        delay = SERVER_PROBE_SECONDS if not retry_after_seconds or retry_after_seconds <= 0 else retry_after_seconds
        self._probe_at = time.monotonic() + delay
        if first:
            logger.info(
                "gp load: pausing background GP reads - %s; probing every %ss until it clears",
                reason,
                round(delay, 1),
            )

    def leave_pause(self, sample: dict | None) -> None:
        if not self.paused:
            return
        logger.info(
            "gp load: resuming background GP reads - sql cpu %s%% below %s%%, %s runnable",
            (sample or {}).get("sql_cpu_pct"),
            SERVER_CPU_RESUME_PCT,
            (sample or {}).get("runnable_tasks"),
        )
        self._paused_reason = None
        self._probe_at = 0.0

    def note_sample(self, sample: dict | None) -> None:
        """Feed a server sample through the pause state machine, whichever op it rode in on."""
        if sample is not None and sample.get("source") == UNAVAILABLE and not self._unavailable_warned:
            self._unavailable_warned = True
            logger.warning(
                "gp load: the relay's SQL login cannot read server load (VIEW SERVER STATE not granted), "
                "so GP reads are paced on op cost and elapsed time only, with no pause on server CPU. "
                "Grant VIEW SERVER STATE to the relay's login to enable the full throttle."
            )
        if self.paused:
            if may_resume(sample):
                self.leave_pause(sample)
            return
        reason = pause_reason(sample)
        if reason:
            self.enter_pause(reason)

    def note_busy(self, error: RelayBusyError) -> None:
        """The relay refused an op before running it. Same pause, and its retry advice becomes the
        first probe delay - the relay is closer to the server than we are."""
        detail = f"relay refused: sql cpu {error.sql_cpu_pct}% above its {error.ceiling_pct}% ceiling"
        self.enter_pause(detail, retry_after_seconds=error.retry_after_seconds)

    # -- pacing ----------------------------------------------------------------------------------

    def note_op(self, company: str, op: str, meta: dict | None, elapsed_ms: float, *, floor_seconds: float) -> float:
        """Record what an op cost and when the next one may run. Returns the pace in seconds.

        `elapsed_ms` is the backend's own wall-clock measurement of the round trip, used when the relay
        reports no cost block - it is always available and is never smaller than the server's own
        elapsed, so falling back to it is conservative in the right direction."""
        meta = meta or {}
        cost = meta.get("cost") or {}
        self.note_sample(meta.get("server"))

        server_elapsed = cost.get("elapsed_ms")
        measured = float(server_elapsed) if server_elapsed else float(elapsed_ms or 0.0)
        median = self.median_ms(company, op)
        pressured = is_under_pressure(measured, median)
        self.observe(company, op, measured)

        cpu_ms = cost.get("cpu_ms")
        pace = pace_seconds(
            floor_seconds=floor_seconds,
            cpu_ms=cpu_ms,
            elapsed_ms=measured,
            under_pressure=pressured,
        )
        self._next_op_at = time.monotonic() + pace
        if pace > floor_seconds:
            logger.info(
                "gp load: %s %s paced %.1fs (floor %.1fs) - cpu_ms=%s elapsed_ms=%.0f median_ms=%s%s",
                company,
                op,
                pace,
                floor_seconds,
                cpu_ms,
                measured,
                None if median is None else round(median),
                " pressure=3x" if pressured else "",
            )
        return pace

    def wait_seconds(self) -> float:
        """Seconds still owed before the next background op may run."""
        return max(0.0, self._next_op_at - time.monotonic())

    def next_op_at(self) -> float:
        return self._next_op_at

    def defer(self, seconds: float) -> None:
        """Push the next-op instant out by hand, for a caller that could not run its op at all."""
        self._next_op_at = max(self._next_op_at, time.monotonic() + max(0.0, seconds))

    def reset(self) -> None:
        """Drop every observation and clear the pause. For tests, and for a relay reconnect where the
        medians describe a server we can no longer assume is the same one."""
        self._elapsed.clear()
        self._next_op_at = 0.0
        self._paused_reason = None
        self._probe_at = 0.0


policy = GpLoadPolicy()


# --- the bits that touch the relay -------------------------------------------------------------------


async def paced_call(
    company: str,
    op: str,
    payload: dict | None = None,
    *,
    floor_seconds: float,
    timeout: float | None = None,
    background: bool = True,
) -> dict:
    """Run one op with pacing on both sides of it.

    `background` is the flag the relay's busy gate keys on, and it defaults True because everything
    routed through here is a timer-driven read. The exception is a person pressing a button: the admin
    Sync from GP path runs the same code with background=False, so it is served rather than refused,
    while still taking its turn in the budget - a deliberate action should be slow if the server is
    busy, not silently dropped.

    Waits out whatever the previous op earned, makes the call, records the cost, and returns
    {"result", "meta", "elapsed_ms", "cpu_ms", "sql_cpu_pct", "pace"} - everything a caller needs for
    its own log line without reaching into the meta itself.

    A `server_busy` refusal enters the pause here rather than at each call site, so no caller can
    forget to; the error still propagates, because the caller's pass genuinely did not happen."""
    wait = policy.wait_seconds()
    if wait > 0:
        await asyncio.sleep(wait)

    started = time.monotonic()
    try:
        kwargs = {} if timeout is None else {"timeout": timeout}
        result, meta = await relay_gateway.relay_call_with_meta(company, op, payload, background=background, **kwargs)
    except RelayBusyError as e:
        policy.note_busy(e)
        raise
    elapsed_ms = (time.monotonic() - started) * 1000
    pace = policy.note_op(company, op, meta, elapsed_ms, floor_seconds=floor_seconds)
    cost = (meta or {}).get("cost") or {}
    server = (meta or {}).get("server") or {}
    return {
        "result": result,
        "meta": meta,
        "elapsed_ms": elapsed_ms,
        "cpu_ms": cost.get("cpu_ms"),
        "sql_cpu_pct": server.get("sql_cpu_pct"),
        "pace": pace,
    }


async def probe() -> bool:
    """While paused, ask the server how it is doing - but only when a probe is actually due. Returns
    True if the policy is now running again.

    The probe is `server_load`, which the relay exempts from its channel pin and never refuses, so it
    goes out with an empty company and needs none in hand - a paused policy can therefore recover even
    with no hello landed and no company known. It is deliberately NOT budget-paced and NOT marked
    background: it reads the ring buffer and nothing else, and it is the only way out of the pause.

    A probe that cannot answer leaves the pause exactly as it was and tries again next interval; the
    alternative, resuming because we could not ask, is precisely the wrong failure. The one exception
    is a relay that does not have the op at all, which can only happen if the workstation rolled BACK
    to a build predating it while we were paused - there is no way to ask that relay anything, so
    staying paused would wedge the mirror forever. That resumes, into cost-only pacing."""
    if not policy.paused or time.monotonic() < policy.probe_due_at():
        return not policy.paused
    try:
        _, meta = await relay_gateway.relay_call_with_meta("", SERVER_LOAD_OP, {})
        sample = (meta or {}).get("server")
    except RelayBusyError as e:
        # The relay refuses even this: still busy, and it just told us when to look again.
        policy.note_busy(e)
        return False
    except RelayOpUnsupportedError:
        logger.warning(
            "gp load: the connected relay cannot report server load, so the pause cannot be checked. "
            "Resuming on cost-only pacing - update the relay to restore the server-CPU throttle."
        )
        policy.leave_pause(None)
        return True
    except Exception as e:  # noqa: BLE001 - a failed probe must not un-pause and must not raise
        logger.info("gp load: server-load probe failed (%s); staying paused", e)
        policy.enter_pause(policy.paused_reason or "probe failed")
        return False
    if may_resume(sample):
        policy.leave_pause(sample)
        return True
    policy.enter_pause(pause_reason(sample) or policy.paused_reason or "server still busy")
    return False


def paused() -> bool:
    return policy.paused
