"""The demo built as a copy of UBC (#1657), from a made-up company standing in for UBC.

Nothing real is in here: the company is `MIRR`, made up for these tests, with the made-up legacy list of
tests/test_demo_inventory_snapshot.py. It has one job for each thing the build decides:

  T-100  inactive in GP, holds door hardware        -> a project; its hardware to the pool, a made-up schedule
  T-200  active, holds door hardware, has a schedule -> a project with its own schedule, not a made-up one
  T-300  inactive, holds specialties and a hinge    -> a project holding all of it (a specialties job)
  T-400  active, holds nothing, has an open PO      -> a project, the PO copied onto it
  T-500  inactive, holds nothing                    -> not a project

and the GP masters the relay read, an open PO and a closed one. The build runs from those as it runs from
UBC, and then the nightly sync adds a job that turned active.
"""

import asyncio
from decimal import Decimal

import pytest
from sqlalchemy import select, text

from app.auth import NEXUS_ADMIN_ROLE
from app.demo import DEMO_COMPANY
from app.errors import RelayCallError
from app.models.enums import GpJobState, POOrigin, POStatus
from app.repositories import user_repository
from app.services import demo_gp, demo_snapshot

# The real read, kept before the module's fixture stands a no-op in for it.
from app.services.demo_mirror import refresh_gp_masters as _refresh_gp_masters
from tests.test_demo_inventory_snapshot import list_items

MIRR = "MIRR"

_MASTERS = {
    "vendors": [
        {
            "vendor_id": "MVEND",
            "vendor_name": "Mirror Hardware Supply",
            "vendor_class": "HARDWARE",
            "currency": "CAD",
            "contact": "Pat Supplier",
            "email": "orders@mirror-supply.example.com",
        }
    ],
    "vendor_addresses": {
        "MVEND": [
            {
                "code": "MAIN",
                "contact": "Pat Supplier",
                "address1": "5 Mirror Road",
                "address2": None,
                "address3": None,
                "city": "Oakville",
                "state": "ON",
                "postal_code": "L6H 0A1",
                "country": "Canada",
                "phone": None,
            }
        ]
    },
    "customers": [{"customer_number": "MCUST", "customer_name": "Mirror Builders"}],
    "divisions": ["MIRRDIV"],
    "cost_code_master": {"MIRRDIV": [{"cost_code": "300-100", "description": "Hardware", "cost_element": 2}]},
}

_ADMIN = {
    "request": None,
    "_auth_user_id": "u_admin",
    "_auth_roles": [NEXUS_ADMIN_ROLE],
    "_auth_company": None,
}


def _run(document: str, context: dict, **variables):
    from main import schema

    return asyncio.run(schema.execute(document, variable_values=variables, context_value=context))


def _project(session, number: str, state: GpJobState | None):
    from app.models.project import Project

    project = Project(
        company=MIRR,
        project_id=number,
        description=f"Mirror {number}",
        gp_job_state=state,
        customer_number="MCUST",
        client="Mirror Builders",
        division="MIRRDIV",
        city="Oakville",
    )
    session.add(project)
    session.flush()
    return project


def _po(session, project, number: str, status: POStatus, lines: list[tuple]) -> None:
    from app.models.purchase_order import POLineItem, PurchaseOrder

    po = PurchaseOrder(
        company=MIRR,
        gp_company=MIRR,
        po_number=number,
        origin=POOrigin.GP,
        status=status,
        project_id=project.id,
        gp_vendor_id="MVEND",
        vendor_name_snapshot="Mirror Hardware Supply",
    )
    session.add(po)
    session.flush()
    for n, (category, code, ordered, received) in enumerate(lines, start=1):
        session.add(
            POLineItem(
                po_id=po.id,
                hardware_category=category,
                product_code=code,
                ordered_quantity=ordered,
                received_quantity=received,
                unit_cost=Decimal("12.50"),
                gp_line_ord=16384 * n,
                job_cost=True,
                cost_code="300-100-2",
            )
        )
    session.flush()


def _wipe_mirr() -> None:
    """Every MIRR row and what hangs off it, by the demo wipe's own walk pointed at MIRR."""
    from app.database import SessionLocal
    from app.services import demo_reset

    with pytest.MonkeyPatch.context() as mp, SessionLocal() as session:
        mp.setattr(demo_reset, "DEMO_COMPANY", MIRR)
        mp.setattr(demo_reset.demo_gp, "wipe", lambda session: 0)
        demo_reset.wipe(session)
        session.commit()


@pytest.fixture(scope="module")
def mirrored(_migrate_database):
    """MIRR set up as UBC is, the demo built from it, and everything put back afterwards - the legacy list
    and the mirror state this database had stored included."""
    from app.auth import remember_display_name
    from app.database import SessionLocal
    from app.models.demo_inventory_snapshot import DemoInventorySnapshot
    from app.models.demo_mirror_state import DemoMirrorState
    from app.repositories import demo_mirror_state_repository as state
    from app.repositories import demo_snapshot_repository
    from app.services import demo_mirror, demo_reset, storage

    kept_tables = (DemoInventorySnapshot.__table__, DemoMirrorState.__table__)
    with SessionLocal() as session:
        kept = {t.name: [dict(r._mapping) for r in session.execute(t.select())] for t in kept_tables}
    remember_display_name(_ADMIN["_auth_user_id"], "Test Admin")
    _wipe_mirr()

    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("DEMO_SOURCE", "ubc")
        mp.setattr(demo_mirror, "MIRROR_COMPANY", MIRR)
        mp.setattr(user_repository, "get_user_demo_mode", lambda user_id: False)
        mp.setattr(storage, "upload_file", lambda key, data, content_type, **kw: key)
        mp.setattr(storage, "delete_file", lambda key: None)

        async def _no_reads():
            return {"list": None, "masters": None}

        async def _no_read():
            return None

        # SharePoint and the relay are not here; what they last returned is stored below.
        mp.setattr(demo_mirror, "refresh_sources", _no_reads)
        mp.setattr(demo_mirror, "refresh_legacy_list", _no_read)
        mp.setattr(demo_mirror, "refresh_gp_masters", _no_read)

        with SessionLocal() as session:
            for table in kept_tables:
                session.execute(table.delete())
            demo_snapshot_repository.store(
                session,
                file_name=demo_mirror.LEGACY_LIST_NAME,
                rows=demo_snapshot.parse_list_items(list_items()),
                uploaded_by=demo_mirror.LEGACY_LIST_READER,
            )
            state.put(session, state.GP_MASTERS, {"masters": _MASTERS, "read_at": "2026-10-15T06:00:00"})
            _project(session, "T-100", GpJobState.INACTIVE)
            t200 = _project(session, "T-200", GpJobState.ACTIVE)
            _project(session, "T-300", GpJobState.INACTIVE)
            t400 = _project(session, "T-400", GpJobState.ACTIVE)
            _project(session, "T-500", GpJobState.INACTIVE)
            _po(
                session,
                t400,
                "MPO-OPEN",
                POStatus.PARTIALLY_RECEIVED,
                [("HINGE", "HNG X", 10, 4), ("STOP", "ST Y", 5, 0)],
            )
            _po(session, t400, "MPO-DONE", POStatus.CLOSED, [("HINGE", "HNG X", 2, 2)])
            # Open with no lines: the PO mirror skips such a read, and so does the copy.
            _po(session, t400, "MPO-EMPTY", POStatus.GP_REGISTERED, [])
            session.commit()
            t200_id = str(t200.id)

        # T-200's own schedule, imported as MIRR imports one.
        acting = {**_ADMIN, "_auth_acting_company": MIRR}
        result = _run(
            "mutation F($input: FinalizeImportSessionInput!) "
            "{ finalizeImportSession(input: $input) { purchaseOrders { id } } }",
            acting,
            input={
                "projectId": t200_id,
                "openings": [{"openingNumber": "CL-01", "building": "Clinic", "floor": "1", "leafCount": 1}],
                "hardwareItems": [
                    {
                        "openingNumber": "CL-01",
                        "productCode": "HNG 4.5 US26D",
                        "hardwareCategory": "HINGE",
                        "itemQuantity": 3,
                    }
                ],
                "scheduleFilename": "clinic.xml",
            },
        )
        assert result.errors is None, result.errors

        asyncio.run(demo_reset.reset())
        yield mp
        with SessionLocal() as session:
            demo_reset.wipe(session)
            for table in kept_tables:
                session.execute(table.delete())
                if kept[table.name]:
                    session.execute(table.insert(), kept[table.name])
            session.commit()
    _wipe_mirr()


def _scalar(sql: str, **params):
    from app.database import SessionLocal

    with SessionLocal() as session:
        return session.execute(text(sql), params).all()


def _demo_projects() -> set[str]:
    return {r[0] for r in _scalar("SELECT project_id FROM projects WHERE company = :c", c=DEMO_COMPANY)}


def test_the_projects_are_the_jobs_active_in_gp_or_holding_stock(mirrored):
    # Ruled on #1657. T-100 and T-300 are inactive in GP and still hold stock; T-500 holds nothing.
    assert _demo_projects() == {"T-100", "T-200", "T-300", "T-400"}


def test_a_project_carries_its_job_as_gp_has_it(mirrored):
    from app.database import SessionLocal
    from app.models.project import Project

    with SessionLocal() as session:
        t100 = session.scalars(
            select(Project).where(Project.company == DEMO_COMPANY, Project.project_id == "T-100")
        ).one()
        assert (t100.description, t100.gp_job_state, t100.customer_number) == (
            "Mirror T-100",
            GpJobState.INACTIVE,
            "MCUST",
        )


def test_a_specialties_job_holds_everything_and_the_pool_the_rest(mirrored):
    on_projects = dict(
        _scalar(
            "SELECT p.project_id || ':' || i.product_code, sum(i.quantity) FROM inventory_locations i "
            "JOIN projects p ON p.id = i.project_id WHERE p.company = :c GROUP BY 1",
            c=DEMO_COMPANY,
        )
    )
    pool = dict(
        _scalar(
            "SELECT s.product_code, sum(s.quantity) FROM stock_items s JOIN warehouses w ON w.id = s.warehouse_id "
            "WHERE w.company = :c AND s.kind = 'STOCK' GROUP BY 1",
            c=DEMO_COMPANY,
        )
    )
    # T-300 holds specialties, so its hinge is its own too (ruled on #1657).
    assert on_projects == {"T-300:GRAB BAR 36": 7, "T-300:HNG 4.5 US26D": 3}
    assert pool["HNG 4.5 US26D"] == 6 + 3 and pool["CYL 1E74"] == 1000 and pool["MIRROR 24X36"] == 2


def test_a_job_with_its_own_schedule_keeps_it_and_the_others_get_one_made_up(mirrored):
    rows = _scalar(
        "SELECT p.project_id, o.opening_number FROM openings o JOIN projects p ON p.id = o.project_id "
        "WHERE p.company = :c",
        c=DEMO_COMPANY,
    )
    openings: dict[str, set] = {}
    for project, opening in rows:
        openings.setdefault(project, set()).add(opening)
    assert openings["T-200"] == {"CL-01"}  # MIRR's own, not one made up from the list
    assert "001" in openings["T-100"] and "001" in openings["T-300"]
    assert "T-400" not in openings  # nothing on the list to make one from


def test_the_open_po_is_copied_onto_its_job_and_the_closed_and_empty_ones_are_not(mirrored):
    pos = _scalar(
        "SELECT po.po_number, po.status, p.project_id, li.gp_line_ord, li.ordered_quantity, li.received_quantity "
        "FROM purchase_orders po JOIN po_line_items li ON li.po_id = po.id "
        "LEFT JOIN projects p ON p.id = po.project_id WHERE po.company = :c ORDER BY li.gp_line_ord",
        c=DEMO_COMPANY,
    )
    assert [tuple(r) for r in pos] == [
        ("MPO-OPEN", "PARTIALLY_RECEIVED", "T-400", 16384, 10, 4),
        ("MPO-OPEN", "PARTIALLY_RECEIVED", "T-400", 32768, 5, 0),
    ]


def test_the_copied_po_is_received_on_from_where_gp_had_it(mirrored):
    # The simulated GP knows what GP had received before the copy: six more of the ten, and no more.
    with pytest.raises(RelayCallError, match="still to receive"):
        demo_gp.call_sync("create_receipt", {"po_number": "MPO-OPEN", "lines": [{"po_line_ord": 16384, "quantity": 7}]})
    demo_gp.call_sync("create_receipt", {"po_number": "MPO-OPEN", "lines": [{"po_line_ord": 16384, "quantity": 6}]})
    po = demo_gp.call_sync("read_pos_by_number", {"po_numbers": ["MPO-OPEN"]})["pos"][0]
    assert [ln["received"] for ln in po["lines"]] == [10.0, 0.0]


def test_the_simulated_gp_answers_with_the_masters_read_from_gp(mirrored):
    vendors = demo_gp.call_sync("list_vendors", {})["vendors"]
    assert [v["vendor_id"] for v in vendors] == ["MVEND"]
    contact = demo_gp.call_sync("get_vendor_contact", {"vendor_id": "MVEND"})
    assert contact["email"] == "orders@mirror-supply.example.com"
    assert demo_gp.call_sync("list_vendor_addresses", {"vendor_id": "MVEND"})["addresses"][0]["code"] == "MAIN"
    codes = demo_gp.call_sync("list_cost_codes", {"job": "T-100"})["cost_codes"]
    assert [c["cost_code"] for c in codes] == ["300-100"]
    # The demo buyer everybody registers as is always there.
    assert "DEMOBUYER" in demo_gp.call_sync("list_buyers", {})["buyers"]
    # A vendor GP does not have is refused, as GP refuses one.
    with pytest.raises(RelayCallError):
        demo_gp.call_sync("get_vendor_contact", {"vendor_id": "DEMOHAGER"})


def test_an_admin_sees_what_the_demo_is_built_from(mirrored):
    result = _run(
        "{ demoMirror { source legacyRows vendorCount projectCount specialtiesProjectCount projectUnits poolUnits"
        " openPoCount demoProjectCount building } }",
        dict(_ADMIN),
    )
    assert result.errors is None, result.errors
    status = result.data["demoMirror"]
    assert status == {
        "source": "ubc",
        "legacyRows": 14,
        "vendorCount": 1,
        "projectCount": 4,
        "specialtiesProjectCount": 1,
        "projectUnits": 7 + 3,
        "poolUnits": 6 + 3 + 3 + 3 + 2 + 1 + 1000 + 2 + 3 + 12 + 5,
        "openPoCount": 1,
        "demoProjectCount": 4,
        "building": False,
    }


def test_the_status_counts_what_the_build_reads_without_reading_a_schedule(mirrored, monkeypatch):
    # #1833: the status is polled every few seconds while a build runs, and only counts. It reads the summary
    # source - no schedule, no PO line - and that counts the same jobs, POs and vendors the build reads.
    from app.database import SessionLocal
    from app.services import demo_mirror

    with SessionLocal() as session:
        full = demo_mirror.load_source(session)
        summary = demo_mirror.load_source(session, summary=True)
    assert (summary.jobs, summary.rows, summary.masters) == (full.jobs, full.rows, full.masters)
    assert [(p["po_number"], p["vendor_id"], p["vendor_name"]) for p in summary.open_pos] == [
        (p["po_number"], p["vendor_id"], p["vendor_name"]) for p in full.open_pos
    ]
    assert "T-200" in full.schedules and summary.schedules == {}

    def _refused(*args, **kwargs):
        raise AssertionError("the status read a schedule")

    monkeypatch.setattr(demo_mirror, "_schedules", _refused)
    monkeypatch.setattr(demo_mirror.import_repository, "get_project_hardware_schedule", _refused)
    result = _run("{ demoMirror { legacyRows vendorCount projectCount openPoCount } }", dict(_ADMIN))
    assert result.errors is None, result.errors
    assert result.data["demoMirror"] == {"legacyRows": 14, "vendorCount": 1, "projectCount": 4, "openPoCount": 1}


def test_only_an_admin_sees_or_rebuilds_the_demo(mirrored):
    owner = {"request": None, "_auth_user_id": "u_owner", "_auth_roles": ["Tenant Owner"], "_auth_company": "UBC"}
    for document in ("{ demoMirror { source } }", "mutation { rebuildDemo { building } }"):
        result = _run(document, owner)
        assert result.errors, document


def test_a_rebuild_is_refused_while_one_runs(mirrored, monkeypatch):
    from app.services import demo_build

    monkeypatch.setattr(demo_build, "building", lambda: True)
    result = _run("mutation { rebuildDemo { building } }", dict(_ADMIN))
    assert result.errors and "being built" in result.errors[0].message


def test_switching_on_again_does_not_rebuild(mirrored, monkeypatch):
    from app.services import demo_build, demo_reset

    async def _never(**kw):
        pytest.fail("a built demo is not rebuilt by switching on")

    monkeypatch.setattr(demo_reset, "reset", _never)
    asyncio.run(demo_build.ensure_built("u_someone"))


def test_masters_read_after_the_build_reach_the_demo_there_is(mirrored, monkeypatch):
    # #1657: the masters read is paced behind every other GP read, so a build does not wait on it; what
    # it brings back is answered with from then on, the copied POs' vendors kept.
    from app.services import demo_mirror

    fresh = {**_MASTERS, "vendors": _MASTERS["vendors"] + [{"vendor_id": "MNEW", "vendor_name": "New Vendor"}]}

    async def _read():
        return fresh

    monkeypatch.setattr(demo_mirror, "read_gp_masters", _read)
    assert asyncio.run(_refresh_gp_masters()) is None
    vendors = {v["vendor_id"] for v in demo_gp.call_sync("list_vendors", {})["vendors"]}
    assert vendors == {"MVEND", "MNEW"}


def test_the_nightly_sync_adds_a_job_that_turned_active_and_nothing_else(mirrored):
    # Last: it changes what the tests above read.
    from app.database import SessionLocal
    from app.models.project import Project
    from app.services import demo_build

    with SessionLocal() as session:
        t500 = session.scalars(select(Project).where(Project.company == MIRR, Project.project_id == "T-500")).one()
        t500.gp_job_state = GpJobState.ACTIVE
        session.commit()
    pos_before = _scalar("SELECT count(*) FROM purchase_orders WHERE company = :c", c=DEMO_COMPANY)
    stock_before = _scalar(
        "SELECT sum(s.quantity) FROM stock_items s JOIN warehouses w ON w.id = s.warehouse_id WHERE w.company = :c",
        c=DEMO_COMPANY,
    )

    added = asyncio.run(demo_build.nightly())

    assert added["projects_added"] == ["T-500"]
    assert _demo_projects() == {"T-100", "T-200", "T-300", "T-400", "T-500"}
    assert _scalar("SELECT count(*) FROM purchase_orders WHERE company = :c", c=DEMO_COMPANY) == pos_before
    assert (
        _scalar(
            "SELECT sum(s.quantity) FROM stock_items s JOIN warehouses w ON w.id = s.warehouse_id WHERE w.company = :c",
            c=DEMO_COMPANY,
        )
        == stock_before
    )
    # Again: nothing new, nothing added.
    assert asyncio.run(demo_build.nightly())["projects_added"] == []


def test_a_vendor_whose_contact_gp_cannot_read_keeps_the_rest_of_the_read(monkeypatch):
    # #1657: the contact read refused on UBC's GP for every vendor; that cost the whole read of the masters.
    from app.services import demo_mirror, gp_load

    source = demo_mirror.Source(
        name="ubc",
        jobs=[{"job_number": "T-1", "customer_number": "MCUST"}],
        rows=[],
        masters={},
        open_pos=[{"po_number": "P1", "vendor_id": "MVEND"}],
    )
    monkeypatch.setattr(demo_mirror, "ubc_source", lambda session, **kw: source)
    answers = {
        "list_vendors": {
            "vendors": [{"vendor_id": "MVEND", "vendor_name": "Mirror Hardware Supply", "contact": "Pat"}]
        },
        "list_vendor_addresses": {"addresses": [{"code": "MAIN"}]},
        "list_divisions": {"divisions": ["MIRRDIV"]},
    }

    async def _call(company, op, payload=None, *, reads, **kw):
        if op in ("get_vendor_contact", "list_customer_addresses"):
            raise RelayCallError("Argument data type text is invalid for argument 1 of rtrim function.")
        return {"result": answers.get(op, {})}

    monkeypatch.setattr(gp_load, "paced_call", _call)
    masters = asyncio.run(demo_mirror.read_gp_masters())
    assert masters["vendors"] == [
        {"vendor_id": "MVEND", "vendor_name": "Mirror Hardware Supply", "contact": "Pat", "email": None}
    ]
    assert masters["vendor_addresses"] == {"MVEND": [{"code": "MAIN"}]}
    assert masters["customer_addresses"] == {"MCUST": []}
