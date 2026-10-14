"""The legacy inventory snapshot the demo company's warehouse is seeded from (#1638).

Demo mode simulates a company that has just adopted Nexus: it moved the hardware of every ongoing project
into the stock pool and pulls it back to each project from there. The inventory it moved is a real one -
the legacy inventory platform's own export - so the demo warehouse looks like the real warehouse. That
export is the company's data and this repository is public, so it never lands in git: an admin uploads
it, `parse_csv` keeps only what the seed needs (no POs, notes or people), and it is stored in
`demo_inventory_snapshots`, which has no company column, so the demo reset leaves it where it is.

Everything here is pure: the seed (`demo_seed.py`) asks it what to create and creates it through the app's
own mutations. Where the snapshot's rows go:

  - Specialties of an ongoing project go to that project, all of what is on hand.
  - Everything else - door hardware, doors, frames, consumables, and specialties with no real project -
    goes to the stock pool, all of what is on hand. On hand is Project Inventory + Stock + Non Stock;
    Staged and Shipped have left the shelf.
  - Every ongoing project becomes a GP job of the simulated GP, and a door hardware one gets a made-up
    hardware schedule built from its own snapshot rows, so the import wizard offers "use last uploaded".
    A schedule pair is (Part Category 1, schedule key) - the same pair the pool row of that hardware
    carries - so hardware pulled back from the pool lands on the schedule.
"""

import csv
import io
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass

# The legacy export's columns, by the header the export writes.
_COL_SCHEDULE_KEY = "Scheduled Part Number (Hardware Schedule Key value)"
_COL_ORDER_AS = "Part Number (Order As)"
_COL_PROJECT_NUMBER = "Project Number"
_COL_PROJECT_NAME = "Project Name"
_COL_LOCATIONS = "Locations"
_COL_PROJECT_QTY = "Project Inventory Qty"
_COL_NON_STOCK_QTY = "Non Stock Qty"
_COL_STOCK_QTY = "Stock Qty"
_COL_ORDERED_QTY = "Ordered Qty"
_COL_RECEIVED_QTY = "Received Qty"
_COL_INVENTORY_TYPE = "Inventory Type"
_COL_PART_CATEGORY = "Part Category 1"
_COL_FINISH = "Finish"

_REQUIRED_COLUMNS = (
    _COL_SCHEDULE_KEY,
    _COL_ORDER_AS,
    _COL_PROJECT_NUMBER,
    _COL_PROJECT_NAME,
    _COL_LOCATIONS,
    _COL_PROJECT_QTY,
    _COL_NON_STOCK_QTY,
    _COL_STOCK_QTY,
    _COL_INVENTORY_TYPE,
    _COL_PART_CATEGORY,
)

# The legacy inventory types that are not schedule hardware, and the Nexus inventory item type each one
# is catalogued under: (type name, type code). Its code is the hardware category of the type's rows.
#
# The codes are the demo's own. Whether a type code is free is checked against the hardware categories of
# every company's stock, not just the type's own company (custom_items_repository._check_code_free), so a
# plain FRAME here would refuse the seed wherever a real company's stock already says FRAME - and the demo's
# FRAME stock would refuse a real company a FRAME type of its own.
NON_SCHEDULE_TYPES = {
    "Specialties": ("Specialties", "DEMO_SPECIALTY"),
    "Door": ("Doors", "DEMO_DOOR"),
    "Frame": ("Frames", "DEMO_FRAME"),
    "Consumable": ("Consumables", "DEMO_CONSUMABLE"),
}
SPECIALTIES = "Specialties"
_TYPE_CODES = {code for _name, code in NON_SCHEDULE_TYPES.values()}

# The longest product code the catalog takes (custom_items_repository.MAX_PRODUCT_CODE_LENGTH). The export
# has a few part "numbers" that are whole descriptions.
_MAX_PRODUCT_CODE = 100

# The category of a door hardware row the export gave no Part Category 1.
UNCATEGORIZED = "UNCATEGORIZED"

# Project numbers that are not jobs: the warehouse's own stock, retail orders, and the blanks.
_NOT_A_JOB = re.compile(r"^(|UNKNOWN|BCS|RTLORD.*)$", re.IGNORECASE)

# A made-up schedule spreads a project's hardware over at most this many openings.
_MAX_OPENINGS = 30

# The simulated GP's customer every snapshot job is billed to.
SNAPSHOT_CUSTOMER = "DEMOBUILD"


@dataclass(frozen=True)
class SnapshotRow:
    """One row of the export, reduced to what the seed reads."""

    inventory_type: str
    product_code: str
    schedule_key: str
    part_category: str
    finish: str
    project_number: str
    project_name: str
    location: str
    project_qty: int
    stock_qty: int
    non_stock_qty: int
    ordered_qty: int
    received_qty: int

    @property
    def on_hand(self) -> int:
        return self.project_qty + self.stock_qty + self.non_stock_qty

    @property
    def is_schedule_hardware(self) -> bool:
        return self.inventory_type not in NON_SCHEDULE_TYPES

    @property
    def hardware_category(self) -> str:
        """The category the row's units carry in Nexus: its item type's code, or for schedule hardware its
        Part Category 1 - the category its made-up schedule gives it too."""
        if not self.is_schedule_hardware:
            return NON_SCHEDULE_TYPES[self.inventory_type][1]
        category = self.part_category.upper() or UNCATEGORIZED
        # A schedule category may not be an item type's code (#1343): the finalize refuses it.
        return f"{category} HARDWARE" if category in _TYPE_CODES else category

    def to_dict(self) -> dict:
        return {f: getattr(self, f) for f in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, data: dict) -> "SnapshotRow":
        return cls(**{f: data.get(f, 0 if f.endswith("_qty") else "") for f in cls.__dataclass_fields__})


class SnapshotError(ValueError):
    """The upload is not the legacy inventory export."""


def _text(value) -> str:
    return " ".join(str(value or "").split())


def _qty(value) -> int:
    """A quantity cell: blank is 0, thousands separators are dropped, a fraction is cut to whole units."""
    text = str(value or "").replace(",", "").strip()
    if not text:
        return 0
    try:
        return max(0, int(float(text)))
    except ValueError:
        return 0


def parse_csv(content: str) -> list[SnapshotRow]:
    """The export's rows that still have something to say: hardware on hand, or hardware an ongoing
    project is still waiting on. Nothing else is kept - not the PO, the notes, or who entered the row."""
    reader = csv.DictReader(io.StringIO(content.lstrip("﻿")))
    missing = [c for c in _REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
    if missing:
        raise SnapshotError(f"This is not the legacy inventory export: it has no {', '.join(missing)} column.")
    rows = []
    for raw in reader:
        # Cut to the catalog's limit, the same for every row, so a long code still names one product.
        schedule_key = _text(raw.get(_COL_SCHEDULE_KEY))[:_MAX_PRODUCT_CODE]
        row = SnapshotRow(
            # A row with no type is door hardware, the kind nearly every such row is.
            inventory_type=_text(raw.get(_COL_INVENTORY_TYPE)) or "Door Hardware",
            product_code=schedule_key or _text(raw.get(_COL_ORDER_AS))[:_MAX_PRODUCT_CODE],
            schedule_key=schedule_key,
            part_category=_text(raw.get(_COL_PART_CATEGORY)),
            finish=_text(raw.get(_COL_FINISH)),
            project_number=_text(raw.get(_COL_PROJECT_NUMBER)),
            project_name=_text(raw.get(_COL_PROJECT_NAME)),
            location=_text(raw.get(_COL_LOCATIONS)),
            project_qty=_qty(raw.get(_COL_PROJECT_QTY)),
            stock_qty=_qty(raw.get(_COL_STOCK_QTY)),
            non_stock_qty=_qty(raw.get(_COL_NON_STOCK_QTY)),
            ordered_qty=_qty(raw.get(_COL_ORDERED_QTY)),
            received_qty=_qty(raw.get(_COL_RECEIVED_QTY)),
        )
        if row.product_code and (row.on_hand > 0 or _outstanding(row) > 0):
            rows.append(row)
    if not rows:
        raise SnapshotError("The export has no row with hardware on hand.")
    return rows


def _outstanding(row: SnapshotRow) -> int:
    return max(0, row.ordered_qty - row.received_qty)


# --- projects ----------------------------------------------------------------------------------------


def is_job(project_number: str) -> bool:
    return not _NOT_A_JOB.match(project_number.strip())


def ongoing_projects(rows: list[SnapshotRow]) -> dict[str, str]:
    """Every ongoing project, number -> name: a real job that still held project inventory. A number the
    export names two ways takes the name most of its rows use."""
    names: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        if row.project_qty > 0 and is_job(row.project_number):
            names[row.project_number][row.project_name or row.project_number] += 1
    return {number: counts.most_common(1)[0][0] for number, counts in sorted(names.items())}


def gp_jobs(rows: list[SnapshotRow]) -> list[dict]:
    """The ongoing projects as jobs of the simulated GP, in the shape its fixed jobs are written in."""
    return [
        {
            "job_number": number,
            # GP job names are short; the export's longest runs past fifty characters.
            "job_name": name[:50],
            "customer_number": SNAPSHOT_CUSTOMER,
            "job_address_code": "PRIMARY",
            "city": "Toronto",
            "division": "HARDWARE",
        }
        for number, name in ongoing_projects(rows).items()
    ]


# --- locations ---------------------------------------------------------------------------------------

Location = tuple[str, str, str]

# No bay, or no row and bay: the registry needs all three parts, so the missing ones read "-".
NO_PART = "-"

# K-17R, G8R, F-75-L, F-40, and with a shelf qualifier F-54L 01 / F-54R(3).
_COORDINATE = re.compile(r"([A-Z]{1,3})-?(\d{1,3})-?([A-Z]?)\s*(?:\(?(\d{1,2})\)?)?")
# A coordinate followed by a description: G-22L - Blue Stand Up Rack.
_COORDINATE_THEN_TEXT = re.compile(r"([A-Z]{1,3})-?(\d{1,3})-?([A-Z]?)\s+-\s+.+")
# The IS shelves: IS A-4, IS-B-3.
_IS_SHELF = re.compile(r"IS[\s-]([A-Z])-(\d{1,2})")
# Two-part areas: NS-K, Stock-G, Stock-DL, S-F.
_AREA_AND_ROW = re.compile(r"([A-Z]{1,5})-([A-Z]{1,2})")
# A spot that names a person rather than a place: "With ...", "... Office".
_PERSON = re.compile(r"\bWITH\b|\bOFFICE\b")

_MAX_PART = 20


def location_for(raw: str) -> Location | None:
    """The registry location a legacy Locations cell maps to, or None for no shelf.

    A cell naming several locations names where that hardware is spread; the first one stands for it.
    A spot no rule recognises is a named area of the warehouse (SSR, Coast, Warehouse Overflow) and becomes
    an aisle of its own. A spot that names a person, or no spot at all, is no shelf: those units are still
    real, and the warehouse puts them away later."""
    first = raw.split(",")[0]
    token = " ".join(first.upper().split())
    if not token or _PERSON.search(token):
        return None
    if m := _COORDINATE.fullmatch(token):
        aisle, row, bay, shelf = m.groups()
        bay = f"{bay}{int(shelf)}" if shelf else bay
        return aisle, row, bay or NO_PART
    if m := _COORDINATE_THEN_TEXT.fullmatch(token):
        aisle, row, bay = m.groups()
        return aisle, row, bay or NO_PART
    if m := _IS_SHELF.fullmatch(token):
        return "IS", m.group(1), m.group(2)
    if m := _AREA_AND_ROW.fullmatch(token):
        return m.group(1), m.group(2), NO_PART
    return _area_name(token), NO_PART, NO_PART


def _area_name(token: str) -> str:
    """A named area as an aisle, cut at a word to the registry's twenty characters."""
    if len(token) <= _MAX_PART:
        return token
    cut = token[: _MAX_PART + 1].rsplit(" ", 1)[0]
    return cut if cut and len(cut) <= _MAX_PART else token[:_MAX_PART]


def locations(rows: list[SnapshotRow]) -> list[Location]:
    """Every location the snapshot's on-hand hardware sits at, to define in the registry first."""
    found = {location_for(r.location) for r in rows if r.on_hand > 0}
    found.discard(None)
    return sorted(found)


# --- inventory ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class InventoryEntry:
    """One row's on-hand quantity and where it goes: to `project_number`, or to the pool when None."""

    row: SnapshotRow
    project_number: str | None
    location: Location | None

    @property
    def quantity(self) -> int:
        return self.row.on_hand


def inventory_entries(rows: list[SnapshotRow]) -> list[InventoryEntry]:
    projects = ongoing_projects(rows)
    entries = []
    for row in rows:
        if row.on_hand <= 0:
            continue
        to_project = row.inventory_type == SPECIALTIES and row.project_number in projects
        entries.append(InventoryEntry(row, row.project_number if to_project else None, location_for(row.location)))
    return entries


def catalog_items(rows: list[SnapshotRow]) -> list[tuple[str, str, str, str]]:
    """The non-schedule products to catalog, one per (legacy type, product code): (type, code, description,
    finish). The description is Part Category 1, as the migration wizard catalogs them."""
    seen: dict[tuple[str, str], tuple[str, str, str, str]] = {}
    for row in rows:
        if row.on_hand > 0 and not row.is_schedule_hardware:
            key = (row.inventory_type, row.product_code.lower())
            seen.setdefault(key, (row.inventory_type, row.product_code, row.part_category, row.finish))
    return list(seen.values())


# --- made-up hardware schedules ----------------------------------------------------------------------


@dataclass(frozen=True)
class Schedule:
    project_number: str
    openings: list[dict]
    hardware_items: list[dict]


def schedules(rows: list[SnapshotRow]) -> list[Schedule]:
    """A hardware schedule for every ongoing project with door hardware, made up from its snapshot rows.

    A schedule item is a (Part Category 1, schedule key) pair of the project, needing what the project
    held (now in the pool) plus what it still had on order. Rows with no schedule key never were on a
    schedule and stay off it. The openings are made up: numbered 001.., as many as the project's largest
    item needs up to thirty, and each item's quantity is dealt across them starting one opening further
    along than the item before, so the totals are exactly the snapshot's."""
    projects = ongoing_projects(rows)
    needs: dict[str, dict[tuple[str, str], int]] = defaultdict(lambda: defaultdict(int))
    for row in rows:
        if row.project_number in projects and row.is_schedule_hardware and row.schedule_key:
            need = row.project_qty + _outstanding(row)
            if need > 0:
                needs[row.project_number][(row.hardware_category, row.schedule_key)] += need

    out = []
    for number in sorted(needs):
        items = sorted(needs[number].items())
        count = min(_MAX_OPENINGS, max(quantity for _pair, quantity in items))
        openings = [_opening(n, count) for n in range(1, count + 1)]
        hardware = []
        for index, ((category, code), quantity) in enumerate(items):
            for slot, share in _deal(quantity, count, start=index % count):
                hardware.append(
                    {
                        "openingNumber": openings[slot]["openingNumber"],
                        "productCode": code,
                        "hardwareCategory": category,
                        "itemQuantity": share,
                    }
                )
        out.append(Schedule(number, openings, hardware))
    return out


def _opening(n: int, count: int) -> dict:
    floors = max(1, math.ceil(count / 10))
    floor = 1 + (n - 1) * floors // count
    return {
        "openingNumber": f"{n:03d}",
        "building": "Main",
        "floor": str(floor),
        "location": f"Room {floor}{n:02d}",
        "hand": "RH" if n % 2 else "LH",
        "width": "3'0\"",
        "length": "7'0\"",
        "doorType": "HM",
        "frameType": "HM",
        "singlePair": "Single",
        "leafCount": 1,
    }


def _deal(quantity: int, count: int, *, start: int) -> list[tuple[int, int]]:
    """`quantity` dealt over `count` openings from `start` on: (opening index, share), shares summing to
    `quantity`, each opening's share at most one apart from the next."""
    base, extra = divmod(quantity, count)
    shares = []
    for k in range(count):
        share = base + (1 if k < extra else 0)
        if share:
            shares.append(((start + k) % count, share))
    return shares
