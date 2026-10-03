"""Sending a PO to its vendor: off the event loop, and real failures flagged (#1277, #1278).

Nothing is sent and nothing reaches GP: the relay, storage and the mail service are all stubbed."""

import asyncio
import threading
import uuid

import pytest

from app import auth
from app.models.enums import PODocumentType, POStatus
from app.models.purchase_order import PODocument, PurchaseOrder
from app.repositories import user_repository
from app.schemas import po as po_module
from main import schema


class _FakeRequest:
    headers = {"authorization": "Bearer tok"}


@pytest.fixture
def world(db_session, monkeypatch):
    """A registered PO with a generated document, a signed-in caller, and every outside call stubbed.
    Each stub records the thread it ran on, so a test can tell whether it blocked the event loop."""
    monkeypatch.setattr(auth, "verify_clerk_token", lambda token: {"sub": "u_test"})
    monkeypatch.setattr(user_repository, "get_user_roles", lambda user_id: [])
    monkeypatch.setattr(user_repository, "get_user_company", lambda user_id: "TUBC")

    class _Borrowed:
        def __enter__(self):
            return db_session

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(po_module, "SessionLocal", _Borrowed)

    po = PurchaseOrder(
        id=uuid.uuid4(),
        request_number=f"PO-REQ-{uuid.uuid4().hex[:6]}",
        po_number=f"P{uuid.uuid4().hex[:6]}",
        status=POStatus.GP_REGISTERED,
        company="TUBC",
        gp_company="TUBC",
        gp_vendor_id="ACME",
    )
    db_session.add(po)
    db_session.flush()
    db_session.add(
        PODocument(
            id=uuid.uuid4(),
            po_id=po.id,
            file_name="po.pdf",
            content_type="application/pdf",
            file_size=10,
            document_type=PODocumentType.GENERATED_PO,
            s3_key=f"po/{po.id}/po.pdf",
        )
    )
    db_session.flush()

    state = {"threads": {}, "contact": {"email": "orders@acme.test", "contact_name": "Pat"}, "relay_error": None}

    async def _relay_call(company, op, payload=None, timeout=30.0):
        state["threads"]["loop"] = threading.get_ident()
        if state["relay_error"] is not None:
            raise state["relay_error"]
        return state["contact"]

    def _download(key):
        state["threads"]["download"] = threading.get_ident()
        if state.get("storage_error"):
            raise state["storage_error"]
        return b"%PDF"

    def _send(**kwargs):
        state["threads"]["send"] = threading.get_ident()
        if state.get("smtp_error"):
            raise state["smtp_error"]
        state["sent_to"] = kwargs["to"]

    monkeypatch.setattr(po_module.relay_gateway, "relay_call", _relay_call)
    monkeypatch.setattr(po_module.storage, "download_file", _download)
    monkeypatch.setattr(po_module.email_service, "send_email", _send)
    monkeypatch.setattr(po_module.email_service, "is_configured", lambda: True)
    state["po_id"] = str(po.id)
    return state


def _email(state):
    result = asyncio.run(
        schema.execute(
            "mutation($id: ID!) { emailPoToVendor(poId: $id) { sent failed message sentTo } }",
            variable_values={"id": state["po_id"]},
            context_value={
                "request": _FakeRequest(),
                "_auth_user_id": "u_test",
                "_auth_roles": [],
                "_auth_company": "TUBC",
            },
        )
    )
    assert result.errors is None, result.errors
    return result.data["emailPoToVendor"]


def test_the_download_and_the_send_run_off_the_event_loop(world):
    out = _email(world)
    assert out == {
        "sent": True,
        "failed": False,
        "message": out["message"],
        "sentTo": "orders@acme.test",
    }
    loop = world["threads"]["loop"]
    assert world["threads"]["download"] != loop
    assert world["threads"]["send"] != loop


def test_a_mail_server_failure_is_flagged_as_failed(world):
    world["smtp_error"] = po_module.email_service.EmailError("connection refused")
    out = _email(world)
    assert (out["sent"], out["failed"]) == (False, True)
    assert "connection refused" in out["message"]


def test_gp_unreachable_is_flagged_as_failed(world):
    from app.errors import RelayUnavailableError

    world["relay_error"] = RelayUnavailableError("no relay is currently connected")
    out = _email(world)
    assert (out["sent"], out["failed"]) == (False, True)


def test_a_document_storage_cannot_return_is_flagged_as_failed(world):
    world["storage_error"] = ConnectionError("bucket unreachable")
    out = _email(world)
    assert (out["sent"], out["failed"]) == (False, True)
    assert "sent_to" not in world


def test_a_missing_vendor_email_is_a_step_for_the_user_not_a_failure(world):
    world["contact"] = {"email": None}
    out = _email(world)
    assert (out["sent"], out["failed"]) == (False, False)
    assert "accounting" in out["message"]
