"""Which relay failures may be queued (#353 PR E).

One bit decides whether a failed GP write is safe to retry automatically, and getting it wrong posts
a duplicate receipt into GP. It is worth a test of its own."""

from app.errors import RelayUnavailableError
from app.services import gp_outbox_enqueue
from app.services.relay_gateway import RelayGateway


def test_an_undispatched_failure_may_be_queued():
    # No socket / wrong company / send failure: the job never left the backend, so GP cannot have run it.
    assert gp_outbox_enqueue.may_enqueue(RelayUnavailableError("no relay is currently connected")) is True
    assert gp_outbox_enqueue.may_enqueue(RelayUnavailableError("wrong company", dispatched=False)) is True


def test_a_dispatched_failure_may_not_be_queued():
    # The job was on the wire when the socket died: GP may have committed and the reply was lost.
    assert gp_outbox_enqueue.may_enqueue(RelayUnavailableError("relay disconnected", dispatched=True)) is False


def test_the_gateway_marks_a_lost_in_flight_job_as_dispatched():
    """`_fail_all` runs when a socket with jobs on it disconnects. Every one of those futures must
    carry dispatched=True, or the outbox would queue writes GP may already hold."""
    import asyncio

    async def run():
        gateway = RelayGateway()
        future = asyncio.get_running_loop().create_future()
        gateway._pending["job-1"] = future
        gateway._fail_all("relay disconnected")
        with_error = None
        try:
            await future
        except RelayUnavailableError as e:
            with_error = e
        assert with_error is not None
        assert with_error.dispatched is True

    asyncio.run(run())


def test_a_plain_unavailable_error_defaults_to_not_dispatched():
    # The default matters: relay_call raises bare RelayUnavailableError() for the no-socket case,
    # which is exactly the case the outbox exists to absorb.
    assert RelayUnavailableError().dispatched is False
