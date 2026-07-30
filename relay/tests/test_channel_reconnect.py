"""Channel reconnect classification (issue #204): a failed connect must say WHY - a rejected secret
(needs re-enrollment) vs a lost single-connection race (slot busy) vs a transient drop - not collapse
every failure to a generic "retrying". Uses the real websockets exception types so an upgrade that
renames the attributes the classifier reads is caught here."""

import asyncio
import functools
import logging
import time

from websockets.datastructures import Headers
from websockets.exceptions import ConnectionClosedError, InvalidStatusCode
from websockets.frames import Close

from ucnexus_relay import channel
from ucnexus_relay.config import PRODUCTION_BACKEND_URL, get_settings

PR_URL = "wss://backend-uc-nexus-pr-384.up.railway.app/relay-link"


def test_http_403_handshake_rejection_is_secret_rejected():
    # The backend refuses a bad/orphaned secret before accept(); the client sees HTTP 403 at the
    # handshake, not a WS close frame.
    category, message = channel._classify_connect_failure(InvalidStatusCode(403, Headers()))
    assert category == "secret_rejected"
    assert "re-enroll" in message.lower()


def test_http_401_handshake_rejection_is_secret_rejected():
    category, _ = channel._classify_connect_failure(InvalidStatusCode(401, Headers()))
    assert category == "secret_rejected"


def test_4409_close_is_slot_busy():
    # A valid secret that loses the single-connection race is accepted, then closed with 4409.
    exc = ConnectionClosedError(Close(channel._SLOT_BUSY_CLOSE_CODE, ""), None)
    category, message = channel._classify_connect_failure(exc)
    assert category == "slot_busy"
    assert "standing by" in message.lower()


def test_network_drop_is_generic_retry():
    category, message = channel._classify_connect_failure(OSError("connection refused"))
    assert category == "dropped"
    assert message == "channel connection dropped, retrying"


def test_normal_close_is_generic_retry():
    # A plain server-side close (e.g. backend restart) is a transient drop, not a secret problem.
    exc = ConnectionClosedError(Close(1000, ""), None)
    assert channel._classify_connect_failure(exc)[0] == "dropped"


def test_channel_state_snapshot_reflects_the_mark_helpers(clean_channel_states):
    # the live state _run_channel maintains + /health exposes (so the UI shows the REAL channel state)
    url = PRODUCTION_BACKEND_URL
    channel._mark_connected(url)
    snap = channel.channel_state_snapshot()
    assert snap["connected"] is True
    assert snap["state"] == "connected"
    channel._mark_disconnected(url, "secret_rejected")
    snap = channel.channel_state_snapshot()
    assert snap["connected"] is False
    assert snap["state"] == "secret_rejected"
    channel._mark_disconnected(url)
    assert channel.channel_state_snapshot()["state"] == "disconnected"


def test_channel_state_snapshot_reports_gp_jobs_in_flight():
    # #353 PR D: the update poller lives in the app PARENT and the job set lives in the serve CHILD, so
    # /health is the only place it can learn "a GP write is running - do not swap the exe right now".
    channel._INFLIGHT = 0
    channel._LAST_JOB_AT = None
    idle = channel.channel_state_snapshot()
    assert idle["jobs_in_flight"] == 0
    assert idle["last_job_finished_ago"] is None

    channel._INFLIGHT = 2
    assert channel.channel_state_snapshot()["jobs_in_flight"] == 2

    channel._INFLIGHT = 0
    channel._LAST_JOB_AT = time.monotonic()
    finished = channel.channel_state_snapshot()
    assert finished["jobs_in_flight"] == 0
    assert 0 <= finished["last_job_finished_ago"] < 5
    channel._LAST_JOB_AT = None


def test_close_code_1012_is_classified_as_a_server_restart():
    # #353 PR F: the backend's graceful shutdown closes with 1012 (Service Restart). That is a deploy,
    # not a fault - the relay must recognise it so it can dial again immediately.
    exc = ConnectionClosedError(Close(1012, "going away"), None)
    category, message = channel._classify_connect_failure(exc)
    assert category == "server_restarting"
    assert "restarting" in message.lower()


def test_a_generic_close_is_still_a_plain_drop():
    # The 1012 case must not swallow ordinary drops, which still deserve a growing backoff.
    exc = ConnectionClosedError(Close(1006, ""), None)
    assert channel._classify_connect_failure(exc)[0] == "dropped"


# --- the clean-close blind spot (issue #384) ---------------------------------------------------------
# Only an EXCEPTIONAL close reaches _classify_connect_failure. When _run_once returned normally - the
# socket closed without raising - _run_channel reset its backoff and redialled in silence, so relay.log
# showed a bare "channel connected" with no drop line before it. That is exactly what the 2026-07-28
# outage looks like in the relay's own log, and it is why neither end could say when the channel went.


def _use_fast_config(monkeypatch, tmp_path) -> None:
    """Point channel.get_settings at a config with no reconnect delay, so a test can drive the retry
    loop without sleeping through it.

    lru_cache-wrapped rather than a bare lambda because _run_channel calls get_settings.cache_clear()
    on every iteration - that is how a re-enrolment self-heals without a restart - and a stub without
    it raises into the "could not re-read config.toml" branch, adding a warning per iteration."""
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[auth]\nshared_secret = "s3cret"\n\n[channel]\nreconnect_min_seconds = 0.0\nreconnect_max_seconds = 0.0\n',
        encoding="utf-8",
    )
    get_settings.cache_clear()
    monkeypatch.setattr(channel, "get_settings", functools.lru_cache(maxsize=1)(lambda: get_settings(str(cfg))))


def _clean_closes(monkeypatch, tmp_path, url: str, times: int) -> None:
    """Run the real _run_channel against a _run_once that returns normally `times` times, then stops."""
    stop = asyncio.Event()
    runs: list[str] = []

    async def fake_run_once(u, secret, cfg):
        runs.append(u)
        if len(runs) >= times:
            stop.set()

    monkeypatch.setattr(channel, "_run_once", fake_run_once)
    _use_fast_config(monkeypatch, tmp_path)
    asyncio.run(channel._run_channel(url, stop))
    assert len(runs) == times


def _closed_clean_records(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if getattr(r, "category", None) == "closed_clean"]


def test_a_clean_close_logs_a_reconnect_event(monkeypatch, tmp_path, caplog, clean_channel_states):
    with caplog.at_level(logging.DEBUG):
        _clean_closes(monkeypatch, tmp_path, PRODUCTION_BACKEND_URL, 1)

    records = _closed_clean_records(caplog)
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    assert records[0].message == "channel closed without an error; reconnecting"
    assert records[0].url == PRODUCTION_BACKEND_URL
    assert records[0].backoff == 0.0  # a clean run still resets the backoff before redialling
    assert channel._STATES[PRODUCTION_BACKEND_URL]["state"] == "disconnected"


def test_repeated_clean_closes_on_a_test_channel_are_demoted(monkeypatch, tmp_path, caplog, clean_channel_states):
    # #414: a PR environment is torn down when its PR closes and its URL then sits in config.toml
    # failing forever. Its noise must not bury production's own reconnect events, so the second and
    # later repeats of the same category drop to DEBUG - the same rule the classified failures use.
    with caplog.at_level(logging.DEBUG):
        _clean_closes(monkeypatch, tmp_path, PR_URL, 3)

    levels = [r.levelno for r in _closed_clean_records(caplog)]
    assert levels == [logging.WARNING, logging.DEBUG, logging.DEBUG]


def test_repeated_clean_closes_on_the_production_channel_stay_loud(monkeypatch, tmp_path, caplog, clean_channel_states):
    # The primary channel demotes only secret_rejected, which cannot self-heal until someone re-enrols.
    # A production channel that keeps closing cleanly is a real, distinct event every time - and the
    # exact symptom issue #384 was opened about, so it must never be quietened.
    with caplog.at_level(logging.DEBUG):
        _clean_closes(monkeypatch, tmp_path, PRODUCTION_BACKEND_URL, 3)

    levels = [r.levelno for r in _closed_clean_records(caplog)]
    assert levels == [logging.WARNING, logging.WARNING, logging.WARNING]
