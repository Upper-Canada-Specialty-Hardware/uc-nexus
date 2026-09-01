"""Pushed preview channels: production tells the relay which PR environments exist, over the socket it
already holds.

#414 let the relay hold more than one backend URL and #456 let that list change without a restart, but
the list itself still came from a TOML file on this one workstation - edited by hand, on a machine
nobody testing is sitting at. The relay then asked production for the list over https, which needed the
enrolled secret to authenticate a second, separate call and broke the moment those drifted. Now the
backend pushes the full list down the channel it is already authenticated on.

That means a frame off the network decides what a GP-credentialed process dials, so the checks that
matter here are the ones that keep that frame from meaning too much:

- it can only ADD to what config.toml names, never replace or reorder it
- only the exact preview hostname shape is accepted, so no frame can name an arbitrary host
- only the PRODUCTION channel is listened to, so a preview backend cannot name the next one to dial
- a pushed URL can never become the primary channel, so it always inherits the sandbox company pin
- the full list arrives every time, so a URL that stops being listed is retired
"""

import asyncio
import contextlib
import json
import logging

import pytest

from ucnexus_relay import channel
from ucnexus_relay.config import PRODUCTION_BACKEND_URL, get_settings

PR_URL = "wss://backend-uc-nexus-pr-554.up.railway.app/relay-link"
OTHER_PR_URL = "wss://backend-uc-nexus-pr-510.up.railway.app/relay-link"


@pytest.fixture(autouse=True)
def _reset_pushed_state():
    channel._pushed = None
    channel._wake = None
    yield
    channel._pushed = None
    channel._wake = None


class _Settings:
    def __init__(self, accept=True):
        self.channel = type("C", (), {"accept_pushed_preview_backends": accept})()
        self.auth = type("A", (), {"shared_secret": "enrolled-secret"})()


def _accepting(monkeypatch, accept=True):
    monkeypatch.setattr(channel, "get_settings", lambda *a, **k: _Settings(accept))


def _push(urls, url=PRODUCTION_BACKEND_URL):
    channel._handle_channels_frame({"type": "channels", "urls": list(urls)}, url)
    return channel._pushed_urls()


# --- what a pushed frame may contain ---------------------------------------------------------------


def test_a_pushed_list_is_taken_from_production(monkeypatch):
    _accepting(monkeypatch)
    assert _push([PR_URL, OTHER_PR_URL]) == [PR_URL, OTHER_PR_URL]


@pytest.mark.parametrize(
    "hostile",
    [
        "wss://attacker.example.com/relay-link",
        "wss://backend-uc-nexus-pr-554.attacker.example.com/relay-link",
        "ws://backend-uc-nexus-pr-554.up.railway.app/relay-link",  # downgraded to plaintext
        "wss://backend-uc-nexus-pr-554.up.railway.app/something-else",
        "wss://backend-production-7866.up.railway.app/relay-link",  # production, which stays primary-by-config
        "https://backend-uc-nexus-pr-554.up.railway.app/relay-link",
    ],
)
def test_only_the_preview_hostname_shape_is_accepted(monkeypatch, hostile):
    # This is the load-bearing check on the relay side: the process holds GP credentials, so "the
    # backend said so" is not on its own a reason to dial a host.
    _accepting(monkeypatch)
    assert _push([hostile, PR_URL]) == [PR_URL]


def test_a_rejected_url_is_named_in_the_log(monkeypatch, caplog):
    _accepting(monkeypatch)
    with caplog.at_level(logging.WARNING):
        _push(["wss://attacker.example.com/relay-link"])
    assert any(getattr(r, "category", None) == "pushed_channels_rejected" for r in caplog.records)


def test_a_frame_with_no_url_list_changes_nothing(monkeypatch, caplog):
    _accepting(monkeypatch)
    _push([PR_URL])
    with caplog.at_level(logging.WARNING):
        channel._handle_channels_frame({"type": "channels"}, PRODUCTION_BACKEND_URL)
    assert channel._pushed_urls() == [PR_URL]  # kept, not wiped by a malformed frame
    assert any(getattr(r, "category", None) == "pushed_channels_rejected" for r in caplog.records)


def test_non_string_entries_are_dropped_rather_than_raising(monkeypatch):
    _accepting(monkeypatch)
    assert _push([None, 42, PR_URL]) == [PR_URL]


# --- who is allowed to push ------------------------------------------------------------------------


def test_only_the_production_channel_is_listened_to(monkeypatch, caplog):
    # A preview backend is the least trusted thing this process talks to. One that could name the next
    # backend to dial could walk the relay onto a host of its choosing.
    _accepting(monkeypatch)
    with caplog.at_level(logging.DEBUG):
        assert _push([OTHER_PR_URL], url=PR_URL) == []
    assert channel._pushed is None  # not even an empty list - the frame was never applied
    assert any(getattr(r, "category", None) == "pushed_channels_ignored" for r in caplog.records)


def test_pushes_can_be_switched_off(monkeypatch):
    _accepting(monkeypatch, accept=False)
    assert _push([PR_URL]) == []


def test_an_unreadable_config_refuses_the_push(monkeypatch):
    def _boom(*a, **k):
        raise OSError("config.toml is being written")

    monkeypatch.setattr(channel, "get_settings", _boom)
    assert _push([PR_URL]) == []


# --- replace semantics -----------------------------------------------------------------------------


def test_a_later_push_replaces_the_earlier_one(monkeypatch):
    # The frame carries the full list every time, so a URL that stops being named is a PR that closed.
    _accepting(monkeypatch)
    assert _push([PR_URL, OTHER_PR_URL]) == [PR_URL, OTHER_PR_URL]
    assert _push([OTHER_PR_URL]) == [OTHER_PR_URL]


def test_an_empty_push_retires_every_pushed_channel(monkeypatch):
    _accepting(monkeypatch)
    _push([PR_URL])
    assert _push([]) == []


def test_a_change_is_logged_once_and_a_repeat_is_not(monkeypatch, caplog):
    # The backend re-sends the list on every reconnect; a line per send would bury the edit that matters.
    _accepting(monkeypatch)
    with caplog.at_level(logging.INFO):
        _push([PR_URL])
        _push([PR_URL])
    pushed = [r for r in caplog.records if r.message == "backend channels pushed"]
    assert len(pushed) == 1
    assert pushed[0].added == [PR_URL]
    assert pushed[0].removed == []


def test_a_removal_is_named_in_the_log(monkeypatch, caplog):
    _accepting(monkeypatch)
    _push([PR_URL, OTHER_PR_URL])
    with caplog.at_level(logging.INFO):
        _push([OTHER_PR_URL])
    line = [r for r in caplog.records if r.message == "backend channels pushed"][-1]
    assert line.removed == [PR_URL]
    assert line.added == []


# --- the frame arriving on the socket ---------------------------------------------------------------


class _FakeWs:
    """Just enough of a websockets client for _run_once: an async iterator of raw frames, plus send."""

    def __init__(self, frames, done):
        self._frames, self._done, self.sent = list(frames), done, []

    async def send(self, payload):
        self.sent.append(json.loads(payload))

    def __aiter__(self):
        async def gen():
            for frame in self._frames:
                yield json.dumps(frame)
            await self._done.wait()

        return gen()


def _fake_connect(monkeypatch, ws):
    class _Cm:
        async def __aenter__(self):
            return ws

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(channel.websockets, "connect", lambda url, **kw: _Cm())


def test_a_channels_frame_off_the_socket_is_applied_and_never_dispatched(monkeypatch, clean_channel_states):
    # It has no id and no op; dispatching it would answer the backend with unknown_op instead.
    dispatched = []

    async def fake_handle_job(job, allowed_companies=None):
        dispatched.append(job)
        return {"id": job.get("id"), "ok": True, "result": {}}

    monkeypatch.setattr(channel, "_handle_job", fake_handle_job)

    async def run():
        done = asyncio.Event()
        ws = _FakeWs([{"type": "channels", "urls": [PR_URL]}], done)
        _fake_connect(monkeypatch, ws)
        task = asyncio.create_task(
            channel._run_once(PRODUCTION_BACKEND_URL, "secret", get_settings().channel)
        )
        for _ in range(6):
            await asyncio.sleep(0)
        done.set()
        await task
        return ws.sent

    sent = asyncio.run(run())
    assert channel._pushed_urls() == [PR_URL]
    assert dispatched == []
    assert [f.get("type") for f in sent] == ["hello"]  # a push is not answered


# --- waking the supervisor --------------------------------------------------------------------------


def test_a_push_dials_the_new_channel_without_waiting_out_the_tick(monkeypatch, tmp_path, clean_channel_states):
    """The whole point of pushing rather than polling: the PR environment is dialled about a second
    after the backend learns of it, not on whatever tick comes next."""
    _accepting(monkeypatch)
    started: list[str] = []

    async def fake_run_channel(url, stop_event=None):
        started.append(url)
        await asyncio.Event().wait()

    monkeypatch.setattr(channel, "_run_channel", fake_run_channel)
    monkeypatch.setattr(channel, "_configured_channels", lambda: ([PRODUCTION_BACKEND_URL], "hash"))
    # A tick long enough that a test finishing in milliseconds cannot have waited one out.
    monkeypatch.setattr(channel, "CHANNEL_RECONCILE_SECONDS", 30)

    async def run():
        stop = asyncio.Event()
        task = asyncio.create_task(channel.run_forever(stop))
        await _tick()
        assert started == [PRODUCTION_BACKEND_URL]

        _push([PR_URL])
        await _tick()
        observed = list(started)

        stop.set()
        if channel._wake is not None:
            channel._wake.set()
        await _tick()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        return observed

    assert asyncio.run(run()) == [PRODUCTION_BACKEND_URL, PR_URL]


def test_a_pushed_url_already_in_config_is_not_dialled_twice(monkeypatch, tmp_path, clean_channel_states):
    # Two channels to the same backend fight over its single connection slot, closing each other with
    # 4409 forever - and an operator mid-migration off the manual step may well have both.
    _accepting(monkeypatch)
    started: list[str] = []

    async def fake_run_channel(url, stop_event=None):
        started.append(url)
        await asyncio.Event().wait()

    monkeypatch.setattr(channel, "_run_channel", fake_run_channel)
    monkeypatch.setattr(channel, "_configured_channels", lambda: ([PRODUCTION_BACKEND_URL, PR_URL], "hash"))
    monkeypatch.setattr(channel, "CHANNEL_RECONCILE_SECONDS", 0)
    _push([PR_URL + "/"])

    async def run():
        stop = asyncio.Event()
        task = asyncio.create_task(channel.run_forever(stop))
        for _ in range(3):
            await _tick()
        stop.set()
        await _tick()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    asyncio.run(run())
    assert started == [PRODUCTION_BACKEND_URL, PR_URL]


def test_a_push_with_no_supervisor_running_is_just_recorded(monkeypatch):
    # The channels live under the supervisor, so there is no frame to receive without one - but a
    # handler that assumed the event exists would crash the read loop rather than the wake being a no-op.
    _accepting(monkeypatch)
    channel._wake = None
    assert _push([PR_URL]) == [PR_URL]


async def _tick() -> None:
    """Let the supervisor run one reconcile pass."""
    for _ in range(8):
        await asyncio.sleep(0)


def test_the_pushed_state_starts_empty_and_only_adds():
    # Before any frame arrives the relay dials exactly what config.toml names, as it did before pushes.
    assert channel._pushed is None
    assert channel._pushed_urls() == []
