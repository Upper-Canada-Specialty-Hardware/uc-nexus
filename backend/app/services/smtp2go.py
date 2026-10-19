"""Email to addresses outside the company, through SMTP2GO (#1690).

ucsh-mailer delivers inside the company and nowhere else, so a sign-in code for any other address goes
out here instead, as uc-velocity's do. Two settings on the backend service: `SMTP2GO_API_KEY`, and
`SMTP2GO_SENDER`, the approved sender (`UC Nexus <someone@approved-domain>`). Unconfigured means
disabled. Nothing that reaches a ucsh.com address may come through here: that is ucsh-mailer's.
"""

import logging
import os
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

_ENDPOINT = "https://api.smtp2go.com/v3/email/send"
# A webhook is waiting on this, and Clerk retries one that fails.
_TIMEOUT_SECONDS = 10.0


class Smtp2goError(Exception):
    """SMTP2GO did not accept the message, or could not be reached."""


@dataclass(frozen=True)
class Smtp2goConfig:
    api_key: str
    sender: str


def get_config() -> Smtp2goConfig | None:
    api_key = (os.getenv("SMTP2GO_API_KEY") or "").strip()
    sender = (os.getenv("SMTP2GO_SENDER") or "").strip()
    if not (api_key and sender):
        return None
    return Smtp2goConfig(api_key=api_key, sender=sender)


def is_configured() -> bool:
    return get_config() is not None


def send(*, to: str, subject: str, text: str | None, html: str | None) -> None:
    """Send one message to one address. Raises Smtp2goError unless SMTP2GO accepted exactly it."""
    config = get_config()
    if config is None:
        raise Smtp2goError("SMTP2GO is not configured on this deployment")
    body: dict = {"sender": config.sender, "to": [to], "subject": subject}
    if text:
        body["text_body"] = text
    if html:
        body["html_body"] = html
    # The key goes in a header, not the body, so a logged request body could never carry it.
    headers = {"X-Smtp2go-Api-Key": config.api_key}

    try:
        resp = httpx.post(_ENDPOINT, json=body, headers=headers, timeout=_TIMEOUT_SECONDS)
    except httpx.HTTPError as exc:
        logger.warning("SMTP2GO could not be reached: %s", type(exc).__name__)
        raise Smtp2goError("SMTP2GO could not be reached") from exc
    try:
        result = resp.json()
    except ValueError:
        result = None
    data = result.get("data") if isinstance(result, dict) else None
    data = data if isinstance(data, dict) else {}
    if resp.status_code >= 400 or data.get("succeeded") != 1 or data.get("failed") != 0:
        # The status and SMTP2GO's own error code only: its error text can quote the message back.
        logger.warning(
            "SMTP2GO did not accept the message: http %s, error code %s",
            resp.status_code,
            data.get("error_code") or "-",
        )
        raise Smtp2goError(f"SMTP2GO did not accept the message ({resp.status_code})")
