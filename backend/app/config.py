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


def is_production_environment() -> bool:
    """Whether this deployment is the production Railway environment.

    Named off RAILWAY_ENVIRONMENT_NAME rather than inferred from a URL or a flag, so it cannot be
    turned off by a variable somebody sets on production by mistake. Empty off Railway, which reads as
    "not production" - correct for a local checkout.
    """
    return RAILWAY_ENVIRONMENT_NAME.strip().lower() == "production"


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

# Railway injects the project this service belongs to. Empty off Railway.
RAILWAY_PROJECT_ID = os.getenv("RAILWAY_PROJECT_ID", "")

# Railway API token, set ONLY on production. It lets /relay-channels tell the workstation relay which
# preview environments exist right now, so adding a PR environment stops being a hand edit on that
# machine (app/services/relay_channels.py). Blank disables discovery and the route answers an empty
# list, which is the correct answer everywhere except production - a preview environment must not be
# able to advertise other preview environments.
#
# Use a WORKSPACE token. Railway offers three kinds and only two of them are viable here: an account
# token carries everything the account can reach, and a PROJECT token authenticates with a
# `Project-Access-Token` header rather than `Authorization: Bearer` AND is scoped to a single
# environment, so it could neither authenticate this call nor see its siblings. A workspace token is
# the narrowest one that can list a project's environments over Bearer auth.
#
# Railway has no read-only scope on any of them, so this is a write-capable credential however
# narrowly it is scoped. Nothing here ever issues a mutation, and it lives on production alone.
RAILWAY_API_TOKEN = os.getenv("RAILWAY_API_TOKEN", "")

# Overridable because Railway has served its public API from more than one host; a change there should
# be a variable edit, not a redeploy of pinned code.
RAILWAY_API_URL = os.getenv("RAILWAY_API_URL", "https://backboard.railway.com/graphql/v2")
