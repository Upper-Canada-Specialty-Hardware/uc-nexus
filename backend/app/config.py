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

# LEGACY (#353 PR C): the Fernet key for relay_installs.secret_encrypted. Since migration 067 the relay
# secret is stored as a SHA-256 hash, so this key is not read for any install enrolled or adopted after
# it - it survives only to decrypt pre-067 rows, which authenticate_secret upgrades in place on their
# next handshake. Once `SELECT count(*) FROM relay_installs WHERE secret_encrypted IS NOT NULL` is 0 it
# can be deleted from the environment.
# Generate with:  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
RELAY_SECRET_ENC_KEY = os.getenv("RELAY_SECRET_ENC_KEY", "")
