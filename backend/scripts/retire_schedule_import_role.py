"""Take the retired "Hardware Schedule Import" role off every Clerk account that holds it (#1390).

The role opened nothing: no launcher card, sidebar entry or page keyed on it. The product owner retired
it rather than give it a page, and ruled that accounts holding it lose it. The User Management page no
longer offers it and `updateUserRoles` refuses granting it; this takes it off the accounts that already
have it. Nothing else on an account changes.

Run it from `backend/`, against production through the recipe the other scripts use:

    railway run --service backend --environment production -- \
        poetry run python scripts/retire_schedule_import_role.py            # --plan, the default
    ... scripts/retire_schedule_import_role.py --strip

Idempotent: an account without the role is left alone. `--plan` writes nothing.
"""

import argparse
import sys
from pathlib import Path

# Run as a script from backend/ (`python scripts/...`), which puts backend/scripts on sys.path rather
# than backend/ itself. Under pytest the repository root is already there and this is a no-op.
_BACKEND_ROOT = str(Path(__file__).resolve().parent.parent)
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from app import config  # noqa: E402
from app.repositories import user_repository  # noqa: E402

# A literal rather than an import: app/auth.py never named it, and the app no longer offers it.
RETIRED_ROLE = "Hardware Schedule Import"


def _roles(user: dict) -> list[str]:
    return list(user.get("roles") or [])


def _label(user: dict) -> str:
    """How an account is named in the output: its email, or its Clerk id when it has none."""
    return user.get("email") or user.get("id") or "(unknown)"


def holders(users: list[dict]) -> list[dict]:
    return [u for u in users if RETIRED_ROLE in _roles(u)]


def plan(users: list[dict]) -> int:
    """Print who holds the role and what they keep. No writes."""
    found = holders(users)
    print(f"{len(found)} of {len(users)} Clerk accounts hold {RETIRED_ROLE!r}.")
    for user in found:
        kept = [r for r in _roles(user) if r != RETIRED_ROLE]
        print(f"  {_label(user)}: keeps {', '.join(kept) if kept else '(no roles)'}")
    if found:
        print("No changes were made. Run --strip to take the role off.")
    return 0


def strip(users: list[dict]) -> int:
    """Remove the role from every holder, merging into publicMetadata so nothing else there is lost.

    `_merge_public_metadata` rather than `update_user_roles`: that one also clears the GP buyer identity
    of an account without PO User (#687 gap 6), a side effect this retirement must not have."""
    found = holders(users)
    for user in found:
        kept = [r for r in _roles(user) if r != RETIRED_ROLE]
        user_repository._merge_public_metadata(user["id"], {"roles": kept})
        print(f"  {_label(user)}: now {', '.join(kept) if kept else '(no roles)'}")
    print(f"Removed {RETIRED_ROLE!r} from {len(found)} account(s).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--plan", action="store_true", help="print who holds the role and write nothing (the default)")
    mode.add_argument("--strip", action="store_true", help=f"remove {RETIRED_ROLE!r} from every account")
    args = parser.parse_args(argv)

    if not (config.CLERK_SECRET_KEY or "").strip():
        print("CLERK_SECRET_KEY is not set, so Clerk cannot be read or written. Refusing to run.")
        return 2

    users = user_repository.list_users()
    return strip(users) if args.strip else plan(users)


if __name__ == "__main__":
    raise SystemExit(main())
