"""Clerk's sign-in code emails, delivered by Nexus (#1690).

The signature and the payload are pure functions; the route is driven through TestClient with delivery
stood in for; delivery itself runs against the test database with ucsh-mailer stood in for, so nothing
here ever reaches a mail service.
"""

import base64
import hashlib
import hmac
import json
import time
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from app.services import clerk_email, clerk_email_delivery, mailer

SECRET = "whsec_" + base64.b64encode(b"k" * 32).decode()


def _sign(raw: bytes, *, message_id="msg_1", timestamp=None, secret=SECRET) -> dict:
    timestamp = str(int(time.time()) if timestamp is None else timestamp)
    key = base64.b64decode(secret.removeprefix("whsec_"))
    digest = hmac.new(key, f"{message_id}.{timestamp}.".encode() + raw, hashlib.sha256).digest()
    return {
        "svix-id": message_id,
        "svix-timestamp": timestamp,
        "svix-signature": "v1," + base64.b64encode(digest).decode(),
    }


def _event(**data) -> bytes:
    email = {
        "object": "email",
        "id": "ema_1",
        "to_email_address": "alice@ucsh.com",
        "subject": "123456 is your verification code",
        "body": "<p>123456</p>",
        "body_plain": "123456",
        "delivered_by_clerk": False,
        "slug": "verification_code",
    }
    email.update(data)
    return json.dumps({"type": "email.created", "object": "event", "data": email}).encode()


# --- the signature ----------------------------------------------------------------------------------


def _verify(raw, headers, **kwargs):
    clerk_email.verify_signature(raw, *clerk_email.signature_headers(headers), SECRET, **kwargs)


def test_a_correct_signature_passes():
    raw = _event()
    _verify(raw, _sign(raw))


def test_a_rotated_secret_still_matches_its_second_signature():
    raw = _event()
    headers = _sign(raw)
    headers["svix-signature"] = "v1,bm90LWl0 " + headers["svix-signature"]
    _verify(raw, headers)


@pytest.mark.parametrize(
    "tamper",
    [
        lambda raw, h: (raw + b" ", h),
        lambda raw, h: (raw, {**h, "svix-id": "msg_2"}),
        lambda raw, h: (raw, {**h, "svix-signature": "v2," + h["svix-signature"][3:]}),
        lambda raw, h: (raw, _sign(raw, secret="whsec_" + base64.b64encode(b"x" * 32).decode())),
        lambda raw, h: (raw, _sign(raw, timestamp=int(time.time()) - 301)),
        lambda raw, h: (raw, _sign(raw, timestamp=int(time.time()) + 301)),
        lambda raw, h: (raw, {**h, "svix-timestamp": "1" * 11}),
        lambda raw, h: (raw, {**h, "svix-timestamp": "-5"}),
    ],
    ids=["body", "id", "version", "other-secret", "stale", "future", "huge-timestamp", "negative-timestamp"],
)
def test_anything_but_the_exact_signed_request_is_refused(tamper):
    raw, headers = tamper(_event(), _sign(_event()))
    with pytest.raises(clerk_email.WebhookAuthError):
        _verify(raw, headers)


def test_the_standard_webhooks_headers_are_the_same_scheme():
    raw = _event()
    headers = {k.replace("svix-", "webhook-"): v for k, v in _sign(raw).items()}
    _verify(raw, headers)


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"svix-id": "msg_1", "svix-timestamp": "1"},
        {"svix-id": "msg_1", "svix-timestamp": "1", "svix-signature": "v1,x", "webhook-id": "msg_1"},
    ],
    ids=["unsigned", "incomplete", "mixed"],
)
def test_an_unsigned_incomplete_or_mixed_header_set_is_refused(headers):
    with pytest.raises(clerk_email.WebhookAuthError):
        clerk_email.signature_headers(headers)


def test_a_secret_that_is_not_a_whsec_is_refused():
    raw = _event()
    with pytest.raises(clerk_email.WebhookAuthError):
        clerk_email.verify_signature(raw, *clerk_email.signature_headers(_sign(raw)), "not-a-secret")


# --- the payload ------------------------------------------------------------------------------------


def test_the_message_is_clerks_own_subject_and_bodies():
    assert clerk_email.parse_event(_event()) == clerk_email.ClerkEmail(
        email_id="ema_1",
        to="alice@ucsh.com",
        subject="123456 is your verification code",
        html="<p>123456</p>",
        text="123456",
    )


def test_an_email_clerk_delivers_itself_and_other_events_ask_for_nothing():
    assert clerk_email.parse_event(_event(delivered_by_clerk=True)) is None
    assert clerk_email.parse_event(json.dumps({"type": "user.created", "data": {}}).encode()) is None


@pytest.mark.parametrize(
    "raw",
    [
        b"not json",
        b"[]",
        _event(delivered_by_clerk=None),
        _event(to_email_address="a@ucsh.com, b@ucsh.com"),
        _event(to_email_address="a@ucsh.com\r\nBcc: b@ucsh.com"),
        _event(to_email_address="nobody"),
        _event(to_email_address="@ucsh.com"),
        _event(subject="code\r\nBcc: b@ucsh.com"),
        _event(body=None, body_plain="  "),
        _event(body=5),
        _event(id=""),
    ],
    ids=[
        "json",
        "shape",
        "delivery-unsaid",
        "two-recipients",
        "header-in-address",
        "no-at",
        "no-local",
        "header-in-subject",
        "no-body",
        "body-type",
        "no-id",
    ],
)
def test_a_message_that_cannot_be_sent_as_it_stands_is_refused(raw):
    with pytest.raises(clerk_email.WebhookPayloadError):
        clerk_email.parse_event(raw)


def test_a_text_only_message_is_fine():
    assert clerk_email.parse_event(_event(body=None)).text == "123456"


# --- the route --------------------------------------------------------------------------------------


@pytest.fixture
def client(monkeypatch):
    import main

    monkeypatch.setenv("CLERK_WEBHOOK_SIGNING_SECRET", SECRET)
    delivered = []

    def _deliver(email):
        delivered.append(email)
        return "sent"

    monkeypatch.setattr(clerk_email_delivery, "deliver", _deliver)
    test_client = TestClient(main.app)
    test_client.delivered = delivered
    return test_client


def _post(client, raw, headers):
    return client.post("/webhooks/clerk/email", content=raw, headers={"content-type": "application/json", **headers})


def test_a_signed_code_is_delivered(client):
    raw = _event()
    resp = _post(client, raw, _sign(raw))
    assert resp.status_code == 200 and resp.json() == {"status": "sent"}
    assert [e.email_id for e in client.delivered] == ["ema_1"]


def test_a_bad_signature_sends_nothing(client):
    raw = _event()
    resp = _post(client, raw + b" ", _sign(raw))
    assert resp.status_code == 401
    assert client.delivered == []


def test_a_bad_payload_sends_nothing(client):
    raw = _event(to_email_address="nobody")
    resp = _post(client, raw, _sign(raw))
    assert resp.status_code == 400
    assert client.delivered == []


def test_an_email_clerk_sent_itself_is_acknowledged_and_not_sent(client):
    raw = _event(delivered_by_clerk=True)
    resp = _post(client, raw, _sign(raw))
    assert resp.status_code == 200 and resp.json() == {"status": "ignored"}
    assert client.delivered == []


def test_an_outside_address_is_acknowledged_so_clerk_stops_retrying(client, monkeypatch):
    monkeypatch.setattr(clerk_email_delivery, "deliver", lambda email: "not_internal")
    raw = _event()
    resp = _post(client, raw, _sign(raw))
    assert resp.status_code == 200 and resp.json() == {"status": "not_internal"}


def test_an_oversized_body_is_refused_unread(client):
    raw = b"x" * (clerk_email.MAX_BODY_BYTES + 1)
    resp = _post(client, raw, _sign(raw))
    assert resp.status_code == 413
    assert client.delivered == []


def test_without_a_signing_secret_nothing_is_accepted(client, monkeypatch):
    monkeypatch.delenv("CLERK_WEBHOOK_SIGNING_SECRET")
    raw = _event()
    resp = _post(client, raw, _sign(raw))
    assert resp.status_code == 503
    assert client.delivered == []


def test_a_failed_send_answers_an_error_so_clerk_retries(client, monkeypatch):
    def _fail(email):
        raise clerk_email_delivery.DeliveryError("ucsh-mailer did not send it")

    monkeypatch.setattr(clerk_email_delivery, "deliver", _fail)
    raw = _event()
    assert _post(client, raw, _sign(raw)).status_code == 502


# --- the senders ------------------------------------------------------------------------------------


@pytest.fixture
def senders(monkeypatch):
    """ucsh-mailer stood in for. `mailer_refuses` is the mailer's error code for the next send; anything
    posted elsewhere lands in `elsewhere`, which must stay empty."""
    monkeypatch.setenv("MAILER_URL", "https://mailer.example")
    monkeypatch.setenv("MAILER_KEY", "ucshm_nexus_test")
    monkeypatch.setattr(mailer.time, "sleep", lambda seconds: None)
    state = {"mailer": [], "elsewhere": [], "mailer_refuses": None}

    def _post(url, *, json, headers, timeout):
        if not url.startswith("https://mailer.example"):
            state["elsewhere"].append(url)
            return httpx.Response(200, json={})
        state["mailer"].append({"json": json, "headers": headers})
        code = state["mailer_refuses"]
        if code:
            return httpx.Response(503 if code == "hve_unavailable" else 400, json={"error": code})
        return httpx.Response(200, json={"status": "sent"})

    monkeypatch.setattr(httpx, "post", _post)
    return state


def test_the_mailer_error_carries_its_code(senders):
    senders["mailer_refuses"] = "recipient_not_internal"
    with pytest.raises(mailer.MailerError) as caught:
        mailer.send(to=["bob@example.test"], subject="s", text="t", idempotency_key="k1")
    assert caught.value.code == "recipient_not_internal"


def test_a_caller_with_its_own_retries_asks_for_one_try(senders):
    senders["mailer_refuses"] = "hve_unavailable"
    with pytest.raises(mailer.MailerError):
        mailer.send(to=["bob@example.test"], subject="s", text="t", idempotency_key="k1", attempts=1)
    assert len(senders["mailer"]) == 1


# --- delivery, against the database -----------------------------------------------------------------


@pytest.fixture
def email(_migrate_database):
    """A Clerk email with an id of its own, and its receipt removed again afterwards."""
    from app.database import SessionLocal
    from app.models.clerk_email_delivery import ClerkEmailDelivery

    message = clerk_email.ClerkEmail(
        email_id=f"ema_test_{uuid.uuid4().hex}", to="alice@ucsh.com", subject="s", html="<p>t</p>", text="t"
    )
    yield message
    with SessionLocal() as session, session.begin():
        session.query(ClerkEmailDelivery).filter_by(clerk_email_id=message.email_id).delete()


def _receipt(email_id):
    from app.database import SessionLocal
    from app.models.clerk_email_delivery import ClerkEmailDelivery

    with SessionLocal() as session:
        row = session.get(ClerkEmailDelivery, email_id)
        return row.route if row else None


def test_a_ucsh_address_goes_through_the_mailer_once(senders, email):
    assert clerk_email_delivery.deliver(email) == "sent"
    assert clerk_email_delivery.deliver(email) == "duplicate"

    [request] = senders["mailer"]
    assert request["json"]["to"] == ["alice@ucsh.com"]
    assert request["headers"]["Idempotency-Key"] == f"nexus-clerk-{email.email_id}"
    assert senders["elsewhere"] == []
    assert _receipt(email.email_id) == "mailer"


def test_an_outside_address_is_sent_nowhere(senders, email):
    """Codes are for ucsh.com users only (#1810): the mailer's refusal ends it, with nothing kept."""
    senders["mailer_refuses"] = "recipient_not_internal"

    assert clerk_email_delivery.deliver(email) == "not_internal"

    assert len(senders["mailer"]) == 1
    assert senders["elsewhere"] == []
    assert _receipt(email.email_id) is None


def test_a_mailer_outage_is_never_sent_around_it(senders, email):
    """Mail for a ucsh.com address goes through the mailer or not at all; Clerk retries it."""
    senders["mailer_refuses"] = "hve_unavailable"

    with pytest.raises(clerk_email_delivery.DeliveryError):
        clerk_email_delivery.deliver(email)

    assert senders["elsewhere"] == []
    assert _receipt(email.email_id) is None


def test_the_webhook_tries_the_mailer_once_and_leaves_the_retrying_to_clerk(senders, email):
    """#1828: it runs inside the transaction holding the lock, so three slow tries held a connection."""
    senders["mailer_refuses"] = "hve_unavailable"

    with pytest.raises(clerk_email_delivery.DeliveryError):
        clerk_email_delivery.deliver(email)

    assert len(senders["mailer"]) == 1


def test_a_failed_send_leaves_no_receipt_so_the_retry_sends(senders, email):
    senders["mailer_refuses"] = "hve_unavailable"
    with pytest.raises(clerk_email_delivery.DeliveryError):
        clerk_email_delivery.deliver(email)
    assert _receipt(email.email_id) is None

    senders["mailer_refuses"] = None
    assert clerk_email_delivery.deliver(email) == "sent"
    assert _receipt(email.email_id) == "mailer"
