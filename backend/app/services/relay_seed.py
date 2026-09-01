"""Seed a trusted relay credential into non-production environments from an env var (#414, #654).

Why this exists: a Railway PR environment gets a fresh Postgres with an empty `relay_installs`, so
`authenticate_secret` matches nothing and a relay's `/relay-link` handshake closes 4403. Every
relay-dependent path - the GP vendor/buyer/job dropdowns, Create PO, receiving - is therefore dead in
a PR environment, and a GP-touching change can only be verified after it merges.

WHICH credential is seeded is the #654 change, and it inverts the default. Originally the only option
was the real workstation relay's hash, which made every preview environment depend on one
GP-credentialed machine in an office being switched on and reachable - and on it being told, somehow,
to dial that preview. The default now is a STUB relay running inside the preview itself, answering
from fixtures: nothing external, nothing to configure, and a PR is testable the moment it deploys.
`PREVIEW_REAL_RELAY` opts an environment back into the real relay when a change genuinely needs live
GP, and that flag also switches on the announce loop that gets the workstation relay to dial here
(app/services/preview_announce.py).

Exactly one of the two is ever seeded. The label prefix (`seed:` for the real relay, `stub:` for the
stub) is what lets a redeploy after the flag flips recognise and remove the row of the other kind -
otherwise both credentials would keep authenticating, and which relay held the single connection slot
would come down to whichever dialled first.

What is seeded is a HASH, not a secret. `relay_installs` only ever stores the SHA-256 digest of a
relay's Bearer secret (see app/crypto.hash_secret), and `authenticate_secret` matches on that digest
alone. So a digest in a Railway variable lets the relay that holds the preimage authenticate here with
the secret it already has - no re-enrollment, and nothing replayable stored in Railway.

Two guards keep this out of production, and the variables are SUPPOSED to be set there (#431). Railway
clones a new PR environment from production directly - there is no separate base environment - so
production is the only place a hash can sit for a PR environment to inherit it at all. It is inert
there: `seed_from_env` refuses outright when `RAILWAY_ENVIRONMENT_NAME` says production, rather than
trusting the variables to be absent. And the companies a seeded install may serve are sandbox
companies: the relay's own `allowed_companies` guardrail already blocks production GP companies, and
`relay_gateway.relay_call` refuses any company that does not match the registered install's, so a PR
backend cannot reach past the sandbox even if someone sets a variable somewhere unexpected.
"""

import logging
import re
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import (
    PREVIEW_REAL_RELAY,
    RAILWAY_ENVIRONMENT_NAME,
    RELAY_SEED_COMPANIES,
    RELAY_SEED_SECRET_HASH,
    RELAY_STUB_COMPANIES,
    RELAY_STUB_SECRET_HASH,
)
from app.database import SessionLocal
from app.models.relay_install import RelayInstall

logger = logging.getLogger(__name__)

# Every row this service creates is labelled with one of these prefixes, which is what lets it
# recognise its own work later - to clean up a rotated hash, to remove the row of the other kind when
# PREVIEW_REAL_RELAY flips, and to stay off rows it did not create.
SEED_LABEL_PREFIX = "seed:"
STUB_LABEL_PREFIX = "stub:"
_LABEL_PREFIXES = (SEED_LABEL_PREFIX, STUB_LABEL_PREFIX)

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def parse_companies(raw: str) -> list[str]:
    """A comma-separated company list from configuration, in the form relay_installs stores: trimmed,
    uppercased, de-duplicated, order preserved. Empty entries are dropped rather than stored - the list
    is what relay_call's membership check is made against, so a blank one would be a company nothing
    could ever match."""
    cleaned: list[str] = []
    for part in (raw or "").split(","):
        code = part.strip().upper()
        if code and code not in cleaned:
            cleaned.append(code)
    return cleaned


def _real_relay_install(session: Session) -> RelayInstall | None:
    """The first install that a real relay actually enrolled, or None.

    `hostname` is the discriminator: only `enroll_install` writes it, from the workstation's own
    `socket.gethostname()`. Seeded rows never have one, so this does not see its own output and
    re-seeding keeps working across deploys. A naming-independent signal is the point - an environment
    whose database holds a genuinely paired relay is production or a copy of it, however it is named."""
    return session.scalars(select(RelayInstall).where(RelayInstall.hostname.is_not(None)).limit(1)).first()


def _is_production(environment_name: str) -> bool:
    return environment_name.strip().lower() == "production"


def _label(environment_name: str, prefix: str) -> str:
    return f"{prefix}{environment_name.strip() or 'local'}"


def _drop_superseded(session: Session, *, environment_name: str, label: str, secret_hash: str) -> None:
    """Remove every row this service owns for this environment except the one being seeded.

    Two cases, one query. A ROTATED hash leaves the previous row under the same label, and without this
    the superseded secret keeps authenticating here forever. A FLIPPED `PREVIEW_REAL_RELAY` leaves the
    row of the other kind, under the other prefix - and two live credentials on one environment means
    the connection slot goes to whichever relay dials first, which is not a decision anybody made."""
    owned = [_label(environment_name, prefix) for prefix in _LABEL_PREFIXES]
    stale = session.scalars(select(RelayInstall).where(RelayInstall.label.in_(owned))).all()
    for row in stale:
        if row.label == label and row.secret_hash == secret_hash:
            continue
        logger.info(
            "removing a superseded seeded relay install",
            extra={"install_id": str(row.id), "label": row.label},
        )
        session.delete(row)


def seed_from_env(
    session: Session,
    *,
    environment_name: str,
    secret_hash: str,
    companies: list[str],
    label_prefix: str = SEED_LABEL_PREFIX,
) -> RelayInstall | None:
    """Ensure a relay install exists for `secret_hash`, or return None if seeding does not apply.

    Idempotent: re-running it on every boot converges on exactly one row. Two rules make that safe
    rather than merely convergent, and both matter more than the convergence does.

    It never MUTATES a row it did not create. An earlier draft repaired the company of whatever row
    already carried the hash, which is fine for its own seed row and catastrophic for the real one: in
    any environment holding a genuine install (production, or a database restored from it) that
    silently repoints a live credential from UBC/UCSH to TUBC, and the original value survives only in
    a log line. A row that already carries the hash is now left completely alone.

    And it refuses outright wherever a relay has genuinely enrolled - see `_real_relay_install`. The
    environment-name check alone is a single-string denylist that fails OPEN: rename the base
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
            "a relay seed hash is set here and seeding was skipped, which is correct: seeding never "
            "runs in production. Leave the variable in place - Railway clones a new PR environment from "
            "production, so this is where a PR environment inherits it from.",
        )
        return None

    if not _HEX64.match(secret_hash):
        logger.error(
            "the relay seed hash is not a SHA-256 hex digest (expected 64 hex chars); skipping relay "
            "credential seeding. Copy the value from Admin -> Relay Installs.",
            extra={"length": len(secret_hash)},
        )
        return None

    if not companies:
        logger.error(
            "no GP companies are configured for the relay credential being seeded; skipping. An install "
            "that lists none can serve no call and is refused at the handshake.",
        )
        return None

    paired = _real_relay_install(session)
    if paired is not None:
        logger.error(
            "a relay seed hash is set, but this database already holds a relay install that a real "
            "relay enrolled - refusing to seed. Seeding is for a fresh PR environment; a database with "
            "a genuine install is production or a copy of it, whatever the environment is named.",
            extra={"install_id": str(paired.id), "label": paired.label, "environment": environment_name},
        )
        return None

    label = _label(environment_name, label_prefix)
    _drop_superseded(session, environment_name=environment_name, label=label, secret_hash=secret_hash)

    existing = session.scalars(select(RelayInstall).where(RelayInstall.secret_hash == secret_hash)).first()
    if existing is not None:
        # Deliberately untouched, companies included. See the docstring.
        missing = [c for c in companies if c not in (existing.companies or [])]
        if missing:
            logger.warning(
                "an install already carries the seed hash but does not list every configured company; "
                "leaving it as it is. relay_call will refuse any company it does not list.",
                extra={"install_id": str(existing.id), "companies": list(existing.companies or [])},
            )
        return existing

    now = datetime.utcnow()
    install = RelayInstall(
        id=uuid.uuid4(),
        label=label,
        companies=list(companies),
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
        extra={"install_id": str(install.id), "label": install.label, "companies": list(install.companies)},
    )
    return install


def seed_on_startup() -> None:
    """Startup hook (see main.lifespan). Never raises: a backend that cannot seed must still boot -
    the failure mode is 'relay-dependent pages do not work in this PR environment', which is exactly
    where things stood before this existed.

    Which credential is seeded is decided here, once: the stub by default, the real workstation relay
    when PREVIEW_REAL_RELAY says this environment needs live GP."""
    if not RELAY_SEED_SECRET_HASH and not RELAY_STUB_SECRET_HASH:
        return
    if PREVIEW_REAL_RELAY:
        secret_hash, raw_companies, prefix, variable = (
            RELAY_SEED_SECRET_HASH,
            RELAY_SEED_COMPANIES,
            SEED_LABEL_PREFIX,
            "RELAY_SEED_SECRET_HASH",
        )
    else:
        secret_hash, raw_companies, prefix, variable = (
            RELAY_STUB_SECRET_HASH,
            RELAY_STUB_COMPANIES,
            STUB_LABEL_PREFIX,
            "RELAY_STUB_SECRET_HASH",
        )
    if not secret_hash:
        logger.warning(
            "PREVIEW_REAL_RELAY is %s, so %s is the hash this environment seeds - and it is not set. "
            "No relay credential was seeded; relay-dependent pages will not work here.",
            "on" if PREVIEW_REAL_RELAY else "off",
            variable,
        )
        return
    try:
        with SessionLocal() as session:
            seed_from_env(
                session,
                environment_name=RAILWAY_ENVIRONMENT_NAME,
                secret_hash=secret_hash,
                companies=parse_companies(raw_companies),
                label_prefix=prefix,
            )
            # Committed unconditionally: the pass may have deleted the row of the other kind without
            # inserting one (a hash that was already there), and that deletion is the whole point of
            # the flip. A clean session commits nothing.
            session.commit()
    except Exception:
        logger.exception("relay credential seeding failed; continuing startup without it")
