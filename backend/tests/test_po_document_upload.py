"""PO document upload: size, decoding, served type, key name, and no orphaned objects (#1233, #1235).

Storage is stubbed throughout; nothing reaches the bucket."""

import base64
import uuid

import pytest

from app.errors import ValidationError
from app.models.enums import PODocumentType, POStatus
from app.models.purchase_order import PurchaseOrder
from app.repositories import po_repository
from app.services import storage


@pytest.fixture
def bucket(monkeypatch):
    stored, deleted = {}, []

    def _upload(key, data, content_type, *, as_attachment=False):
        stored[key] = {"size": len(data), "type": content_type, "attachment": as_attachment}
        return key

    monkeypatch.setattr(storage, "upload_file", _upload)
    monkeypatch.setattr(storage, "delete_file", lambda key: deleted.append(key))
    return stored, deleted


def _po(session) -> PurchaseOrder:
    po = PurchaseOrder(
        id=uuid.uuid4(),
        request_number=f"PO-REQ-{uuid.uuid4().hex[:6]}",
        status=POStatus.GP_REGISTERED,
        company="TUBC",
    )
    session.add(po)
    session.flush()
    return po


def _upload(session, po, data=b"%PDF-1.7 test", content_type="application/pdf", name="quote.pdf", raw=None):
    return po_repository.upload_po_document(
        session,
        po.id,
        name,
        content_type,
        PODocumentType.MISCELLANEOUS,
        raw if raw is not None else base64.b64encode(data).decode(),
    )


def test_a_pdf_keeps_its_type_and_is_not_forced_to_download(db_session, bucket):
    stored, _ = bucket
    doc = _upload(db_session, _po(db_session))
    assert doc.content_type == "application/pdf"
    assert stored[doc.s3_key] == {"size": 13, "type": "application/pdf", "attachment": False}


@pytest.mark.parametrize("content_type", ["text/html", "image/svg+xml", "application/x-msdownload", ""])
def test_an_unlisted_type_is_stored_as_a_download(db_session, bucket, content_type):
    stored, _ = bucket
    doc = _upload(db_session, _po(db_session), content_type=content_type, name="page.html")
    assert doc.content_type == "application/octet-stream"
    assert stored[doc.s3_key]["attachment"] is True


def test_the_storage_key_name_is_sanitised_and_the_row_keeps_the_original(db_session, bucket):
    po = _po(db_session)
    doc = _upload(db_session, po, name="../../evil dir/Quote #12 (final).pdf")
    assert doc.file_name == "../../evil dir/Quote #12 (final).pdf"
    prefix = f"po-documents/{po.id}/{doc.id}_"
    assert doc.s3_key.startswith(prefix)
    tail = doc.s3_key[len(prefix) :]
    assert tail == "evil_dir_Quote_12_final_.pdf"
    assert "/" not in tail and ".." not in tail


@pytest.mark.parametrize("raw", ["not base64!!", "QUJD\nRA==", "QUJ"])
def test_malformed_base64_is_a_field_error(db_session, bucket, raw):
    stored, _ = bucket
    with pytest.raises(ValidationError) as e:
        _upload(db_session, _po(db_session), raw=raw)
    assert e.value.field == "file_data_base64"
    assert stored == {}


def test_an_empty_file_is_refused(db_session, bucket):
    with pytest.raises(ValidationError):
        _upload(db_session, _po(db_session), raw="")


def test_an_oversized_file_is_refused_before_decoding(db_session, bucket, monkeypatch):
    stored, _ = bucket
    monkeypatch.setattr(po_repository, "MAX_PO_DOCUMENT_BYTES", 10)
    with pytest.raises(ValidationError) as e:
        _upload(db_session, _po(db_session), data=b"x" * 11)
    assert e.value.field == "file_data_base64"
    assert stored == {}
    # Exactly at the cap still goes through.
    assert _upload(db_session, _po(db_session), data=b"x" * 10).file_size == 10


def test_a_failure_after_the_upload_removes_the_object(db_session, bucket, monkeypatch):
    stored, deleted = bucket

    def _boom(*a, **k):
        raise RuntimeError("row could not be built")

    monkeypatch.setattr(po_repository, "PODocument", _boom)
    with pytest.raises(RuntimeError):
        _upload(db_session, _po(db_session))
    assert len(stored) == 1
    assert deleted == list(stored)


def test_discard_never_raises(monkeypatch):
    def _down(key):
        raise ConnectionError("bucket unreachable")

    monkeypatch.setattr(storage, "delete_file", _down)
    po_repository.discard_uploaded_file("po-documents/x/y.pdf")  # logged, not raised


def test_the_resolver_removes_the_object_when_the_commit_fails(db_session, bucket, monkeypatch):
    """#1235: the object goes in before the commit; a commit that fails must not leave it behind."""
    import asyncio

    from app import auth
    from app.repositories import user_repository
    from app.schemas import po as po_module
    from main import schema

    stored, deleted = bucket
    monkeypatch.setattr(auth, "verify_clerk_token", lambda token: {"sub": "u_test"})
    monkeypatch.setattr(user_repository, "get_user_roles", lambda user_id: [])
    monkeypatch.setattr(user_repository, "get_user_company", lambda user_id: "TUBC")

    class _Borrowed:
        def __enter__(self):
            return db_session

        def __exit__(self, *exc):
            return False

    def _commit_fails():
        raise RuntimeError("commit failed")

    po = _po(db_session)
    monkeypatch.setattr(po_module, "SessionLocal", _Borrowed)
    monkeypatch.setattr(db_session, "commit", _commit_fails)

    class _FakeRequest:
        headers = {"authorization": "Bearer tok"}

    result = asyncio.run(
        schema.execute(
            """mutation($po: ID!, $data: String!) {
                uploadPoDocument(poId: $po, fileName: "q.pdf", contentType: "application/pdf",
                                 documentType: MISCELLANEOUS, fileDataBase64: $data) { id }
            }""",
            variable_values={"po": str(po.id), "data": base64.b64encode(b"%PDF").decode()},
            context_value={
                "request": _FakeRequest(),
                "_auth_user_id": "u_test",
                "_auth_roles": [],
                "_auth_company": "TUBC",
            },
        )
    )
    assert result.errors
    assert len(stored) == 1
    assert deleted == list(stored)
