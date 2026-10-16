"""Internal email through ucsh-mailer (#1677).

ucsh-mailer is the org's mail service: one HTTPS call, sent on through Microsoft 365. It delivers
inside the company and nowhere else, which is the org's rule for any mail to a ucsh.com address. A
vendor is outside, so the PO email (`app/services/email.py`, SMTP) is not this.

Two settings on the backend service: `MAILER_URL`, and `MAILER_KEY`, the key the mailer issued to the
nexus product. Unconfigured means disabled.
"""

import logging
import os
import time
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

# The mailer's own word for "try again": HVE was unreachable or deferred the message. Every other
# refusal (a bad key, an outside address, a reused idempotency key) fails the same way every time.
_RETRYABLE_STATUS = 503
_ATTEMPTS = 3
_RETRY_DELAY_SECONDS = 1.0


class MailerError(Exception):
    """The mailer refused the message or could not be reached."""


@dataclass(frozen=True)
class MailerConfig:
    url: str
    key: str


def get_config() -> MailerConfig | None:
    url = (os.getenv("MAILER_URL") or "").strip().rstrip("/")
    key = (os.getenv("MAILER_KEY") or "").strip()
    if not (url and key):
        return None
    return MailerConfig(url=url, key=key)


def is_configured() -> bool:
    return get_config() is not None


def send(*, to: list[str], subject: str, text: str, html: str | None = None, idempotency_key: str) -> None:
    """Send one message. Raises MailerError when it is not sent.

    `idempotency_key` makes a retry safe: within ten minutes the mailer answers the same key and body
    with the first result and sends nothing new, so the retries below can never mail twice.
    """
    config = get_config()
    if config is None:
        raise MailerError("Email is not configured on this deployment")
    body: dict = {"to": to, "subject": subject, "text": text}
    if html:
        body["html"] = html
    headers = {"Authorization": f"Bearer {config.key}", "Idempotency-Key": idempotency_key}

    last = "no attempt made"
    for attempt in range(1, _ATTEMPTS + 1):
        try:
            resp = httpx.post(f"{config.url}/v1/send", json=body, headers=headers, timeout=30.0)
        except httpx.HTTPError as exc:
            last = f"the mailer could not be reached: {exc}"
        else:
            if resp.status_code < 400:
                return
            try:
                error = resp.json().get("error") or resp.text
            except ValueError:
                error = resp.text
            last = f"the mailer refused it: {resp.status_code} {error}"
            if resp.status_code != _RETRYABLE_STATUS:
                break
        if attempt < _ATTEMPTS:
            time.sleep(_RETRY_DELAY_SECONDS * attempt)
    # The recipients are logged, the body is not: a report carries what a user typed.
    logger.warning("Mail to %s not sent: %s", ", ".join(to), last)
    raise MailerError(last)
