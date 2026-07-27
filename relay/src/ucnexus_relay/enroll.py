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
import re
import secrets
import socket
import sys
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

from . import dpapi
from .config import DEFAULT_CONFIG_PATH

_MUTATION = (
    "mutation Enroll($input: EnrollRelayInstallInput!) { "
    "enrollRelayInstall(input: $input) { ok installId } }"
)


def _post_graphql(url: str, query: str, variables: dict) -> dict:
    body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 (trusted backend URL from operator)
        return json.loads(resp.read().decode())


def write_secret_to_config(config_path: Path, secret: str) -> None:
    """Replace the [auth] shared_secret value in config.toml, preserving the rest of the file. The
    `secret` written here is the storage form: either a token_urlsafe plaintext (dev) or a DPAPI
    `enc:dpapi:<base64>` blob. Both contain only TOML-safe chars (URL-safe + standard base64), so there's
    nothing to escape inside the double-quoted string."""
    text = config_path.read_text(encoding="utf-8")
    pattern = re.compile(r'^(\s*shared_secret\s*=\s*)".*?"', re.MULTILINE)
    if not pattern.search(text):
        raise SystemExit(f"could not find [auth] shared_secret in {config_path}; set it manually to the new secret")
    config_path.write_text(pattern.sub(rf'\1"{secret}"', text, count=1), encoding="utf-8")


class EnrollError(Exception):
    """Enrollment failed. `detail` carries the backend errors / raw response for logging or the UI."""

    def __init__(self, message: str, detail=None):
        super().__init__(message)
        self.message = message
        self.detail = detail


def _company_from_config(config_path: Path) -> str:
    """Read [gp].default_company directly (tomllib), not via get_settings - enrollment only needs the
    company, and the config at this point may not yet validate as full Settings (the wizard writes [sql]/
    [gp] and a placeholder secret before enrolling)."""
    try:
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return "TUBC"
    return (data.get("gp") or {}).get("default_company") or "TUBC"


def enroll_relay(*, token: str, backend_url: str, config_path: str | Path, encrypt: bool = True) -> dict:
    """Generate this install's long-lived secret, register it with the backend using the one-time token,
    and write it (DPAPI-encrypted unless encrypt=False) into config.toml [auth] shared_secret. Returns a
    result dict; raises EnrollError on any failure. Shared by the CLI (main) and the UI setup wizard."""
    config_path = Path(config_path)
    hostname = socket.gethostname()
    company = _company_from_config(config_path)
    secret = secrets.token_urlsafe(32)

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

    # the backend stores the PLAINTEXT secret (the frontend presents it as the Bearer token); locally we
    # persist the DPAPI-encrypted form so config.toml holds no plaintext at rest.
    stored = secret if not encrypt else dpapi.protect(secret)
    write_secret_to_config(config_path, stored)
    return {
        "ok": True,
        "install_id": data.get("installId"),
        "hostname": hostname,
        "company": company,
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
        f"enrolled install {r['install_id']} as host {r['hostname']} (company {r['company']}); "
        f"secret written {r['how']} to {args.config}. a running relay picks this up on its next "
        f"reconnect (within ~30s) - no restart needed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
