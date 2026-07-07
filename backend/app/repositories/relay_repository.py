"""Relay install provisioning + enrollment + credential lookup.

Trust model: the Railway backend cannot reach the relay (it binds to localhost on a workstation), but
the relay CAN reach the backend. So provisioning mints a one-time enrollment token (shown once in the
UC Nexus admin UI); the relay, during its one-time setup, generates its OWN long-lived Bearer secret and
registers it here with that token. Nothing long-lived is ever hand-copied."""

import secrets
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.crypto import decrypt_secret, encrypt_secret, hash_token
from app.errors import ConflictError, NotFoundError, ValidationError
from app.models.relay_install import RelayInstall

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
    enrolled installs. Secrets are Fernet-encrypted (reversible, not hashed - see get_credential), so
    this decrypts each enrolled install's secret and compares in constant time. POC scale (a handful
    of installs) makes the linear scan fine. Returns None on no match instead of raising - the caller
    (the /relay-link route) treats that as a clean close, same as a bad token anywhere else here."""
    secret = (secret or "").strip()
    if not secret:
        return None
    installs = session.scalars(select(RelayInstall).where(RelayInstall.secret_encrypted.is_not(None))).all()
    for install in installs:
        try:
            candidate = decrypt_secret(install.secret_encrypted)
        except Exception:
            continue
        if secrets.compare_digest(candidate, secret):
            install.last_seen_at = datetime.utcnow()
            session.flush()
            return install
    return None


def get_credential(session: Session) -> str:
    """Return the decrypted Bearer secret for the enrolled install. POC: the single (most recently)
    enrolled install. Production keys this per workstation/user assignment."""
    install = session.scalars(
        select(RelayInstall).where(RelayInstall.secret_encrypted.is_not(None)).order_by(RelayInstall.enrolled_at.desc())
    ).first()
    if install is None:
        raise NotFoundError("no enrolled relay install found")
    install.last_seen_at = datetime.utcnow()
    session.flush()
    return decrypt_secret(install.secret_encrypted)
