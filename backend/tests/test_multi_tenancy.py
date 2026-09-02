"""A tenant is a GP company, and nothing crosses between two of them (#637).

The rows this suite builds live in two companies at once - TUBC, the one the product has always run
against, and TFAKE, a second one that exists only here. That pairing is the whole point: a scoping
bug is invisible in a single-company database, because every row passes every filter.

Three kinds of assertion, and they are not interchangeable:

  - READS are filtered. A scoped caller's list contains their own rows and does not contain the other
    company's, checked by identity rather than by count so a query that returns nothing still fails.
  - WRITES are refused by id. Every by-id mutation goes through `app/repositories/tenancy.py`, which
    answers NOT FOUND rather than forbidden - a forbidden answer would confirm the row exists and turn
    any id-taking field into an existence oracle.
  - IDENTITY is per company. A GP job number is unique within one, so TUBC 1001 and TFAKE 1001 are two
    projects; the sync, the PO mirror and the adopt path all have to agree about that.

The scope itself comes from `tenant_scope`, which is exercised directly here against a seeded context
rather than through Clerk - the memo it reads is the only input, and seeding it is what lets a resolver
be driven in a test at all.
"""

import uuid
from datetime import datetime
from decimal import Decimal

import pytest

from app.auth import ADMIN_ROLE, ForbiddenError, caller_company, tenant_scope
from app.auth_policy import ROOT_FIELD_POLICY
from app.errors import NotFoundError, ValidationError
from app.models.enums import POStatus, PullRequestSource, PullRequestStatus, ShippingOutRequestStatus
from app.models.inventory import InventoryLocation
from app.models.project import Project
from app.models.pull_request import PullRequest
from app.models.purchase_order import POLineItem, PurchaseOrder
from app.models.shipping_out_request import ShippingOutRequest
from app.models.stock_item import StockItem
from app.repositories import (
    custom_items_repository,
    po_repository,
    project_repository,
    shipment_method_repository,
    tenancy,
    warehouse_admin_repository,
)
from app.repositories import gp_po_sync_repository as sync_repo
from app.repositories import warehouse as warehouse_repository

OTHER = "TFAKE"


# --- tenant_scope: who is scoped to what -------------------------------------------------------


def _ctx(roles, company=None):
    """A request context with the two memos `tenant_scope` reads already filled, which is what lets
    it answer without a Clerk round trip (or a request object).

    The company key is seeded even when it is None - that is the whole point of the memo carrying a
    distinct "not looked up yet" sentinel, so an unassigned account costs no Clerk call either."""
    return {"request": None, "_auth_roles": roles, "_auth_company": company}


class _Info:
    def __init__(self, roles, company=None):
        self.context = _ctx(roles, company)


def test_an_admin_is_unscoped():
    """None means "no restriction", and it is the ADMIN answer alone. The admin surface - projects,
    relay installs, the outbox, user management - exists to look across companies."""
    assert tenant_scope(_Info([ADMIN_ROLE], company="TUBC")) is None


def test_everyone_else_is_pinned_to_their_own_company():
    assert tenant_scope(_Info(["Warehouse Manager"], company="TUBC")) == "TUBC"


def test_a_non_admin_with_no_company_is_refused_rather_than_shown_nothing():
    """Scoping them to nothing would render an empty application, which is indistinguishable from the
    data having gone. The message names the fix instead."""
    with pytest.raises(ForbiddenError) as e:
        tenant_scope(_Info([], company=None))
    assert "admin" in str(e.value).lower()


def test_the_company_lookup_is_memoised_per_request(monkeypatch):
    """Roles and company are two keys of one Clerk metadata object, so a query naming eight root
    fields must not make eight lookups to answer the same question."""
    from app.repositories import user_repository

    calls: list[str] = []

    def _lookup(user_id):
        calls.append(user_id)
        return "TUBC"

    monkeypatch.setattr(user_repository, "get_user_company", _lookup)
    ctx = {"request": None, "_auth_user_id": "u_1"}

    assert caller_company(ctx) == "TUBC"
    assert caller_company(ctx) == "TUBC"
    assert calls == ["u_1"]


def test_an_unassigned_account_is_memoised_too(monkeypatch):
    """None is a real answer, not "not looked up yet" - a brand-new account is the common case and
    must not cost a Clerk call per root field of every query it makes."""
    from app.repositories import user_repository

    calls: list[str] = []
    monkeypatch.setattr(user_repository, "get_user_company", lambda uid: calls.append(uid) or None)
    ctx = {"request": None, "_auth_user_id": "u_1"}

    assert caller_company(ctx) is None
    assert caller_company(ctx) is None
    assert calls == ["u_1"]


# --- updateUserCompany -------------------------------------------------------------------------


def test_assigning_a_company_is_admin_only():
    """It decides which company's rows an account can read and write at all, so it sits at the bar
    `updateUserRoles` beside it sets."""
    assert ROOT_FIELD_POLICY["updateUserCompany"] == ADMIN_ROLE


def test_the_company_is_stored_trimmed_and_uppercased(monkeypatch):
    from app.repositories import user_repository

    written: dict = {}
    monkeypatch.setattr(
        user_repository,
        "_merge_public_metadata",
        lambda user_id, patch: written.update(patch) or {"id": user_id},
    )

    user_repository.update_user_company("u_1", "  tubc  ")

    assert written == {"company": "TUBC"}


def test_a_blank_company_clears_the_assignment(monkeypatch):
    from app.repositories import user_repository

    written: dict = {}
    monkeypatch.setattr(
        user_repository,
        "_merge_public_metadata",
        lambda user_id, patch: written.update(patch) or {"id": user_id},
    )

    user_repository.update_user_company("u_1", "   ")

    assert written == {"company": None}


def test_an_over_length_company_is_refused_against_gps_own_width():
    from app.repositories import user_repository

    with pytest.raises(ValidationError):
        user_repository.normalize_company("A" * 16)


# --- the archive + admin detail policy ---------------------------------------------------------


def test_archiving_and_the_admin_detail_are_admin_only():
    assert ROOT_FIELD_POLICY["setProjectArchived"] == ADMIN_ROLE
    assert ROOT_FIELD_POLICY["adminProjectDetail"] == ADMIN_ROLE


# --- the company reaches the wire ---------------------------------------------------------------
# Adding the column to a model is only half of it: a field the schema does not publish is a 400 on
# every query that selects it, and an input field the schema does not accept is a 400 on every
# mutation that sends it. Both are asserted against the BUILT schema rather than the dataclass, which
# is what the client actually validates against.


def test_the_warehouse_type_publishes_its_company():
    from main import schema

    fields = schema._schema.type_map["Warehouse"].fields

    assert "company" in fields
    # Non-null: a warehouse always belongs to somebody, so a client never has to handle a null here.
    assert str(fields["company"].type) == "String!"


def test_both_po_reads_publish_the_tenant():
    """The register row and the detail read. A DRAFT has a company and no gp_company, so a register
    that only published gp_company had no way to say whose draft it was."""
    from main import schema

    for type_name in ("PurchaseOrder", "POListRow"):
        fields = schema._schema.type_map[type_name].fields

        assert "company" in fields, type_name
        # Non-null, unlike gp_company: a PO has a tenant from the moment it is raised.
        assert str(fields["company"].type) == "String!", type_name
        assert str(fields["gpCompany"].type) == "String", type_name


def test_the_warehouse_update_input_accepts_a_company():
    from main import schema

    fields = schema._schema.type_map["UpdateWarehouseInput"].fields

    assert "company" in fields
    # Nullable, like every other field on this input: omitted means "leave it alone".
    assert str(fields["company"].type) == "String"


def test_the_warehouse_converter_carries_the_company():
    from types import SimpleNamespace

    from app.schemas.converters import warehouse_to_type

    row = SimpleNamespace(
        id=uuid.uuid4(),
        company="TUBC",
        name="Warden",
        code="WRD",
        address=None,
        city=None,
        province=None,
        postal_code=None,
        is_primary=True,
        is_active=True,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )

    assert warehouse_to_type(row).company == "TUBC"


# --- DB-backed: two companies side by side -----------------------------------------------------


def _project(session, company, *, job=None, archived=False) -> Project:
    p = Project(
        id=uuid.uuid4(),
        company=company,
        project_id=job or f"MT-{uuid.uuid4().hex[:8]}",
        description=f"{company} job",
        archived=archived,
    )
    session.add(p)
    session.flush()
    return p


def _warehouse(session, company) -> uuid.UUID:
    wh = warehouse_admin_repository.create_warehouse(
        session,
        name=f"WH {uuid.uuid4().hex[:8]}",
        code=f"W{uuid.uuid4().hex[:6]}",
        company=company,
    )
    return wh.id


def _po(session, company, *, project=None, status=POStatus.GP_REGISTERED, number=None) -> PurchaseOrder:
    po = PurchaseOrder(
        id=uuid.uuid4(),
        company=company,
        po_number=number or f"PO-{uuid.uuid4().hex[:8]}",
        request_number=None,
        project_id=project.id if project is not None else None,
        status=status,
        gp_company=company,
        vendor_name_snapshot="Acme",
        ordered_at=datetime.utcnow(),
    )
    session.add(po)
    session.flush()
    return po


@pytest.fixture
def two_companies(db_session):
    """One project, warehouse and PO in each of two companies. Everything else in the suite hangs off
    this, because a filter that is only ever shown one company's rows cannot be seen to work."""
    mine = _project(db_session, "TUBC")
    theirs = _project(db_session, OTHER)
    return {
        "mine": mine,
        "theirs": theirs,
        "my_warehouse": _warehouse(db_session, "TUBC"),
        "their_warehouse": _warehouse(db_session, OTHER),
        "my_po": _po(db_session, "TUBC", project=mine),
        "their_po": _po(db_session, OTHER, project=theirs),
    }


# --- identity is per company -------------------------------------------------------------------


def test_the_same_job_number_adopts_as_two_projects(db_session):
    """A GP job number is unique WITHIN a company. Migration 024's single-column constraint would let
    the first company to adopt a number lock every other company out of it."""
    job = f"MT-{uuid.uuid4().hex[:8]}"

    first = project_repository.adopt_gp_job(db_session, job_number=job, job_name="TUBC's", company="TUBC")
    second = project_repository.adopt_gp_job(db_session, job_number=job, job_name="Theirs", company=OTHER)

    assert first.id != second.id
    assert {first.company, second.company} == {"TUBC", OTHER}


def test_re_adopting_within_one_company_is_still_a_conflict(db_session):
    from app.errors import ConflictError

    job = f"MT-{uuid.uuid4().hex[:8]}"
    project_repository.adopt_gp_job(db_session, job_number=job, job_name="First", company="TUBC")

    with pytest.raises(ConflictError):
        project_repository.adopt_gp_job(db_session, job_number=job, job_name="Again", company="TUBC")


def test_a_setup_verdict_is_stamped_only_on_its_own_companys_project(db_session):
    """The verdict map is keyed by job number, which is not unique across companies - an unscoped
    stamp would write one company's answer onto another company's project of the same number."""
    job = f"MT-{uuid.uuid4().hex[:8]}"
    mine = _project(db_session, "TUBC", job=job)
    theirs = _project(db_session, OTHER, job=job)

    project_repository.stamp_gp_setup_health(db_session, {job: {"ok": False, "issues": []}}, "TUBC")

    db_session.refresh(mine)
    db_session.refresh(theirs)
    assert mine.gp_setup_ok is False
    assert theirs.gp_setup_ok is None


def test_a_projects_lookup_by_job_number_is_scoped(db_session):
    job = f"MT-{uuid.uuid4().hex[:8]}"
    mine = _project(db_session, "TUBC", job=job)
    _project(db_session, OTHER, job=job)

    found = project_repository.get_project_by_schedule_id(db_session, job, company="TUBC")

    assert found is not None
    assert found.id == mine.id


# --- the mirrored PO carries its company -------------------------------------------------------


def test_a_mirrored_po_is_stamped_with_the_company_it_was_read_from(db_session):
    from sqlalchemy import select

    number = f"MIR-{uuid.uuid4().hex[:6]}"
    action = sync_repo.upsert_mirrored_po(
        db_session,
        OTHER,
        {
            "po_number": number,
            "source_table": "work",
            "doc_date": "2026-01-05",
            "vendor_id": "V1",
            "vendor_name": "Acme",
            "lines": [{"ord": 16384, "qty": 4, "received": 0, "unit_cost": 1, "item": "HG", "itemdesc": "Hinge"}],
        },
        {},
    )
    assert action == "created"

    row = db_session.scalars(select(PurchaseOrder).where(PurchaseOrder.po_number == number)).first()
    assert row is not None
    # Two columns, one value: `company` is the tenant every scoped read filters on, `gp_company` is
    # where in GP the PO lives.
    assert row.company == OTHER
    assert row.gp_company == OTHER


def test_the_job_match_only_sees_its_own_companys_projects(db_session):
    """A job number shared across companies must not attribute one company's PO to the other's
    project - which is what an unscoped project map would do."""
    job = f"MT-{uuid.uuid4().hex[:8]}"
    mine = _project(db_session, "TUBC", job=job)

    matched = sync_repo._match_project_id([{"job": job}], {job: mine.id})
    unmatched = sync_repo._match_project_id([{"job": job}], {})

    assert matched == mine.id
    assert unmatched is None


# --- reads are filtered ------------------------------------------------------------------------


def test_the_project_picker_shows_only_the_callers_company(db_session, two_companies):
    rows = project_repository.list_projects_with_opening_counts(db_session, company="TUBC")
    ids = {p.id for p, _count in rows}

    assert two_companies["mine"].id in ids
    assert two_companies["theirs"].id not in ids


def test_an_admin_sees_every_company(db_session, two_companies):
    rows = project_repository.list_projects_with_opening_counts(db_session, company=None)
    ids = {p.id for p, _count in rows}

    assert {two_companies["mine"].id, two_companies["theirs"].id} <= ids


def test_purchase_orders_are_filtered_by_company(db_session, two_companies):
    ids = {po.id for po in po_repository.get_purchase_orders(db_session, company="TUBC")}

    assert two_companies["my_po"].id in ids
    assert two_companies["their_po"].id not in ids


def test_the_register_page_is_filtered_by_company(db_session, two_companies):
    rows, _counts, total = po_repository.get_purchase_orders_page(db_session, company="TUBC", limit=200)
    ids = {r.id for r in rows}

    assert two_companies["my_po"].id in ids
    assert two_companies["their_po"].id not in ids
    # The paged total is the count of the SAME filtered set, not of the whole register - a total that
    # counted every company's rows would make the pager offer pages the caller cannot see.
    assert total == len(rows)


def test_warehouses_are_filtered_by_company(db_session, two_companies):
    ids = {w.id for w in warehouse_admin_repository.list_warehouses(db_session, company="TUBC")}

    assert two_companies["my_warehouse"] in ids
    assert two_companies["their_warehouse"] not in ids


def test_an_empty_warehouse_can_be_moved_to_another_company(db_session, two_companies):
    """The admin Warehouses page edits the company like any other field, and the move has to take
    effect on the scoped reads immediately - the building is the root everything in it scopes
    through. Empty is the only state in which it is allowed; see the refusal below."""
    warehouse_admin_repository.update_warehouse(db_session, two_companies["my_warehouse"], company="tfake")

    assert two_companies["my_warehouse"] not in {
        w.id for w in warehouse_admin_repository.list_warehouses(db_session, company="TUBC")
    }
    assert two_companies["my_warehouse"] in {
        w.id for w in warehouse_admin_repository.list_warehouses(db_session, company=OTHER)
    }


def test_an_occupied_warehouse_cannot_change_company(db_session, two_companies):
    """Everything in the building takes its tenant from the building, so a move re-tenants all of it
    at once - and the inventory in it belongs to projects of the OLD company, leaving rows whose
    project and warehouse disagree about whose they are. Refused, and the message names what is in
    the way rather than making somebody hunt for it."""
    _inventory(db_session, two_companies["mine"], two_companies["my_warehouse"])

    with pytest.raises(ValidationError) as e:
        warehouse_admin_repository.update_warehouse(db_session, two_companies["my_warehouse"], company=OTHER)

    assert e.value.field == "company"
    # `_inventory` puts one stock row and one inventory row in the building, and both are named.
    assert "1 stock item" in str(e.value)
    assert "1 inventory row" in str(e.value)


def test_a_receive_draft_alone_blocks_the_move(db_session, two_companies):
    """A counted-but-unapproved receive is against this building; approving it after a move would
    book the hardware into the wrong company."""
    from app.models.enums import ReceiveDraftStatus
    from app.models.receive_draft import ReceiveDraft

    db_session.add(
        ReceiveDraft(
            id=uuid.uuid4(),
            po_id=two_companies["my_po"].id,
            warehouse_id=two_companies["my_warehouse"],
            status=ReceiveDraftStatus.PENDING_APPROVAL,
            created_by_user_id="u_1",
            created_by_name="Wendy Warehouse",
        )
    )
    db_session.flush()

    with pytest.raises(ValidationError) as e:
        warehouse_admin_repository.update_warehouse(db_session, two_companies["my_warehouse"], company=OTHER)

    assert "1 receive draft" in str(e.value)


def test_a_defined_layout_alone_does_not_block_the_move(db_session, two_companies):
    """A rack is a description of the building, not something in it - an empty layout moves with the
    walls, so the registry is deliberately not part of the occupancy check."""
    from app.models.warehouse_location import WarehouseLocation

    db_session.add(
        WarehouseLocation(
            id=uuid.uuid4(),
            warehouse_id=two_companies["my_warehouse"],
            aisle="A",
            row="1",
            bay="1",
            active=True,
            created_at=datetime.utcnow(),
        )
    )
    db_session.flush()

    warehouse_admin_repository.update_warehouse(db_session, two_companies["my_warehouse"], company=OTHER)

    assert warehouse_admin_repository.get_warehouse(db_session, two_companies["my_warehouse"]).company == OTHER


def test_re_sending_the_company_it_already_has_is_never_a_move(db_session, two_companies):
    """The admin form round-trips every field on every save, so an occupied warehouse would become
    un-editable in any other respect if the guard fired on an unchanged company."""
    _inventory(db_session, two_companies["mine"], two_companies["my_warehouse"])

    warehouse_admin_repository.update_warehouse(
        db_session, two_companies["my_warehouse"], company="tubc", name="Renamed While Full"
    )

    updated = warehouse_admin_repository.get_warehouse(db_session, two_companies["my_warehouse"])
    assert updated.company == "TUBC"
    assert updated.name == "Renamed While Full"


def test_a_warehouse_update_that_names_no_company_leaves_it_alone(db_session, two_companies):
    """The column is NOT NULL - a building always belongs to somebody - so an omitted or blank
    company is "not sent" rather than a clear."""
    warehouse_admin_repository.update_warehouse(db_session, two_companies["my_warehouse"], name="Renamed")
    warehouse_admin_repository.update_warehouse(db_session, two_companies["my_warehouse"], company="   ")

    moved = warehouse_admin_repository.get_warehouse(db_session, two_companies["my_warehouse"])
    assert moved.company == "TUBC"
    assert moved.name == "Renamed"


def test_an_over_length_warehouse_company_is_refused(db_session, two_companies):
    with pytest.raises(ValidationError) as e:
        warehouse_admin_repository.update_warehouse(db_session, two_companies["my_warehouse"], company="A" * 16)
    assert e.value.field == "company"


def test_describe_occupancy_is_empty_for_an_empty_warehouse(db_session, two_companies):
    assert warehouse_admin_repository.describe_occupancy(db_session, two_companies["my_warehouse"]) == []


def test_the_primary_warehouse_fallback_stays_inside_the_company(db_session, two_companies):
    """`is_primary` is one global flag, so an unscoped fallback would book one company's delivery into
    another company's building."""
    picked = warehouse_admin_repository.get_primary_warehouse_id(db_session, company=OTHER)

    assert picked == two_companies["their_warehouse"]


def test_inventory_rows_are_filtered_through_their_project(db_session, two_companies):
    mine = _inventory(db_session, two_companies["mine"], two_companies["my_warehouse"])
    theirs = _inventory(db_session, two_companies["theirs"], two_companies["their_warehouse"])

    ids = {r["inventory_location"].id for r in warehouse_repository.get_inventory_rows(db_session, company="TUBC")}

    assert mine.id in ids
    assert theirs.id not in ids


def _inventory(session, project, warehouse_id, *, quantity=5) -> InventoryLocation:
    stock = StockItem(
        id=uuid.uuid4(),
        warehouse_id=warehouse_id,
        hardware_category="HINGE",
        product_code="HG-100",
        quantity=0,
        deficient_quantity=0,
        received_at=datetime.utcnow(),
    )
    session.add(stock)
    session.flush()
    il = InventoryLocation(
        id=uuid.uuid4(),
        project_id=project.id,
        stock_item_id=stock.id,
        warehouse_id=warehouse_id,
        hardware_category="HINGE",
        product_code="HG-100",
        quantity=quantity,
        deficient_quantity=0,
        aisle="A",
        row="1",
        bay="1",
        received_at=datetime.utcnow(),
    )
    session.add(il)
    session.flush()
    return il


def test_stock_is_filtered_through_its_warehouse(db_session, two_companies):
    """Stock is jobless by definition, so it has no project to scope through - the warehouse is what
    says whose it is."""
    mine = StockItem(
        id=uuid.uuid4(),
        warehouse_id=two_companies["my_warehouse"],
        hardware_category="HINGE",
        product_code=f"HG-{uuid.uuid4().hex[:6]}",
        quantity=3,
        deficient_quantity=0,
        received_at=datetime.utcnow(),
    )
    theirs = StockItem(
        id=uuid.uuid4(),
        warehouse_id=two_companies["their_warehouse"],
        hardware_category="HINGE",
        product_code=f"HG-{uuid.uuid4().hex[:6]}",
        quantity=3,
        deficient_quantity=0,
        received_at=datetime.utcnow(),
    )
    db_session.add_all([mine, theirs])
    db_session.flush()

    from app.repositories import stock as stock_repository

    ids = {si.id for si in stock_repository.get_stock_items(db_session, company="TUBC")}

    assert mine.id in ids
    assert theirs.id not in ids


def test_pull_requests_are_filtered_through_their_project(db_session, two_companies):
    mine = _pull(db_session, two_companies["mine"])
    theirs = _pull(db_session, two_companies["theirs"])

    ids = {pr.id for pr in warehouse_repository.get_pull_requests(db_session, company="TUBC")}

    assert mine.id in ids
    assert theirs.id not in ids


def _pull(session, project) -> PullRequest:
    pr = PullRequest(
        id=uuid.uuid4(),
        request_number=f"PR-{uuid.uuid4().hex[:8]}",
        project_id=project.id,
        source=PullRequestSource.SHIPPING_OUT,
        status=PullRequestStatus.PENDING,
        requested_by="tester",
    )
    session.add(pr)
    session.flush()
    return pr


def test_shipping_requests_are_filtered_through_their_project(db_session, two_companies):
    from app.repositories import shipping_repository

    mine = _shipping_request(db_session, two_companies["mine"])
    theirs = _shipping_request(db_session, two_companies["theirs"])

    ids = {r.id for r in shipping_repository.get_shipping_out_requests(db_session, company="TUBC")}

    assert mine.id in ids
    assert theirs.id not in ids


def _shipping_request(session, project) -> ShippingOutRequest:
    req = ShippingOutRequest(
        id=uuid.uuid4(),
        request_number=f"SO-{uuid.uuid4().hex[:8]}",
        project_id=project.id,
        status=ShippingOutRequestStatus.PENDING,
        created_by="tester",
    )
    session.add(req)
    session.flush()
    return req


def test_the_catalog_is_one_companys_own(db_session):
    """The seeded FRAME/SPECIALTY/CONSUMABLE types belong to TUBC, so a second company starts with an
    empty catalog rather than inheriting theirs."""
    mine = custom_items_repository.get_item_types(db_session, company="TUBC")
    theirs = custom_items_repository.get_item_types(db_session, company=OTHER)

    assert {t.code for t in mine} >= {"FRAME", "SPECIALTY", "CONSUMABLE"}
    assert theirs == []


def test_two_companies_can_define_the_same_type_code(db_session):
    """A globally unique code would make the second tenant's catalog unbuildable, not merely
    awkward - FRAME is exactly the code they would both want."""
    created = custom_items_repository.create_item_type(db_session, name="Frames", code="FRAME", company=OTHER)

    assert created.code == "FRAME"
    assert created.company == OTHER


def test_two_companies_can_run_the_same_shipment_method(db_session):
    a = shipment_method_repository.create_shipment_method(db_session, name="Our truck", company="TUBC")
    b = shipment_method_repository.create_shipment_method(db_session, name="Our truck", company=OTHER)

    assert a.id != b.id
    names = {m.name for m in shipment_method_repository.get_shipment_methods(db_session, company=OTHER)}
    assert names == {"Our truck"}


def test_one_company_still_cannot_spell_a_method_twice(db_session):
    from app.errors import ConflictError

    shipment_method_repository.create_shipment_method(db_session, name="Flatbed", company="TUBC")

    with pytest.raises(ConflictError):
        shipment_method_repository.create_shipment_method(db_session, name="flatbed", company="TUBC")


# --- writes are refused by id ------------------------------------------------------------------


def test_a_cross_company_row_reads_as_not_found_rather_than_forbidden(db_session, two_companies):
    """A forbidden answer confirms the row exists, which turns any id-taking field into an existence
    oracle. Out of scope reads exactly as absent."""
    with pytest.raises(NotFoundError):
        tenancy.require_project_in_scope(db_session, two_companies["theirs"].id, "TUBC")

    with pytest.raises(NotFoundError):
        tenancy.require_po_in_scope(db_session, two_companies["their_po"].id, "TUBC")

    with pytest.raises(NotFoundError):
        tenancy.require_warehouse_in_scope(db_session, two_companies["their_warehouse"], "TUBC")


def test_an_id_that_does_not_exist_at_all_reads_the_same_way(db_session):
    with pytest.raises(NotFoundError):
        tenancy.require_project_in_scope(db_session, uuid.uuid4(), "TUBC")


def test_the_callers_own_rows_pass_and_an_admin_passes_everything(db_session, two_companies):
    tenancy.require_project_in_scope(db_session, two_companies["mine"].id, "TUBC")
    tenancy.require_project_in_scope(db_session, two_companies["theirs"].id, None)


def test_a_null_project_is_not_a_scope_failure(db_session):
    """A stock PO, a jobless receive and an unscoped location read all legitimately have no project."""
    tenancy.require_project_in_scope(db_session, None, "TUBC")


def test_a_stock_po_takes_the_callers_company(db_session):
    po = po_repository.create_po(
        db_session,
        line_items=[{"hardware_category": "HINGE", "product_code": "HG-100", "ordered_quantity": 1, "unit_cost": 1.0}],
        company=OTHER,
    )

    assert po.company == OTHER
    assert po.project_id is None


def test_the_import_wizard_stamps_the_projects_company_on_every_draft_it_raises(db_session, two_companies):
    """The wizard's finalize builds its draft POs directly rather than through `create_po`, so it is
    its own place where the tenant has to be stamped - and it was the one path that missed it, which
    only showed up as a NOT NULL violation against a real database."""
    from sqlalchemy import select

    from app.repositories import import_repository

    project = two_companies["theirs"]
    import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [{"opening_number": "A01"}],
            "hardware_items": [
                {
                    "opening_number": "A01",
                    "product_code": "HG-100",
                    "hardware_category": "HINGE",
                    "item_quantity": 1,
                }
            ],
            "po_drafts": [
                {
                    "po_number": None,
                    "notes": None,
                    "hardware_item_refs": [
                        {"opening_number": "A01", "product_code": "HG-100", "hardware_category": "HINGE"}
                    ],
                    "line_item_aliases": [],
                }
            ],
        },
    )
    db_session.flush()

    raised = db_session.scalars(select(PurchaseOrder).where(PurchaseOrder.project_id == project.id)).all()
    assert raised, "the wizard raised no draft to check"
    # The PROJECT's company, not a default and not the caller's - a PO and its job are one tenant.
    assert {po.company for po in raised} == {OTHER}


def test_a_project_po_takes_the_projects_company_whatever_was_asked_for(db_session, two_companies):
    """A PO and the job it is raised against cannot belong to different tenants, so the project wins."""
    po = po_repository.create_po(
        db_session,
        line_items=[{"hardware_category": "HINGE", "product_code": "HG-100", "ordered_quantity": 1, "unit_cost": 1.0}],
        project_id=two_companies["theirs"].id,
        company="TUBC",
    )

    assert po.company == OTHER


def test_registering_a_po_into_another_companys_gp_is_refused(db_session, two_companies):
    po = po_repository.create_po(
        db_session,
        line_items=[{"hardware_category": "HINGE", "product_code": "HG-100", "ordered_quantity": 1, "unit_cost": 1.0}],
        company="TUBC",
    )

    with pytest.raises(ValidationError) as e:
        po_repository.register_po_in_gp(
            db_session,
            po.id,
            gp_vendor_id="V1",
            vendor_name_snapshot="Acme",
            po_number=f"PO-{uuid.uuid4().hex[:6]}",
            gp_company=OTHER,
            line_items=[
                {"hardware_category": "HINGE", "product_code": "HG-100", "ordered_quantity": 1, "unit_cost": 1.0}
            ],
        )
    assert e.value.field == "gp_company"


def test_a_stock_draft_cannot_adopt_another_companys_project(db_session, two_companies):
    po = po_repository.create_po(
        db_session,
        line_items=[{"hardware_category": "HINGE", "product_code": "HG-100", "ordered_quantity": 1, "unit_cost": 1.0}],
        company="TUBC",
    )

    with pytest.raises(ValidationError) as e:
        po_repository.register_po_in_gp(
            db_session,
            po.id,
            gp_vendor_id="V1",
            vendor_name_snapshot="Acme",
            po_number=f"PO-{uuid.uuid4().hex[:6]}",
            gp_company="TUBC",
            line_items=[
                {"hardware_category": "HINGE", "product_code": "HG-100", "ordered_quantity": 1, "unit_cost": 1.0}
            ],
            project_id=two_companies["theirs"].id,
        )
    assert e.value.field == "project_id"


# --- archive ------------------------------------------------------------------------------------


def test_an_archived_project_leaves_the_picker_and_stays_on_the_admin_list(db_session):
    live = _project(db_session, "TUBC")
    retired = _project(db_session, "TUBC")

    project_repository.set_project_archived(db_session, retired.id, True)

    picker = {p.id for p, _ in project_repository.list_projects_with_opening_counts(db_session, include_archived=False)}
    admin = {p.id for p, _ in project_repository.list_projects_with_opening_counts(db_session, include_archived=True)}

    assert live.id in picker
    assert retired.id not in picker
    assert {live.id, retired.id} <= admin


def test_archiving_is_reversible(db_session):
    project = _project(db_session, "TUBC", archived=True)

    project_repository.set_project_archived(db_session, project.id, False)

    picker = {p.id for p, _ in project_repository.list_projects_with_opening_counts(db_session, include_archived=False)}
    assert project.id in picker


# --- the admin project detail --------------------------------------------------------------------


def test_the_admin_detail_counts_pos_by_status_inventory_and_open_requests(db_session, two_companies):
    project = two_companies["mine"]
    warehouse = two_companies["my_warehouse"]

    _po(db_session, "TUBC", project=project, status=POStatus.GP_REGISTERED)
    _po(db_session, "TUBC", project=project, status=POStatus.CLOSED)
    _inventory(db_session, project, warehouse, quantity=7)
    _inventory(db_session, project, warehouse, quantity=3)
    _shipping_request(db_session, project)

    detail = project_repository.get_admin_project_detail(db_session, project.id)

    counts = dict(detail["po_counts_by_status"])
    # The fixture's own PO is GP_REGISTERED too, so that status carries two.
    assert counts[POStatus.GP_REGISTERED] == 2
    assert counts[POStatus.CLOSED] == 1
    assert detail["inventory_on_hand"] == 10
    assert detail["open_shipping_request_count"] == 1


def test_a_rejected_request_is_not_open(db_session, two_companies):
    project = two_companies["mine"]
    req = _shipping_request(db_session, project)
    req.status = ShippingOutRequestStatus.REJECTED
    db_session.flush()

    detail = project_repository.get_admin_project_detail(db_session, project.id)

    assert detail["open_shipping_request_count"] == 0


def test_a_request_whose_pull_is_finished_is_not_open(db_session, two_companies):
    """Counting every accepted request forever would make the number grow and say nothing about what
    is still in flight."""
    project = two_companies["mine"]
    pull = _pull(db_session, project)
    pull.status = PullRequestStatus.COMPLETED
    req = _shipping_request(db_session, project)
    req.status = ShippingOutRequestStatus.APPROVED
    req.pull_request_id = pull.id
    db_session.flush()

    detail = project_repository.get_admin_project_detail(db_session, project.id)

    assert detail["open_shipping_request_count"] == 0


def test_a_soft_deleted_po_is_not_counted(db_session, two_companies):
    project = two_companies["mine"]
    cancelled = _po(db_session, "TUBC", project=project, status=POStatus.CANCELLED)
    cancelled.deleted_at = datetime.utcnow()
    db_session.flush()

    detail = project_repository.get_admin_project_detail(db_session, project.id)

    assert POStatus.CANCELLED not in dict(detail["po_counts_by_status"])


def test_the_detail_is_none_for_a_project_that_does_not_exist(db_session):
    assert project_repository.get_admin_project_detail(db_session, uuid.uuid4()) is None


# --- a line item is scoped through its PO --------------------------------------------------------


def test_a_po_line_item_is_scoped_through_its_purchase_order(db_session, two_companies):
    line = POLineItem(
        id=uuid.uuid4(),
        po_id=two_companies["their_po"].id,
        hardware_category="HINGE",
        product_code="HG-100",
        ordered_quantity=1,
        received_quantity=0,
        unit_cost=Decimal("1.00"),
    )
    db_session.add(line)
    db_session.flush()

    with pytest.raises(NotFoundError):
        tenancy.require_po_line_item_in_scope(db_session, line.id, "TUBC")
    tenancy.require_po_line_item_in_scope(db_session, line.id, OTHER)
