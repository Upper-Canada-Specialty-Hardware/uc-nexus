"""The protect-secret CLI (encrypt a plaintext shared_secret in place). Windows-only - it actually
calls DPAPI."""

import re
import sys

import pytest

from ucnexus_relay import dpapi
from ucnexus_relay.protect_secret import main

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows-only")


def _secret_value(text: str) -> str:
    return re.search(r'^\s*shared_secret\s*=\s*"(.*?)"', text, re.MULTILINE).group(1)


@windows_only
def test_encrypts_plaintext_in_place(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('[auth]\nshared_secret = "my-plain-secret"\n\n[gp]\nmode = "sql"\n', encoding="utf-8")

    assert main(["--config", str(cfg)]) == 0

    text = cfg.read_text(encoding="utf-8")
    val = _secret_value(text)
    assert dpapi.is_encrypted(val)
    assert dpapi.unprotect(val) == "my-plain-secret"
    assert 'mode = "sql"' in text  # rest of the file preserved


@windows_only
def test_idempotent_when_already_encrypted(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('[auth]\nshared_secret = "secret"\n', encoding="utf-8")
    assert main(["--config", str(cfg)]) == 0
    after_first = cfg.read_text(encoding="utf-8")
    # second run is a no-op - already an enc:dpapi: blob
    assert main(["--config", str(cfg)]) == 0
    assert cfg.read_text(encoding="utf-8") == after_first


def test_missing_config_errors(tmp_path):
    assert main(["--config", str(tmp_path / "nope.toml")]) == 1
