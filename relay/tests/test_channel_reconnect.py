"""Channel reconnect classification (issue #204): a failed connect must say WHY - a rejected secret
(needs re-enrollment) vs a lost single-connection race (slot busy) vs a transient drop - not collapse
every failure to a generic "retrying". Uses the real websockets exception types so an upgrade that
renames the attributes the classifier reads is caught here."""

import time

from websockets.datastructures import Headers
from websockets.exceptions import ConnectionClosedError, InvalidStatusCode
from websockets.frames import Close

from ucnexus_relay import channel


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


def test_channel_state_snapshot_reflects_the_mark_helpers():
    # the live state run_forever maintains + /health exposes (so the UI shows the REAL channel state)
    channel._mark_connected()
    snap = channel.channel_state_snapshot()
    assert snap["connected"] is True
    assert snap["state"] == "connected"
    channel._mark_disconnected("secret_rejected")
    snap = channel.channel_state_snapshot()
    assert snap["connected"] is False
    assert snap["state"] == "secret_rejected"
    channel._mark_disconnected()
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
