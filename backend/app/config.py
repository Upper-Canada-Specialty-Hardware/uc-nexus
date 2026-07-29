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

# Railway sets this to the environment's name ("production", "pr-414", ...). Empty off Railway.
# app/services/relay_seed.py uses it as the production kill-switch for credential seeding.
RAILWAY_ENVIRONMENT_NAME = os.getenv("RAILWAY_ENVIRONMENT_NAME", "")

# SHA-256 hex of the workstation relay's long-lived Bearer secret - the same digest already sitting in
# production's relay_installs.secret_hash, copied from Admin -> Relay Installs. Set ONLY on the Railway
# environment that PR deploys duplicate, so a PR backend can accept the one relay that exists without a
# manual provision + enroll per PR (#414). A hash is a verifier, not a credential: it cannot be replayed
# to authenticate. relay_seed refuses to act on it in production regardless.
RELAY_SEED_SECRET_HASH = os.getenv("RELAY_SEED_SECRET_HASH", "")
