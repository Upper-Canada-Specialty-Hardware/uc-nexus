"""GP SYNC STATE: the backend's own account of its sync work, pushed down the channel it already
holds and kept here for the window's NEXUS GP TRAFFIC tab to render.

The pushed channel list (test_channel_push.py) is the other frame the backend sends, and the checks on
the two are deliberately different. That one names the next hosts a GP-credentialed process will dial,
so only production's word is taken for it. This one names no host, is never acted on and only ever
reaches a panel, so any channel may send its own - which is why what matters here is that the copies
stay apart, that the primary channel's is the one published, and that a frame with nothing in it does
not replace a usable account with a blank one.
"""

import asyncio
import json
import logging

import pytest

from ucnexus_relay import channel
from ucnexus_relay.config import PRODUCTION_BACKEND_URL, get_settings

PR_URL = "wss://backend-uc-nexus-pr-554.up.railway.app/relay-link"
LOCAL_URL = "ws://127.0.0.1:8000/relay-link"


@pytest.fixture(autouse=True)
def _empty_sync_state():
    """Keyed by backend URL and module-level, so one test's copy would otherwise be the next test's
    snapshot."""
    saved = dict(channel._GP_SYNC_STATE)
    channel._GP_SYNC_STATE.clear()
    yield channel._GP_SYNC_STATE
    channel._GP_SYNC_STATE.clear()
    channel._GP_SYNC_STATE.update(saved)


def _frame(company="UBC", **extra):
    return {
        "type": "gp_sync_state",
        "generated_at": "2026-09-14T12:00:00Z",
        "po_sync_enabled": True,
        "job_sync_enabled": True,
        "companies": [{"company": company, "mirrored_pos": 3650, "open_pos": 2344}],
        **extra,
    }


def test_a_pushed_frame_is_stored_with_the_moment_it_arrived():
    channel._handle_gp_sync_state_frame(_frame(), PRODUCTION_BACKEND_URL)

    snapshot = channel.gp_sync_state_snapshot()
    assert snapshot["url"] == PRODUCTION_BACKEND_URL
    assert snapshot["received_at"].endswith("Z")
    # Stored verbatim apart from the envelope: the relay renders this and never reads a decision out
    # of it, so the backend stays free to add a field without a relay release.
    assert "type" not in snapshot["state"]
    assert snapshot["state"]["companies"] == [{"company": "UBC", "mirrored_pos": 3650, "open_pos": 2344}]
    assert snapshot["state"]["po_sync_enabled"] is True


def test_every_channel_keeps_its_own_copy_and_the_primary_one_is_published():
    """Two backends describing their own sync work must not overwrite each other, and the tab reports
    on production - the same rule channel_state_snapshot follows for the channel state itself."""
    channel._handle_gp_sync_state_frame(_frame("TUBC"), PR_URL)
    channel._handle_gp_sync_state_frame(_frame("UBC"), PRODUCTION_BACKEND_URL)

    assert set(channel._GP_SYNC_STATE) == {PR_URL, PRODUCTION_BACKEND_URL}
    snapshot = channel.gp_sync_state_snapshot()
    assert snapshot["url"] == PRODUCTION_BACKEND_URL
    assert snapshot["state"]["companies"][0]["company"] == "UBC"


def test_a_non_primary_copy_stands_in_when_no_primary_has_sent_one():
    """A dev checkout dialling localhost, or a workstation whose production backend is older than this
    feature: the tab shows the account it has rather than nothing at all."""
    channel._handle_gp_sync_state_frame(_frame("TUBC"), LOCAL_URL)

    snapshot = channel.gp_sync_state_snapshot()
    assert snapshot["url"] == LOCAL_URL
    assert snapshot["state"]["companies"][0]["company"] == "TUBC"


def test_nothing_is_published_until_a_frame_has_arrived():
    assert channel.gp_sync_state_snapshot() is None


@pytest.mark.parametrize(
    "frame",
    [
        {"type": "gp_sync_state"},  # no company list at all
        {"type": "gp_sync_state", "companies": None},
        {"type": "gp_sync_state", "companies": {"UBC": {}}},  # a mapping, not the list the tab renders
        "not a frame",
    ],
)
def test_a_frame_with_no_company_list_is_ignored(frame, caplog):
    channel._handle_gp_sync_state_frame(_frame(), PRODUCTION_BACKEND_URL)

    with caplog.at_level(logging.WARNING):
        channel._handle_gp_sync_state_frame(frame, PRODUCTION_BACKEND_URL)

    assert any(getattr(r, "category", None) == "gp_sync_state_rejected" for r in caplog.records)
    # and the usable account it would have replaced is still there
    assert channel.gp_sync_state_snapshot()["state"]["companies"][0]["company"] == "UBC"


def test_forgetting_a_channel_drops_its_copy(clean_channel_states):
    """A retired preview environment's account of its own sync work is only as current as the socket it
    arrived on; going on rendering it would read as news."""
    channel._handle_gp_sync_state_frame(_frame("TUBC"), PR_URL)

    channel.forget_channel(PR_URL)

    assert channel._GP_SYNC_STATE == {}
    assert channel.gp_sync_state_snapshot() is None


def test_the_hello_advertises_the_gp_sync_state_feature():
    # How the backend knows this build will accept its sync state rather than treat the frame as an
    # unknown job. An older relay advertises only "channels", so the backend never sends one.
    assert channel._hello_frame()["features"] == ["channels", "gp_sync_state"]


# --- the frame arriving on the socket ----------------------------------------------------------------


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


def test_a_sync_state_frame_off_the_socket_is_stored_and_never_dispatched(monkeypatch, clean_channel_states):
    # It has no id and no op; dispatching it would answer the backend with unknown_op instead.
    dispatched = []

    async def fake_handle_job(job, allowed_companies=None):
        dispatched.append(job)
        return {"id": job.get("id"), "ok": True, "result": {}}

    monkeypatch.setattr(channel, "_handle_job", fake_handle_job)

    class _Cm:
        def __init__(self, ws):
            self._ws = ws

        async def __aenter__(self):
            return self._ws

        async def __aexit__(self, *exc):
            return False

    async def run():
        done = asyncio.Event()
        ws = _FakeWs([_frame()], done)
        monkeypatch.setattr(channel.websockets, "connect", lambda url, **kw: _Cm(ws))
        task = asyncio.create_task(
            channel._run_once(PRODUCTION_BACKEND_URL, "secret", get_settings().channel)
        )
        for _ in range(12):
            await asyncio.sleep(0.005)
        done.set()
        await task
        return ws.sent

    sent = asyncio.run(run())

    assert dispatched == []
    assert [f.get("type") for f in sent] == ["hello"]  # a push is not answered
    assert channel.gp_sync_state_snapshot()["state"]["companies"][0]["company"] == "UBC"
