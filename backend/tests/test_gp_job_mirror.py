"""The GP job as GP holds it, and the writes GP will not take against it (#730).

If GP contains it, GP owns it. Against a relay advertising job_mirror, every GP JOBS SYNC pass
overwrites the GP-held project fields from GP's job record, leaves the Nexus-only ones alone, and marks
a job GP no longer holds at all NOT_IN_GP on the second pass that misses it. An inactive, closed or
not-in-GP job refuses PO REGISTRATION, GP RECEIVE ENTRY and a job edit, and a job edit writes into GP
first and saves nothing when GP does not take it.

**Never touches GP.** The relay is stubbed everywhere. The first half needs no database; the rest is
DB-backed and skipped without DATABASE_URL.
"""

import asyncio
import inspect
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from app import auth
from app.errors import GpJobNotOpenError, RelayCallError, RelayUnavailableError, ValidationError
from app.models.enums import GpJobState, ReceiveDraftStatus
from app.models.project import Project as ProjectModel
from app.repositories import project_repository, user_repository
from app.schemas import po as po_schema
from app.schemas import project as project_schema
from app.schemas import warehouse as warehouse_schema
from app.schemas.inputs import UpdateProjectInput
from app.services import gp_job_sync, gp_outbox_worker
from app.services.relay_gateway import JOB_MIRROR_FEATURE

PREFIX = "MIRROR-730-"
# The sync tests run against a company of their own: a mirroring pass stamps every project of the
# company it reads, and must not stamp another test's committed rows.
SYNC_COMPANY = "M730"


def _record(job_number: str, **overrides) -> dict:
    """A full list_jobs / update_job record, as the relay sends it."""
    record = {
        "job_number": job_number,
        "job_name": "Cowichan District Hospital",
        "gp_job_state": "active",
        "closed_date": None,
        "closed_by": None,
        "customer_number": "ISLANDHEALTH",
        "customer_name": "Island Health",
        "job_address_code": "SITE",
        "billto_address_code": "PRIMARY",
        "address1": "3045 Gibbins Rd",
        "address2": "Unit 4",
        "city": "Duncan",
        "state": "BC",
        "zip_code": "V9L 1E5",
        "country": "Canada",
        "division": "DOORS",
        "tax_schedule_id": "BC GST+PST",
        "use_tax_schedule_id": "BC USE",
        "estimator_id": "EST01",
        "estimator_name": "Erin Estimator",
        "ws_manager_id": "PM01",
        "ws_manager_name": "Paula Manager",
        "created_date": "2025-11-03",
        "schedule_start_date": "2026-01-05",
        "scheduled_completion_date": "2026-12-18",
        "bid_due_date": "1900-01-01",
        "orig_contract_amount": 125000.5,
        "contract_to_date": "130000.25",
        "total_actual_cost": 0.0,
        "billed_amount_ttd": 40000,
        "retention_amount_ttd": "4000",
        "net_billed_ttd": 36000.0,
    }
    record.update(overrides)
    return record


def _nexus_only(**overrides) -> dict:
    values = dict(
        project_manager="Nexus PM",
        job_site_name="Hospital East Wing",
        contractor="BuildCo",
        application="Healthcare",
        gc_contact_name="Bob GC",
        gc_phone="250-555-0100",
        gc_email="bob@gc.example",
        off_site_storage_agreement=True,
        estimator_code="TITAN-EST",
        titan_user_id="titan-user",
        schedule_filename="schedule.xml",
        archived=True,
    )
    values.update(overrides)
    return values


# --- apply_gp_job_record: what GP owns and what it does not ------------------------------------------


def test_the_record_overwrites_every_gp_held_field():
    project = ProjectModel(project_id="23093", company="TUBC", description="Old name", client="Old client")

    project_repository.apply_gp_job_record(project, _record("23093"))

    assert project.description == "Cowichan District Hospital"
    assert project.client == "Island Health"
    assert (project.address, project.address2, project.city, project.state, project.zip, project.country) == (
        "3045 Gibbins Rd",
        "Unit 4",
        "Duncan",
        "BC",
        "V9L 1E5",
        "Canada",
    )
    assert project.customer_number == "ISLANDHEALTH"
    assert (project.job_address_code, project.billto_address_code) == ("SITE", "PRIMARY")
    assert (project.division, project.tax_schedule_id, project.use_tax_schedule_id) == (
        "DOORS",
        "BC GST+PST",
        "BC USE",
    )
    assert (project.estimator_id, project.estimator_name) == ("EST01", "Erin Estimator")
    assert (project.ws_manager_id, project.ws_manager_name) == ("PM01", "Paula Manager")
    assert project.gp_created_date == date(2025, 11, 3)
    assert project.schedule_start_date == date(2026, 1, 5)
    assert project.scheduled_completion_date == date(2026, 12, 18)
    assert project.gp_job_state == GpJobState.ACTIVE


def test_the_nexus_only_fields_are_never_touched():
    project = ProjectModel(project_id="23093", company="TUBC", **_nexus_only())

    project_repository.apply_gp_job_record(project, _record("23093"))

    for name, value in _nexus_only().items():
        assert getattr(project, name) == value, name


def test_gps_1900_placeholder_and_a_null_read_as_no_date():
    project = ProjectModel(project_id="23093", company="TUBC", bid_due_date=date(2026, 2, 1))

    project_repository.apply_gp_job_record(
        project, _record("23093", bid_due_date="1900-01-01", schedule_start_date=None, created_date="1900-01-01")
    )

    assert project.bid_due_date is None
    assert project.schedule_start_date is None
    assert project.gp_created_date is None


def test_money_is_read_from_a_number_or_a_numeric_string():
    project = ProjectModel(project_id="23093", company="TUBC")

    project_repository.apply_gp_job_record(project, _record("23093"))

    assert project.orig_contract_amount == Decimal("125000.5")
    assert project.contract_to_date == Decimal("130000.25")
    assert project.total_actual_cost == Decimal("0.0")
    assert project.billed_amount_ttd == Decimal("40000")
    assert project.retention_amount_ttd == Decimal("4000")
    assert project.net_billed_ttd == Decimal("36000.0")


def test_gp_empties_a_field_it_holds_as_empty():
    """Overwritten, never compared: GP holding a blank is GP's value."""
    project = ProjectModel(project_id="23093", company="TUBC", address2="Unit 4", division="DOORS")

    project_repository.apply_gp_job_record(project, _record("23093", address2="  ", division=None))

    assert project.address2 is None
    assert project.division is None


def test_a_key_the_record_does_not_carry_is_left_alone():
    project = ProjectModel(project_id="23093", company="TUBC", description="Kept", client="Kept client")

    project_repository.apply_gp_job_record(project, {"job_number": "23093", "gp_job_state": "closed"})

    assert project.description == "Kept"
    assert project.client == "Kept client"
    assert project.gp_job_state == GpJobState.CLOSED


@pytest.mark.parametrize(
    "wire, state",
    [("active", GpJobState.ACTIVE), ("inactive", GpJobState.INACTIVE), ("closed", GpJobState.CLOSED)],
)
def test_the_job_state_maps_and_seeing_the_job_clears_the_missing_stamp(wire, state):
    project = ProjectModel(
        project_id="23093", company="TUBC", gp_job_state=GpJobState.NOT_IN_GP, gp_missing_since=datetime(2026, 9, 1)
    )

    project_repository.apply_gp_job_record(project, _record("23093", gp_job_state=wire, closed_date="2026-08-30"))

    assert project.gp_job_state == state
    assert project.gp_missing_since is None
    assert project.gp_closed_date == date(2026, 8, 30)


# --- the relay's live refusals -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "code, words",
    [("job_inactive", "inactive in GP"), ("job_closed", "closed in GP"), ("job_not_registered", "not in GP")],
)
def test_the_relays_job_refusals_read_as_one_error(code, words):
    refusal = project_repository.gp_job_refusal(RelayCallError("no", detail={"error": code}), "23093")

    assert isinstance(refusal, GpJobNotOpenError)
    assert refusal.code == "GP_JOB_NOT_OPEN"
    assert "GP job 23093" in refusal.message
    assert words in refusal.message


def test_any_other_refusal_is_not_a_job_refusal():
    assert project_repository.gp_job_refusal(RelayCallError("no", detail={"error": "job_already_exists"}), "1") is None
    assert project_repository.gp_job_refusal(RelayCallError("no"), "1") is None


def test_the_relays_context_names_the_job_when_the_caller_cannot():
    # A receipt carries only the PO number; the relay says which job refused it.
    e = RelayCallError("no", detail={"error": "job_closed", "context": {"job_number": "23094"}})

    assert "GP job 23094" in project_repository.gp_job_refusal(e, None).message


def test_the_guard_is_not_on_shipping_or_import():
    """Shipping out and importing a schedule write nothing into GP, so a closed job must not stop them."""
    from app.repositories import import_repository, shipping_repository

    assert "require_gp_job_open" not in inspect.getsource(shipping_repository)
    assert "require_gp_job_open" not in inspect.getsource(import_repository)


def test_a_queued_writes_job_is_read_off_its_payload():
    assert gp_outbox_worker._job_number_of({"lines": [{"job_number": None}, {"job_number": " 23093 "}]}) == "23093"
    assert gp_outbox_worker._job_number_of({"job_number": "23094"}) == "23094"
    assert gp_outbox_worker._job_number_of({"po_number": "PO1"}) is None


# --- what a job edit sends GP ----------------------------------------------------------------------------


def _current(**overrides) -> ProjectModel:
    values = dict(
        project_id="23093",
        company="TUBC",
        description="Cowichan District Hospital",
        customer_number="ISLANDHEALTH",
        job_address_code="SITE",
        billto_address_code="PRIMARY",
        address="3045 Gibbins Rd",
        city="Duncan",
        state="BC",
        zip="V9L 1E5",
        schedule_start_date=date(2026, 1, 5),
    )
    values.update(overrides)
    return ProjectModel(**values)


def test_an_edit_that_repeats_what_is_there_changes_nothing_in_gp():
    edit = UpdateProjectInput(
        description=" Cowichan District Hospital ",
        address="3045 Gibbins Rd",
        city="Duncan",
        schedule_start_date=date(2026, 1, 5),
        project_manager="New PM",
    )

    assert project_schema._gp_job_changes(_current(), edit) == {}


def test_only_the_changed_fields_are_sent():
    edit = UpdateProjectInput(description="Cowichan Hospital", state="BC", division="HARDWARE")

    assert project_schema._gp_job_changes(_current(), edit) == {"job_name": "Cowichan Hospital", "division": "HARDWARE"}


def test_a_blanked_gp_field_or_a_cleared_date_is_no_change():
    """update_job reads a blank as not sent, so GP cannot be cleared this way - sending one would only
    pretend to."""
    edit = UpdateProjectInput(description="  ", state="", schedule_start_date=None)

    assert project_schema._gp_job_changes(_current(), edit) == {}


def test_a_changed_date_is_sent_as_iso():
    edit = UpdateProjectInput(bid_due_date=date(2026, 3, 2))

    assert project_schema._gp_job_changes(_current(), edit) == {"bid_due_date": "2026-03-02"}


def test_the_street_and_the_city_travel_together():
    assert project_schema._gp_job_changes(_current(), UpdateProjectInput(city="North Cowichan")) == {
        "address1": "3045 Gibbins Rd",
        "city": "North Cowichan",
    }


def test_a_picked_job_address_code_never_goes_with_a_new_site_address():
    with pytest.raises(ValidationError):
        project_schema._gp_job_changes(_current(), UpdateProjectInput(address="1 New St", job_address_code="OTHER"))


def test_a_new_customer_needs_its_bill_to_code():
    with pytest.raises(ValidationError) as excinfo:
        project_schema._gp_job_changes(_current(), UpdateProjectInput(customer_number="VIHA", job_address_code="S2"))
    assert excinfo.value.field == "billto_address_code"


def test_a_new_customer_needs_a_site():
    with pytest.raises(ValidationError) as excinfo:
        project_schema._gp_job_changes(
            _current(), UpdateProjectInput(customer_number="VIHA", billto_address_code="PRIMARY")
        )
    assert excinfo.value.field == "job_address_code"


def test_a_new_customer_takes_its_codes_even_when_they_are_spelled_the_same():
    edit = UpdateProjectInput(customer_number="VIHA", billto_address_code="PRIMARY", job_address_code="SITE")

    assert project_schema._gp_job_changes(_current(), edit) == {
        "customer_number": "VIHA",
        "billto_address_code": "PRIMARY",
        "job_address_code": "SITE",
    }


def test_a_new_customer_with_a_new_site_address_sends_no_address_code():
    edit = UpdateProjectInput(customer_number="VIHA", billto_address_code="MAIN", address="1 New St")

    assert project_schema._gp_job_changes(_current(), edit) == {
        "customer_number": "VIHA",
        "billto_address_code": "MAIN",
        "address1": "1 New St",
        "city": "Duncan",
    }


# --- the live refusals on the write paths, without a database ------------------------------------------


def test_a_registration_gp_refuses_for_the_job_reads_as_the_job_error(monkeypatch):
    from app.schemas.inputs import RegisterPOInput, RegisterPOLineItemInput

    monkeypatch.setattr(po_schema, "current_user", lambda info: {"user_id": "user_1"})
    monkeypatch.setattr(po_schema, "tenant_scope", lambda info: None)
    monkeypatch.setattr(po_schema.user_repository, "get_user_gp_buyer_id", lambda user_id: "mira")
    monkeypatch.setattr(po_schema.gp_idempotency, "load", lambda key: None)
    monkeypatch.setattr(po_schema, "_prepare_register_po", lambda **kw: {"lines": [{"job_number": "23093"}]})

    async def _live_check(company, job_number):
        return None

    async def _relay_call(company, op, payload=None, timeout=None):
        raise RelayCallError("Job 23093 is inactive", detail={"error": "job_inactive"})

    monkeypatch.setattr(po_schema.gp_job_sync, "check_job_setup_live", _live_check)
    monkeypatch.setattr(po_schema.relay_gateway, "_socket", object())
    monkeypatch.setattr(po_schema.relay_gateway, "_features", frozenset({po_schema.CREATE_PO_IDEMPOTENCY_FEATURE}))
    monkeypatch.setattr(po_schema.relay_gateway, "relay_call", _relay_call)

    with pytest.raises(GpJobNotOpenError) as excinfo:
        asyncio.run(
            po_schema.POMutations().register_po_in_gp(
                None,
                RegisterPOInput(
                    po_id=str(uuid.uuid4()),
                    gp_vendor_id="GPV1",
                    gp_vendor_name="GP Vendor",
                    gp_company="TUBC",
                    buyer_id="mira",
                    line_items=[
                        RegisterPOLineItemInput(
                            id=None, hardware_category="HINGE", product_code="HG-1", ordered_quantity=1, unit_cost=1.0
                        )
                    ],
                    idempotency_key=str(uuid.uuid4()),
                    site="VANCOUVER",
                ),
            )
        )
    assert "GP job 23093 is inactive in GP" in excinfo.value.message


def _stub_the_approval(monkeypatch, relay_error):
    from app.repositories.warehouse.receive_drafts import ApprovalContext

    released: list = []
    ctx = ApprovalContext(uuid.uuid4(), uuid.uuid4(), None, "Wendy Warehouse", [])
    monkeypatch.setattr(warehouse_schema, "current_user", lambda info: {"user_id": "user_1"})
    monkeypatch.setattr(warehouse_schema, "tenant_scope", lambda info: None)
    monkeypatch.setattr(warehouse_schema, "resolve_display_name", lambda user_id: "Rita Reviewer")
    monkeypatch.setattr(warehouse_schema, "_authorize_draft_approval", lambda info, user_id, draft_id: None)
    monkeypatch.setattr(warehouse_schema.gp_idempotency, "load", lambda key: None)
    monkeypatch.setattr(warehouse_schema, "_claim_draft_for_approval", lambda *a, **k: ctx)
    monkeypatch.setattr(warehouse_schema, "_prepare_create_receive", lambda **kw: ("TUBC", {"po_number": "PO1"}))
    monkeypatch.setattr(warehouse_schema, "_release_draft_claim", lambda draft_id, key: released.append(draft_id))
    monkeypatch.setattr(warehouse_schema, "_po_job_number", lambda po_id: "23093")

    async def _relay_call(company, op, payload=None, timeout=None):
        raise relay_error

    monkeypatch.setattr(warehouse_schema.relay_gateway, "relay_call", _relay_call)
    return released


def _approve():
    from app.schemas.inputs import ApproveReceiveDraftInput

    return asyncio.run(
        warehouse_schema.WarehouseMutations().approve_receive_draft(
            None, ApproveReceiveDraftInput(draft_id=str(uuid.uuid4()), idempotency_key=str(uuid.uuid4()))
        )
    )


def test_a_receipt_gp_refuses_for_the_job_reads_as_the_job_error_and_releases_the_draft(monkeypatch):
    released = _stub_the_approval(monkeypatch, RelayCallError("closed", detail={"error": "job_closed"}))

    with pytest.raises(GpJobNotOpenError) as excinfo:
        _approve()

    assert "GP job 23093 is closed in GP" in excinfo.value.message
    assert len(released) == 1  # GP did not commit, so the draft goes back in the queue


def test_any_other_receipt_refusal_passes_through_unchanged(monkeypatch):
    _stub_the_approval(monkeypatch, RelayCallError("eConnect 4612", detail={"error": "econnect"}))

    with pytest.raises(RelayCallError) as excinfo:
        _approve()

    assert not isinstance(excinfo.value, GpJobNotOpenError)


# --- DB-backed ---------------------------------------------------------------------------------------------


def _relay(monkeypatch, *, jobs, company=SYNC_COMPANY, mirror=True, raises=None):
    """The relay socket, faked the way test_gp_job_sync.py fakes it, with or without job_mirror."""

    async def _call_with_meta(_company, op, payload=None, timeout=None, *, background=False):
        if op == "job_setup_health":
            return {"jobs": []}, {"cost": None, "server": None}
        if raises is not None:
            raise raises
        return {"company": _company, "jobs": jobs}, {"cost": None, "server": None}

    monkeypatch.setattr(type(gp_job_sync.relay_gateway), "companies", property(lambda self: [company]))
    monkeypatch.setattr(type(gp_job_sync.relay_gateway), "connected", property(lambda self: True))
    monkeypatch.setattr(gp_job_sync.relay_gateway, "relay_call_with_meta", _call_with_meta)
    monkeypatch.setattr(gp_job_sync.relay_gateway, "_features", frozenset({JOB_MIRROR_FEATURE} if mirror else set()))
    monkeypatch.setattr(gp_job_sync.gp_load, "policy", gp_job_sync.gp_load.GpLoadPolicy())


@pytest.fixture
def clean_projects(_migrate_database):
    """The sync writes through its own sessions, so what it creates is removed by hand."""
    from app.database import SessionLocal

    yield
    with SessionLocal() as session:
        for project in session.query(ProjectModel).filter(ProjectModel.project_id.like(f"{PREFIX}%")).all():
            session.delete(project)
        session.commit()


def _seed(**values) -> None:
    from app.database import SessionLocal

    with SessionLocal() as session:
        session.add(ProjectModel(id=uuid.uuid4(), company=SYNC_COMPANY, **values))
        session.commit()


def _load(job_number: str) -> ProjectModel:
    from app.database import SessionLocal

    with SessionLocal() as session:
        project = session.query(ProjectModel).filter_by(project_id=job_number, company=SYNC_COMPANY).one()
        session.expunge(project)
        return project


def test_a_mirroring_pass_overwrites_existing_projects_and_leaves_nexus_only_fields(monkeypatch, clean_projects):
    job = f"{PREFIX}A"
    _seed(project_id=job, description="Adopted name", client="Old client", **_nexus_only())
    _relay(monkeypatch, jobs=[_record(job)])

    total, adopted = asyncio.run(gp_job_sync.run_once())

    assert (total, adopted) == (1, 0)
    project = _load(job)
    assert project.description == "Cowichan District Hospital"
    assert project.client == "Island Health"
    assert project.customer_number == "ISLANDHEALTH"
    assert project.bid_due_date is None  # GP's 1900 placeholder
    assert project.orig_contract_amount == Decimal("125000.50000")
    assert project.gp_job_state == GpJobState.ACTIVE
    for name, value in _nexus_only().items():
        assert getattr(project, name) == value, name


def test_a_mirroring_pass_creates_a_missing_project_with_the_whole_record(monkeypatch, clean_projects):
    job = f"{PREFIX}B"
    _relay(monkeypatch, jobs=[_record(job, gp_job_state="closed", closed_date="2026-06-30")])

    total, adopted = asyncio.run(gp_job_sync.run_once())

    assert (total, adopted) == (1, 1)
    project = _load(job)
    assert project.client == "Island Health"
    assert project.gp_job_state == GpJobState.CLOSED
    assert project.gp_closed_date == date(2026, 6, 30)


def test_without_the_feature_the_pass_is_what_it_always_was(monkeypatch, clean_projects):
    """An older relay's list carries a number and a name. Overwriting from it would blank everything
    else, so nothing existing is touched and a new project gets the name alone."""
    existing, new = f"{PREFIX}C", f"{PREFIX}D"
    _seed(project_id=existing, description="Adopted name", client="Kept client", city="Kept city")
    _relay(monkeypatch, jobs=[_record(existing), _record(new)], mirror=False)

    total, adopted = asyncio.run(gp_job_sync.run_once())

    assert (total, adopted) == (2, 1)
    kept = _load(existing)
    assert (kept.description, kept.client, kept.city, kept.gp_job_state) == (
        "Adopted name",
        "Kept client",
        "Kept city",
        None,
    )
    created = _load(new)
    assert created.description == "Cowichan District Hospital"
    assert created.client is None
    assert created.gp_job_state is None


def test_a_job_gp_no_longer_holds_is_not_in_gp_only_on_the_second_miss(monkeypatch, clean_projects):
    present, gone = f"{PREFIX}E", f"{PREFIX}F"
    _seed(project_id=gone, description="Kept name", client="Kept client", gp_job_state=GpJobState.ACTIVE)
    _relay(monkeypatch, jobs=[_record(present)])

    asyncio.run(gp_job_sync.run_once())
    first = _load(gone)
    assert first.gp_job_state == GpJobState.ACTIVE
    assert first.gp_missing_since is not None

    asyncio.run(gp_job_sync.run_once())
    second = _load(gone)
    assert second.gp_job_state == GpJobState.NOT_IN_GP
    # The last thing GP said about the job stays.
    assert (second.description, second.client) == ("Kept name", "Kept client")


def test_a_job_that_comes_back_starts_over(monkeypatch, clean_projects):
    job = f"{PREFIX}G"
    _seed(project_id=job, gp_job_state=GpJobState.NOT_IN_GP, gp_missing_since=datetime.utcnow() - timedelta(hours=1))
    _relay(monkeypatch, jobs=[_record(job, gp_job_state="inactive")])

    asyncio.run(gp_job_sync.run_once())

    project = _load(job)
    assert project.gp_job_state == GpJobState.INACTIVE
    assert project.gp_missing_since is None


def test_an_empty_list_marks_nothing(monkeypatch, clean_projects):
    """A company with no jobs at all is likelier an empty read than the truth."""
    job = f"{PREFIX}H"
    _seed(project_id=job, gp_job_state=GpJobState.ACTIVE)
    _relay(monkeypatch, jobs=[])

    asyncio.run(gp_job_sync.run_once())
    asyncio.run(gp_job_sync.run_once())

    project = _load(job)
    assert project.gp_job_state == GpJobState.ACTIVE
    assert project.gp_missing_since is None


def test_a_failed_read_marks_nothing(monkeypatch, clean_projects):
    job = f"{PREFIX}I"
    _seed(project_id=job, gp_job_state=GpJobState.ACTIVE)
    _relay(monkeypatch, jobs=[], raises=RuntimeError("GP read failed"))

    for _ in range(2):
        with pytest.raises(RelayUnavailableError):
            asyncio.run(gp_job_sync.run_once())

    assert _load(job).gp_missing_since is None


# --- require_gp_job_open ------------------------------------------------------------------------------------


def _project(session, state=None, job=None) -> ProjectModel:
    project = ProjectModel(
        id=uuid.uuid4(),
        project_id=job or f"{PREFIX}{uuid.uuid4().hex[:8]}",
        description="Job",
        company="TUBC",
        gp_job_state=state,
    )
    session.add(project)
    session.flush()
    return project


@pytest.mark.parametrize("state", [None, GpJobState.ACTIVE])
def test_a_never_mirrored_or_active_job_passes(db_session, state):
    project_repository.require_gp_job_open(db_session, _project(db_session, state).id)


@pytest.mark.parametrize(
    "state, words",
    [(GpJobState.INACTIVE, "inactive"), (GpJobState.CLOSED, "closed"), (GpJobState.NOT_IN_GP, "not in GP")],
)
def test_an_inactive_closed_or_absent_job_refuses(db_session, state, words):
    project = _project(db_session, state, job="23093")

    with pytest.raises(GpJobNotOpenError) as excinfo:
        project_repository.require_gp_job_open(db_session, project.id)

    assert excinfo.value.code == "GP_JOB_NOT_OPEN"
    assert "GP job 23093" in excinfo.value.message
    assert words in excinfo.value.message


def test_no_project_passes(db_session):
    project_repository.require_gp_job_open(db_session, None)
    project_repository.require_gp_job_open(db_session, uuid.uuid4())


class _NoCloseSession:
    """The test session as a context manager that does not close it, so a resolver helper opening
    SessionLocal() runs inside the test's own transaction."""

    def __init__(self, session):
        self._session = session

    def __enter__(self):
        return self._session

    def __exit__(self, *exc):
        return False


def test_po_registration_refuses_an_inactive_job_before_anything_is_built(monkeypatch, db_session):
    from app.repositories import po_repository

    project = _project(db_session, GpJobState.INACTIVE)
    draft = po_repository.create_po(
        db_session,
        line_items=[
            {
                "hardware_category": "HINGE",
                "product_code": "HG-100",
                "ordered_quantity": 1,
                "unit_cost": 10.0,
                "classification": None,
                "order_as": None,
            }
        ],
        project_id=project.id,
        company="TUBC",
    )
    monkeypatch.setattr(po_schema, "SessionLocal", lambda: _NoCloseSession(db_session))

    with pytest.raises(GpJobNotOpenError):
        po_schema._prepare_register_po(
            po_id=draft.id,
            gp_vendor_id="GPV1",
            buyer_id="mira",
            cost_code="210-200-2",
            line_items_data=[],
            site="VANCOUVER",
        )


def test_gp_receive_entry_refuses_a_closed_job_even_on_a_po_already_in_gp(monkeypatch, db_session):
    from app.models.enums import POOrigin, POStatus
    from app.models.purchase_order import PurchaseOrder

    project = _project(db_session, GpJobState.CLOSED)
    po = PurchaseOrder(
        id=uuid.uuid4(),
        company="TUBC",
        gp_company="TUBC",
        po_number="PO730001",
        origin=POOrigin.GP,
        project_id=project.id,
        status=POStatus.GP_REGISTERED,
    )
    db_session.add(po)
    db_session.flush()
    monkeypatch.setattr(warehouse_schema, "SessionLocal", lambda: _NoCloseSession(db_session))
    monkeypatch.setattr(
        warehouse_schema.warehouse_repository,
        "validate_receive_eligibility",
        lambda session, po_id, received_by, lines: ("PO730001", "TUBC", []),
    )

    with pytest.raises(GpJobNotOpenError):
        warehouse_schema._prepare_create_receive(po_id=po.id, received_by="Wendy", line_items_data=[])


@pytest.mark.parametrize("state", [GpJobState.INACTIVE, GpJobState.CLOSED, GpJobState.NOT_IN_GP])
def test_a_count_cannot_be_drafted_against_a_job_that_is_not_open(db_session, state):
    """Refused at the count, not only at approval: hardware counted against a job GP will not take a
    receipt on could never be booked."""
    from tests.test_receive_drafts import _draft, _make_po

    project = _project(db_session, state)
    po, li = _make_po(db_session, project.id)

    with pytest.raises(GpJobNotOpenError):
        _draft(db_session, po, li)


def test_editing_or_resubmitting_a_draft_after_the_job_closed_is_refused(db_session):
    from app.repositories import warehouse as warehouse_repository
    from tests.test_receive_drafts import AUTHOR, _draft, _lines, _make_po

    project = _project(db_session, GpJobState.ACTIVE)
    po, li = _make_po(db_session, project.id)
    draft = _draft(db_session, po, li)
    project.gp_job_state = GpJobState.CLOSED
    db_session.flush()

    with pytest.raises(GpJobNotOpenError):
        warehouse_repository.update_receive_draft(db_session, draft.id, _lines(li, 2), AUTHOR, False)
    # Only a rejected draft can be resubmitted; the rejection itself is not what is under test.
    draft.status = ReceiveDraftStatus.REJECTED
    db_session.flush()
    with pytest.raises(GpJobNotOpenError):
        warehouse_repository.resubmit_receive_draft(db_session, draft.id, AUTHOR)


@pytest.mark.parametrize("state", [None, GpJobState.ACTIVE])
def test_a_count_on_a_never_mirrored_or_active_job_is_drafted(db_session, state):
    from tests.test_receive_drafts import _draft, _make_po

    project = _project(db_session, state)
    po, li = _make_po(db_session, project.id)

    assert _draft(db_session, po, li).id is not None


def test_a_count_on_a_stock_po_is_drafted(db_session):
    from tests.test_receive_drafts import _draft, _make_po

    po, li = _make_po(db_session, None)

    assert _draft(db_session, po, li).id is not None


def test_a_queued_write_gp_refuses_for_the_job_fails_for_good_in_the_same_words(_migrate_database, monkeypatch):
    from app.database import SessionLocal
    from app.models.gp_outbox import GpWriteOutbox
    from app.repositories import gp_outbox_repository

    key = str(uuid.uuid4())
    with SessionLocal() as session:
        row = gp_outbox_repository.enqueue(
            session,
            idempotency_key=key,
            op="register_po_in_gp",
            relay_op="create_po",
            company="TUBC",
            payload={"header": {}, "lines": [{"job_number": "23093"}]},
            persist_context={"po_id": str(uuid.uuid4())},
            entity_key=f"po:{uuid.uuid4()}",
            label="Register PO in GP",
        )
        row_id = row.id
        session.commit()

    async def _relay_call(company, op, payload=None, timeout=30.0):
        raise RelayCallError("Job 23093 is closed", detail={"error": "job_closed"})

    monkeypatch.setattr(gp_outbox_worker.relay_gateway, "relay_call", _relay_call)
    monkeypatch.setattr(
        gp_outbox_worker.relay_gateway, "_features", frozenset({gp_outbox_worker.CREATE_PO_IDEMPOTENCY_FEATURE})
    )
    try:
        asyncio.run(gp_outbox_worker._drain_one(row_id))
        with SessionLocal() as session:
            row = gp_outbox_repository.get_entry(session, row_id)
            assert row.status == "FAILED"
            assert row.failure_kind == "gp_rejected"
            assert row.last_error_code == "GP_JOB_NOT_OPEN"
            assert "GP job 23093 is closed in GP" in row.last_error
    finally:
        with SessionLocal() as session:
            row = session.get(GpWriteOutbox, row_id)
            if row is not None:
                session.delete(row)
                session.commit()


# --- updateProject through the schema ----------------------------------------------------------------------

_UPDATE = """
mutation($id: ID!, $input: UpdateProjectInput!) {
  updateProject(id: $id, input: $input) {
    description client city customerNumber projectManager gpJobState scheduleStartDate origContractAmount
  }
}
"""


class _FakeRequest:
    headers = {"authorization": "Bearer tok"}


def _execute(project_id, edit: dict):
    from main import schema

    context = {
        "request": _FakeRequest(),
        "_auth_user_id": "u_test",
        "_auth_roles": [auth.TENANT_OWNER_ROLE],
        "_auth_company": "TUBC",
    }
    return asyncio.run(
        schema.execute(_UPDATE, variable_values={"id": str(project_id), "input": edit}, context_value=context)
    )


@pytest.fixture
def tenant_owner(monkeypatch, db_session):
    monkeypatch.setattr(auth, "verify_clerk_token", lambda token: {"sub": "u_test"})
    monkeypatch.setattr(user_repository, "get_user_roles", lambda user_id: [auth.TENANT_OWNER_ROLE])
    monkeypatch.setattr(user_repository, "get_user_company", lambda user_id: "TUBC")
    monkeypatch.setattr(project_schema, "SessionLocal", lambda: _NoCloseSession(db_session))
    monkeypatch.setattr(project_schema.relay_gateway, "_features", frozenset({JOB_MIRROR_FEATURE}))
    return db_session


def _relay_for_edits(monkeypatch, *, reply=None, raises=None) -> list:
    calls: list = []

    async def _relay_call(company, op, payload=None, timeout=None):
        calls.append((company, op, payload))
        if raises is not None:
            raise raises
        return reply

    monkeypatch.setattr(project_schema.relay_gateway, "relay_call", _relay_call)
    return calls


def _editable(session, **overrides) -> ProjectModel:
    values = dict(
        id=uuid.uuid4(),
        project_id="23093",
        company="TUBC",
        description="Cowichan District Hospital",
        client="Island Health",
        address="3045 Gibbins Rd",
        city="Duncan",
        project_manager="Old PM",
        gp_job_state=GpJobState.ACTIVE,
    )
    values.update(overrides)
    project = ProjectModel(**values)
    session.add(project)
    session.flush()
    return project


def test_a_gp_edit_writes_gp_first_applies_the_read_back_then_saves_nexus_fields(monkeypatch, tenant_owner):
    project = _editable(tenant_owner)
    calls = _relay_for_edits(
        monkeypatch, reply={"job": _record("23093", job_name="Cowichan Hospital", city="North Cowichan")}
    )

    result = _execute(project.id, {"description": "Cowichan Hospital", "projectManager": "New PM"})

    assert result.errors is None, result.errors
    assert calls == [("TUBC", "update_job", {"job_number": "23093", "job_name": "Cowichan Hospital"})]
    data = result.data["updateProject"]
    assert data["description"] == "Cowichan Hospital"
    assert data["city"] == "North Cowichan"  # GP's read-back, not the input
    assert data["customerNumber"] == "ISLANDHEALTH"
    assert data["projectManager"] == "New PM"
    assert data["origContractAmount"] == 125000.5


def test_an_edit_with_no_gp_change_never_calls_the_relay(monkeypatch, tenant_owner):
    project = _editable(tenant_owner, gp_job_state=GpJobState.CLOSED)
    calls = _relay_for_edits(monkeypatch, raises=AssertionError("the relay must not be asked"))

    result = _execute(project.id, {"description": "Cowichan District Hospital", "projectManager": "New PM"})

    assert result.errors is None, result.errors
    assert calls == []
    assert result.data["updateProject"]["projectManager"] == "New PM"


def _unchanged(session, project_id):
    session.expire_all()
    project = session.get(ProjectModel, project_id)
    return project.description, project.project_manager


def test_a_relay_that_is_down_saves_nothing(monkeypatch, tenant_owner):
    project = _editable(tenant_owner)
    _relay_for_edits(monkeypatch, raises=RelayUnavailableError("no relay is currently connected"))

    result = _execute(project.id, {"description": "Cowichan Hospital", "projectManager": "New PM"})

    assert result.errors[0].extensions["code"] == "RELAY_UNAVAILABLE"
    assert _unchanged(tenant_owner, project.id) == ("Cowichan District Hospital", "Old PM")


def test_gp_refusing_for_the_job_saves_nothing(monkeypatch, tenant_owner):
    project = _editable(tenant_owner)
    _relay_for_edits(monkeypatch, raises=RelayCallError("inactive", detail={"error": "job_inactive"}))

    result = _execute(project.id, {"description": "Cowichan Hospital", "projectManager": "New PM"})

    assert result.errors[0].extensions["code"] == "GP_JOB_NOT_OPEN"
    assert _unchanged(tenant_owner, project.id) == ("Cowichan District Hospital", "Old PM")


def test_any_other_gp_refusal_saves_nothing(monkeypatch, tenant_owner):
    project = _editable(tenant_owner)
    _relay_for_edits(monkeypatch, raises=RelayCallError("address code not on customer", detail={"error": "x"}))

    result = _execute(project.id, {"description": "Cowichan Hospital", "projectManager": "New PM"})

    assert result.errors[0].extensions["code"] == "VALIDATION_ERROR"
    assert _unchanged(tenant_owner, project.id) == ("Cowichan District Hospital", "Old PM")


def test_a_mirrored_inactive_job_is_refused_before_gp_is_asked(monkeypatch, tenant_owner):
    project = _editable(tenant_owner, gp_job_state=GpJobState.INACTIVE)
    calls = _relay_for_edits(monkeypatch, raises=AssertionError("the relay must not be asked"))

    result = _execute(project.id, {"description": "Cowichan Hospital", "projectManager": "New PM"})

    assert result.errors[0].extensions["code"] == "GP_JOB_NOT_OPEN"
    assert calls == []
    assert _unchanged(tenant_owner, project.id) == ("Cowichan District Hospital", "Old PM")


def test_a_relay_without_the_feature_is_refused_and_saves_nothing(monkeypatch, tenant_owner):
    project = _editable(tenant_owner)
    monkeypatch.setattr(project_schema.relay_gateway, "_features", frozenset())
    calls = _relay_for_edits(monkeypatch, raises=AssertionError("the relay must not be asked"))

    result = _execute(project.id, {"description": "Cowichan Hospital", "projectManager": "New PM"})

    assert result.errors[0].extensions["code"] == "RELAY_OP_UNSUPPORTED"
    assert calls == []
    assert _unchanged(tenant_owner, project.id) == ("Cowichan District Hospital", "Old PM")


def test_a_changed_client_is_refused(monkeypatch, tenant_owner):
    project = _editable(tenant_owner)
    _relay_for_edits(monkeypatch, raises=AssertionError("the relay must not be asked"))

    result = _execute(project.id, {"client": "Someone Else"})

    assert result.errors[0].extensions["code"] == "VALIDATION_ERROR"


def test_another_companys_project_is_not_found(monkeypatch, tenant_owner):
    project = _editable(tenant_owner, company="UCSH")
    calls = _relay_for_edits(monkeypatch, raises=AssertionError("the relay must not be asked"))

    result = _execute(project.id, {"description": "Cowichan Hospital"})

    assert result.errors
    assert calls == []
