"""Encryption + hashing for relay install credentials.

The relay's long-lived Bearer secret is stored ENCRYPTED (Fernet) - not hashed - because the frontend
needs the raw value back to send as the Authorization header (relayCredential returns it decrypted).
The one-time enrollment token is stored HASHED (we only ever verify a presented token, never return it)."""

import hashlib
import os

from cryptography.fernet import Fernet

from app.errors import AppError


def _fernet() -> Fernet:
    key = os.getenv("RELAY_SECRET_ENC_KEY", "")
    if not key:
        raise AppError("RELAY_SECRET_ENC_KEY is not configured", "CONFIG_ERROR")
    return Fernet(key.encode())


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()


def hash_token(token: str) -> str:
    """SHA-256 of a one-time enrollment token (stored, then compared on enroll)."""
    return hashlib.sha256(token.encode()).hexdigest()
