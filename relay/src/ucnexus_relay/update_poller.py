"""Background auto-update polling for the relay desktop app (#353 PR D).

Until this existed, the self-updater was UI-only: someone had to be at the workstation, open the
relay window, and press Update now. Every relay-side fix therefore needed physical access to a
tagging workstation - the exact dependency #353 exists to remove.

The poller runs in the desktop app PARENT process, not the `serve` child, because staging an update
needs the app's pid and the app must then shut itself down so the exe unlocks (see
`RelayApp.begin_update`). It reads `/health` to find out whether the child is busy, which is the only
channel across that process boundary.

Every decision is a pure function over dicts (`should_stage`, `is_busy`, `next_delay`) so the policy
is testable without a network, a GUI, or GP. `run()` is the only part that touches the world."""

import random
import threading
import time
from pathlib import Path

from . import layout, updater
from .logging_setup import get_logger

logger = get_logger()

_sleep = time.sleep  # module-level seam so the self-check's tests never sleep for real

# First check well after start-up: a relay that just launched is usually a relay someone is watching
# (or one that just came back from an update), and swapping the exe out from under that is startling.
# The jitter spreads a fleet so a release is not fetched by every relay in the same second.
FIRST_DELAY_SECONDS = 600
FIRST_JITTER_SECONDS = 300
INTERVAL_SECONDS = 86400
INTERVAL_JITTER_SECONDS = 7200

# When a check is deferred (a GP job is in flight, or /health is not answering) retry sooner than the
# daily tick, but give up after MAX_DEFERRALS so a permanently busy or permanently broken relay falls
# back to the normal cadence instead of polling every 15 minutes forever.
DEFER_RETRY_SECONDS = 900
MAX_DEFERRALS = 8

# Treat the relay as busy for this long after the last job finished. The backend records a relay
# result and then persists the UC Nexus side of the write; killing the relay inside that window is
# survivable but pointlessly risky when the alternative is waiting two minutes.
BUSY_GRACE_SECONDS = 120

# The post-update self-check: how long the freshly updated build gets to bring its backend channel up
# before it is judged a bad build, and how often that is re-checked. Five minutes is far past a normal
# connect (the channel dials seconds after serve binds and retries with backoff), so the only thing
# that runs out this clock is a build that cannot connect at all.
SELF_CHECK_SECONDS = 300.0
SELF_CHECK_POLL_SECONDS = 15.0


def should_stage(check: dict, ledger: dict, cancel_requested: bool) -> tuple[bool, str]:
    """Decide whether to stage the update `check` describes. Returns (stage?, reason).

    The ledger rules matter: `updater.apply_staged_update` refuses a target past MAX_ATTEMPTS, and
    `_stage_ledger` preserves the attempt count for the same unfinished target. A poller that
    re-staged regardless would burn those attempts on a schedule and end with a relay that can never
    update again, even to a good build. A HIGHER build resets the count (existing `_stage_ledger`
    behaviour), which is the escape hatch: publish a fix and the relay tries again."""
    if not check.get("ok"):
        return False, f"update check failed: {check.get('error') or 'unknown error'}"
    if not check.get("update_available"):
        return False, "already on the latest build"
    if not (check.get("url") or "").strip():
        return False, "release has no download URL"
    if cancel_requested:
        return False, "an update cancel is pending (the user closed the relay mid-update)"

    status = ledger.get("status")
    if status in ("staging", "applying"):
        # ...unless nothing has touched it for far longer than a helper can legally run (#369). A helper
        # that died before writing its terminal status would otherwise pin this branch forever and the
        # relay would silently never update again. Startup reconciliation normally clears it first; this
        # is the backstop for a relay that stays up for weeks.
        if not updater.ledger_is_abandoned(ledger):
            return False, f"an update is already in progress ({status})"

    latest = check.get("latest")
    if (
        status == "failed"
        and ledger.get("target_build") == latest
        and int(ledger.get("attempts") or 0) >= updater.MAX_ATTEMPTS
    ):
        return False, f"{latest} already failed {updater.MAX_ATTEMPTS} times; waiting for a newer build"
    if status == "rolled_back" and ledger.get("target_build") == latest:
        # It installed, ran, and could not reach the backend, so the self-check put the previous version
        # back. Re-staging it would walk the workstation through the same 5 minutes offline every day.
        return False, f"{latest} was rolled back after it could not reach the backend; waiting for a newer build"
    return True, f"update available: {latest}"


def is_busy(health: dict) -> bool:
    """Whether the serve child is mid-GP-work (or unreachable). Fail-safe: an empty or malformed
    /health payload means we cannot tell, and "cannot tell" must never authorise killing the relay
    while eConnect is holding a transaction open."""
    if not health:
        return True
    channel = health.get("channel")
    if not isinstance(channel, dict):
        return True
    if int(channel.get("jobs_in_flight") or 0) > 0:
        return True
    last = channel.get("last_job_finished_ago")
    if last is not None and float(last) < BUSY_GRACE_SECONDS:
        return True
    return False


def next_delay(rng: random.Random, first: bool = False) -> float:
    if first:
        return FIRST_DELAY_SECONDS + rng.uniform(0, FIRST_JITTER_SECONDS)
    return INTERVAL_SECONDS + rng.uniform(0, INTERVAL_JITTER_SECONDS)


def _read_health() -> dict:
    """The serve child's /health, or {} if it is not answering (which is_busy treats as busy)."""
    from .ui import config_summary, relay_health

    try:
        cfg = config_summary()
        return relay_health(cfg.get("host", "127.0.0.1"), cfg.get("port", 7321)) or {}
    except Exception:  # noqa: BLE001
        logger.exception("update poller: could not read relay health")
        return {}


def run(app, stop: threading.Event, rng: random.Random | None = None) -> None:
    """The poll loop. Sleeps on `stop` so a shutdown is immediate rather than up to a day late; every
    iteration is wrapped so a transient failure (GitHub unreachable, health blip) never kills the
    thread and silently ends auto-updating."""
    rng = rng or random.Random()
    install_dir = app._install_dir()
    deferrals = 0
    delay = next_delay(rng, first=True)

    while not stop.wait(delay):
        delay = next_delay(rng)
        try:
            if is_busy(_read_health()):
                if deferrals < MAX_DEFERRALS:
                    deferrals += 1
                    delay = DEFER_RETRY_SECONDS
                    logger.info(
                        "update poller: relay is busy with GP work; deferring (%s/%s)", deferrals, MAX_DEFERRALS
                    )
                else:
                    deferrals = 0
                    logger.info("update poller: still busy after %s deferrals; waiting for the next tick", MAX_DEFERRALS)
                continue
            deferrals = 0

            check = updater.check_update()
            ledger = updater.read_ledger(install_dir)
            stage, reason = should_stage(check, ledger, updater.cancel_requested(install_dir))
            if not stage:
                logger.info("update poller: not updating - %s", reason)
                continue

            logger.info("update poller: %s; staging", reason)
            result = app.begin_update(check["url"], check.get("latest"))
            if not result.get("ok"):
                logger.warning("update poller: staging failed - %s", result.get("error"))
                continue
            return  # staged: the app is tearing itself down for the handoff, so stop polling
        except Exception:  # noqa: BLE001
            logger.exception("update poller: unexpected error; will retry on the next tick")


# --- post-update self-check --------------------------------------------------------------------------
# An update is only "applied" as far as the helper can see: it health-gates the relaunch, and /health
# answers as soon as uvicorn binds - which says nothing about whether the new build can still reach the
# backend. A build that starts cleanly and never connects therefore records `success` and leaves the
# workstation dark, with no one on site to notice. This is the second gate: the channel has to actually
# come up, or the previous version goes back.


def channel_connected(health: dict) -> bool:
    """Whether the serve child reports its PRIMARY backend channel connected. The top level of the
    /health channel snapshot mirrors production, which is the connection that matters here."""
    channel = health.get("channel") if isinstance(health, dict) else None
    return bool(isinstance(channel, dict) and channel.get("connected"))


def _has_channels(health: dict) -> bool:
    """Whether serve is dialling anything at all. An unenrolled relay (no secret) runs no channel by
    design, so there is nothing for the self-check to prove and nothing a rollback would fix."""
    channel = health.get("channel") if isinstance(health, dict) else None
    return bool(isinstance(channel, dict) and channel.get("channels"))


def needs_self_check(ledger: dict) -> bool:
    """Only right after an update landed: the ledger says success, that target is the build now running,
    and no verdict has been recorded for it yet (see updater.record_self_check for why once)."""
    target = ledger.get("target_build") or ""
    if ledger.get("status") != "success" or not target or ledger.get("self_check"):
        return False
    return target == updater.current_build()


def _previous_version_dir(install_dir):
    """The highest-build app-<build>/ folder that is NOT the one `current` points at, or None if this
    install has no earlier version left to fall back to (layout keeps two)."""
    current = layout.current_target(install_dir)
    for candidate in layout.version_dirs(install_dir):
        if current is None or candidate.name != Path(current).name:
            return candidate
    return None


def _restart_serve_from_current(install_dir) -> None:
    """Bring the serve child back on whatever `current` now points at.

    Deliberately NOT app.restart_serve(): that relaunches sys.executable, which in this path IS the
    build being rolled back, so serve would come straight back up on it and the rollback would not
    reach GP until the next logon. The desktop window stays on the new build until then either way -
    serve is the process that holds the backend channel, and it is the one that has to move."""
    from . import setup, single_instance

    setup.stop_serve(install_dir)
    _sleep(1.5)  # let port 7321 free before the rolled-back serve binds it
    setup.start_serve(single_instance.installed_exe_path(install_dir), install_dir)


def _roll_back(install_dir, target: str) -> str:
    previous = _previous_version_dir(install_dir)
    if previous is None:
        # Nothing to go back to, so leave the relay on the build it has: a broken channel beats no relay.
        logger.warning(
            "update self-check: %s never connected to the backend, but there is no previous version to "
            "roll back to; leaving it in place",
            target,
        )
        updater.record_self_check(install_dir, "no_previous_version")
        return "no_previous_version"
    if not layout.repoint_current(install_dir, previous):
        logger.warning("update self-check: could not repoint current back to %s; leaving %s in place", previous, target)
        updater.record_self_check(install_dir, "rollback_failed")
        return "rollback_failed"
    logger.warning("update self-check: %s never connected to the backend; rolled back to %s", target, previous.name)
    _restart_serve_from_current(install_dir)
    updater.mark_rolled_back(
        install_dir,
        f"{target} started but its backend channel never connected within "
        f"{int(SELF_CHECK_SECONDS)}s; rolled back to {previous.name}",
    )
    return "rolled_back"


def _self_check(app, stop: threading.Event, monotonic) -> str | None:
    install_dir = app._install_dir()
    ledger = updater.read_ledger(install_dir)
    if not needs_self_check(ledger):
        return None
    target = ledger.get("target_build") or ""
    deadline = monotonic() + SELF_CHECK_SECONDS
    while not stop.is_set():
        health = _read_health()
        if channel_connected(health):
            logger.info("update self-check: %s is connected to the backend", target)
            updater.record_self_check(install_dir, "connected")
            return "connected"
        if monotonic() >= deadline:
            if not _has_channels(health):
                # No channel is configured (an unenrolled relay), so "not connected" is not a verdict
                # on this build.
                updater.record_self_check(install_dir, "no_channel")
                return "no_channel"
            return _roll_back(install_dir, target)
        stop.wait(SELF_CHECK_POLL_SECONDS)
    return None


def self_check(app, stop: threading.Event, monotonic=time.monotonic) -> str | None:
    """Verify that the build a just-applied update installed can still reach the backend, and put the
    previous version back if it cannot. Returns the verdict it recorded, or None when there was nothing
    to check (no update landed, or the app is shutting down).

    Wrapped whole: this runs in a background thread at app start, and a bug in it must never be the
    reason a relay does not come up."""
    try:
        return _self_check(app, stop, monotonic)
    except Exception:  # noqa: BLE001
        logger.exception("update self-check: unexpected error; leaving the relay on the current build")
        return None


def start(app) -> threading.Event:
    """Spawn the poll + self-check threads and hand back their shared stop event (set it first on
    teardown, so neither can act while the app is already shutting down). Frozen builds only: a dev
    checkout has no exe to swap."""
    stop = threading.Event()
    import sys

    if not getattr(sys, "frozen", False):
        return stop
    threading.Thread(target=self_check, args=(app, stop), daemon=True, name="update-self-check").start()
    threading.Thread(target=run, args=(app, stop), daemon=True, name="update-poller").start()
    return stop
