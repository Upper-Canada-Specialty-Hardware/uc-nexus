"""Outbound email (#500).

The only thing Nexus sends today is a purchase order to the vendor it was placed with. There was no
email capability in the backend at all before this, so the shape here is deliberately small: one
send function, SMTP config from the environment, and no queue.

Unconfigured means disabled. `SMTP_HOST` absent is not an error state - it is a deployment that has
not been given a mailbox yet, and every caller checks `is_configured()` and says so rather than
failing a user action over it. That also means a PR environment, which has no SMTP, never
accidentally mails a real vendor.
"""

import logging
import os
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

logger = logging.getLogger(__name__)


class EmailError(Exception):
    """The send was attempted and the server refused it."""


@dataclass(frozen=True)
class SmtpConfig:
    host: str
    port: int
    username: str | None
    password: str | None
    from_address: str
    use_tls: bool


def get_config() -> SmtpConfig | None:
    """The configured mailbox, or None when this deployment has none.

    from_address falls back to username because for a shared mailbox they are the same string, and
    getting one without the other is a misconfiguration nobody would notice until a send failed.
    """
    host = (os.getenv("SMTP_HOST") or "").strip()
    if not host:
        return None
    username = (os.getenv("SMTP_USERNAME") or "").strip() or None
    from_address = (os.getenv("SMTP_FROM_ADDRESS") or "").strip() or username
    if not from_address:
        logger.warning("SMTP_HOST is set but neither SMTP_FROM_ADDRESS nor SMTP_USERNAME is; email disabled")
        return None
    return SmtpConfig(
        host=host,
        port=int(os.getenv("SMTP_PORT") or 587),
        username=username,
        password=(os.getenv("SMTP_PASSWORD") or "").strip() or None,
        from_address=from_address,
        # Office 365 wants STARTTLS on 587. Opt out only for a local capture server.
        use_tls=(os.getenv("SMTP_USE_TLS") or "true").strip().lower() != "false",
    )


def is_configured() -> bool:
    return get_config() is not None


@dataclass(frozen=True)
class Attachment:
    file_name: str
    content_type: str
    content: bytes


def send_email(
    *,
    to: str,
    subject: str,
    body: str,
    attachments: list[Attachment] | None = None,
    cc: str | None = None,
) -> None:
    """Send one message. Raises EmailError if the server refuses it.

    Synchronous on purpose. The one caller is a user pressing a button and waiting for the outcome,
    and a queue would only move the failure somewhere nobody is looking.
    """
    config = get_config()
    if config is None:
        raise EmailError("Email is not configured on this deployment")

    message = EmailMessage()
    message["From"] = config.from_address
    message["To"] = to
    if cc:
        message["Cc"] = cc
    message["Subject"] = subject
    message.set_content(body)

    for attachment in attachments or []:
        maintype, _, subtype = attachment.content_type.partition("/")
        message.add_attachment(
            attachment.content,
            maintype=maintype or "application",
            subtype=subtype or "octet-stream",
            filename=attachment.file_name,
        )

    try:
        with smtplib.SMTP(config.host, config.port, timeout=30) as server:
            if config.use_tls:
                server.starttls()
            if config.username and config.password:
                server.login(config.username, config.password)
            server.send_message(message)
    except (smtplib.SMTPException, OSError) as exc:
        # The address is logged, the body is not: a PO document is commercial information.
        logger.warning("Email to %s failed: %s", to, exc)
        raise EmailError(str(exc)) from exc
