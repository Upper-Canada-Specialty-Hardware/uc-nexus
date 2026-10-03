"""One-time relay enrollment CLI.

Run during setup with an enrollment token minted in UC Nexus (admin -> provision relay install):

    python -m ucnexus_relay.enroll --token <ENROLLMENT_TOKEN> --backend-url https://<backend-host>/graphql

The relay generates its OWN long-lived Bearer secret, registers it with the UC Nexus backend using the
one-time token (the backend can't reach the relay, but the relay can reach the backend), and writes that
secret into this install's config.toml [auth] shared_secret. Nothing long-lived is ever hand-copied -
only the throwaway enrollment token is carried from UC Nexus to here.

A relay that is already running does NOT need restarting: channel.run_forever re-reads config.toml on
every reconnect attempt, so it picks the new secret up within one backoff interval. That used to be a
manual step, and forgetting it stranded the relay in a permanent 403 loop with a valid enrolment row
in the database.
"""

import argparse
import json
import os
import re
import secrets
import socket
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from . import dpapi
from .config import DEFAULT_CONFIG_PATH
from .fsutil import atomic_write_text

_MUTATION = "mutation Enroll($input: EnrollRelayInstallInput!) { enrollRelayInstall(input: $input) { ok installId } }"


def _post_graphql(url: str, query: str, variables: dict) -> dict:
    body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 (trusted backend URL from operator)
        return json.loads(resp.read().decode())


class EnrollError(Exception):
    """Enrollment failed. `detail` carries the backend errors / raw response for logging or the UI."""

    def __init__(self, message: str, detail=None):
        super().__init__(message)
        self.message = message
        self.detail = detail


_SECRET_LINE = re.compile(r'^(\s*shared_secret\s*=\s*)".*?"', re.MULTILINE)

_ADOPT_HINT = (
    "UC Nexus has already accepted this enrollment, so the token is spent. In UC Nexus Admin -> Relay Installs, "
    "press Adopt next connection on this install: the relay's next connection is then accepted with the "
    "secret it already holds"
)


def check_config_writable(config_path: Path) -> None:
    """Refuse up front, before the one-time token is spent (#1384), a config.toml the secret could not be
    written into: unreadable, with no [auth] shared_secret line, or in a place this process cannot write."""
    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError as e:
        raise EnrollError(f"cannot read {config_path}: {e}") from e
    if not _SECRET_LINE.search(text):
        raise EnrollError(f"could not find [auth] shared_secret in {config_path}; add the line, then enroll again")
    try:
        with open(config_path, "a", encoding="utf-8"):
            pass
        fd, probe = tempfile.mkstemp(prefix=".enroll-probe.", dir=config_path.parent)
        os.close(fd)
        os.unlink(probe)
    except OSError as e:
        raise EnrollError(f"{config_path} cannot be written: {e}") from e


def write_secret_to_config(config_path: Path, secret: str) -> None:
    """Replace the [auth] shared_secret value in config.toml, preserving the rest of the file, atomically
    (#1386). The `secret` written here is the storage form: either a token_urlsafe plaintext (dev) or a DPAPI
    `enc:dpapi:<base64>` blob. Both contain only TOML-safe chars (URL-safe + standard base64), so there's
    nothing to escape inside the double-quoted string."""
    text = config_path.read_text(encoding="utf-8")
    if not _SECRET_LINE.search(text):
        raise EnrollError(f"could not find [auth] shared_secret in {config_path}; set it manually to the new secret")
    atomic_write_text(config_path, _SECRET_LINE.sub(rf'\1"{secret}"', text, count=1))


def enroll_relay(*, token: str, backend_url: str, config_path: str | Path, encrypt: bool = True) -> dict:
    """Generate this install's long-lived secret, register it with the backend using the one-time token,
    and write it (DPAPI-encrypted unless encrypt=False) into config.toml [auth] shared_secret, creating
    that file if the workstation has none. Returns a result dict; raises EnrollError on any failure.
    Shared by the CLI (main) and the UI setup wizard."""
    config_path = Path(config_path)
    hostname = socket.gethostname()
    secret = secrets.token_urlsafe(32)

    # Everything that can fail locally happens BEFORE the token is spent (#1384). A workstation may have
    # no config.toml at all - the installer seeds one from config.example.toml, but a hand-copied exe has
    # nothing and the Setup tab no longer writes one - so the minimal file (placeholder secret) is created
    # here. Done only when the file is ABSENT: one that exists without an [auth] shared_secret line was
    # hand-edited, and is refused rather than rewritten.
    if not config_path.exists():
        from . import setup  # lazy: enroll runs as a CLI and should not pull the wizard's helpers in

        try:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            created = setup.write_config({}, config_path)
        except OSError as e:
            raise EnrollError(f"cannot create {config_path}: {e}") from e
        if not created.get("ok"):
            raise EnrollError(created.get("error") or f"cannot create {config_path}")
    check_config_writable(config_path)
    # the backend stores the PLAINTEXT secret (the frontend presents it as the Bearer token); locally we
    # persist the DPAPI-encrypted form so config.toml holds no plaintext at rest. Protected up front too.
    try:
        stored = secret if not encrypt else dpapi.protect(secret)
    except Exception as e:  # noqa: BLE001
        raise EnrollError(f"could not encrypt the secret: {e}") from e

    variables = {"input": {"enrollmentToken": token, "hostname": hostname, "secret": secret}}
    try:
        result = _post_graphql(backend_url, _MUTATION, variables)
    except urllib.error.URLError as e:
        raise EnrollError(f"enrollment request failed: {e}") from e

    if result.get("errors"):
        raise EnrollError("enrollment rejected by backend", detail=result["errors"])
    data = (result.get("data") or {}).get("enrollRelayInstall") or {}
    if not data.get("ok"):
        raise EnrollError("enrollment did not succeed", detail=result)

    try:
        write_secret_to_config(config_path, stored)
    except (OSError, EnrollError) as e:
        reason = e.message if isinstance(e, EnrollError) else str(e)
        raise EnrollError(f"could not write the secret to {config_path} ({reason}). {_ADOPT_HINT}.") from e
    return {
        "ok": True,
        "install_id": data.get("installId"),
        "hostname": hostname,
        "how": "plaintext" if not encrypt else "DPAPI-encrypted (CurrentUser)",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Enroll this relay with UC Nexus (one-time setup).")
    parser.add_argument("--token", required=True, help="one-time enrollment token from UC Nexus")
    parser.add_argument("--backend-url", required=True, help="UC Nexus backend GraphQL URL, e.g. https://host/graphql")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="path to config.toml")
    parser.add_argument(
        "--no-encrypt",
        action="store_true",
        help="store the secret as plaintext (dev only); the default DPAPI-encrypts it at rest",
    )
    args = parser.parse_args(argv)

    try:
        r = enroll_relay(
            token=args.token, backend_url=args.backend_url, config_path=args.config, encrypt=not args.no_encrypt
        )
    except EnrollError as e:
        detail = f": {json.dumps(e.detail)}" if e.detail is not None else ""
        print(f"{e.message}{detail}", file=sys.stderr)
        return 1

    print(
        f"enrolled install {r['install_id']} as host {r['hostname']}; "
        f"secret written {r['how']} to {args.config}. a running relay picks this up on its next "
        f"reconnect (within ~30s) - no restart needed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
