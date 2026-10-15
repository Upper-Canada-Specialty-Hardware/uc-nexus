"""The legacy inventory list the demo warehouse is built from (#1638, #1657): its rules, no database.

The list below is made up: the real one is the company's own data and never enters this repository. It
has the real export's header and one row for each thing the build decides - where a row's units go, what
location a legacy location string becomes, which projects are jobs, what a made-up schedule asks for. The
build from it is tests/test_demo_mirror.py, which reads it from here.
"""

import pytest

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
    # A specialties job: everything on it goes to it, its door hardware too (#1657). Specialties with no
    # real job go to the pool.
    ("", "GRAB BAR 36", "T-300", "Test Washrooms", "NS-K", 4, 1, 0, 0, 2, 7, 7, "Specialties", "Satin", "Grab Bar"),
    ("HNG 4.5 US26D", "HNG 45 26D", "T-300", "Test Washrooms", "K-17R", 2, 0, 0, 0, 1, 2, 2, "", "", "Hinge"),
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
    lines[10] = lines[10].replace(",1000,", ',"1,000",')
    return "\n".join(lines) + "\n"


# The SharePoint list's internal names for the export's columns, as the live read returns its items.
_LIST_NAMES = (
    "HWSPartNumberEquivalent",
    "Title",
    "Project_x0020_Number_x0020_Temp",
    "Project_x0020_Name_x0020_Temp",
    "Locations",
    "Project_x0020_Inventory_x0020_Qt",
    "Non_x0020_Stock_x0020_Qty",
    None,  # staged: the list has it, the build does not read it
    None,  # shipped
    "Stock_x0020_Qty",
    "Ordered_x0020_Qty",
    "Received_x0020_Qty",
    "Inventory_x0020_Type",
    "Finish",
    "Part_x0020_Category_x0020_1",
)


def list_items() -> list[dict]:
    """The made-up list as the live SharePoint read returns it: one dict of internal names per item."""
    items = []
    for n, row in enumerate(_ROWS):
        item = {"sp_item_id": str(n + 1), "Purchase_x0020_Order_x0020_Numbe": "PO1", "Supplier": "Vendor"}
        item.update({name: value for name, value in zip(_LIST_NAMES, row, strict=True) if name})
        items.append(item)
    return items


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


def test_the_live_list_reads_as_the_export_does(rows):
    assert ds.parse_list_items(list_items()) == rows


def test_the_jobs_the_list_holds_anything_against(rows):
    assert ds.holding_jobs(rows) == {"T-100": "Test Tower", "T-200": "Test Clinic", "T-300": "Test Washrooms"}
    assert ds.specialties_jobs(rows) == {"T-300"}


_PROJECTS = {"T-100", "T-200", "T-300"}


def _where(rows, projects) -> dict[tuple, int]:
    where: dict[tuple, int] = {}
    for e in ds.inventory_entries(rows, projects):
        key = (e.row.product_code, e.project_number)
        where[key] = where.get(key, 0) + e.quantity
    return where


def test_a_specialties_job_keeps_everything_and_the_rest_goes_to_the_pool(rows):
    # Ruled on #1657: everything tagged to a specialties job is its project's, door hardware included.
    where = _where(rows, _PROJECTS)
    assert where[("GRAB BAR 36", "T-300")] == 7  # project + non stock + stock
    assert where[("HNG 4.5 US26D", "T-300")] == 3
    assert where[("MIRROR 24X36", None)] == 2
    assert where[("DISPENSER", None)] == 1
    assert where[("HNG 4.5 US26D", None)] == 6 + 3  # the other jobs' hinges; staged and shipped have left
    assert where[("CLS 4040 AL", None)] == 3
    assert where[("CYL 1E74", None)] == 1000
    assert ("EXT 98 26D", None) not in where  # nothing on hand
    kinds = {e.row.product_code: e.row.hardware_category for e in ds.inventory_entries(rows, _PROJECTS)}
    assert kinds["HM DOOR 3070"] == "DEMO_DOOR" and kinds["SILICONE"] == "DEMO_CONSUMABLE"
    assert kinds["GRAB BAR 36"] == "DEMO_SPECIALTY"


def test_a_specialties_job_that_is_no_demo_project_goes_to_the_pool(rows):
    where = _where(rows, {"T-100"})
    assert where[("GRAB BAR 36", None)] == 7 and ("GRAB BAR 36", "T-300") not in where


def test_a_door_hardware_category_that_is_a_type_code_is_kept_apart():
    row = ds.SnapshotRow.from_dict(
        {"inventory_type": "Door Hardware", "part_category": "demo_frame", "product_code": "X"}
    )
    assert row.hardware_category == "DEMO_FRAME HARDWARE"


def test_a_made_up_schedule_asks_for_what_the_job_held_and_still_had_on_order(rows):
    by_project = {s.project_number: s for s in ds.schedules(rows, _PROJECTS)}
    assert set(by_project) == {"T-100", "T-200", "T-300"}
    assert {s.project_number for s in ds.schedules(rows, {"T-200"})} == {"T-200"}
    tower = by_project["T-100"]
    need = {}
    for item in tower.hardware_items:
        key = (item["hardwareCategory"], item["productCode"])
        need[key] = need.get(key, 0) + item["itemQuantity"]
    assert need == {("HINGE", "HNG 4.5 US26D"): 6, ("CLOSER", "CLS 4040 AL"): 4, ("EXIT DEVICE", "EXT 98 26D"): 2}
    assert len(tower.openings) == 6
    assert {i["openingNumber"] for i in tower.hardware_items} <= {o["openingNumber"] for o in tower.openings}
    # The pairs a pull-back lands on are the pairs the pool rows carry.
    pool = {
        (e.row.hardware_category, e.row.product_code)
        for e in ds.inventory_entries(rows, _PROJECTS)
        if not e.project_number
    }
    assert {("HINGE", "HNG 4.5 US26D"), ("CLOSER", "CLS 4040 AL")} <= pool
