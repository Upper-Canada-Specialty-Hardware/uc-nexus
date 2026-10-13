"""Reset the demo company back to its starting state (#1608).

Reset is two things: delete every demo row, then run the seed (app/services/demo_seed.py).

Which rows are demo rows is worked out from the schema rather than listed by hand, so a table added
later is covered without anybody remembering to add it here. A row is a demo row when

  - it carries a `company` or `gp_company` column that says `DEMO` - projects, warehouses, POs, item
    types, doors on hand, shipment methods and the rest of what is scoped by company; or
  - it points, through a foreign key, at a demo row - openings, line items, receipts, pulls,
    shipments, read marks and everything else that hangs off those.

The walk only ever goes from a demo row to the rows that point at it, never the other way, so it cannot
reach into a real company: a real row would have to point at a demo row to be caught, and tenant scoping
is what keeps that from happening. Deleted children first, in one transaction.
"""

import asyncio
import logging
import uuid
import warnings
from collections import defaultdict

from sqlalchemy import Table, delete, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import SessionLocal, engine
from app.demo import DEMO_COMPANY
from app.errors import ConflictError
from app.models import Base
from app.models.audit_log import InventoryAuditLog
from app.models.project import Project
from app.models.purchase_order import PODocument
from app.services import demo_gp, storage

logger = logging.getLogger(__name__)

_COMPANY_COLUMNS = ("company", "gp_company")

# Tables the walk leaves alone: the simulated GP's own memory, which `demo_gp.wipe` clears, and the
# alembic bookkeeping that is not a model.
_SKIPPED = frozenset({"demo_gp_records"})

# Key for the session-level advisory lock one reset holds from the first delete to the end of the seed.
_RESET_LOCK_KEY = 1_608_002


def _tables() -> list[Table]:
    """Every model table, parents before children. Two tables point at each other (an inventory row and
    the return line it came back on), which SQLAlchemy warns it cannot order; `wipe` breaks that cycle
    itself by clearing the nullable side first, so the warning says nothing here."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return [t for t in Base.metadata.sorted_tables if t.name not in _SKIPPED]


def _single_pk(table: Table):
    columns = list(table.primary_key.columns)
    return columns[0] if len(columns) == 1 else None


def demo_rows(session: Session) -> dict[str, set]:
    """The primary keys of every demo row, by table name. Tables without a single-column primary key
    are not listed; `wipe` deletes their demo rows by the foreign keys that make them demo rows."""
    tables = _tables()
    doomed: dict[str, set] = defaultdict(set)

    for table in tables:
        pk = _single_pk(table)
        if pk is None:
            continue
        for name in _COMPANY_COLUMNS:
            if name in table.c:
                doomed[table.name].update(session.scalars(select(pk).where(table.c[name] == DEMO_COMPANY)))

    changed = True
    while changed:
        changed = False
        for table in tables:
            pk = _single_pk(table)
            if pk is None:
                continue
            for fk in table.foreign_keys:
                parent = fk.column.table
                parent_ids = doomed.get(parent.name)
                if not parent_ids or parent.name in _SKIPPED:
                    continue
                parent_pk = _single_pk(parent)
                if parent_pk is None:
                    continue
                if fk.column is parent_pk:
                    targets = select(pk).where(fk.parent.in_(parent_ids))
                else:
                    targets = select(pk).where(fk.parent.in_(select(fk.column).where(parent_pk.in_(parent_ids))))
                found = set(session.scalars(targets)) - doomed[table.name]
                if found:
                    doomed[table.name].update(found)
                    changed = True
    return {name: ids for name, ids in doomed.items() if ids}


def wipe(session: Session) -> dict[str, int]:
    """Delete every demo row and everything the simulated GP remembers. Returns the count per table. The
    caller commits."""
    doomed = demo_rows(session)
    tables = _tables()
    # Clear the nullable references between demo rows first. That is what lets two tables that point at
    # each other be deleted at all, and it costs nothing for the rest: the rows are about to go. A
    # reference a check constraint will not let go of (an inventory row has to say where it came from)
    # is left as it is, each in a savepoint of its own; the other side of the cycle lets go instead.
    for table in tables:
        pk = _single_pk(table)
        ids = doomed.get(table.name)
        if pk is None or not ids:
            continue
        for fk in table.foreign_keys:
            if fk.parent.nullable and doomed.get(fk.column.table.name):
                try:
                    with session.begin_nested():
                        session.execute(table.update().where(pk.in_(ids)).values({fk.parent.name: None}))
                except IntegrityError:
                    pass
    # Children first. The schema order is a good first guess but not a guarantee - the tables in a cycle
    # drop out of it - so a delete a remaining reference still blocks is put back for the next pass, in a
    # savepoint, until every pass deletes something or nothing is left. A pass that deletes nothing
    # while something remains is a reference this walk did not find, and that is raised.
    statements = []
    for table in reversed(tables):
        pk = _single_pk(table)
        if pk is not None:
            ids = doomed.get(table.name)
            if ids:
                statements.append((table.name, delete(table).where(pk.in_(ids))))
            continue
        # A table keyed on several columns (a read mark, say) is a leaf: its demo rows are the ones whose
        # foreign keys point at demo rows.
        clauses = []
        for fk in table.foreign_keys:
            parent_ids = doomed.get(fk.column.table.name)
            parent_pk = _single_pk(fk.column.table)
            if parent_ids and fk.column is parent_pk:
                clauses.append(fk.parent.in_(parent_ids))
        if clauses:
            statements.append((table.name, delete(table).where(or_(*clauses))))

    counts: dict[str, int] = {}
    while statements:
        blocked, last_error = [], None
        for name, statement in statements:
            try:
                with session.begin_nested():
                    counts[name] = counts.get(name, 0) + session.execute(statement).rowcount
            except IntegrityError as e:
                blocked.append((name, statement))
                last_error = e
        if len(blocked) == len(statements):
            raise last_error
        statements = blocked
    # The audit log names what an event was about by id rather than by foreign key, so a stock row's
    # history (which carries no project) is found by the ids of the rows deleted above.
    doomed_ids = {i for ids in doomed.values() for i in ids if isinstance(i, uuid.UUID)}
    if doomed_ids:
        audit = InventoryAuditLog.__table__
        counts[audit.name] = (
            counts.get(audit.name, 0) + session.execute(delete(audit).where(audit.c.entity_id.in_(doomed_ids))).rowcount
        )
    counts["demo_gp_records"] = demo_gp.wipe(session)
    return {name: n for name, n in counts.items() if n}


def has_demo_data() -> bool:
    """Whether the demo company has been seeded: it has projects once it has been."""
    with SessionLocal() as session:
        return session.scalar(select(Project.id).where(Project.company == DEMO_COMPANY).limit(1)) is not None


def _acquire_lock():
    """Take the reset lock on a connection of its own, or None when another reset holds it."""
    conn = engine.connect()
    if conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": _RESET_LOCK_KEY}).scalar():
        return conn
    conn.close()
    return None


def _release_lock(conn) -> None:
    try:
        conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _RESET_LOCK_KEY})
    finally:
        conn.close()


def _wipe_committed() -> dict[str, int]:
    with SessionLocal() as session:
        # The demo POs' documents are files in storage as well as rows; read their keys before the rows go.
        doomed_docs = demo_rows(session).get(PODocument.__tablename__) or set()
        keys = (
            list(session.scalars(select(PODocument.s3_key).where(PODocument.id.in_(doomed_docs))))
            if doomed_docs
            else []
        )
        counts = wipe(session)
        session.commit()
    for key in keys:
        # Best effort, after the commit: a file left behind is a few bytes nobody can reach, while a
        # storage hiccup must not cost the reset it ran inside.
        try:
            storage.delete_file(key)
        except Exception:  # noqa: BLE001
            logger.warning("demo reset: could not delete stored document %s", key)
    return counts


async def reset(*, only_if_empty: bool = False) -> bool:
    """Wipe the demo company and seed it again. One at a time: a second reset while one runs is refused
    rather than interleaved with it. `only_if_empty` seeds a demo company that has never been seeded
    and leaves one that has alone - the first entry into demo mode. Returns whether it seeded."""
    from app.services import demo_seed

    lock = await asyncio.to_thread(_acquire_lock)
    if lock is None:
        if only_if_empty:
            # Somebody else is seeding it right now; what they leave behind is the starting state.
            return False
        raise ConflictError("The demo data is being reset already. Wait a moment and reload.")
    try:
        if only_if_empty and await asyncio.to_thread(has_demo_data):
            return False
        counts = await asyncio.to_thread(_wipe_committed)
        logger.info("demo reset: wiped %s", counts)
        try:
            await demo_seed.seed()
        except Exception:
            # A seed that stops part way leaves a demo company nobody should walk into, and one that
            # has projects, so the next first entry would take it as seeded. Wiped again, the next
            # entry or reset seeds it from the start - and the error still reaches whoever asked.
            logger.exception("demo reset: the seed failed; wiping what it left")
            await asyncio.to_thread(_wipe_committed)
            raise
        logger.info("demo reset: seeded")
        return True
    finally:
        await asyncio.to_thread(_release_lock, lock)
