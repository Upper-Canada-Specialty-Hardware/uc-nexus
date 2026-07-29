"""Seed a trusted relay credential into non-production environments from an env var (#414).

Why this exists: a Railway PR environment gets a fresh Postgres with an empty `relay_installs`, so
`authenticate_secret` matches nothing and the relay's `/relay-link` handshake closes 4403. Every
relay-dependent path - the GP vendor/buyer/job dropdowns, Create PO, receiving - is therefore dead in
a PR environment, and a GP-touching change can only be verified after it merges. The alternative was
an admin provisioning an install and re-enrolling the workstation relay against every PR backend,
which is both manual and destructive: enrollment rewrites the workstation's one secret, so pairing it
with a PR environment un-pairs it from production.

What is seeded is a HASH, not a secret. `relay_installs` only ever stores the SHA-256 digest of the
relay's self-generated Bearer secret (see app/crypto.hash_secret), and `authenticate_secret` matches
on that digest alone. So copying the digest out of production's row into a PR environment lets the one
existing workstation relay authenticate there with the secret it already holds - no re-enrollment, no
new credential, and nothing replayable stored in Railway (a digest cannot be presented as a Bearer
token; only its preimage can, and that never leaves the workstation).

Two guards keep this out of production. Railway PR environments duplicate the base environment's
variables, so `RELAY_SEED_SECRET_HASH` will be visible in production too - `seed_from_env` refuses
outright when `RAILWAY_ENVIRONMENT_NAME` says production, rather than trusting the variable to be
absent. And the seeded install is pinned to `TUBC`: the relay's own `allowed_companies` guardrail
already blocks production GP companies, and `relay_gateway.relay_call` refuses any company that does
not match the registered install's, so a PR backend cannot reach past the sandbox even if someone
sets the variable somewhere unexpected.
"""

import logging
import re
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import RAILWAY_ENVIRONMENT_NAME, RELAY_SEED_SECRET_HASH
from app.database import SessionLocal
from app.models.relay_install import RelayInstall

logger = logging.getLogger(__name__)

# The GP sandbox every non-production environment is pinned to (#414). Not configurable: a variable
# here would be one typo away from pointing a PR backend at a live GP company, and the whole reason
# seeding is acceptable at all is that the blast radius is a sandbox.
SEED_COMPANY = "TUBC"

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _is_production(environment_name: str) -> bool:
    return environment_name.strip().lower() == "production"


def seed_from_env(session: Session, *, environment_name: str, secret_hash: str) -> RelayInstall | None:
    """Ensure a relay install exists for `secret_hash`, or return None if seeding does not apply.

    Idempotent, and keyed on the hash rather than the label: the install this creates is
    indistinguishable from an enrolled one as far as `authenticate_secret` is concerned, so re-running
    it on every boot must converge on exactly one row. A row that already carries the hash (whether
    seeded here or genuinely enrolled) is left alone apart from repairing its company."""
    secret_hash = (secret_hash or "").strip().lower()
    if not secret_hash:
        return None

    if _is_production(environment_name):
        logger.error(
            "RELAY_SEED_SECRET_HASH is set in the production environment and was IGNORED. Railway "
            "duplicates variables into PR environments, so this belongs only on the environment PR "
            "deploys are cloned from - remove it from production.",
        )
        return None

    if not _HEX64.match(secret_hash):
        logger.error(
            "RELAY_SEED_SECRET_HASH is not a SHA-256 hex digest (expected 64 hex chars); skipping "
            "relay credential seeding. Copy the value from Admin -> Relay Installs.",
            extra={"length": len(secret_hash)},
        )
        return None

    existing = session.scalars(select(RelayInstall).where(RelayInstall.secret_hash == secret_hash)).first()
    if existing is not None:
        if existing.company != SEED_COMPANY:
            logger.warning(
                "seeded relay install had the wrong company; repointing to the sandbox",
                extra={"install_id": str(existing.id), "was": existing.company, "now": SEED_COMPANY},
            )
            existing.company = SEED_COMPANY
            session.flush()
        return existing

    now = datetime.utcnow()
    install = RelayInstall(
        id=uuid.uuid4(),
        label=f"seed:{environment_name.strip() or 'local'}",
        company=SEED_COMPANY,
        secret_hash=secret_hash,
        # Marked enrolled on creation: there is no enrollment token and none is wanted - the relay
        # already holds the matching secret. Leaving this null would show the row as "pending" on
        # Admin -> Relay Installs forever while it happily authenticates.
        enrolled_at=now,
    )
    session.add(install)
    session.flush()
    logger.info(
        "seeded a trusted relay install for this non-production environment",
        extra={"install_id": str(install.id), "label": install.label, "company": install.company},
    )
    return install


def seed_on_startup() -> None:
    """Startup hook (see main.lifespan). Never raises: a backend that cannot seed must still boot -
    the failure mode is 'relay-dependent pages do not work in this PR environment', which is exactly
    where things stood before this existed."""
    if not RELAY_SEED_SECRET_HASH:
        return
    try:
        with SessionLocal() as session:
            if (
                seed_from_env(
                    session,
                    environment_name=RAILWAY_ENVIRONMENT_NAME,
                    secret_hash=RELAY_SEED_SECRET_HASH,
                )
                is not None
            ):
                session.commit()
    except Exception:
        logger.exception("relay credential seeding failed; continuing startup without it")
