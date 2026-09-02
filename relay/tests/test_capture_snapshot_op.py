"""The capture_snapshot op (#666): `ucnexus-relay capture`'s per-company assembly, reached over the
channel instead of from a console on the workstation.

Everything goes through channel._dispatch, the way a backend job arrives, with GP faked out - what is
under test is the handler's wiring and the shape it hands the backend, not the assembly itself.
test_capture.py owns that, and this deliberately does not restate it.
"""

import pytest

from ucnexus_relay import capture, channel, db, fixture_ops

_RECORD = {"vendors": [], "jobs": [], "purchase_orders": []}


class _Conn:
    """A read connection that is never read from: capture_company is faked, so nothing runs SQL."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def gp(monkeypatch):
    """A GP that hands back one fixed record, and the list of companies it was opened for - so a
    refusal that never opened a connection is provable rather than inferred."""
    opened: list[str] = []
    monkeypatch.setattr(db, "get_read_connection", lambda company: opened.append(company) or _Conn())
    monkeypatch.setattr(capture, "capture_company", lambda conn: dict(_RECORD))
    return opened


def test_the_record_rides_out_with_the_snapshot_format_and_version(serving, gp):
    """The constants come from the relay so the backend never holds a second copy of them - it writes
    whatever the op said the format was."""
    serving(["TUBC"], {"TUBC": "Upper Canada Building"})

    reply = channel._dispatch("capture_snapshot", "TUBC", {})

    assert reply == {
        "ok": True,
        "result": {
            "format": fixture_ops.SNAPSHOT_FORMAT,
            "version": fixture_ops.SNAPSHOT_VERSION,
            "record": {"name": "Upper Canada Building", **_RECORD},
        },
    }
    assert gp == ["TUBC"]


def test_the_name_comes_from_discovery_rather_than_a_second_read(serving, gp):
    """The channel refreshed GP's company master to decide it serves this company at all, so the
    display name is already in hand; capture.py only re-reads it because a CLI run has no channel."""
    serving(["TUBC", "TUCSH"], {"TUBC": "Upper Canada Building", "TUCSH": "UC Specialty Hardware"})

    record = channel._dispatch("capture_snapshot", "TUCSH", {})["result"]["record"]

    assert record["name"] == "UC Specialty Hardware"


def test_no_discovered_name_leaves_the_field_out_entirely(serving, gp):
    """Same rule capture.py applies to a name it could not read: absent, not guessed. Discovery on the
    far side then falls back to the company code, as it does for any older snapshot."""
    serving(["TUBC"], {"TUBC": ""})

    record = channel._dispatch("capture_snapshot", "TUBC", {})["result"]["record"]

    assert "name" not in record
    assert record == _RECORD


def test_a_company_this_relay_does_not_serve_never_opens_a_connection(serving, gp):
    serving(["TUBC"])

    reply = channel._dispatch("capture_snapshot", "TUCSH", {})

    assert reply["ok"] is False
    assert reply["error"]["error"] == "company_not_allowed"
    assert gp == []


def test_a_non_production_channel_cannot_capture_a_company_outside_its_pin(serving, gp):
    """The op is a read of a whole company, so the channel pin (#414) has to hold for it exactly as it
    does for every other one - _dispatch checks before any handler runs."""
    serving(["TUBC", "UBC"])

    reply = channel._dispatch("capture_snapshot", "UBC", {}, allowed_companies=["TUBC"])

    assert reply["ok"] is False
    assert reply["error"]["error"] == "company_not_allowed_on_channel"
    assert gp == []


def test_the_op_is_advertised_in_the_hello_frame(serving, gp):
    """The backend refuses to call an op the connected relay did not advertise, so a build that serves
    this one has to say so - that is the whole 'update the relay' error path (#315)."""
    serving(["TUBC"])

    assert "capture_snapshot" in channel._hello_frame()["ops"]
