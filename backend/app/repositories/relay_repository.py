"""Relay install provisioning + enrollment + credential lookup.

Trust model: the Railway backend cannot reach the relay (it binds to localhost on a workstation), but
the relay CAN reach the backend. So provisioning mints a one-time enrollment token (shown once in the
UC Nexus admin UI); the relay, during its one-time setup, generates its OWN long-lived Bearer secret and
registers it here with that token. Nothing long-lived is ever hand-copied."""

import logging
import secrets
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.crypto import decrypt_secret, encrypt_secret, hash_token
from app.errors import ConflictError, ValidationError
from app.models.relay_install import RelayInstall

logger = logging.getLogger(__name__)

_ENROLLMENT_TTL = timedelta(hours=24)


def list_installs(session: Session) -> list[RelayInstall]:
    return list(session.scalars(select(RelayInstall).order_by(RelayInstall.created_at.desc())).all())


def provision_install(session: Session, label: str, company: str) -> tuple[RelayInstall, str]:
    """Create an install row + a one-time enrollment token. Returns (install, raw_token); the raw token
    is shown to the admin ONCE and only its hash is stored."""
    label = (label or "").strip()
    company = (company or "").strip()
    if not label:
        raise ValidationError("label is required", field="label")
    if not company:
        raise ValidationError("company is required", field="company")

    token = secrets.token_urlsafe(32)
    install = RelayInstall(
        id=uuid.uuid4(),
        label=label,
        company=company,
        enrollment_token_hash=hash_token(token),
        enrollment_token_expires_at=datetime.utcnow() + _ENROLLMENT_TTL,
    )
    session.add(install)
    session.flush()
    return install, token


def enroll_install(session: Session, enrollment_token: str, hostname: str, secret: str) -> RelayInstall:
    """Called by the relay (authenticated by the enrollment token, not Clerk). Stores the relay's
    self-generated secret encrypted; the token is single-use (a second attempt is rejected as
    already-used via the enrolled_at guard)."""
    secret = (secret or "").strip()
    if not secret:
        raise ValidationError("secret is required", field="secret")

    install = session.scalars(
        select(RelayInstall).where(RelayInstall.enrollment_token_hash == hash_token(enrollment_token))
    ).first()
    if install is None:
        raise ValidationError("invalid enrollment token", field="enrollment_token")
    if install.enrolled_at is not None:
        raise ConflictError("this enrollment token has already been used", field="enrollment_token")
    if install.enrollment_token_expires_at and install.enrollment_token_expires_at < datetime.utcnow():
        raise ValidationError("enrollment token has expired", field="enrollment_token")

    now = datetime.utcnow()
    install.hostname = (hostname or "").strip() or None
    install.secret_encrypted = encrypt_secret(secret)
    install.enrolled_at = now
    install.last_seen_at = now
    # single use is enforced by the enrolled_at guard above: a second attempt with the same token finds
    # this now-enrolled row and is rejected as already-used. (Keeping the hash makes that a clear error
    # rather than a generic "invalid token".)
    session.flush()
    return install


def authenticate_secret(session: Session, secret: str) -> RelayInstall | None:
    """Verify a Bearer secret presented on the outbound WS channel's connect handshake against the
    enrolled installs. Secrets are Fernet-encrypted (reversible, not hashed), so this decrypts each
    enrolled install's secret and compares in constant time. POC scale (a handful
    of installs) makes the linear scan fine. Returns None on no match instead of raising - the caller
    (the /relay-link route) treats that as a clean close, same as a bad token anywhere else here."""
    secret = (secret or "").strip()
    if not secret:
        return None
    installs = session.scalars(select(RelayInstall).where(RelayInstall.secret_encrypted.is_not(None))).all()
    undecryptable = 0
    for install in installs:
        try:
            candidate = decrypt_secret(install.secret_encrypted)
        except Exception:
            # A row whose stored secret will not decrypt is NOT a wrong-secret case: it means
            # RELAY_SECRET_ENC_KEY is missing or has been rotated since enrolment. Swallowing that
            # silently makes a config error indistinguishable from a stale relay secret - both just
            # 403 the handshake forever with nothing in the log. Count it and say so below.
            undecryptable += 1
            logger.warning(
                "relay install secret failed to decrypt - RELAY_SECRET_ENC_KEY is missing or was rotated "
                "since this install enrolled; re-enrolment will not fix it until the key is restored",
                extra={"install_id": str(install.id), "label": install.label, "hostname": install.hostname},
            )
            continue
        if secrets.compare_digest(candidate, secret):
            install.last_seen_at = datetime.utcnow()
            session.flush()
            return install

    # Never log the presented secret. The counts alone separate the three real causes: no enrolled
    # installs at all (wiped DB), all undecryptable (key problem), or a genuine mismatch (the relay is
    # holding a secret from before it was re-enrolled - it needs a restart, not another enrolment).
    logger.warning(
        "relay handshake rejected",
        extra={
            "enrolled_installs": len(installs),
            "undecryptable": undecryptable,
            "cause": (
                "no enrolled installs"
                if not installs
                else "encryption key mismatch"
                if undecryptable == len(installs)
                else "secret mismatch - relay is presenting a stale secret"
            ),
        },
    )
    return None
