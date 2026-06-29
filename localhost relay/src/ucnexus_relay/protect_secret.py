"""DPAPI-encrypt the shared_secret already sitting in config.toml.

For the set-by-hand path: an operator pastes a plaintext secret into [auth] shared_secret, then runs

    python -m ucnexus_relay.protect_secret           (or: ucnexus-relay.exe protect-secret)

to encrypt it in place. The enroll CLI already encrypts what it writes, so this is only needed when the
secret was set manually. Idempotent - a value that's already `enc:dpapi:` is left untouched.
"""

import argparse
import re
import sys
from pathlib import Path

from . import dpapi
from .config import DEFAULT_CONFIG_PATH
from .enroll import write_secret_to_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DPAPI-encrypt the shared_secret in config.toml (CurrentUser).")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="path to config.toml")
    args = parser.parse_args(argv)

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"config file not found: {config_path}", file=sys.stderr)
        return 1

    text = config_path.read_text(encoding="utf-8")
    m = re.search(r'^\s*shared_secret\s*=\s*"(.*?)"', text, re.MULTILINE)
    if not m:
        print(f"could not find [auth] shared_secret in {config_path}", file=sys.stderr)
        return 1

    current = m.group(1)
    if dpapi.is_encrypted(current):
        print("shared_secret is already DPAPI-encrypted; nothing to do.")
        return 0

    write_secret_to_config(config_path, dpapi.protect(current))
    print(f"shared_secret in {config_path} is now DPAPI-encrypted (CurrentUser). restart the relay.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
