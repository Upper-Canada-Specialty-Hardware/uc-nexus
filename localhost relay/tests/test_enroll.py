"""Enrollment config-rewrite (the non-network part). Network enroll is exercised manually during setup."""

import pytest

from ucnexus_relay.enroll import write_secret_to_config


def test_write_secret_replaces_shared_secret(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('[auth]\nshared_secret = "OLD_VALUE"\n\n[gp]\ndefault_company = "TUBC"\n', encoding="utf-8")
    write_secret_to_config(cfg, "NEW_SECRET_xyz")
    text = cfg.read_text(encoding="utf-8")
    assert 'shared_secret = "NEW_SECRET_xyz"' in text
    assert "OLD_VALUE" not in text
    assert 'default_company = "TUBC"' in text  # rest of the file preserved


def test_write_secret_errors_when_no_shared_secret(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('[gp]\ndefault_company = "TUBC"\n', encoding="utf-8")
    with pytest.raises(SystemExit):
        write_secret_to_config(cfg, "NEW")
