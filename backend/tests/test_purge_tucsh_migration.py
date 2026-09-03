"""Migration 105 removes TUCSH and only TUCSH. DB-backed (db_session).

The purge is exercised through the migration module's own `purge()` rather than through
`alembic upgrade`, because the schema the fixture runs against is already at head. The module is
loaded by path: `alembic/versions/` is not a package, so there is no import name for it.

The second company in here is the whole test. A delete scoped to the wrong thing still passes every
assertion about the rows that went; only a row that had to survive can catch it.
"""

import importlib.util
import uuid
from decimal import Decimal
from pathlib import Path

import sqlalchemy as sa

from app.models.enums import POStatus
from app.models.gp_po_sync_state import GpPoSyncState
from app.models.purchase_order import POLineItem, PurchaseOrder

OTHER = "UCSH"

_MIGRATION_PATH = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "105_purge_tucsh_rows.py"


def _load_migration():
    spec = importlib.util.spec_from_file_location("alembic_version_105", _MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load_migration()


def _po(company: str, po_number: str) -> PurchaseOrder:
    return PurchaseOrder(
        id=uuid.uuid4(),
        company=company,
        gp_company=company,
        po_number=po_number,
        status=POStatus.GP_REGISTERED,
    )


def _line(po: PurchaseOrder) -> POLineItem:
    return POLineItem(
        id=uuid.uuid4(),
        po_id=po.id,
        hardware_category="HINGE",
        product_code="TA2714",
        ordered_quantity=4,
        unit_cost=Decimal("12.5000"),
    )


def _exists(db_session, table: str, row_id) -> bool:
    return db_session.execute(sa.text(f"SELECT 1 FROM {table} WHERE id = :id"), {"id": row_id}).first() is not None


def test_purge_removes_tucsh_and_leaves_the_other_company(db_session):
    doomed = _po(migration.COMPANY, "0009001")
    kept = _po(OTHER, "0009002")
    doomed_line = _line(doomed)
    kept_line = _line(kept)
    sync_state = GpPoSyncState(id=uuid.uuid4(), company=migration.COMPANY, backfill_cursor="0009001")
    db_session.add_all([doomed, kept, doomed_line, kept_line, sync_state])
    db_session.flush()

    counts = migration.purge(db_session.connection())

    assert not _exists(db_session, "purchase_orders", doomed.id)
    assert not _exists(db_session, "po_line_items", doomed_line.id)
    assert not _exists(db_session, "gp_po_sync_state", sync_state.id)

    assert _exists(db_session, "purchase_orders", kept.id)
    assert _exists(db_session, "po_line_items", kept_line.id)

    assert counts["purchase_orders"] == 1
    assert counts["po_line_items"] == 1
    assert counts["gp_po_sync_state"] == 1


def test_purge_is_idempotent(db_session):
    doomed = _po(migration.COMPANY, "0009003")
    db_session.add_all([doomed, _line(doomed), GpPoSyncState(id=uuid.uuid4(), company=migration.COMPANY)])
    db_session.flush()

    migration.purge(db_session.connection())
    second = migration.purge(db_session.connection())

    assert set(second.values()) == {0}
