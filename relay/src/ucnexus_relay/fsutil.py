"""Atomic file writes for the relay's own state (#1386).

config.toml holds the enrolled secret and update-state.json the update ledger. Written in place, a crash
or power loss mid-write leaves a truncated file: the secret is gone and the install is stranded. Writing a
temp file beside the target, flushing and fsyncing it, then os.replace-ing it over the target means a
reader sees either the old file or the new one, never half of one."""

import os
import tempfile
from pathlib import Path


def atomic_write_text(path: str | Path, text: str, encoding: str = "utf-8") -> None:
    path = Path(path)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
