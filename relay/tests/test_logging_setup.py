"""Logging setup: relay.log rotates so a long-lived relay can't grow it without bound."""

import logging
from logging.handlers import RotatingFileHandler

from ucnexus_relay import logging_setup


def test_configure_logging_uses_a_rotating_file_handler(tmp_path, monkeypatch):
    # reset the one-shot guard so this call actually (re)configures, and restore it after
    monkeypatch.setattr(logging_setup, "_CONFIGURED", False)
    root = logging.getLogger()
    before = set(root.handlers)
    try:
        logging_setup.configure_logging("INFO", str(tmp_path / "relay.log"))
        rotating = [h for h in root.handlers if isinstance(h, RotatingFileHandler)]
        assert rotating, "relay.log must use a RotatingFileHandler so it can't grow unbounded"
        assert rotating[0].maxBytes > 0 and rotating[0].backupCount >= 1
    finally:
        for h in [h for h in root.handlers if h not in before]:
            root.removeHandler(h)
            h.close()
