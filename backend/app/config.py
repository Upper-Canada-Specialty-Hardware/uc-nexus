import os
import re
from urllib.parse import quote

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
# where no session exists yet. A hash is a verifier, not a credential, so Railway stores nothing
# replayable. Blank disables the secret path, leaving only the admin path.
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
# So this one lives on PRODUCTION, sits inert there because `testing_sign_in_secret_hash()` refuses to
# read it in production, and is inherited by every preview created afterwards.
#
# What it does mean: one secret opens the sign-in bootstrap on every preview environment at once,
# rather than one secret per environment. It is bounded the same way the rest of the preview
# machinery is - previews hold disposable data, and the sign-in route is still gated on
# TESTING_ENABLED first. Rotate it here and every preview follows on its next deploy.
PREVIEW_TESTING_SIGN_IN_SECRET_HASH = os.getenv("PREVIEW_TESTING_SIGN_IN_SECRET_HASH", "")

# Railway sets this to the environment's name ("production", "uc-nexus-pr-414", ...). Empty off
# Railway. Everything that must behave differently on production or on a preview is named off it.
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

# The password of the read-only login a preview environment uses to pg_dump production. Set on
# PRODUCTION and nowhere else: production is what CREATES the role from it (app/services/
# preview_clone_role.py), and a Railway fork inherits every production variable at creation, so the
# preview that comes out already holds the credential it needs to clone the database it was forked
# from. Blank disables cloning on both sides - production mints no role, and a preview boots empty.
PREVIEW_CLONE_PASSWORD = os.getenv("PREVIEW_CLONE_PASSWORD", "")

# The role that password belongs to. A constant rather than a variable: both halves have to agree on
# the name and there is no reason for a deployment to choose its own.
PREVIEW_CLONE_ROLE = "preview_clone"

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


def preview_clone_source_url() -> str | None:
    """The connection string a preview pg_dumps production through, or None when cloning is off.

    Built from the db-admin public-proxy coordinates because they are already here and already point
    at production's Postgres from outside Railway - a preview lives in its own Railway project
    network, so the private hostname production's own DATABASE_URL uses is unreachable from it.

    None when either half is missing, which is the state everywhere cloning is not configured: local
    dev and CI never set PG_DIRECT_HOST, and a preview forked before PREVIEW_CLONE_PASSWORD existed
    inherits no password. The caller boots empty rather than failing on it."""
    host = PG_DIRECT_HOST.strip()
    password = PREVIEW_CLONE_PASSWORD.strip()
    if not host or not password:
        return None
    return (
        f"postgresql://{PREVIEW_CLONE_ROLE}:{quote(password, safe='')}@"
        f"{host}:{PG_DIRECT_PORT.strip()}/{PG_DIRECT_DBNAME.strip()}"
        f"?sslmode={PG_DIRECT_SSLMODE.strip()}"
    )


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


# The shared secret a preview presents to production's POST/DELETE /preview-channels, which is how
# production learns a preview exists at all. Set on PRODUCTION - which both verifies it and is where a
# new preview inherits its copy from at environment creation. The secret itself rather than a
# digest: the preview has to PRESENT it, so both sides need the value. Blank on either side closes
# the route (401), which leaves the relay dialling nothing but production.
PREVIEW_REGISTRY_SECRET = os.getenv("PREVIEW_REGISTRY_SECRET", "")

# Where a preview announces itself. Constant in practice - production's public backend origin - and a
# variable only so a fork or a renamed service is a variable edit rather than a code change.
PRODUCTION_BACKEND_ORIGIN = os.getenv("PRODUCTION_BACKEND_ORIGIN", "https://backend-production-7866.up.railway.app")
