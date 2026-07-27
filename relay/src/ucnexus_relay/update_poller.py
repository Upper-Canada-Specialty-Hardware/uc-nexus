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

from . import updater
from .logging_setup import get_logger

logger = get_logger()

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
        return False, f"an update is already in progress ({status})"

    latest = check.get("latest")
    if (
        status == "failed"
        and ledger.get("target_build") == latest
        and int(ledger.get("attempts") or 0) >= updater.MAX_ATTEMPTS
    ):
        return False, f"{latest} already failed {updater.MAX_ATTEMPTS} times; waiting for a newer build"
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


def start(app) -> threading.Event:
    """Spawn the poll thread and hand back its stop event (set it first on teardown, so a poll cannot
    begin staging an update while the app is already shutting down). Frozen builds only: a dev
    checkout has no exe to swap."""
    stop = threading.Event()
    import sys

    if not getattr(sys, "frozen", False):
        return stop
    threading.Thread(target=run, args=(app, stop), daemon=True, name="update-poller").start()
    return stop
