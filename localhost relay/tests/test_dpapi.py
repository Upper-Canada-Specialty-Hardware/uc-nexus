"""DPAPI at-rest protection. The round-trip + decrypt tests need Windows; the prefix/passthrough logic
is platform-independent and always runs."""

import sys

import pytest

from ucnexus_relay import dpapi

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows-only")


def test_is_encrypted_prefix():
    assert dpapi.is_encrypted("enc:dpapi:anything")
    assert not dpapi.is_encrypted("plain-token")
    assert not dpapi.is_encrypted("")


def test_unprotect_passes_through_plaintext():
    # a dev config with a plaintext secret must keep working, even on non-Windows
    assert dpapi.unprotect("plain-secret-123") == "plain-secret-123"


@windows_only
def test_round_trip():
    secret = "s3cr3t-token_ABC-123"
    blob = dpapi.protect(secret)
    assert blob.startswith(dpapi.ENC_PREFIX)
    assert secret not in blob  # stored as ciphertext, not plaintext
    assert dpapi.unprotect(blob) == secret


@windows_only
def test_protect_uses_random_salt():
    # DPAPI salts each call, so two encryptions of the same value differ but both decrypt back
    a = dpapi.protect("same-value")
    b = dpapi.protect("same-value")
    assert a != b
    assert dpapi.unprotect(a) == dpapi.unprotect(b) == "same-value"


@windows_only
def test_get_settings_decrypts_shared_secret(tmp_path):
    from ucnexus_relay.config import get_settings

    secret = "round-trip-secret-xyz"
    enc = dpapi.protect(secret)
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f'[auth]\nshared_secret = "{enc}"\n\n[backend]\nurl = "wss://x/relay-link"\n\n[sql]\nserver = "x"\n',
        encoding="utf-8",
    )
    # unique path -> not served from the lru_cache of other tests
    s = get_settings(str(cfg))
    assert s.auth.shared_secret == secret
