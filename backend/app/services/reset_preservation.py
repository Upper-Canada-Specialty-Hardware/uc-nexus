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

**Statements are built through SQLAlchemy Core, not string SQL.** Two of the preserved models store
JSON (`BuyerAssignment.cost_codes`, and four columns on `PODocumentSettings`). Round-tripping those
through `text()` bind params does not work: psycopg2 adapts a Python list to a Postgres *array*, so
the restore fails with "column is of type json but expression is of type text[]". Core carries the
column types, so JSON, UUID, enum and datetime all serialize correctly, and a column the snapshot is
missing falls back to the model's Python-side default instead of being inserted as NULL.

One table cannot be restored by row. `buyer_assignment_projects` is keyed on `projects.id`, and
projects do not survive a reset - they are re-adopted from GP afterwards with **new** UUIDs, so every
snapshotted `project_id` is stale the moment the schema drops. It is snapshotted as
`(buyer_assignment_id, GP job number)` pairs instead and re-linked by job number once the GP sync has
re-adopted the projects. The left side stays valid because `buyer_assignments` rows do come back with
their original UUIDs.
"""

import logging
from dataclasses import dataclass, field

from sqlalchemy import insert, select
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.engine import Connection

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


@dataclass
class ResetSnapshot:
    """Everything read out of the database before the schema is dropped."""

    # Table name -> the rows to put back, as plain dicts. Plain on purpose: the ORM model is about to
    # have its table dropped, so nothing here may hold a live identity-mapped instance.
    rows: dict[str, list[dict]] = field(default_factory=dict)
    # (buyer_assignment_id, job_number) pairs - see the module docstring for why these are not rows.
    buyer_project_pairs: list[dict] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        return {table: len(rows) for table, rows in self.rows.items()}


def preserved_columns(model, live_column_names) -> list[str]:
    """The model's columns that the live table also has, in model declaration order.

    Pure function over names - the unit test for this needs no database. The intersection is the
    half-migrated tolerance: a column the model declares but the live table predates is skipped on the
    way out rather than crashing the SELECT, and a column the live table has but the model no longer
    declares is dropped, which is correct because the rebuilt schema will not have it either."""
    live = set(live_column_names)
    return [c.name for c in model.__table__.columns if c.name in live]


def snapshot_statement(model, live_column_names):
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
    snap = ResetSnapshot()

    for model in PRESERVED_MODELS:
        table = model.__table__
        if not inspector.has_table(table.name):
            continue
        stmt = snapshot_statement(model, [c["name"] for c in inspector.get_columns(table.name)])
        if stmt is None:
            continue
        snap.rows[table.name] = [dict(r) for r in conn.execute(stmt).mappings()]

    if inspector.has_table(buyer_assignment_projects.name) and inspector.has_table(Project.__table__.name):
        projects = Project.__table__
        pairs = select(
            buyer_assignment_projects.c.buyer_assignment_id,
            # projects.project_id IS the GP job number; there is no schedule_id column.
            projects.c.project_id.label("job_number"),
        ).select_from(buyer_assignment_projects.join(projects, projects.c.id == buyer_assignment_projects.c.project_id))
        snap.buyer_project_pairs = [dict(r) for r in conn.execute(pairs).mappings()]

    return snap


def restore(conn: Connection, snap: ResetSnapshot) -> dict[str, int]:
    """Insert the snapshotted rows back into the rebuilt schema, original UUIDs intact.

    Runs before anything can lazily seed a default row - `PODocumentSettings` in particular is read
    through a get-or-create helper, so restoring first is what stops a defaults row being seeded
    alongside the admin-edited one."""
    for model in PRESERVED_MODELS:
        rows = snap.rows.get(model.__table__.name)
        if rows:
            conn.execute(insert(model.__table__), rows)
    return snap.counts


def relink_buyer_projects(conn: Connection, pairs: list[dict]) -> tuple[int, int]:
    """Re-attach each buyer assignment to its projects by GP job number. Returns (restored, dropped).

    Call this only after the GP job sync has re-adopted the projects; before that, `projects` is empty
    and every pair drops. A pair whose job no longer exists in GP matches nothing and is dropped by
    design - the buyer keeps their row and cost codes, they just lose a link to a job that is gone."""
    if not pairs:
        return 0, 0

    projects = Project.__table__
    by_job = {row.project_id: row.id for row in conn.execute(select(projects.c.project_id, projects.c.id))}
    rows = [
        {"buyer_assignment_id": pair["buyer_assignment_id"], "project_id": by_job[pair["job_number"]]}
        for pair in pairs
        if pair["job_number"] in by_job
    ]
    if rows:
        conn.execute(insert(buyer_assignment_projects), rows)
    return len(rows), len(pairs) - len(rows)
