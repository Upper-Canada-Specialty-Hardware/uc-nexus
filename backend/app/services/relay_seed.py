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

Two guards keep this out of production, and the variable is SUPPOSED to be set there (#431). Railway
clones a new PR environment from production directly - there is no separate base environment - so
production is the only place `RELAY_SEED_SECRET_HASH` can sit for a PR environment to inherit it at
all. It is inert there: `seed_from_env` refuses outright when `RAILWAY_ENVIRONMENT_NAME` says
production, rather than trusting the variable to be absent, and set-but-ignored on production is the
intended steady state, not a misconfiguration to clean up. (That inheritance is taken at environment
creation and never refreshed, so a PR environment that already existed when the variable was set on
production needs it set on that environment's own backend service too.) And the seeded install is
pinned to `TUBC`: the relay's own `allowed_companies` guardrail already blocks production GP
companies, and `relay_gateway.relay_call` refuses any company that does not match the registered
install's, so a PR backend cannot reach past the sandbox even if someone sets the variable somewhere
unexpected.
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

# Every row this service creates is labelled with this prefix, which is what lets it recognise its own
# work later - both to clean up a rotated hash and to stay off rows it did not create.
SEED_LABEL_PREFIX = "seed:"

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _real_relay_install(session: Session) -> RelayInstall | None:
    """The first install that a real relay actually enrolled, or None.

    `hostname` is the discriminator: only `enroll_install` writes it, from the workstation's own
    `socket.gethostname()`. Seeded rows never have one, so this does not see its own output and
    re-seeding keeps working across deploys. A naming-independent signal is the point - an environment
    whose database holds a genuinely paired relay is production or a copy of it, however it is named."""
    return session.scalars(select(RelayInstall).where(RelayInstall.hostname.is_not(None)).limit(1)).first()


def _is_production(environment_name: str) -> bool:
    return environment_name.strip().lower() == "production"


def _seed_label(environment_name: str) -> str:
    return f"{SEED_LABEL_PREFIX}{environment_name.strip() or 'local'}"


def seed_from_env(session: Session, *, environment_name: str, secret_hash: str) -> RelayInstall | None:
    """Ensure a relay install exists for `secret_hash`, or return None if seeding does not apply.

    Idempotent: re-running it on every boot converges on exactly one row. Two rules make that safe
    rather than merely convergent, and both matter more than the convergence does.

    It never MUTATES a row it did not create. An earlier draft repaired the company of whatever row
    already carried the hash, which is fine for its own seed row and catastrophic for the real one: in
    any environment holding a genuine install (production, or a database restored from it) that
    silently repoints a live credential from UBC/UCSH to TUBC, and the original value survives only in
    a log line. A row that already carries the hash is now left completely alone.

    And it refuses outright wherever a relay has genuinely enrolled - see _looks_like_a_real_relay_env.
    The environment-name check alone is a single-string denylist that fails OPEN: rename the base
    environment, restore a dump into staging, or point DATABASE_URL somewhere shared, and a credential
    whose preimage lives in a Railway variable gets inserted next to the real one."""
    secret_hash = (secret_hash or "").strip().lower()
    if not secret_hash:
        return None

    if _is_production(environment_name):
        # INFO, not ERROR (#431): this is the intended steady state, not an operator mistake. Railway
        # clones a PR environment from production, so the variable has to live here for a new PR
        # environment to inherit it - an ERROR line invites someone to "fix" production by deleting it,
        # which silently breaks every PR environment created afterwards.
        logger.info(
            "RELAY_SEED_SECRET_HASH is set here and seeding was skipped, which is correct: seeding never "
            "runs in production. Leave the variable in place - Railway clones a new PR environment from "
            "production, so this is where a PR environment inherits it from.",
        )
        return None

    if not _HEX64.match(secret_hash):
        logger.error(
            "RELAY_SEED_SECRET_HASH is not a SHA-256 hex digest (expected 64 hex chars); skipping "
            "relay credential seeding. Copy the value from Admin -> Relay Installs.",
            extra={"length": len(secret_hash)},
        )
        return None

    paired = _real_relay_install(session)
    if paired is not None:
        logger.error(
            "RELAY_SEED_SECRET_HASH is set, but this database already holds a relay install that a real "
            "relay enrolled - refusing to seed. Seeding is for a fresh PR environment; a database with "
            "a genuine install is production or a copy of it, whatever the environment is named.",
            extra={"install_id": str(paired.id), "label": paired.label, "environment": environment_name},
        )
        return None

    existing = session.scalars(select(RelayInstall).where(RelayInstall.secret_hash == secret_hash)).first()
    if existing is not None:
        # Deliberately untouched, company included. See the docstring.
        if existing.company != SEED_COMPANY:
            logger.warning(
                "an install already carries the seed hash but is not on the sandbox company; leaving it "
                "as it is. relay_call will refuse any company that does not match it.",
                extra={"install_id": str(existing.id), "company": existing.company},
            )
        return existing

    # Drop this environment's PREVIOUS seed row, if the hash has been rotated since. Without it the
    # superseded secret keeps authenticating here forever, and the grid grows a row per rotation.
    label = _seed_label(environment_name)
    stale = session.scalars(
        select(RelayInstall).where(RelayInstall.label == label, RelayInstall.secret_hash != secret_hash)
    ).all()
    for row in stale:
        logger.info(
            "removing a superseded seeded relay install",
            extra={"install_id": str(row.id), "label": row.label},
        )
        session.delete(row)

    now = datetime.utcnow()
    install = RelayInstall(
        id=uuid.uuid4(),
        label=label,
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
