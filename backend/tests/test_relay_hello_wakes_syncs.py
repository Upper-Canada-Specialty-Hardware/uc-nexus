"""The relay read loop wakes the GP sync loops when the hello lands.

/relay-link calls wake() the instant try_register succeeds, which is one frame too early to be useful:
the GP company list arrives on the hello, and until it does both sync loops see `connected` true and
`companies` empty. On 2026-09-03 that left the PO mirror silent for over ten minutes after a 17:36
reconnect. The read loop's own wake is what closes that gap; the short hello grace in each loop is the
backstop for a relay that never sends one.
"""

import asyncio

import pytest

import main


class FakeWebSocket:
    """Feeds a fixed script of frames, then ends the read loop the way a disconnect would."""

    def __init__(self, frames):
        self.frames = list(frames)
        self.sent: list[dict] = []

    async def receive_json(self):
        if not self.frames:
            raise RuntimeError("socket closed")
        return self.frames.pop(0)

    async def send_json(self, data):
        self.sent.append(data)


@pytest.fixture
def woken(monkeypatch):
    """Record the wakes instead of nudging the real loops, which are not running under pytest."""
    calls: list[str] = []
    monkeypatch.setattr(main.gp_po_sync, "wake", lambda: calls.append("po"))
    monkeypatch.setattr(main.gp_job_sync, "wake", lambda: calls.append("job"))
    monkeypatch.setattr(main.preview_registry, "channels", lambda: [])

    async def no_push(channels):
        return None

    monkeypatch.setattr(main.relay_gateway, "push_channels", no_push)
    return calls


def _read(websocket):
    with pytest.raises(RuntimeError):
        asyncio.run(main._relay_read_loop(websocket))


def test_a_hello_with_companies_wakes_both_sync_loops(woken, monkeypatch):
    monkeypatch.setattr(main.relay_gateway, "_socket", object())

    _read(FakeWebSocket([{"type": "hello", "build": "relay-v1", "ops": ["sync_pos"], "companies": ["TUBC"]}]))

    assert woken == ["po", "job"]


def test_a_hello_that_discovered_nothing_wakes_nobody(woken, monkeypatch):
    """A relay serving no companies has nothing for either loop to do, and waking them would only burn
    a turn each to discover that."""
    monkeypatch.setattr(main.relay_gateway, "_socket", object())

    _read(FakeWebSocket([{"type": "hello", "build": "relay-v1", "companies": []}]))

    assert woken == []


def test_ordinary_frames_wake_nobody(woken, monkeypatch):
    """A pong and a job reply are not news about which companies exist."""
    monkeypatch.setattr(main.relay_gateway, "_socket", object())

    _read(FakeWebSocket([{"type": "pong"}, {"id": "nope", "ok": True, "result": None}]))

    assert woken == []
