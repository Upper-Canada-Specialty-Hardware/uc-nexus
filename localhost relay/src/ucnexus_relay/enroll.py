"""One-time relay enrollment CLI.

Run during setup with an enrollment token minted in UC Nexus (admin -> provision relay install):

    python -m ucnexus_relay.enroll --token <ENROLLMENT_TOKEN> --backend-url https://<backend-host>/graphql

The relay generates its OWN long-lived Bearer secret, registers it with the UC Nexus backend using the
one-time token (the backend can't reach the relay, but the relay can reach the backend), and writes that
secret into this install's config.toml [auth] shared_secret. Restart the relay afterwards. Nothing
long-lived is ever hand-copied - only the throwaway enrollment token is carried from UC Nexus to here.
"""

import argparse
import json
import re
import secrets
import socket
import sys
import urllib.error
import urllib.request
from pathlib import Path

from . import dpapi
from .config import DEFAULT_CONFIG_PATH, get_settings

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

    config_path = Path(args.config)
    hostname = socket.gethostname()
    company = get_settings(args.config).gp.default_company
    secret = secrets.token_urlsafe(32)

    variables = {"input": {"enrollmentToken": args.token, "hostname": hostname, "secret": secret}}
    try:
        result = _post_graphql(args.backend_url, _MUTATION, variables)
    except urllib.error.URLError as e:
        print(f"enrollment request failed: {e}", file=sys.stderr)
        return 1

    if result.get("errors"):
        print(f"enrollment rejected: {json.dumps(result['errors'])}", file=sys.stderr)
        return 1
    data = (result.get("data") or {}).get("enrollRelayInstall") or {}
    if not data.get("ok"):
        print(f"enrollment did not succeed: {json.dumps(result)}", file=sys.stderr)
        return 1

    # the backend stores the PLAINTEXT secret (it's what the frontend will present as the Bearer token);
    # locally we persist the DPAPI-encrypted form so config.toml holds no plaintext at rest.
    stored = secret if args.no_encrypt else dpapi.protect(secret)
    write_secret_to_config(config_path, stored)
    how = "plaintext" if args.no_encrypt else "DPAPI-encrypted (CurrentUser)"
    print(
        f"enrolled install {data.get('installId')} as host {hostname} (company {company}); "
        f"secret written {how} to {config_path}. restart the relay."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
