"""Hashing (and legacy encryption) for relay install credentials.

**Both relay credentials are stored hashed.** The one-time enrollment token always was. The relay's
long-lived Bearer secret became a hash in migration 067 (#353 PR C): storing it reversibly made
`RELAY_SECRET_ENC_KEY` a single point of *permanent* failure - rotate or lose that key and every
enrolled relay is orphaned with no recovery path, because the plaintext exists nowhere else.

`encrypt_secret` / `decrypt_secret` survive only to read pre-067 rows, which
`relay_repository.authenticate_secret` upgrades to a hash in place on their next handshake. That
retirement is finished (#382): the gating count reached 0, and `RELAY_SECRET_ENC_KEY` is set in no
environment any more - not on Railway, not in `.env.example`.

    SELECT count(*) FROM relay_installs WHERE secret_encrypted IS NOT NULL;  -- 0

With no key present `has_encryption_key` is False, so `authenticate_secret` skips the legacy decrypt
path and `_fernet` / `encrypt_secret` / `decrypt_secret` are reachable only from the tests.
`has_encryption_key` itself is NOT dead with them: it still runs on every rejected handshake to fill
the `encryption_key_present` log field.

No new legacy row can appear. `set_install_secret` NULLs `secret_encrypted` on every enroll and adopt,
and the only other statement naming the column is `/admin/reset-data` (main.py), which round-trips
existing values across a schema rebuild - it can preserve a legacy row, never create one.

Restoring one from an old backup would not help. Fernet needs the exact original key and no copy of it
survives anywhere, so a recovered pre-067 row is simply unreadable; an orphaned relay is recovered
through the admin-armed adopt window (066, #353 PR B) instead. Deleting these functions and dropping
the column is a separate job, and it has to touch that reset-data SQL too."""

import hashlib
import os

from cryptography.fernet import Fernet

from app.errors import AppError


def _fernet() -> Fernet:
    key = os.getenv("RELAY_SECRET_ENC_KEY", "")
    if not key:
        raise AppError("RELAY_SECRET_ENC_KEY is not configured", "CONFIG_ERROR")
    return Fernet(key.encode())


def has_encryption_key() -> bool:
    """Whether RELAY_SECRET_ENC_KEY is set. Callers use this to SKIP the legacy decrypt path entirely
    rather than raise: a missing key is fatal only for pre-067 rows, and a hash-only install must
    authenticate perfectly well without it."""
    return bool(os.getenv("RELAY_SECRET_ENC_KEY"))


def encrypt_secret(plaintext: str) -> str:
    """Legacy: only used to construct pre-067 rows (in tests). Nothing writes these in production."""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(token: str) -> str:
    """Legacy: read a pre-067 `secret_encrypted` so its row can be upgraded to a hash in place."""
    return _fernet().decrypt(token.encode()).decode()


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def hash_token(token: str) -> str:
    """SHA-256 of a one-time enrollment token (stored, then compared on enroll)."""
    return _sha256_hex(token)


def hash_secret(secret: str) -> str:
    """SHA-256 of the relay's long-lived Bearer secret.

    No KDF and no salt, deliberately. A KDF exists to make *low-entropy* secrets expensive to
    brute-force. This credential is not a human password: the relay generates it itself as
    `secrets.token_urlsafe(32)` (relay/src/ucnexus_relay/enroll.py) - 256 bits of CSPRNG entropy, which
    no amount of stretching improves on. Meanwhile per-handshake bcrypt/argon2 cost is a real downside
    during a reconnect storm, when every relay in a fleet is re-dialling at once. The same reasoning
    already governs `hash_token`."""
    return _sha256_hex(secret)
