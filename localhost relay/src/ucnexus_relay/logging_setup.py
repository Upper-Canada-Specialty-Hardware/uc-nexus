"""Structured JSON logging to file + console."""

import logging

from pythonjsonlogger import jsonlogger

_CONFIGURED = False


def configure_logging(level: str = "INFO", file_path: str = "relay.log") -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    fmt = jsonlogger.JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    root = logging.getLogger()
    root.setLevel(level)
    fh = logging.FileHandler(file_path)
    fh.setFormatter(fmt)
    root.addHandler(fh)
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    root.addHandler(ch)
    _CONFIGURED = True


def get_logger() -> logging.Logger:
    return logging.getLogger("ucnexus_relay")
