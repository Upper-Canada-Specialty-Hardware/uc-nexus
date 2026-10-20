"""Deliver the emails Clerk hands over, each exactly once (#1690).

The org's rule: every email to a ucsh.com address goes through ucsh-mailer. Clerk's "delivered by Clerk"
switch is per template, not per address, so once it is off every code for every address comes here, and
the ruling on #1690 is that an address outside the company goes out through SMTP2GO.

Which is which is the mailer's call, not a domain list kept here: every message is offered to ucsh-mailer
first, and only its `recipient_not_internal` refusal sends it to SMTP2GO. Any other mailer failure is
NOT retried through SMTP2GO - that would put mail for a ucsh.com address outside the mailer - so the
webhook answers with an error and Clerk retries it.

Once only: a transaction-scoped advisory lock on the Clerk email id holds a second delivery of the same
email (Clerk's retry while the first is still sending) until the first ends, then it finds the receipt
the first committed. The receipt is written only after the send succeeded, in the same transaction, so
a failed send leaves nothing behind and Clerk's retry sends it. The one gap is a send that succeeded
followed by a commit that failed: Clerk retries, and outside the mailer's ten-minute idempotency window
that mails it again. A second code is the right side to err on.
"""

import logging

from sqlalchemy import select, text

from app.database import SessionLocal
from app.models.clerk_email_delivery import ClerkEmailDelivery
from app.services import mailer, smtp2go
from app.services.clerk_email import ClerkEmail

logger = logging.getLogger(__name__)

# The two-key advisory lock's first key: this issue, so it cannot meet another lock's single bigint key.
_LOCK_NAMESPACE = 1690


class DeliveryError(Exception):
    """The email was not sent; the webhook answers with an error so Clerk retries it."""


def deliver(email: ClerkEmail) -> str:
    """Send `email` unless it was sent before. Returns 'sent' or 'duplicate'; raises DeliveryError."""
    with SessionLocal() as session, session.begin():
        session.execute(
            text("SELECT pg_advisory_xact_lock(:ns, hashtext(:id))"), {"ns": _LOCK_NAMESPACE, "id": email.email_id}
        )
        if session.scalar(select(ClerkEmailDelivery.clerk_email_id).filter_by(clerk_email_id=email.email_id)):
            return "duplicate"
        route = _send(email)
        session.add(ClerkEmailDelivery(clerk_email_id=email.email_id, route=route))
    # Logged by Clerk's id alone: the address and the code are the user's.
    logger.info("Clerk email %s sent through %s", email.email_id, route)
    return "sent"


def _send(email: ClerkEmail) -> str:
    try:
        mailer.send(
            to=[email.to],
            subject=email.subject,
            text=email.text,
            html=email.html,
            # Clerk's id is stable across its retries, so the mailer answers a retry with the first send.
            idempotency_key=f"nexus-clerk-{email.email_id}",
        )
        return "mailer"
    except mailer.MailerError as exc:
        if exc.code != mailer.RECIPIENT_NOT_INTERNAL:
            raise DeliveryError(f"ucsh-mailer did not send it: {exc}") from exc

    # TODO(#1769): SMTP2GO_API_KEY and SMTP2GO_SENDER are not set on production yet - the cutover went ahead
    # without them so ucsh.com codes reach ucsh-mailer now. Until they are, a code for an address outside the
    # company fails here and Clerk retries it. Set them (#1741) and remove this comment.
    try:
        smtp2go.send(to=email.to, subject=email.subject, text=email.text, html=email.html)
    except smtp2go.Smtp2goError as exc:
        raise DeliveryError(str(exc)) from exc
    return "smtp2go"
