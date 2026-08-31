"""Relay install provisioning + enrollment + credential lookup.

Trust model: the Railway backend cannot reach the relay (it binds to localhost on a workstation), but
the relay CAN reach the backend. So provisioning mints a one-time enrollment token (shown once in the
UC Nexus admin UI); the relay, during its one-time setup, generates its OWN long-lived Bearer secret and
registers it here with that token. Nothing long-lived is ever hand-copied."""

import logging
import secrets
import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.crypto import decrypt_secret, has_encryption_key, hash_secret, hash_token
from app.errors import ConflictError, ValidationError
from app.models.relay_install import RelayInstall

logger = logging.getLogger(__name__)

_ENROLLMENT_TTL = timedelta(hours=24)


def list_installs(session: Session) -> list[RelayInstall]:
    return list(session.scalars(select(RelayInstall).order_by(RelayInstall.created_at.desc())).all())


def normalize_companies(companies: list[str] | None) -> list[str]:
    """The GP companies an install may serve, cleaned for storage (#637): trimmed, uppercased,
    de-duplicated, order preserved. Raises rather than storing an empty or over-long code - the list is
    what relay_call's membership check is made against, so a blank entry there would be a company
    nothing could ever match and a silent hole in the install's reach."""
    cleaned: list[str] = []
    for raw in companies or []:
        code = (raw or "").strip().upper()
        if not code:
            continue
        if len(code) > 15:
            raise ValidationError(f"GP company '{code}' is longer than 15 characters", field="companies")
        if code not in cleaned:
            cleaned.append(code)
    if not cleaned:
        raise ValidationError("at least one GP company is required", field="companies")
    return cleaned


def provision_install(session: Session, label: str, companies: list[str]) -> tuple[RelayInstall, str]:
    """Create an install row + a one-time enrollment token. Returns (install, raw_token); the raw token
    is shown to the admin ONCE and only its hash is stored."""
    label = (label or "").strip()
    if not label:
        raise ValidationError("label is required", field="label")
    cleaned_companies = normalize_companies(companies)

    token = secrets.token_urlsafe(32)
    install = RelayInstall(
        id=uuid.uuid4(),
        label=label,
        companies=cleaned_companies,
        enrollment_token_hash=hash_token(token),
        enrollment_token_expires_at=datetime.utcnow() + _ENROLLMENT_TTL,
    )
    session.add(install)
    session.flush()
    return install, token


def set_install_secret(session: Session, install: RelayInstall, secret: str) -> None:
    """The SINGLE writer of a relay's long-lived credential. Enrollment and adoption both go through
    here, so how the secret is stored at rest is decided in exactly one place.

    Writes the hash and NULLs any legacy ciphertext. Nulling rather than keeping both: leftover
    ciphertext means RELAY_SECRET_ENC_KEY still matters, so a later key rotation would turn those rows
    into "undecryptable" - which authenticate_secret correctly reports as a key problem, raising a
    false alarm about a relay that is in fact perfectly healthy."""
    install.secret_hash = hash_secret(secret)
    install.secret_encrypted = None


def enroll_install(session: Session, enrollment_token: str, hostname: str, secret: str) -> RelayInstall:
    """Called by the relay (authenticated by the enrollment token, not Clerk). Stores the hash of the
    relay's self-generated secret; the token is single-use (a second attempt is rejected as
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
    set_install_secret(session, install, secret)
    install.enrolled_at = now
    install.last_seen_at = now
    # single use is enforced by the enrolled_at guard above: a second attempt with the same token finds
    # this now-enrolled row and is rejected as already-used. (Keeping the hash makes that a clear error
    # rather than a generic "invalid token".)
    session.flush()
    return install


def adopt_secret(session: Session, install_id: uuid.UUID, secret: str, adopted_by: str) -> RelayInstall | None:
    """Bind a presented (otherwise unrecognised) secret to an install, under an admin-armed adopt
    window. Called from the /relay-link route ONLY after relay_adopt.peek() returned a window for
    this install - this function does not itself decide whether adoption is allowed.

    Sets enrolled_at when it is still null so a never-enrolled row does not stay "pending" forever
    after a relay has in fact paired with it. Returns None if the row has been deleted since the
    window was armed."""
    install = session.get(RelayInstall, install_id)
    if install is None:
        return None
    now = datetime.utcnow()
    set_install_secret(session, install, secret)
    if install.enrolled_at is None:
        install.enrolled_at = now
    install.adopted_at = now
    install.adopted_by = adopted_by
    install.last_seen_at = now
    session.flush()
    return install


def delete_install(session: Session, install_id: uuid.UUID) -> dict | None:
    """Remove a relay install row outright (#366). Returns a plain dict of the fields worth logging, or
    None when the row is already gone (the resolver turns that into NotFoundError).

    Hard delete, not a soft-delete flag. A flag would have to be honoured by `authenticate_secret` too or
    the "deleted" install keeps authenticating - a new filter on the handshake hot path and a new way to
    be silently wrong. (It would also have kept `secret_encrypted` populated, which is what held up the
    RELAY_SECRET_ENC_KEY retirement - history now that #382 finished it, so the hot-path argument above
    is the one that still carries this decision.) Nothing references relay_installs by foreign key, so
    this is a clean single-row delete.

    The dict is built BEFORE the delete because the caller logs those values afterwards, and the instance
    is unusable by then."""
    install = session.get(RelayInstall, install_id)
    if install is None:
        return None
    snapshot = {
        "id": str(install.id),
        "label": install.label,
        "companies": list(install.companies or []),
        "hostname": install.hostname,
        "enrolled_at": install.enrolled_at.isoformat() if install.enrolled_at else None,
    }
    session.delete(install)
    session.flush()
    return snapshot


def authenticate_secret(session: Session, secret: str) -> RelayInstall | None:
    """Verify a Bearer secret presented on the outbound WS channel's connect handshake against the
    enrolled installs.

    Dual-read. The hash path is the normal one: an indexed equality lookup on the SHA-256 digest, then
    `compare_digest` as the constant-time confirm. The legacy path reads pre-067 `secret_encrypted`
    rows and, on a match, UPGRADES the row in place - so a live relay migrates itself on its next
    reconnect (~30s) with nobody doing anything, and no plaintext ever has to be recovered at
    migration time.

    A missing RELAY_SECRET_ENC_KEY is no longer fatal: the legacy scan is skipped entirely and logged
    once. Returns None on no match instead of raising - the caller (the /relay-link route) treats that
    as a clean close, same as a bad token anywhere else here."""
    secret = (secret or "").strip()
    if not secret:
        return None

    digest = hash_secret(secret)
    install = session.scalars(select(RelayInstall).where(RelayInstall.secret_hash == digest)).first()
    if install is not None and secrets.compare_digest(install.secret_hash, digest):
        install.last_seen_at = datetime.utcnow()
        session.flush()
        return install

    legacy = session.scalars(select(RelayInstall).where(RelayInstall.secret_encrypted.is_not(None))).all()
    key_present = has_encryption_key()
    undecryptable = 0
    if legacy and key_present:
        for candidate_install in legacy:
            try:
                candidate = decrypt_secret(candidate_install.secret_encrypted)
            except Exception:
                # A row whose stored secret will not decrypt is NOT a wrong-secret case: the key has
                # been rotated since enrolment. Swallowing that silently makes a config error
                # indistinguishable from a stale relay secret - both just 403 forever with nothing in
                # the log. Count it and say so below.
                undecryptable += 1
                logger.warning(
                    "relay install secret failed to decrypt - RELAY_SECRET_ENC_KEY was rotated since "
                    "this install enrolled; arm an adopt window (or re-enrol) to rebind it",
                    extra={
                        "install_id": str(candidate_install.id),
                        "label": candidate_install.label,
                        "hostname": candidate_install.hostname,
                    },
                )
                continue
            if secrets.compare_digest(candidate, secret):
                # Upgrade in place: this is the whole migration path for pre-067 rows.
                set_install_secret(session, candidate_install, secret)
                candidate_install.last_seen_at = datetime.utcnow()
                session.flush()
                logger.info(
                    "relay install upgraded to hashed secret",
                    extra={"install_id": str(candidate_install.id), "label": candidate_install.label},
                )
                return candidate_install

    hash_rows = session.scalar(
        select(func.count()).select_from(RelayInstall).where(RelayInstall.secret_hash.is_not(None))
    )
    # Never log the presented secret. The counts alone separate the real causes: no enrolled installs
    # at all (wiped DB), legacy rows with the key gone or rotated (a config problem), or a genuine
    # mismatch (the relay holds a secret from before it was re-enrolled - it needs a restart, or an
    # admin-armed adopt window, not another enrolment).
    cause = (
        "no enrolled installs"
        if not hash_rows and not legacy
        else "legacy rows present but RELAY_SECRET_ENC_KEY is unset"
        if legacy and not key_present
        else "encryption key mismatch"
        if legacy and undecryptable == len(legacy)
        else "secret mismatch - relay is presenting a stale secret"
    )
    # In the message, not in `extra`. This line is read in Railway's deploy log, and the stdlib's
    # default formatter renders only the message - so every field below used to be dropped and the
    # line arrived saying "relay handshake rejected" and nothing else. That is the entire diagnostic
    # for a relay that cannot authenticate, and it named none of the four causes it had computed.
    logger.warning(
        "relay handshake rejected: %s (hash_rows=%s legacy_rows=%s encryption_key_present=%s undecryptable=%s)",
        cause,
        hash_rows,
        len(legacy),
        key_present,
        undecryptable,
    )
    return None
