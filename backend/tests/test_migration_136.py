"""Migration 136 refuses to run over names that differ only by case (#1388)."""

import importlib.util
import pathlib
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import text

_PATH = (
    pathlib.Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "136_shipment_method_names_unique_case_insensitive.py"
)


def _migration():
    spec = importlib.util.spec_from_file_location("m136", _PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upgrade_names_the_clashing_spellings_and_stops(db_session, monkeypatch):
    m = _migration()
    conn = db_session.connection()
    # The index (already applied by the test database) would refuse the clash, so lift it for this
    # transaction only; the fixture rolls it all back.
    conn.execute(text("DROP INDEX uq_shipment_methods_company_lower_name"))
    for name in ("Flatbed", "flatbed"):
        conn.execute(
            text(
                "INSERT INTO shipment_methods (id, company, name, is_active, sort_order, created_at, updated_at) "
                "VALUES (:id, 'TUBX', :name, true, 0, now(), now())"
            ),
            {"id": uuid.uuid4(), "name": name},
        )
    monkeypatch.setattr(m, "op", SimpleNamespace(get_bind=lambda: conn))

    with pytest.raises(RuntimeError, match="TUBX: Flatbed, flatbed"):
        m.upgrade()
