"""Structured JSON logging to file + console."""

import logging
from logging.handlers import RotatingFileHandler

from pythonjsonlogger import jsonlogger

_CONFIGURED = False

# Rotate relay.log so a long-lived relay never grows it without bound (a workstation relay runs for weeks).
# ~2 MB is thousands of JSON events; keep a few rollovers for history.
_MAX_BYTES = 2_000_000
_BACKUP_COUNT = 3


def configure_logging(level: str = "INFO", file_path: str = "relay.log") -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    fmt = jsonlogger.JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    root = logging.getLogger()
    root.setLevel(level)
    fh = RotatingFileHandler(file_path, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    root.addHandler(ch)
    _CONFIGURED = True


def get_logger() -> logging.Logger:
    return logging.getLogger("ucnexus_relay")
