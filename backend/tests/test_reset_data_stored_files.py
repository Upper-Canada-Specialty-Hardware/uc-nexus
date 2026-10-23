"""#1925: /admin/reset-data deletes the stored files of the PO documents and shipment photos it drops.

No Postgres: the reset's flow runs against a fake engine with the drop, alembic and the restore stubbed,
and the key read runs against an in-memory SQLite copy of the two tables. Storage is faked throughout;
nothing here reaches a bucket."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, insert

from app.models.enums import PODocumentType, ShipmentPhotoKind
from app.models.purchase_order import PODocument
from app.models.shipment_photo import ShipmentPhoto


class _FakeConn:
    def __init__(self, events):
        self.events = events

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def execute(self, statement, *_args):
        self.events.append(f"execute {statement}")

    def commit(self):
        self.events.append("commit")


class _FakeEngine:
    def __init__(self, events):
        self.events = events

    def connect(self):
        return _FakeConn(self.events)


@pytest.fixture
def reset_flow(monkeypatch):
    """The reset with everything around the key read and the deletes stubbed, recording what happened
    in order."""
    import alembic.command

    import app.config
    import app.database
    import main
    from app.services import reset_preservation, storage

    events: list[str] = []
    monkeypatch.setattr(app.config, "TESTING_ENABLED", True, raising=False)
    monkeypatch.setattr(main, "require_admin_request", lambda _request: None)
    monkeypatch.setattr(main, "_acquire_reset_lock", lambda: object())
    monkeypatch.setattr(main, "_release_reset_lock", lambda _conn: events.append("unlock"))
    monkeypatch.setattr(app.database, "engine", _FakeEngine(events))
    monkeypatch.setattr(reset_preservation, "snapshot", lambda _conn: events.append("snapshot"))
    monkeypatch.setattr(main, "_stored_file_keys", lambda _conn: events.append("keys") or ["po/a.pdf", "photos/b.jpg"])
    monkeypatch.setattr(alembic.command, "upgrade", lambda *_a: events.append("upgrade"))
    monkeypatch.setattr(reset_preservation, "restore", lambda _conn, _snap: events.append("restore") or {})
    monkeypatch.setattr(main.gp_job_sync, "run_once_blocking", lambda: None)

    def _delete(key):
        events.append(f"delete {key}")
        if key == "po/a.pdf":
            raise RuntimeError("storage is unwell")

    monkeypatch.setattr(storage, "delete_file", _delete)
    return TestClient(main.app), events


def test_the_dropped_rows_files_are_deleted_after_the_restore(reset_flow):
    client, events = reset_flow

    resp = client.post("/admin/reset-data")

    assert resp.status_code == 200
    # The keys are read before the drop, and the files go only once the rebuild has committed.
    assert events.index("keys") < next(i for i, e in enumerate(events) if "DROP SCHEMA" in e)
    assert events.index("delete po/a.pdf") > events.index("restore")
    assert events.index("delete po/a.pdf") > events.index("unlock")
    # A storage failure on one file neither stops the next nor fails the reset.
    assert "delete photos/b.jpg" in events


def _sqlite_with(*models):
    engine = create_engine("sqlite://")
    for model in models:
        model.__table__.create(engine)
    return engine


def test_the_keys_are_read_from_documents_and_photos():
    import main

    engine = _sqlite_with(PODocument, ShipmentPhoto)
    with engine.begin() as conn:
        conn.execute(
            insert(PODocument.__table__).values(
                id=uuid.uuid4(),
                po_id=uuid.uuid4(),
                file_name="slip.pdf",
                content_type="application/pdf",
                file_size=10,
                document_type=PODocumentType.PO_DOCUMENT,
                s3_key="po-documents/slip.pdf",
            )
        )
        conn.execute(
            insert(ShipmentPhoto.__table__).values(
                id=uuid.uuid4(),
                project_id=uuid.uuid4(),
                container_id=uuid.uuid4(),
                kind=ShipmentPhotoKind.LOADING,
                s3_key="shipment-photos/load.jpg",
                file_name="load.jpg",
                content_type="image/jpeg",
                file_size=10,
                taken_by="Floor",
            )
        )

    with engine.connect() as conn:
        assert sorted(main._stored_file_keys(conn)) == ["po-documents/slip.pdf", "shipment-photos/load.jpg"]


def test_a_table_the_database_does_not_have_yet_is_skipped():
    import main

    engine = _sqlite_with(PODocument)
    with engine.connect() as conn:
        assert main._stored_file_keys(conn) == []
