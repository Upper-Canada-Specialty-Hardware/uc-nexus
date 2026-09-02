"""The relay connection event log (#654) - what is written, what is throttled, and what is kept.

Issue #384 made every connection-slot transition loggable; the log answers "what is happening now" for
as long as Railway retains it, and these rows answer "what has been happening" afterwards. Two
properties are load-bearing and both are here: the write can never break or slow the socket path it
runs on, and a relay retrying with a bad secret cannot flood the table.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta

import pytest

from app.models.enums import RelayEventKind
from app.models.relay_event import RelayEvent
from app.models.relay_install import RelayInstall
from app.repositories import relay_event_repository
from app.services import relay_events


@pytest.fixture(autouse=True)
def _clean_throttle():
    relay_events.reset()
    yield
    relay_events.reset()


@pytest.fixture
def inserted(monkeypatch):
    """Capture what would be written, so the service's own behaviour is testable without a database."""
    rows: list[tuple] = []
    monkeypatch.setattr(relay_events, "_insert", lambda *args: rows.append(args))
    return rows


def test_a_write_carries_its_fields_through(inserted):
    install_id = uuid.uuid4()
    at = datetime(2026, 9, 1, 12, 0, 0)

    asyncio.run(
        relay_events.write(
            RelayEventKind.DISCONNECTED,
            at=at,
            install_id=install_id,
            build="relay-v0.2.0",
            companies=["TUBC"],
            reason="peer closed or socket dropped",
            detail={"held_seconds": 12.5},
        )
    )

    assert inserted == [
        (
            RelayEventKind.DISCONNECTED,
            at,
            install_id,
            "relay-v0.2.0",
            ["TUBC"],
            "peer closed or socket dropped",
            {"held_seconds": 12.5},
        )
    ]


def test_a_failing_write_never_reaches_the_socket_path(monkeypatch, caplog):
    """The whole feature is diagnostics. It must never be able to cause the outage it exists to
    explain, so a database that is down costs a log line and nothing else."""

    def boom(*args):
        raise RuntimeError("database is on fire")

    monkeypatch.setattr(relay_events, "_insert", boom)
    with caplog.at_level(logging.WARNING, logger=relay_events.__name__):
        asyncio.run(relay_events.write(RelayEventKind.CONNECTED))  # must not raise
    assert "database is on fire" in caplog.records[-1].getMessage()


def test_refused_secret_is_throttled(inserted):
    # A relay dialling with a drifted secret retries every few seconds forever - 42 rejected handshakes
    # in a few minutes, observed - and one row per retry would bury every other event in the table.
    for _ in range(5):
        asyncio.run(relay_events.write(RelayEventKind.REFUSED_SECRET, reason="no install matched"))
    assert len(inserted) == 1


def test_the_throttle_window_reopens(inserted):
    asyncio.run(relay_events.write(RelayEventKind.REFUSED_SECRET))
    # Age the floor past the window rather than sleeping through it.
    relay_events._last_refused_secret -= relay_events.REFUSED_SECRET_THROTTLE_SECONDS + 1
    asyncio.run(relay_events.write(RelayEventKind.REFUSED_SECRET))
    assert len(inserted) == 2


@pytest.mark.parametrize(
    "kind",
    [
        RelayEventKind.CONNECTED,
        RelayEventKind.DISCONNECTED,
        RelayEventKind.REFUSED_SLOT,
        RelayEventKind.ADOPTED,
    ],
)
def test_nothing_else_is_throttled(inserted, kind):
    # Every other kind is caused by something on this side, so its rate is bounded already - and a
    # flapping relay's repeated connects are exactly the signal somebody would be reading these for.
    for _ in range(3):
        asyncio.run(relay_events.write(kind))
    assert len(inserted) == 3


def test_record_is_a_no_op_with_no_event_loop(inserted):
    # A unit test or a script calling the gateway directly, never production - and it must not open a
    # database connection to find that out.
    relay_events.record(RelayEventKind.CONNECTED)
    assert inserted == []


def test_record_schedules_the_write_on_the_loop(inserted):
    async def run():
        relay_events.record(RelayEventKind.CONNECTED, build="relay-v0.2.0")
        # Fire and forget: nothing on the socket path awaits this, so let the scheduled task run.
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    asyncio.run(run())
    assert len(inserted) == 1
    assert inserted[0][0] is RelayEventKind.CONNECTED


# --- the rows themselves (DB-backed) ---------------------------------------------------------------


def test_a_recorded_event_reads_back_newest_first(db_session):
    older = relay_event_repository.record(db_session, kind=RelayEventKind.CONNECTED, at=datetime(2026, 9, 1, 11, 0, 0))
    newer = relay_event_repository.record(
        db_session,
        kind=RelayEventKind.DISCONNECTED,
        at=datetime(2026, 9, 1, 12, 0, 0),
        reason="peer closed or socket dropped",
    )

    # Filtered to these two rather than sliced: the socket paths commit their own events from a worker
    # thread, so a row this test did not write can legitimately be sitting at the top of the table.
    events = relay_event_repository.list_events(db_session, limit=500)
    mine = [e for e in events if e.id in {older.id, newer.id}]
    assert [e.id for e in mine] == [newer.id, older.id]
    assert mine[0].reason == "peer closed or socket dropped"


def test_the_install_label_is_snapshotted_at_write_time(db_session):
    install = RelayInstall(id=uuid.uuid4(), label="TAGGING3W10", secret_hash="a" * 64)
    db_session.add(install)
    db_session.flush()

    event = relay_event_repository.record(db_session, kind=RelayEventKind.CONNECTED, install_id=install.id)
    assert event.install_label == "TAGGING3W10"


def test_deleting_an_install_keeps_its_history(db_session):
    # Retiring a workstation (#366) must not erase what it did, and history that can only say "an
    # install that no longer exists" is worth nothing - hence the label snapshot beside the FK.
    install = RelayInstall(id=uuid.uuid4(), label="RETIRED", secret_hash="b" * 64)
    db_session.add(install)
    db_session.flush()
    event = relay_event_repository.record(db_session, kind=RelayEventKind.CONNECTED, install_id=install.id)
    event_id = event.id

    db_session.delete(install)
    db_session.flush()
    db_session.expire_all()

    surviving = db_session.get(RelayEvent, event_id)
    assert surviving is not None
    assert surviving.install_id is None  # ON DELETE SET NULL
    assert surviving.install_label == "RETIRED"


def test_pruning_drops_only_what_is_past_retention(db_session):
    now = datetime.utcnow()
    old = relay_event_repository.record(
        db_session, kind=RelayEventKind.CONNECTED, at=now - timedelta(days=relay_events.RETENTION_DAYS + 1)
    )
    recent = relay_event_repository.record(db_session, kind=RelayEventKind.CONNECTED, at=now)

    relay_event_repository.prune(db_session, older_than=now - timedelta(days=relay_events.RETENTION_DAYS))
    db_session.flush()

    assert db_session.get(RelayEvent, old.id) is None
    assert db_session.get(RelayEvent, recent.id) is not None


def test_every_kind_survives_the_column_check(db_session):
    # `kind` is a String + CHECK rather than a PG enum (migration 103); the two lists have to agree.
    for kind in RelayEventKind:
        relay_event_repository.record(db_session, kind=kind)
    db_session.flush()
