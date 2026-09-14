"""GP SYNC STATE: the document, who may read it, and when it is pushed (#679).

NEXUS GP TRAFFIC has two surfaces built by two other agents against one contract, so the shape of this
document is the interface and is asserted key for key - a field quietly renamed here is a blank column
on the admin page and a blank pill in the relay window, with nothing failing to say so.

The rest is the two rules that keep it cheap and safe: it is pushed only to a relay that ASKED for the
frame (an older build would read it as a job reply and log an uncorrelated id), and it is admin-only,
because it names the relay build, the install holding the socket, and every company GP serves.

Almost none of it needs a database: the one function that touches it is stubbed everywhere but the two
cases at the end, which is itself the proof that the rest of the snapshot is already in memory. Those
two run the real statements, because a wrong column name or a filtered count that will not compile is
otherwise invisible until production.
"""

import asyncio
import uuid
from datetime import datetime

import pytest

from app import auth
from app.auth import ADMIN_ROLE
from app.models.enums import POStatus
from app.models.gp_po_sync_state import GpPoSyncState
from app.models.purchase_order import PurchaseOrder
from app.repositories import user_repository
from app.services import gp_job_sync, gp_load, gp_po_sync, gp_sync_state
from main import schema

# --- fixtures ---------------------------------------------------------------------------------------


class _FakeGateway:
    """The relay as the snapshot reads it: what it said on its hello, and the last GP server sample any
    reply carried."""

    def __init__(
        self,
        *,
        connected=True,
        build="relay-v0.3.0-build.74",
        companies=("TUBC",),
        company_names=None,
        install_id="8f1d2c3e-0000-4000-8000-000000000001",
        server_sample=None,
        features=("gp_sync_state",),
    ):
        self.connected = connected
        self.build = build
        self.companies = list(companies)
        self.company_names = dict(company_names or {"TUBC": "Test UBC"})
        self.install_id = install_id
        self.last_server_sample = server_sample
        self._features = set(features)
        self.pushed: list[dict] = []

    def has_feature(self, name: str) -> bool:
        return name in self._features

    async def push_gp_sync_state(self, snapshot: dict) -> None:
        self.pushed.append(snapshot)


def _db(companies=("TUBC",), **overrides):
    """What _read_db hands back, with one initialized company holding a few POs."""
    data = {
        "companies": list(companies),
        "progress": {
            "TUBC": {
                "initialization_done": True,
                "initialization_cursor": "PO0012345",
                "open_pass_cursor": "PO0009000",
                "open_pass_started_at": datetime(2026, 9, 14, 12, 0, 0),
            }
        },
        "po_counts": {"TUBC": {"mirrored_pos": 3650, "open_pos": 2344}},
        "pending_writes": {
            "pending": 1,
            "in_flight": 0,
            "failed": 2,
            "oldest_pending_at": datetime(2026, 9, 14, 11, 0, 0),
            "last_drained_at": datetime(2026, 9, 14, 11, 30, 0),
        },
    }
    data.update(overrides)
    return data


@pytest.fixture
def stubbed(monkeypatch):
    """A snapshot with no database, no relay socket and both sync loops idle. Returns the fake gateway
    so a test can change what the relay is reporting."""
    gateway = _FakeGateway()
    monkeypatch.setattr(gp_sync_state, "relay_gateway", gateway)
    monkeypatch.setattr(gp_sync_state, "_read_db", lambda companies_hint: _db(companies_hint or ("TUBC",)))
    monkeypatch.setattr(gp_load, "policy", gp_load.GpLoadPolicy())
    monkeypatch.setattr(gp_po_sync, "_activity", None)
    monkeypatch.setattr(gp_po_sync, "_last_open_pass", {})
    monkeypatch.setattr(gp_po_sync, "_last_new_po_check_result", {})
    monkeypatch.setattr(gp_job_sync, "_activity", None)
    monkeypatch.setattr(gp_job_sync, "_last_run", {})
    return gateway


# --- the document -----------------------------------------------------------------------------------


def test_the_snapshot_has_exactly_the_fields_the_contract_names(stubbed):
    state = gp_sync_state.snapshot()

    assert set(state) == {
        "generated_at",
        "relay",
        "po_sync_enabled",
        "job_sync_enabled",
        "pacing",
        "initialization_window",
        "activity",
        "companies",
        "pending_writes",
    }
    assert set(state["relay"]) == {"connected", "build", "companies", "install_id"}
    assert set(state["pacing"]) == {
        "reads_per_minute",
        "read_batch",
        "reads_available",
        "paused",
        "paused_reason",
        "resume_check_in_seconds",
        "cpu_pause_pct",
        "sql_cpu_pct",
        "sql_cpu_sampled_at",
    }
    assert set(state["initialization_window"]) == {"label", "open"}
    assert set(state["activity"]) == {"kind", "company", "page", "cursor", "started_at"}
    assert set(state["pending_writes"]) == {
        "pending",
        "in_flight",
        "failed",
        "oldest_pending_at",
        "last_drained_at",
    }
    assert set(state["companies"][0]) == {
        "company",
        "name",
        "initialization_done",
        "initialization_cursor",
        "open_pass_started_at",
        "open_pass_cursor",
        "last_open_pass_finished_at",
        "last_open_pass",
        "last_new_po_check_at",
        "last_new_po_check_pos",
        "last_jobs_sync_at",
        "last_jobs_sync",
        "mirrored_pos",
        "open_pos",
    }


def test_every_timestamp_is_iso_utc_with_a_trailing_z(stubbed):
    """The same document is JSON on the relay socket, so the stamps have to be strings that say which
    zone they are in - and the relay window renders an age from them."""
    state = gp_sync_state.snapshot()

    assert state["generated_at"].endswith("Z")
    assert state["companies"][0]["open_pass_started_at"] == "2026-09-14T12:00:00Z"
    assert state["pending_writes"]["oldest_pending_at"] == "2026-09-14T11:00:00Z"
    assert state["pending_writes"]["last_drained_at"] == "2026-09-14T11:30:00Z"


def test_the_relay_and_pacing_blocks_report_what_is_in_memory(stubbed):
    stubbed.last_server_sample = {"sql_cpu_pct": 12, "sampled_at": "2026-09-14T12:00:05Z"}

    state = gp_sync_state.snapshot()

    assert state["relay"] == {
        "connected": True,
        "build": "relay-v0.3.0-build.74",
        "companies": ["TUBC"],
        "install_id": "8f1d2c3e-0000-4000-8000-000000000001",
    }
    assert state["pacing"]["reads_per_minute"] == gp_load.READS_PER_MINUTE
    assert state["pacing"]["read_batch"] == gp_load.READ_BATCH
    assert state["pacing"]["reads_available"] == pytest.approx(gp_load.READS_PER_MINUTE, abs=1.0)
    assert state["pacing"]["paused"] is False
    assert state["pacing"]["paused_reason"] is None
    # Null rather than a number: there is no probe to wait for while nothing is paused.
    assert state["pacing"]["resume_check_in_seconds"] is None
    assert state["pacing"]["cpu_pause_pct"] == gp_load.SERVER_CPU_PAUSE_PCT
    assert state["pacing"]["sql_cpu_pct"] == 12
    assert state["pacing"]["sql_cpu_sampled_at"] == "2026-09-14T12:00:05Z"


def test_a_paused_policy_reports_its_reason_and_when_it_will_look_again(stubbed):
    gp_load.policy.enter_pause("sql cpu 71% at or above the 40.0% ceiling", retry_after_seconds=60.0)

    state = gp_sync_state.snapshot()

    assert state["pacing"]["paused"] is True
    assert state["pacing"]["paused_reason"].startswith("sql cpu 71%")
    assert 0 < state["pacing"]["resume_check_in_seconds"] <= 60.0
    # And with neither loop running, the GP CPU PAUSE is the reason nothing is happening.
    assert state["activity"]["kind"] == "paused"


def test_a_company_the_relay_serves_with_no_mirror_progress_yet_is_still_listed(stubbed):
    """A newly enrolled company has no row until its first pass, and "nothing has been mirrored" is
    exactly what somebody enrolling one wants to see."""
    stubbed.companies = ["TUBC", "UCSH"]
    stubbed.company_names = {"TUBC": "Test UBC"}

    rows = {row["company"]: row for row in gp_sync_state.snapshot()["companies"]}

    assert list(rows) == ["TUBC", "UCSH"]
    assert rows["UCSH"]["name"] is None
    assert rows["UCSH"]["initialization_done"] is False
    assert rows["UCSH"]["initialization_cursor"] is None
    assert (rows["UCSH"]["mirrored_pos"], rows["UCSH"]["open_pos"]) == (0, 0)
    assert rows["TUBC"]["name"] == "Test UBC"
    assert (rows["TUBC"]["mirrored_pos"], rows["TUBC"]["open_pos"]) == (3650, 2344)


def test_with_no_relay_connected_the_companies_come_from_the_mirror_progress_rows(monkeypatch):
    """The page still has to answer with nothing on the socket - that is when somebody opens it."""
    gateway = _FakeGateway(connected=False, build=None, companies=(), install_id=None)
    monkeypatch.setattr(gp_sync_state, "relay_gateway", gateway)
    monkeypatch.setattr(gp_sync_state, "_read_db", lambda companies_hint: _db(companies_hint or ("TUBC",)))
    monkeypatch.setattr(gp_load, "policy", gp_load.GpLoadPolicy())

    state = gp_sync_state.snapshot()

    assert state["relay"] == {"connected": False, "build": None, "companies": [], "install_id": None}
    assert [row["company"] for row in state["companies"]] == ["TUBC"]
    assert state["companies"][0]["mirrored_pos"] == 3650


def test_the_last_passes_are_reported_per_company(stubbed, monkeypatch):
    monkeypatch.setattr(
        gp_po_sync,
        "_last_open_pass",
        {
            "TUBC": {
                "finished_at": datetime(2026, 9, 14, 11, 58, 0),
                "pages": 94,
                "pos": 2344,
                "left_open_table": 3,
                "missing_in_gp": 1,
                "cancelled": 0,
                "created": 2,
                "updated": 12,
            }
        },
    )
    monkeypatch.setattr(
        gp_po_sync, "_last_new_po_check_result", {"TUBC": {"at": datetime(2026, 9, 14, 11, 59, 0), "pos": 0}}
    )
    monkeypatch.setattr(
        gp_job_sync, "_last_run", {"TUBC": {"at": datetime(2026, 9, 14, 11, 45, 0), "total": 84, "adopted": 0}}
    )

    row = gp_sync_state.snapshot()["companies"][0]

    assert row["last_open_pass_finished_at"] == "2026-09-14T11:58:00Z"
    assert row["last_open_pass"] == {
        "pages": 94,
        "pos": 2344,
        "left_open_table": 3,
        "missing_in_gp": 1,
        "cancelled": 0,
        "created": 2,
        "updated": 12,
    }
    assert row["last_new_po_check_at"] == "2026-09-14T11:59:00Z"
    assert row["last_new_po_check_pos"] == 0
    assert row["last_jobs_sync_at"] == "2026-09-14T11:45:00Z"
    assert row["last_jobs_sync"] == {"total": 84, "adopted": 0}


def test_a_company_with_no_pass_behind_it_reports_nulls_rather_than_zeroes(stubbed):
    """Null is "no pass has finished"; zero would read as "a pass finished and moved nothing"."""
    row = gp_sync_state.snapshot()["companies"][0]

    assert row["last_open_pass_finished_at"] is None
    assert row["last_open_pass"] is None
    assert row["last_new_po_check_at"] is None
    assert row["last_new_po_check_pos"] is None
    assert row["last_jobs_sync_at"] is None
    assert row["last_jobs_sync"] is None


# --- what the loops are doing -------------------------------------------------------------------------


def test_the_po_mirror_is_what_doing_now_reports_when_both_loops_have_a_record(stubbed, monkeypatch):
    """It is the loop that runs for most of the day, and the one somebody watching is waiting on."""
    monkeypatch.setattr(
        gp_po_sync,
        "_activity",
        {
            "kind": "open-pos-sync",
            "company": "TUBC",
            "page": 14,
            "cursor": "PO0012300",
            "started_at": datetime(2026, 9, 14, 12, 0, 30),
        },
    )
    monkeypatch.setattr(
        gp_job_sync,
        "_activity",
        {"kind": "jobs-sync", "company": "UCSH", "page": None, "cursor": None, "started_at": datetime.utcnow()},
    )

    assert gp_sync_state.activity() == {
        "kind": "open-pos-sync",
        "company": "TUBC",
        "page": 14,
        "cursor": "PO0012300",
        "started_at": "2026-09-14T12:00:30Z",
    }


def test_the_job_sync_answers_when_the_po_mirror_is_between_passes(stubbed, monkeypatch):
    monkeypatch.setattr(
        gp_job_sync,
        "_activity",
        {
            "kind": "jobs-sync",
            "company": "UCSH",
            "page": None,
            "cursor": None,
            "started_at": datetime(2026, 9, 14, 12, 1, 0),
        },
    )

    assert gp_sync_state.activity() == {
        "kind": "jobs-sync",
        "company": "UCSH",
        "page": None,
        "cursor": None,
        "started_at": "2026-09-14T12:01:00Z",
    }


def test_nothing_running_and_nothing_paused_is_idle(stubbed):
    assert gp_sync_state.activity() == {
        "kind": "idle",
        "company": None,
        "page": None,
        "cursor": None,
        "started_at": None,
    }


def test_nothing_running_while_gp_is_too_busy_is_paused_not_idle(stubbed):
    gp_load.policy.enter_pause("sql cpu 71% at or above the 40.0% ceiling")

    assert gp_sync_state.activity()["kind"] == "paused"


# --- the push ------------------------------------------------------------------------------------------


@pytest.fixture
def pushing(monkeypatch):
    """A gateway that records pushes, with the snapshot itself stubbed - what is pushed is the document
    tested above; what is tested here is WHETHER it goes out."""
    gateway = _FakeGateway()
    monkeypatch.setattr(gp_sync_state, "relay_gateway", gateway)
    monkeypatch.setattr(gp_sync_state, "snapshot", lambda: {"generated_at": "2026-09-14T12:00:00Z"})
    return gateway


def test_a_relay_that_asked_for_the_frame_gets_one(pushing):
    assert asyncio.run(gp_sync_state._push_once()) is True
    assert pushing.pushed == [{"generated_at": "2026-09-14T12:00:00Z"}]


def test_a_relay_that_did_not_advertise_the_feature_is_left_alone(pushing):
    """An older build would read the frame as a job reply and log an uncorrelated id."""
    pushing._features = set()

    assert asyncio.run(gp_sync_state._push_once()) is False
    assert pushing.pushed == []


def test_nothing_is_built_at_all_with_no_relay_connected(pushing, monkeypatch):
    """The gate is checked BEFORE the snapshot, so a dark relay costs no database work."""
    pushing.connected = False

    def _must_not_run():
        raise AssertionError("the snapshot was built for a relay that is not connected")

    monkeypatch.setattr(gp_sync_state, "snapshot", _must_not_run)

    assert asyncio.run(gp_sync_state._push_once()) is False
    assert pushing.pushed == []


def test_wake_is_safe_before_the_push_loop_has_started(monkeypatch):
    monkeypatch.setattr(gp_sync_state, "_wake_event", None)
    gp_sync_state.wake()  # must not raise


def test_the_kill_switch_reads_the_environment(monkeypatch):
    monkeypatch.delenv("GP_SYNC_STATE_ENABLED", raising=False)
    assert gp_sync_state.enabled() is True
    monkeypatch.setenv("GP_SYNC_STATE_ENABLED", "false")
    assert gp_sync_state.enabled() is False


# --- the database half ------------------------------------------------------------------------------
# Everything above stubs _read_db, which is the point: nothing else in the snapshot costs a query.
# These two run the real statements.


@pytest.fixture
def borrowed_session(db_session, monkeypatch):
    """Run the service's own session against the test's transaction, so seeded rows are visible without
    committing them."""

    class _Borrowed:
        def __enter__(self):
            return db_session

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(gp_sync_state, "SessionLocal", _Borrowed)
    return db_session


def test_read_db_counts_a_companys_mirrored_and_open_pos(borrowed_session):
    company = f"T{uuid.uuid4().hex[:8].upper()}"
    borrowed_session.add(
        GpPoSyncState(
            id=uuid.uuid4(),
            company=company,
            backfill_done=True,
            backfill_cursor="PO0012345",
            open_book_cursor="PO0009000",
        )
    )
    for po_number, status in (
        ("PO0000001", POStatus.GP_REGISTERED),
        ("PO0000002", POStatus.PARTIALLY_RECEIVED),
        ("PO0000003", POStatus.CLOSED),
        ("PO0000004", POStatus.CANCELLED),
    ):
        borrowed_session.add(PurchaseOrder(id=uuid.uuid4(), company=company, po_number=po_number, status=status))
    # A draft has no GP number, so it is not a PO GP holds and is not counted at all.
    borrowed_session.add(
        PurchaseOrder(id=uuid.uuid4(), company=company, request_number="PO-REQ-1", status=POStatus.DRAFT)
    )
    borrowed_session.flush()

    db = gp_sync_state._read_db([company])

    assert db["companies"] == [company]
    assert db["progress"][company] == {
        "initialization_done": True,
        "initialization_cursor": "PO0012345",
        "open_pass_cursor": "PO0009000",
        "open_pass_started_at": None,
    }
    assert db["po_counts"][company] == {"mirrored_pos": 4, "open_pos": 2}
    assert set(db["pending_writes"]) == {
        "pending",
        "in_flight",
        "failed",
        "oldest_pending_at",
        "last_drained_at",
    }


def test_read_db_falls_back_to_the_mirror_progress_rows_with_no_relay(borrowed_session):
    company = f"T{uuid.uuid4().hex[:8].upper()}"
    borrowed_session.add(GpPoSyncState(id=uuid.uuid4(), company=company, backfill_done=False))
    borrowed_session.flush()

    assert company in gp_sync_state._read_db([])["companies"]


# --- through the schema ----------------------------------------------------------------------------------

GP_SYNC_STATE_QUERY = """
query {
  gpSyncState {
    generatedAt
    relay { connected build companies installId }
    poSyncEnabled
    jobSyncEnabled
    pacing {
      readsPerMinute readBatch readsAvailable paused pausedReason
      resumeCheckInSeconds cpuPausePct sqlCpuPct sqlCpuSampledAt
    }
    initializationWindow { label open }
    activity { kind company page cursor startedAt }
    companies {
      company name initializationDone initializationCursor
      openPassStartedAt openPassCursor lastOpenPassFinishedAt
      lastOpenPass { pages pos leftOpenTable missingInGp cancelled created updated }
      lastNewPoCheckAt lastNewPoCheckPos
      lastJobsSyncAt lastJobsSync { total adopted }
      mirroredPos openPos
    }
    pendingWrites { pending inFlight failed oldestPendingAt lastDrainedAt }
  }
}
"""


class _FakeRequest:
    def __init__(self, token: str = "tok"):
        self.headers = {"authorization": f"Bearer {token}"}


def _execute(query: str):
    return asyncio.run(schema.execute(query, context_value={"request": _FakeRequest()}))


def _sign_in(monkeypatch, roles):
    monkeypatch.setattr(auth, "verify_clerk_token", lambda token: {"sub": "u_gp_sync_state"})
    monkeypatch.setattr(user_repository, "get_user_roles", lambda user_id: roles)
    monkeypatch.setattr(user_repository, "get_user_company", lambda user_id: "TUBC")


def test_an_admin_gets_the_whole_document(stubbed, monkeypatch):
    _sign_in(monkeypatch, [ADMIN_ROLE])

    result = _execute(GP_SYNC_STATE_QUERY)

    assert result.errors is None, result.errors
    state = result.data["gpSyncState"]
    assert state["relay"]["build"] == "relay-v0.3.0-build.74"
    assert state["activity"]["kind"] == "idle"
    assert state["initializationWindow"]["label"]
    assert state["pendingWrites"] == {
        "pending": 1,
        "inFlight": 0,
        "failed": 2,
        "oldestPendingAt": "2026-09-14T11:00:00+00:00",
        "lastDrainedAt": "2026-09-14T11:30:00+00:00",
    }
    row = state["companies"][0]
    assert row["company"] == "TUBC"
    assert row["initializationDone"] is True
    assert (row["mirroredPos"], row["openPos"]) == (3650, 2344)
    assert row["lastOpenPass"] is None


def test_the_document_still_answers_with_no_relay_connected(monkeypatch):
    """Nothing on the socket is when somebody opens the page, so this is the case that must not fail."""
    _sign_in(monkeypatch, [ADMIN_ROLE])
    monkeypatch.setattr(gp_sync_state, "relay_gateway", _FakeGateway(connected=False, build=None, companies=()))
    monkeypatch.setattr(gp_sync_state, "_read_db", lambda companies_hint: _db(companies_hint or ("TUBC",)))
    monkeypatch.setattr(gp_load, "policy", gp_load.GpLoadPolicy())

    result = _execute(GP_SYNC_STATE_QUERY)

    assert result.errors is None, result.errors
    assert result.data["gpSyncState"]["relay"]["connected"] is False
    assert [c["company"] for c in result.data["gpSyncState"]["companies"]] == ["TUBC"]


def test_a_signed_in_non_admin_is_refused(monkeypatch):
    """No stubbed snapshot: the gate runs in the schema extension BEFORE the resolver, so a refusal
    that needed the database would mean the resolver had already started."""
    _sign_in(monkeypatch, ["Shop Assembly User"])

    result = _execute(GP_SYNC_STATE_QUERY)

    assert result.errors
    assert result.errors[0].extensions["code"] == "FORBIDDEN"
    assert result.errors[0].message == f"{ADMIN_ROLE} role required"
