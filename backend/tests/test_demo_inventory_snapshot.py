"""The legacy inventory snapshot the demo warehouse is seeded from (#1638).

The export below is made up: the real one is the company's own data and never enters this repository. It
has the real export's header and one row for each thing the seed decides - where a row's units go, what
location a legacy location string becomes, which projects are jobs, what a made-up schedule asks for.

Two groups: the pure rules (no database), then a demo reset seeded from a stored snapshot.
"""

import asyncio

import pytest
from sqlalchemy import text

from app.demo import DEMO_COMPANY
from app.services import demo_snapshot as ds

_HEADER = (
    "Scheduled Part Number (Hardware Schedule Key value),Part Number (Order As),Project Number,Project Name,"
    "PO Number,Locations,Project Inventory Qty,Non Stock Qty,Staged Qty,Shipped Qty,Notes,Stock Qty,Ordered Qty,"
    "Received Qty,Last Checked,Inventory Type,Inventory Type 2,Finish,Part Category 1,Supplier,Manufacturer,Brand,"
    "Line,Order,Created,Created By,Project_Number,Project_Number:Project Name"
)
# key, order-as, project number, project name, location, project qty, non stock, staged, shipped, stock,
# ordered, received, inventory type, finish, part category
_ROWS = [
    # Tower: door hardware held for the job, now all to the pool; one still on order; one never scheduled.
    ("HNG 4.5 US26D", "HNG 45 26D", "T-100", "Test Tower", "K-17R", 6, 0, 2, 4, 0, 6, 6, "Door Hardware", "", "Hinge"),
    ("CLS 4040 AL", "4040XP AL", "T-100", "Test Tower", "F-40", 2, 1, 0, 0, 0, 5, 3, "Door Hardware", "", "Closer"),
    ("EXT 98 26D", "98L 26D", "T-100", "Test Tower", "", 0, 0, 0, 0, 0, 2, 0, "Door Hardware", "", "Exit Device"),
    ("", "SCREW PACK", "T-100", "Test Tower", "F-54L 01", 3, 0, 0, 0, 0, 0, 0, "Door Hardware", "", "Fastener"),
    # A second job sharing a code with the first: the pool row is one product.
    ("HNG 4.5 US26D", "HNG 45 26D", "T-200", "Test Clinic", "K-17R", 3, 0, 0, 0, 0, 3, 3, "", "", "Hinge"),
    # Specialties on a job go to it, all on hand; with no real job they go to the pool.
    ("", "GRAB BAR 36", "T-300", "Test Washrooms", "NS-K", 4, 1, 0, 0, 2, 7, 7, "Specialties", "Satin", "Grab Bar"),
    ("", "MIRROR 24X36", "Unknown", "Unknown", "IS A-4", 2, 0, 0, 0, 0, 2, 2, "Specialties", "", "Mirror"),
    ("", "DISPENSER", "RTLORD-1", "Retail Order", "Warehouse Overflow", 1, 0, 0, 0, 0, 1, 1, "Specialties", "", ""),
    # The company's own stock, and the other non-schedule kinds.
    (
        "CYL 1E74",
        "1E74 626",
        "BCS",
        "Warehouse Stock",
        "G-22L - Blue Stand Up Rack",
        0,
        0,
        0,
        0,
        1000,
        0,
        0,
        "Door Hardware",
        "",
        "Cylinder",
    ),
    ("", "HM DOOR 3070", "", "", "With Somebody", 0, 2, 0, 0, 0, 0, 0, "Door", "", "Door"),
    ("", "FRAME 3070 16GA", "", "", "F-59, F-44", 0, 0, 0, 0, 3, 0, 0, "Frame", "", "Frame"),
    ("", "SILICONE", "", "", "Coast rack H under non stock", 0, 0, 0, 0, 12, 0, 0, "Consumable", "", "Sealant"),
    # A shelf the made-up warehouse already defines: A-1 02 is A / 1 / 2.
    ("", "KICK PLATE 34", "", "", "A-1 02", 0, 0, 0, 0, 5, 0, 0, "Door Hardware", "", "Kick Plate"),
    # Nothing on hand and nothing on order: dropped.
    ("OLD 1", "OLD 1", "T-100", "Test Tower", "K-1R", 0, 0, 0, 9, 0, 9, 9, "Door Hardware", "", "Hinge"),
]


def _csv() -> str:
    lines = [_HEADER]
    for row in _ROWS:
        key, order_as, number, name, loc, proj, non_stock, staged, shipped, stock, ordered, received = row[:12]
        kind, finish, cat = row[12:]
        cells = [key, order_as, number, name, "PO1", loc, proj, non_stock, staged, shipped, "a note", stock, ordered]
        cells += [received, "10/5/2026", kind, "", finish, cat, "Vendor", "Maker", "Brand", "", "", "4/17/2026 14:46"]
        cells += ["Somebody Real", "", ""]
        lines.append(",".join(f'"{c}"' if isinstance(c, str) and ("," in c) else str(c) for c in cells))
    # A quantity the export writes with a thousands separator.
    lines[9] = lines[9].replace(",1000,", ',"1,000",')
    return "\n".join(lines) + "\n"


@pytest.fixture(scope="module")
def rows() -> list[ds.SnapshotRow]:
    return ds.parse_csv(_csv())


# --- the rules ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, location",
    [
        ("K-17R", ("K", "17", "R")),
        ("G8R", ("G", "8", "R")),
        ("F-75-L", ("F", "75", "L")),
        ("F-40", ("F", "40", "-")),
        ("F-54L 01", ("F", "54", "L1")),
        ("F-54R(3)", ("F", "54", "R3")),
        ("G-22L - Blue Stand Up Rack", ("G", "22", "L")),
        ("NS-K", ("NS", "K", "-")),
        ("Stock-DL", ("STOCK", "DL", "-")),
        ("IS A-4", ("IS", "A", "4")),
        ("IS-B-3", ("IS", "B", "3")),
        ("SSR", ("SSR", "-", "-")),
        ("Warehouse Overflow", ("WAREHOUSE OVERFLOW", "-", "-")),
        ("Coast rack H under non stock", ("COAST RACK H UNDER", "-", "-")),
        ("F-59, F-44", ("F", "59", "-")),
        ("With Somebody", None),
        ("Somebody's Office", None),
        ("", None),
    ],
)
def test_a_legacy_location_becomes_a_registry_location(raw, location):
    assert ds.location_for(raw) == location


def test_only_what_the_seed_reads_is_kept(rows):
    assert {r.product_code for r in rows} >= {"HNG 4.5 US26D", "SCREW PACK", "CYL 1E74"}
    assert "OLD 1" not in {r.product_code for r in rows}
    stored = rows[0].to_dict()
    assert "a note" not in stored.values() and "Somebody Real" not in stored.values() and "PO1" not in stored.values()
    assert next(r for r in rows if r.product_code == "CYL 1E74").stock_qty == 1000


def test_something_else_is_refused_as_an_export():
    with pytest.raises(ds.SnapshotError, match="not the legacy inventory export"):
        ds.parse_csv("Part,Qty\nA,1\n")
    with pytest.raises(ds.SnapshotError, match="could not be read as CSV"):
        ds.parse_csv(_HEADER + '\n"' + "x" * 200_000 + '",1\n')


@pytest.mark.parametrize("cell, quantity", [("1,000", 1000), ("inf", 0), ("1e400", 0), ("abc", 0), ("1e12", 1_000_000)])
def test_a_quantity_cell_reads_as_whole_units_on_a_shelf(cell, quantity):
    assert ds._qty(cell) == quantity


def test_ongoing_projects_are_the_jobs_that_held_hardware(rows):
    assert ds.ongoing_projects(rows) == {"T-100": "Test Tower", "T-200": "Test Clinic", "T-300": "Test Washrooms"}


def test_specialties_go_to_their_job_and_everything_else_to_the_pool(rows):
    where: dict[tuple, int] = {}
    for e in ds.inventory_entries(rows):
        key = (e.row.product_code, e.project_number)
        where[key] = where.get(key, 0) + e.quantity
    assert where[("GRAB BAR 36", "T-300")] == 7  # project + non stock + stock
    assert where[("MIRROR 24X36", None)] == 2
    assert where[("DISPENSER", None)] == 1
    assert where[("HNG 4.5 US26D", None)] == 6 + 3  # both jobs' hinges; staged and shipped have left
    assert where[("CLS 4040 AL", None)] == 3
    assert where[("CYL 1E74", None)] == 1000
    assert ("EXT 98 26D", None) not in where  # nothing on hand
    kinds = {e.row.product_code: e.row.hardware_category for e in ds.inventory_entries(rows)}
    assert kinds["HM DOOR 3070"] == "DEMO_DOOR" and kinds["SILICONE"] == "DEMO_CONSUMABLE"
    assert kinds["GRAB BAR 36"] == "DEMO_SPECIALTY"


def test_a_door_hardware_category_that_is_a_type_code_is_kept_apart():
    row = ds.SnapshotRow.from_dict(
        {"inventory_type": "Door Hardware", "part_category": "demo_frame", "product_code": "X"}
    )
    assert row.hardware_category == "DEMO_FRAME HARDWARE"


def test_a_made_up_schedule_asks_for_what_the_job_held_and_still_had_on_order(rows):
    by_project = {s.project_number: s for s in ds.schedules(rows)}
    assert set(by_project) == {"T-100", "T-200"}  # T-300 holds only specialties
    tower = by_project["T-100"]
    need = {}
    for item in tower.hardware_items:
        key = (item["hardwareCategory"], item["productCode"])
        need[key] = need.get(key, 0) + item["itemQuantity"]
    assert need == {("HINGE", "HNG 4.5 US26D"): 6, ("CLOSER", "CLS 4040 AL"): 4, ("EXIT DEVICE", "EXT 98 26D"): 2}
    assert len(tower.openings) == 6
    assert {i["openingNumber"] for i in tower.hardware_items} <= {o["openingNumber"] for o in tower.openings}
    # The pairs a pull-back lands on are the pairs the pool rows carry.
    pool = {(e.row.hardware_category, e.row.product_code) for e in ds.inventory_entries(rows) if not e.project_number}
    assert {("HINGE", "HNG 4.5 US26D"), ("CLOSER", "CLS 4040 AL")} <= pool


# --- a reset seeded from a stored snapshot -----------------------------------------------------------


_ADMIN = {"request": None, "_auth_user_id": "u_admin", "_auth_roles": ["UC Nexus Admin"], "_auth_company": None}


def _run(document: str, context: dict | None = None, **variables) -> dict:
    from main import schema

    result = asyncio.run(schema.execute(document, variable_values=variables, context_value=context or dict(_ADMIN)))
    assert result.errors is None, result.errors
    return result.data


@pytest.fixture(scope="module")
def seeded_from_snapshot(_migrate_database):
    """Store the made-up export through the admin upload, reset the demo company from it, and put both back
    afterwards - the export this database had stored included, since an upload replaces it."""
    from app.auth import remember_display_name
    from app.database import SessionLocal
    from app.models.demo_inventory_snapshot import DemoInventorySnapshot
    from app.repositories import user_repository
    from app.services import demo_reset, storage

    table = DemoInventorySnapshot.__table__
    with SessionLocal() as session:
        kept = [dict(r._mapping) for r in session.execute(table.select())]
    remember_display_name(_ADMIN["_auth_user_id"], "Test Admin")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(user_repository, "get_user_demo_mode", lambda user_id: False)
        mp.setattr(storage, "upload_file", lambda key, data, content_type, **kw: key)
        mp.setattr(storage, "delete_file", lambda key: None)
        summary = _run(
            "mutation U($f: String!, $c: String!) { uploadDemoInventorySnapshot(fileName: $f, csvText: $c) "
            "{ fileName rowCount projectUnits poolUnits projectCount scheduleCount } }",
            f="Inventory.csv",
            c=_csv(),
        )["uploadDemoInventorySnapshot"]
        asyncio.run(demo_reset.reset())
        yield summary
        with SessionLocal() as session:
            demo_reset.wipe(session)
            session.execute(table.delete())
            if kept:
                session.execute(table.insert(), kept)
            session.commit()


def test_the_upload_reports_what_the_reset_will_seed(seeded_from_snapshot):
    assert seeded_from_snapshot == {
        "fileName": "Inventory.csv",
        "rowCount": 13,
        "projectUnits": 7,
        "poolUnits": 6 + 3 + 3 + 3 + 2 + 1 + 1000 + 2 + 3 + 12 + 5,
        "projectCount": 3,
        "scheduleCount": 2,
    }


def test_a_demo_reset_is_not_the_real_migration_having_run(seeded_from_snapshot):
    from app.database import SessionLocal
    from app.repositories import sharepoint_migration_repository

    runs = "SELECT count(*) FROM sharepoint_migration_runs WHERE company "
    with SessionLocal() as session:
        assert session.scalar(text(runs + f"= '{DEMO_COMPANY}'"))
        real = session.scalar(text(runs + f"IS DISTINCT FROM '{DEMO_COMPANY}'"))
        assert sharepoint_migration_repository.has_migration_run(session) == bool(real)


def test_the_export_is_not_replaced_while_a_reset_runs(seeded_from_snapshot):
    from app.services import demo_reset
    from main import schema

    upload = 'mutation U($c: String!) { uploadDemoInventorySnapshot(fileName: "x.csv", csvText: $c) { rowCount } }'
    with demo_reset.no_reset_running():
        result = asyncio.run(schema.execute(upload, variable_values={"c": _csv()}, context_value=dict(_ADMIN)))
    assert result.errors and "being reset" in result.errors[0].message


def test_the_snapshot_survives_the_reset_it_seeded(seeded_from_snapshot):
    from app.database import SessionLocal

    with SessionLocal() as session:
        assert session.scalar(text("SELECT count(*) FROM demo_inventory_snapshots")) == 1


def test_the_ongoing_projects_are_demo_projects_beside_the_made_up_ones(seeded_from_snapshot):
    from app.database import SessionLocal

    with SessionLocal() as session:
        numbers = set(session.scalars(text(f"SELECT project_id FROM projects WHERE company = '{DEMO_COMPANY}'")))
    assert numbers == {"DEMO-1001", "DEMO-1002", "DEMO-1003", "DEMO-1004", "T-100", "T-200", "T-300"}


def test_the_snapshot_is_the_pool_and_the_specialties_are_on_their_job(seeded_from_snapshot):
    from app.database import SessionLocal

    demo = f"'{DEMO_COMPANY}'"
    with SessionLocal() as session:
        pool = dict(
            session.execute(
                text(
                    "SELECT s.product_code, sum(s.quantity) FROM stock_items s "
                    f"JOIN warehouses w ON w.id = s.warehouse_id WHERE w.company = {demo} GROUP BY s.product_code"
                )
            ).all()
        )
        on_job = dict(
            session.execute(
                text(
                    "SELECT p.project_id, sum(i.quantity) FROM inventory_locations i "
                    "JOIN projects p ON p.id = i.project_id "
                    f"WHERE p.company = {demo} AND i.hardware_category = 'DEMO_SPECIALTY' GROUP BY p.project_id"
                )
            ).all()
        )
        nothing_on_tower = session.scalar(
            text(
                "SELECT count(*) FROM inventory_locations i JOIN projects p ON p.id = i.project_id "
                f"WHERE p.company = {demo} AND p.project_id = 'T-100'"
            )
        )
        defined = set(
            session.execute(
                text(
                    "SELECT l.aisle, l.row, l.bay FROM warehouse_locations l "
                    f"JOIN warehouses w ON w.id = l.warehouse_id WHERE w.company = {demo}"
                )
            ).all()
        )
    assert pool["HNG 4.5 US26D"] == 9 and pool["CYL 1E74"] == 1000 and pool["MIRROR 24X36"] == 2
    # Through the pool and on to the job: the drained pool row stays, as the project row's origin.
    assert pool.get("GRAB BAR 36", 0) == 0
    assert on_job == {"T-300": 7}
    assert nothing_on_tower == 0
    assert {("K", "17", "R"), ("F", "40", "-"), ("NS", "K", "-"), ("IS", "A", "4"), ("A", "1", "2")} <= defined
    assert pool["KICK PLATE 34"] == 5  # on the made-up warehouse's own A / 1 / 2


def test_a_job_offers_its_schedule_and_takes_hardware_pulled_back_from_the_pool(seeded_from_snapshot):
    from app.services.demo_seed import Seeder

    async def _walk():
        s = Seeder()
        projects = {p["projectId"]: p["id"] for p in (await s.gql("{ projects { id projectId } }"))["projects"]}
        tower = projects["T-100"]
        schedule = (
            await s.gql(
                "query S($p: ID!) { projectHardwareSchedule(projectId: $p) { project { scheduleFilename } "
                "hardwareItems { hardwareCategory productCode itemQuantity } } }",
                p=tower,
            )
        )["projectHardwareSchedule"]
        hinges = '{ stockItems(productCodeContains: "HNG") { id hardwareCategory productCode available } }'
        pool = (await s.gql(hinges))["stockItems"]
        hinge = max((r for r in pool if r["productCode"] == "HNG 4.5 US26D"), key=lambda r: r["available"])
        await s.gql(
            "mutation A($input: AllocateStockToProjectInput!) { allocateStockToProject(input: $input) { id } }",
            input={
                "stockItemId": hinge["id"],
                "projectId": tower,
                "targetHardwareCategory": hinge["hardwareCategory"],
                "targetProductCode": hinge["productCode"],
                "quantity": 3,
            },
        )
        rows = (await s.gql("query R($p: ID) { inventoryRows(projectId: $p) { matchesSchedule } }", p=tower))[
            "inventoryRows"
        ]
        return schedule, rows

    schedule, rows = asyncio.run(_walk())
    assert schedule["project"]["scheduleFilename"] == "T-100-hardware-schedule.xml"
    from app.database import SessionLocal

    with SessionLocal() as session:
        states = set(
            session.scalars(
                text(
                    "SELECT h.state FROM hardware_items h JOIN projects p ON p.id = h.project_id "
                    f"WHERE p.company = '{DEMO_COMPANY}' AND p.project_id = 'T-100'"
                )
            )
        )
    assert states == {"AVAILABLE"}  # nothing ordered: the import is the demo user's to make
    assert sum(i["itemQuantity"] for i in schedule["hardwareItems"]) == 12
    assert [r["matchesSchedule"] for r in rows] == [True]


def test_the_demo_leaves_a_real_company_its_own_type_codes(seeded_from_snapshot):
    # A type code is checked against every company's stock categories, so the demo's must be its own.
    from app.database import SessionLocal
    from app.repositories import custom_items_repository

    with SessionLocal() as session:
        try:
            for name, code in (("Specialties", "SPECIALTY"), ("Doors", "DOOR"), ("Frames", "FRAME")):
                custom_items_repository.create_item_type(session, name=name, code=code, company="REALCO")
        finally:
            session.rollback()


def test_an_admin_removes_the_export_and_the_demo_goes_back_to_made_up(seeded_from_snapshot):
    # Last: it takes away what the tests above read.
    assert _run("mutation { removeDemoInventorySnapshot }") == {"removeDemoInventorySnapshot": True}
    assert _run("{ demoInventorySnapshot { fileName } }") == {"demoInventorySnapshot": None}
    assert _run("mutation { removeDemoInventorySnapshot }") == {"removeDemoInventorySnapshot": False}
