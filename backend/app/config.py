import os

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

# The dedicated e2e testing Clerk account. Not a real person: a user created once in the Clerk dashboard
# and granted UC Nexus Admin in its publicMetadata.roles. It used to be minted into PR environments;
# those are retired (#868), but the account may still exist, so the auth chokepoint
# (app/auth._reject_e2e_account_in_production) keeps REFUSING this id on production - every environment
# shares the one production Clerk instance, so a session for it is a valid production JWT. Blank makes
# the deny inert.
E2E_CLERK_USER_ID = os.getenv("E2E_CLERK_USER_ID", "")

# SHA-256 hex of the shared testing sign-in secret (#422). /testing/clerk-sign-in mints a REAL Clerk
# session - every environment shares the production Clerk instance - so TESTING_ENABLED alone is an
# environment switch, not an auth gate. A caller must either already hold a UC Nexus Admin session or
# present this digest's preimage in X-Testing-Secret, the bootstrap path for a deployment where no
# session exists yet. A hash is a verifier, not a credential, so Railway stores nothing
# replayable. Blank disables the secret path, leaving only the admin path.
TESTING_SIGN_IN_SECRET_HASH = os.getenv("TESTING_SIGN_IN_SECRET_HASH", "")

# Railway sets this to the environment's name ("production", ...). Empty off Railway. Everything that
# must behave differently on production is named off it.
RAILWAY_ENVIRONMENT_NAME = os.getenv("RAILWAY_ENVIRONMENT_NAME", "")

# Microsoft Entra app registration used to read the legacy SharePoint inventory list during the
# one-time migration (app-only client credentials, application-type Sites.ReadWrite.All). Blank on
# an environment that has not been given them, which leaves the migration wizard refusing with a
# configuration error rather than the app failing to boot.
AZURE_TENANT_ID = os.getenv("AZURE_TENANT_ID", "")
AZURE_CLIENT_ID = os.getenv("AZURE_CLIENT_ID", "")
AZURE_CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET", "")


# The browser origins allowed to call this backend cross-origin (#1115). The production frontend is
# built with VITE_GRAPHQL_URL pointing here, so its requests are cross-origin; the Vite dev server
# proxies /graphql and needs none of this, but its origins are listed so a dev build pointed straight
# at a backend still works. CORS_ALLOW_ORIGINS (comma-separated) replaces the list when a frontend
# gains another domain. The relay's /relay-link socket is not a browser and is not subject to CORS.
DEFAULT_CORS_ALLOW_ORIGINS = (
    "https://frontend-production-34fc.up.railway.app",
    "http://localhost:5173",
    "http://localhost:4173",
)


def cors_allow_origins() -> list[str]:
    raw = os.getenv("CORS_ALLOW_ORIGINS", "")
    origins = [o.strip().rstrip("/") for o in raw.split(",") if o.strip()]
    return origins or list(DEFAULT_CORS_ALLOW_ORIGINS)


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


def db_direct_access_enabled() -> bool:
    """Whether the Database Access page and its five root fields are live in this environment.

    Enabled only when the proxy coordinates are configured. Local dev and CI are covered for free - they
    never set the variable.

    Read off the module constant (not os.getenv) so a test can flip it with monkeypatch."""
    return bool(PG_DIRECT_HOST.strip())


def testing_sign_in_secret_hash() -> str:
    """The digest /testing/clerk-sign-in accepts, or "" when the secret path is closed.

    Read off the module constant at call time, so a test can set it with monkeypatch.
    """
    return TESTING_SIGN_IN_SECRET_HASH.strip()
