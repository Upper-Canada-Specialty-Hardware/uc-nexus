"""Store the relay's Bearer secret hashed, not encrypted (#353 PR C)

Revision ID: 067
Revises: 066
Create Date: 2026-07-27

Storing the relay secret reversibly made `RELAY_SECRET_ENC_KEY` a single point of PERMANENT failure:
rotate or lose it and every enrolled relay is orphaned, because the plaintext exists nowhere the
backend can reach. Hashing removes the key from the authentication path entirely.

SHA-256 hex, no KDF and no salt, deliberately. The credential is not a human password - the relay
generates it as `secrets.token_urlsafe(32)`, 256 bits of CSPRNG entropy, which stretching cannot
improve on, while per-handshake bcrypt/argon2 cost is a real downside during a reconnect storm. The
same reasoning already governs the enrollment-token hash.

**No data migration.** The plaintext is not recoverable here, so this only adds the column and its
index; `relay_repository.authenticate_secret` reads both representations and upgrades a legacy row in
place on its next successful handshake - which for a live relay is within ~30 seconds. Once
`SELECT count(*) FROM relay_installs WHERE secret_encrypted IS NOT NULL` reaches 0,
`RELAY_SECRET_ENC_KEY` is dead weight and can be deleted from the environment.

**Downgrade honesty.** Dropping `secret_hash` orphans any install that has no legacy ciphertext left
- i.e. anything enrolled or adopted from here on. CI's migration-integrity job runs against an empty
database so it passes cleanly, but on a populated one the downgrade means the relay must be recovered
with an admin-armed adopt window (066/#353 PR B) or re-enrolled by hand. That is precisely why the
adopt window landed first.
"""

import sqlalchemy as sa

from alembic import op

revision = "067"
down_revision = "066"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("relay_installs", sa.Column("secret_hash", sa.String(length=64), nullable=True))
    op.create_index("ix_relay_installs_secret_hash", "relay_installs", ["secret_hash"])


def downgrade() -> None:
    op.drop_index("ix_relay_installs_secret_hash", table_name="relay_installs")
    op.drop_column("relay_installs", "secret_hash")
