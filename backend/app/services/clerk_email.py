"""Clerk's email webhook: who sent it and what it asks to be sent (#1690).

Clerk generates and checks every sign-in code; Nexus only delivers them. With "delivered by Clerk"
turned off on a template, Clerk mails nothing for it and instead signs an `email.created` event to
`POST /webhooks/clerk/email` carrying the message it would have sent. This module authenticates that
event and pulls the message out of it. It never reads or checks the code inside the bodies, and it
touches neither the network nor the database: `clerk_email_delivery` sends what it returns.

The event is signed with Svix (Standard Webhooks is the same scheme under other header names): an
HMAC-SHA256 over `<id>.<timestamp>.<raw body>` keyed by the endpoint's `whsec_` secret, set on the
backend as `CLERK_WEBHOOK_SIGNING_SECRET`. A request that is unsigned, mixes the two header families,
is more than five minutes from now, or matches no signature is refused before anything is parsed.
"""

import base64
import binascii
import hashlib
import hmac
import json
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass

# Far above any email Clerk renders, and low enough that a flood of large bodies costs nothing.
MAX_BODY_BYTES = 256 * 1024
# Svix's own tolerance; it is what stops a captured request being replayed later.
MAX_SIGNATURE_AGE_SECONDS = 300


class WebhookAuthError(Exception):
    """The request is not a correctly signed Clerk event."""


class WebhookPayloadError(Exception):
    """The event is signed but not a message that can be sent."""


@dataclass(frozen=True)
class ClerkEmail:
    """One message Clerk has handed over to deliver."""

    email_id: str
    to: str
    subject: str
    html: str | None
    text: str | None


def signing_secret() -> str:
    return (os.getenv("CLERK_WEBHOOK_SIGNING_SECRET") or "").strip()


def signature_headers(headers: Mapping[str, str]) -> tuple[str, str, str]:
    """The id, timestamp and signatures from one complete header family, Svix or Standard Webhooks."""
    svix = tuple((headers.get(f"svix-{name}") or "").strip() for name in ("id", "timestamp", "signature"))
    standard = tuple((headers.get(f"webhook-{name}") or "").strip() for name in ("id", "timestamp", "signature"))
    if all(svix) and not any(standard):
        return svix
    if all(standard) and not any(svix):
        return standard
    raise WebhookAuthError("invalid webhook signature")


def verify_signature(
    raw_body: bytes, message_id: str, timestamp: str, signatures: str, secret: str, *, now: float | None = None
) -> None:
    """Raise WebhookAuthError unless one of `signatures` is the secret's v1 HMAC of this exact body."""
    if not secret.startswith("whsec_"):
        raise WebhookAuthError("invalid webhook signature")
    # Ten digits is every Unix second until 2286; the bound keeps a hostile header from being a huge int.
    if not (timestamp.isascii() and timestamp.isdecimal() and len(timestamp) <= 10):
        raise WebhookAuthError("invalid webhook signature")
    if abs(int(time.time() if now is None else now) - int(timestamp)) > MAX_SIGNATURE_AGE_SECONDS:
        raise WebhookAuthError("invalid webhook signature")
    try:
        key = base64.b64decode(secret.removeprefix("whsec_"), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise WebhookAuthError("invalid webhook signature") from exc
    if not key:
        raise WebhookAuthError("invalid webhook signature")

    expected = hmac.new(key, f"{message_id}.{timestamp}.".encode() + raw_body, hashlib.sha256).digest()
    # Space-separated, and more than one while the secret is being rotated.
    for candidate in signatures.split():
        version, _, encoded = candidate.partition(",")
        if version != "v1" or not encoded:
            continue
        try:
            supplied = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            continue
        if hmac.compare_digest(expected, supplied):
            return
    raise WebhookAuthError("invalid webhook signature")


def parse_event(raw_body: bytes) -> ClerkEmail | None:
    """The message to send, or None for an event that asks for nothing: another event type, or an email
    Clerk delivers itself. Raises WebhookPayloadError for an email that cannot be sent as it stands."""
    try:
        event = json.loads(raw_body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WebhookPayloadError("invalid webhook payload") from exc
    if not isinstance(event, dict):
        raise WebhookPayloadError("invalid webhook payload")
    if event.get("type") != "email.created":
        return None
    data = event.get("data")
    if not isinstance(data, dict) or data.get("object") != "email":
        raise WebhookPayloadError("invalid webhook payload")
    delivered_by_clerk = data.get("delivered_by_clerk")
    if delivered_by_clerk is True:
        # Clerk has sent this one; sending it again would mail it twice.
        return None
    if delivered_by_clerk is not False:
        raise WebhookPayloadError("invalid webhook payload")

    email_id = _text(data, "id", 255)
    to = _text(data, "to_email_address", 320)
    subject = _text(data, "subject", 998)
    # One address, and nothing that could become a second header line or a second recipient.
    if any(c.isspace() or c in ",;" for c in to) or to.count("@") != 1 or "" in to.split("@"):
        raise WebhookPayloadError("invalid webhook payload")
    if "\r" in subject or "\n" in subject:
        raise WebhookPayloadError("invalid webhook payload")
    html, text = _body(data, "body"), _body(data, "body_plain")
    if not (html and html.strip()) and not (text and text.strip()):
        raise WebhookPayloadError("invalid webhook payload")
    return ClerkEmail(email_id=email_id, to=to, subject=subject, html=html, text=text)


def _text(data: dict, key: str, limit: int) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise WebhookPayloadError("invalid webhook payload")
    return value


def _body(data: dict, key: str) -> str | None:
    value = data.get(key)
    if value is not None and not isinstance(value, str):
        raise WebhookPayloadError("invalid webhook payload")
    return value
