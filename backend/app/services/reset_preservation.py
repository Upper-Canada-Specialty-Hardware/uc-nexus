"""The configuration that survives POST /admin/reset-data (#410, #411).

A reset drops and rebuilds the whole public schema. That is the point - it exists to clear project
data - but a handful of tables hold *setup*, not data, and wiping them turns a dev convenience into
an afternoon of re-entry (or, for `relay_installs`, into a GP outage until someone walks to the
workstation and re-enrols the relay).

So the reset snapshots those tables, rebuilds, and puts the rows back with their original UUIDs.
`PRESERVED_MODELS` is the whole list; adding a table to it is a one-line change.

**Columns are derived from the model, never listed by hand** (#411). The previous version named all
13 `relay_installs` columns twice in raw SQL, so a migration adding a column left it NULL on every
preserved row after the next reset, silently. `preserved_columns` takes the names off
`Model.__table__.columns` and intersects them with what the live table actually has - the
intersection is what keeps a half-migrated database (one predating a column the model already
declares) from crashing the snapshot, which is the same tolerance the `has_table` guard gives.

**Statements are built through SQLAlchemy Core, not string SQL.** `PODocumentSettings` stores JSON in
four columns. Round-tripping those through `text()` bind params does not work: psycopg2 adapts a
Python list to a Postgres *array*, so the restore fails with "column is of type json but expression
is of type text[]". Core carries the column types, so JSON, UUID, enum and datetime all serialize
correctly, and a column the snapshot is missing falls back to the model's Python-side default instead
of being inserted as NULL.

One table cannot be restored by row. `buyer_assignment_projects` is keyed on `projects.id`, and
projects do not survive a reset - they are re-adopted from GP afterwards with **new** UUIDs, so every
snapshotted `project_id` is stale the moment the schema drops. It is snapshotted as
`(buyer_assignment_id, company, GP job number)` triples instead and re-linked on that pair once the GP
sync has re-adopted the projects - the company is half of a job's identity since #637, so a job number
alone would re-attach the buyer to whichever company's project of that number came back last. The left
side stays valid because `buyer_assignments` rows do come back with their original UUIDs.
"""

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field

from sqlalchemy import Select, delete, insert, select
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.engine import Connection

from app.models import Base
from app.models.buyer_assignment import BuyerAssignment, buyer_assignment_projects
from app.models.manufacturer_vendor_map import ManufacturerVendorMap
from app.models.po_document_settings import PODocumentSettings
from app.models.project import Project
from app.models.relay_install import RelayInstall
from app.models.warehouse import Warehouse

logger = logging.getLogger(__name__)

# Restored in this order. None of these reference each other, so the order is presentational rather
# than load-bearing - but keep any future FK-dependent table after the one it points at.
PRESERVED_MODELS = (
    RelayInstall,
    Warehouse,
    BuyerAssignment,
    ManufacturerVendorMap,
    PODocumentSettings,
)

# Human labels for the reset's summary line. `/admin/reset-data` returns `message` and the frontend
# alerts it verbatim, so the counts have to agree in number and read as English rather than as table
# names ("1 relay install", not "1 relay_installs").
PRESERVED_LABELS: dict[str, tuple[str, str]] = {
    "relay_installs": ("relay install", "relay installs"),
    "warehouses": ("warehouse", "warehouses"),
    "buyer_assignments": ("buyer assignment", "buyer assignments"),
    "manufacturer_vendor_map": ("manufacturer/vendor mapping", "manufacturer/vendor mappings"),
    "po_document_settings": ("PO document setting", "PO document settings"),
}


@dataclass
class ResetSnapshot:
    """Everything read out of the database before the schema is dropped."""

    # Table name -> the rows to put back, as plain dicts. Plain on purpose: the ORM model is about to
    # have its table dropped, so nothing here may hold a live identity-mapped instance.
    rows: dict[str, list[dict]] = field(default_factory=dict)
    # (buyer_assignment_id, company, job_number) triples - see the module docstring for why these are
    # not rows, and #637 for why the company rides along.
    buyer_project_pairs: list[dict] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        return {table: len(rows) for table, rows in self.rows.items()}


def preserved_columns(model: type[Base], live_column_names: Iterable[str]) -> list[str]:
    """The model's columns that the live table also has, in model declaration order.

    Pure function over names - the unit test for this needs no database. The intersection is the
    half-migrated tolerance: a column the model declares but the live table predates is skipped on the
    way out rather than crashing the SELECT, and a column the live table has but the model no longer
    declares is dropped, which is correct because the rebuilt schema will not have it either."""
    live = set(live_column_names)
    return [c.name for c in model.__table__.columns if c.name in live]


def snapshot_statement(model: type[Base], live_column_names: Iterable[str]) -> Select | None:
    """The SELECT that reads one preserved table, or None when nothing about it is preservable.

    Split out from `snapshot` so it can be asserted on without a database - it is the statement that
    used to be a hand-written column list, and the whole of #411 is that it must never drift from the
    model again."""
    cols = preserved_columns(model, live_column_names)
    if not cols:
        return None
    table = model.__table__
    return select(*[table.c[name] for name in cols])


def snapshot(conn: Connection) -> ResetSnapshot:
    """Read every preserved table, plus the buyer/project link pairs. Safe on a fresh or half-migrated
    database: a table that isn't there yet is simply not preserved, which is exactly the state a reset
    exists to clear."""
    inspector = sa_inspect(conn)
    # One round trip for the whole table list instead of a has_table call per model; this runs against
    # managed Postgres over a network hop, where each extra round trip is a real cost.
    live_tables = set(inspector.get_table_names())
    snap = ResetSnapshot()

    for model in PRESERVED_MODELS:
        table = model.__table__
        if table.name not in live_tables:
            continue
        stmt = snapshot_statement(model, [c["name"] for c in inspector.get_columns(table.name)])
        if stmt is None:
            continue
        snap.rows[table.name] = [dict(r) for r in conn.execute(stmt).mappings()]

    # Only worth collecting when the left-hand side of the link is itself preserved: a pair whose
    # `buyer_assignments` row never comes back would fail the FK on relink, after the schema has already
    # been rebuilt and committed.
    if (
        BuyerAssignment.__table__.name in snap.rows
        and buyer_assignment_projects.name in live_tables
        and Project.__table__.name in live_tables
    ):
        projects = Project.__table__
        pairs = select(
            buyer_assignment_projects.c.buyer_assignment_id,
            # projects.project_id IS the GP job number; there is no schedule_id column. The company
            # travels with it since #637, because a job number is only unique within one - without it
            # a relink would re-attach the buyer to whichever company's project of that number the
            # sync happened to re-adopt last.
            projects.c.company,
            projects.c.project_id.label("job_number"),
        ).select_from(buyer_assignment_projects.join(projects, projects.c.id == buyer_assignment_projects.c.project_id))
        snap.buyer_project_pairs = [dict(r) for r in conn.execute(pairs).mappings()]

    return snap


def restore(conn: Connection, snap: ResetSnapshot) -> dict[str, int]:
    """Put the snapshotted rows back into the rebuilt schema, original UUIDs intact. Returns the count
    actually restored per table, which is not always the count snapshotted - see below.

    **The snapshot wins over whatever the rebuild left in the table.** `alembic upgrade head` replays
    every migration, and some of them seed the table they create: 033 seeds `warehouses` with Warden
    and VP. Those seeds are the previous cycle's rows under fresh UUIDs, so inserting the snapshot on
    top of them is a duplicate-key failure on `uq_warehouses_name`, not a merge. The same window lets
    a concurrent read seed the single `po_document_settings` row through its get-or-create helper
    before the restore lands. Clearing the table first makes the preserved rows authoritative in both
    cases. A table the snapshot has nothing for is left alone, so a fresh database keeps its seeds.

    **One table's failure must not take the others down.** Each table restores inside its own
    SAVEPOINT: relay_installs is the row set whose loss means a GP outage until someone walks to the
    workstation, and it must not be rolled back because some later table hit a constraint."""
    restored: dict[str, int] = {}
    for model in PRESERVED_MODELS:
        table = model.__table__
        rows = snap.rows.get(table.name)
        if rows is None:
            continue
        restored[table.name] = 0
        if not rows:
            continue
        try:
            with conn.begin_nested():
                conn.execute(delete(table))
                conn.execute(insert(table), rows)
        except Exception:  # noqa: BLE001 - one unrestorable table must not discard the rest
            logger.exception("reset: could not restore %s; its %s preserved rows are lost", table.name, len(rows))
            continue
        restored[table.name] = len(rows)
    return restored


def relink_buyer_projects(conn: Connection, pairs: list[dict]) -> tuple[int, int]:
    """Re-attach each buyer assignment to its projects by GP job number. Returns (restored, dropped).

    Call this only after the GP job sync has re-adopted the projects; before that, `projects` is empty
    and every pair drops. A pair whose job no longer exists in GP matches nothing and is dropped by
    design - the buyer keeps their row, they just lose a link to a job that is gone."""
    if not pairs:
        return 0, 0

    projects = Project.__table__
    # Keyed by (company, job number) since #637: a job number alone is no longer an identity, and a
    # single-column map would silently re-attach the buyer to another company's project.
    by_job = {
        (row.company, row.project_id): row.id
        for row in conn.execute(select(projects.c.company, projects.c.project_id, projects.c.id))
    }
    # A buyer whose own row failed to restore has nothing to hang the link on; inserting anyway would
    # fail the FK and 500 the reset after the schema is already rebuilt and committed.
    live_buyers = {row.id for row in conn.execute(select(BuyerAssignment.__table__.c.id))}
    rows = [
        {
            "buyer_assignment_id": pair["buyer_assignment_id"],
            "project_id": by_job[(pair["company"], pair["job_number"])],
        }
        for pair in pairs
        if (pair["company"], pair["job_number"]) in by_job and pair["buyer_assignment_id"] in live_buyers
    ]
    if rows:
        conn.execute(insert(buyer_assignment_projects), rows)
    return len(rows), len(pairs) - len(rows)


def describe_counts(counts: dict[str, int]) -> list[str]:
    """ "1 relay install", "3 warehouses" - the pieces of the reset's summary line.

    The endpoint's `message` is alerted to the user verbatim, so a count of one has to read as one."""
    described = []
    for table, count in counts.items():
        if not count:
            continue
        singular, plural = PRESERVED_LABELS.get(table, (table, table))
        described.append(f"{count} {singular if count == 1 else plural}")
    return described
