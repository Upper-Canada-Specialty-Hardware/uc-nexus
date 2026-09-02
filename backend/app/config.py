import os
import re

from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@localhost:5432/uc_nexus")

# Railway Bucket (S3-compatible) config
BUCKET_ENDPOINT = os.getenv("BUCKET_ENDPOINT", "")
BUCKET_ACCESS_KEY_ID = os.getenv("BUCKET_ACCESS_KEY_ID", "")
BUCKET_SECRET_ACCESS_KEY = os.getenv("BUCKET_SECRET_ACCESS_KEY", "")
BUCKET_NAME = os.getenv("BUCKET_NAME", "")

# Clerk authentication config
CLERK_SECRET_KEY = os.getenv("CLERK_SECRET_KEY", "")
TESTING_ENABLED = os.getenv("TESTING_ENABLED", "").lower() in ("true", "1", "yes")

# The dedicated e2e testing Clerk account (preview-env autonomy plan). Not a real person: a user
# created once in the Clerk dashboard and granted Admin/Manager in its publicMetadata.roles. Set on
# PRODUCTION so every preview inherits it, and it is load-bearing in two places at once:
#   - GET /testing/session mints a sign-in ticket for THIS id and nothing else (the hands-off preview
#     sign-in link that lives in a PR comment).
#   - the auth chokepoint (app/auth._reject_e2e_account_in_production) REFUSES this id on production,
#     which is the entire reason that link is safe to hand around - every environment shares the one
#     production Clerk instance, so a ticket minted for this account is a valid production JWT.
# Blank disables both: /testing/session answers 500 (misconfigured) and the deny is inert.
E2E_CLERK_USER_ID = os.getenv("E2E_CLERK_USER_ID", "")

# SHA-256 hex of this preview environment's per-env session key K. Set by the preview-env workflow on
# the backend service of each uc-nexus-pr-<N>, never on production - GET /testing/session compares
# sha256(?key=) against it in constant time. A verifier, not a credential: the backend holds only the
# hash, and K itself lives nowhere but the PR's "test environment ready" comment. Blank closes the
# route's key path (401).
TESTING_SESSION_KEY_HASH = os.getenv("TESTING_SESSION_KEY_HASH", "")

# SHA-256 hex of the shared testing sign-in secret (#422). /testing/clerk-sign-in mints a REAL Clerk
# session - every environment shares the production Clerk instance - so TESTING_ENABLED alone is an
# environment switch, not an auth gate. A caller must either already hold an Admin/Manager session or
# present this digest's preimage in X-Testing-Secret, the bootstrap path for a fresh PR environment
# where no session exists yet. Same verifier-not-credential shape as RELAY_SEED_SECRET_HASH: Railway
# stores nothing replayable. Blank disables the secret path, leaving only the admin path.
TESTING_SIGN_IN_SECRET_HASH = os.getenv("TESTING_SIGN_IN_SECRET_HASH", "")

# The same digest, but the copy that PREVIEW environments inherit - and the reason a fresh PR
# environment is testable without anybody setting a variable on it.
#
# The direct one above cannot do that job. It must stay unset in production (its preimage mints a REAL
# Clerk session for a real staff account, which is what #422/#424 shut off), and Railway clones a
# preview from production, so there is nothing there for a preview to inherit. Every PR environment
# therefore needed the variable set on it by hand, which is one manual step per PR standing between
# "PR opened" and "an agent can test it".
#
# So this is the RELAY_SEED_SECRET_HASH shape, for the same reason and with the same safeguard: it
# lives on PRODUCTION, sits inert there because `testing_sign_in_secret_hash()` refuses to read it in
# production, and is inherited by every preview created afterwards.
#
# What it does mean: one secret opens the sign-in bootstrap on every preview environment at once,
# rather than one secret per environment. That is the same trade RELAY_SEED_SECRET_HASH already makes,
# and it is bounded the same way - previews hold disposable data, and the sign-in route is still gated
# on TESTING_ENABLED first. Rotate it here and every preview follows on its next deploy.
PREVIEW_TESTING_SIGN_IN_SECRET_HASH = os.getenv("PREVIEW_TESTING_SIGN_IN_SECRET_HASH", "")

# Railway sets this to the environment's name ("production", "pr-414", ...). Empty off Railway.
# app/services/relay_seed.py uses it as the production kill-switch for credential seeding.
RAILWAY_ENVIRONMENT_NAME = os.getenv("RAILWAY_ENVIRONMENT_NAME", "")

# Microsoft Entra app registration used to read the legacy SharePoint inventory list during the
# one-time migration (app-only client credentials, application-type Sites.ReadWrite.All). Blank on
# an environment that has not been given them, which leaves the migration wizard refusing with a
# configuration error rather than the app failing to boot.
AZURE_TENANT_ID = os.getenv("AZURE_TENANT_ID", "")
AZURE_CLIENT_ID = os.getenv("AZURE_CLIENT_ID", "")
AZURE_CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET", "")


def is_production_environment() -> bool:
    """Whether this deployment is the production Railway environment.

    Named off RAILWAY_ENVIRONMENT_NAME rather than inferred from a URL or a flag, so it cannot be
    turned off by a variable somebody sets on production by mistake. Empty off Railway, which reads as
    "not production" - correct for a local checkout.
    """
    return RAILWAY_ENVIRONMENT_NAME.strip().lower() == "production"


# Direct Postgres access (db-admin-postgres-access). The public-proxy coordinates the backend needs to
# emit a working connection string for a login it mints. They live on the Postgres service today, not
# the backend, so they are copied here once from the Railway proxy (e.g. host switchback.proxy.rlwy.net,
# port 28233, db "railway"). A blank host disables the whole feature - which is the state in local dev
# and CI, where the variable is simply never set.
PG_DIRECT_HOST = os.getenv("PG_DIRECT_HOST", "")
PG_DIRECT_PORT = os.getenv("PG_DIRECT_PORT", "5432")
PG_DIRECT_DBNAME = os.getenv("PG_DIRECT_DBNAME", "railway")
PG_DIRECT_SSLMODE = os.getenv("PG_DIRECT_SSLMODE", "require")

# Railway names a per-PR preview environment "uc-nexus-pr-<N>". Anchored so a name that merely contains
# the prefix does not match - the same shape preview_registry's PREVIEW_ENVIRONMENT_RE uses, kept local
# here to avoid importing that module from config.
_PREVIEW_ENVIRONMENT_RE = re.compile(r"^uc-nexus-pr-(\d+)$")


def is_preview_environment() -> bool:
    """Whether this deployment is a Railway per-PR preview environment. Empty name off Railway -> not
    a preview, correct for local dev and CI."""
    return bool(_PREVIEW_ENVIRONMENT_RE.match(RAILWAY_ENVIRONMENT_NAME.strip()))


def preview_frontend_origin() -> str:
    """The public frontend origin for THIS preview environment, e.g.
    ``https://frontend-uc-nexus-pr-42.up.railway.app``.

    Derived from the environment name rather than looked up, exactly as
    app/services/preview_registry.py derives the backend channel URL: Railway public hostnames are
    ``<service>-<environment>.up.railway.app`` and the frontend service is ``frontend`` in every
    environment, so the derivation is total for any name matching the preview shape. GET
    /testing/session (its only caller) is gated on is_preview_environment() first, so this is never
    asked to derive an origin for production or a local checkout, where the name would not fit.
    """
    return f"https://frontend-{RAILWAY_ENVIRONMENT_NAME.strip()}.up.railway.app"


def db_direct_access_enabled() -> bool:
    """Whether the Database Access page and its five root fields are live in this environment.

    Enabled only when the proxy coordinates are configured AND this is not a preview environment. The
    preview-name check is the load-bearing half: a preview inherits the base env's variables, so
    PG_DIRECT_HOST would otherwise be present on a throwaway PR deploy and let it mint real,
    internet-reachable read-write credentials against the shared cluster. Local dev and CI are covered
    for free - they never set the variable.

    Read off the module constants (not os.getenv) so a test can flip either one with monkeypatch."""
    return bool(PG_DIRECT_HOST.strip()) and not is_preview_environment()


def testing_sign_in_secret_hash() -> str:
    """The digest /testing/clerk-sign-in accepts, or "" when the secret path is closed.

    Resolved at call time, not import time, so a test can set the environment without reimporting.
    An explicit per-environment `TESTING_SIGN_IN_SECRET_HASH` always wins, which keeps the documented
    manual override working and lets one environment carry its own secret.
    """
    if TESTING_SIGN_IN_SECRET_HASH.strip():
        return TESTING_SIGN_IN_SECRET_HASH.strip()
    if PREVIEW_TESTING_SIGN_IN_SECRET_HASH.strip() and not is_production_environment():
        return PREVIEW_TESTING_SIGN_IN_SECRET_HASH.strip()
    return ""


# SHA-256 hex of the workstation relay's long-lived Bearer secret - the same digest already sitting in
# production's relay_installs.secret_hash, copied from Admin -> Relay Installs. Set ONLY on the Railway
# environment that PR deploys duplicate, so a PR backend can accept the one relay that exists without a
# manual provision + enroll per PR (#414). A hash is a verifier, not a credential: it cannot be replayed
# to authenticate. relay_seed refuses to act on it in production regardless.
RELAY_SEED_SECRET_HASH = os.getenv("RELAY_SEED_SECRET_HASH", "")

# SHA-256 hex of the STUB relay's Bearer secret - the default relay credential for a preview
# environment. A preview normally runs its own fixture-backed stub relay inside the environment rather
# than borrowing the one GP-credentialed workstation, so nothing has to be dialled from an office
# machine for a PR to be testable. Minted PER PREVIEW by the preview-env workflow, which sets this hash
# on the preview's backend and the matching secret on the stub service, so the pair can never drift.
# Never set on production: seeding never runs there and the stub does not exist there.
RELAY_STUB_SECRET_HASH = os.getenv("RELAY_STUB_SECRET_HASH", "")

# Whether THIS preview environment wants the real workstation relay instead of the stub. Off by
# default, which is the whole point: the default preview is self-contained. Turning it on does two
# things at once - the seeded credential becomes RELAY_SEED_SECRET_HASH (the hash the workstation
# relay's secret matches), and this backend announces itself to production so that relay is told to
# dial it (app/services/preview_announce.py). Set per environment, never on production.
PREVIEW_REAL_RELAY = os.getenv("PREVIEW_REAL_RELAY", "").lower() in ("true", "1", "yes")

# The shared secret a preview presents to production's POST/DELETE /preview-channels, which is how
# production learns a preview exists at all. Set on PRODUCTION - which both verifies it and is where a
# new preview inherits its copy from at environment creation. Not a digest like the seed hashes: the
# preview has to PRESENT it, so both sides need the value itself. Blank on either side closes the
# route (401), which leaves the relay dialling nothing but production.
PREVIEW_REGISTRY_SECRET = os.getenv("PREVIEW_REGISTRY_SECRET", "")

# Where a preview announces itself. Constant in practice - production's public backend origin - and a
# variable only so a fork or a renamed service is a variable edit rather than a code change.
PRODUCTION_BACKEND_ORIGIN = os.getenv("PRODUCTION_BACKEND_ORIGIN", "https://backend-production-7866.up.railway.app")
