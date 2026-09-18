"""Move every Clerk account off the retired "Admin/Manager" role (#729).

That one role string bundled an all-modules bypass with an exemption from the GP COMPANY NEXUS
TENANT line. It is replaced by UC NEXUS ADMIN, which keeps the cross-company half, and TENANT OWNER,
which keeps the rest inside one GP company. Nobody is re-assigned automatically: four named accounts
and the e2e testing account become UC NEXUS ADMIN, and everyone else is given their new roles by
hand afterwards.

Run it from `backend/`:

    poetry run python scripts/migrate_admin_manager_roles.py            # --plan, the default
    poetry run python scripts/migrate_admin_manager_roles.py --grant
    poetry run python scripts/migrate_admin_manager_roles.py --strip

Against production, through the recipe the read-only scripts already use:

    railway run --service backend --environment production -- \
        poetry run python scripts/migrate_admin_manager_roles.py --plan

TWO PASSES, and the order is what keeps the four admins working through the deploy:

  - `--grant` runs BEFORE the deploy. It ADDS "UC Nexus Admin" and leaves "Admin/Manager" in place,
    so those accounts hold both. The frontend in production at that moment ignores a role it does
    not know, so nothing changes for anybody until the new build lands.
  - `--strip` runs right AFTER the deploy is healthy. It removes "Admin/Manager" from everyone, and
    removes "DB Admin" from anyone the strip would otherwise leave holding it without UC Nexus
    Admin - the tier is stacked, never standalone.

Both passes are idempotent: an account that already has the end state is left alone and reported as
unchanged. `--plan` writes nothing at all.
"""

import argparse
import sys
from pathlib import Path

# Run as a script from backend/ (`python scripts/...`), which puts backend/scripts on sys.path
# rather than backend/ itself. Under pytest the repository root is already there and this is a
# no-op.
_BACKEND_ROOT = str(Path(__file__).resolve().parent.parent)
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from app import config  # noqa: E402
from app.auth import DB_ADMIN_ROLE, NEXUS_ADMIN_ROLE  # noqa: E402
from app.repositories import user_repository  # noqa: E402

# The role being retired. A literal rather than an import: app/auth.py no longer names it, which is
# the point of the migration.
RETIRED_ROLE = "Admin/Manager"

# The four people who become UC NEXUS ADMIN. Everybody else who holds the retired role is
# re-assigned by hand after the strip, which is the ruling - nobody is given a new role by default.
NEW_ADMIN_EMAILS = (
    "jonathanr@ucsh.com",
    "stevef@ucsh.com",
    "josep@ucsh.com",
    "jayp@ucsh.com",
)


def _roles(user: dict) -> list[str]:
    return list(user.get("roles") or [])


def _roles_after_strip(roles: list[str]) -> list[str]:
    """What `--strip` leaves an account holding: no retired role, and no orphaned DB Admin."""
    after = [r for r in roles if r != RETIRED_ROLE]
    if DB_ADMIN_ROLE in after and NEXUS_ADMIN_ROLE not in after:
        after = [r for r in after if r != DB_ADMIN_ROLE]
    return after


def _label(user: dict) -> str:
    """How an account is named in the output: its email, or its Clerk id when it has none."""
    return user.get("email") or user.get("id") or "(unknown)"


def _fmt(roles: list[str]) -> str:
    return ", ".join(roles) if roles else "(none)"


def _print_table(rows: list[tuple[str, str, str]], headers: tuple[str, str, str]) -> None:
    widths = [len(h) for h in headers]
    for row in rows:
        widths = [max(w, len(cell)) for w, cell in zip(widths, row, strict=True)]
    line = "  ".join(h.ljust(w) for h, w in zip(headers, widths, strict=True))
    print(line)
    print("  ".join("-" * w for w in widths))
    for row in rows:
        print("  ".join(cell.ljust(w) for cell, w in zip(row, widths, strict=True)))


def _write_roles(user: dict, roles: list[str]) -> None:
    """Set one account's roles, merging into publicMetadata so nothing else there is lost.

    `_merge_public_metadata` rather than `update_user_roles`: that one also clears the GP buyer
    identity of an account without PO User (#687 gap 6), which is the right behaviour for the Edit
    User dialog and the wrong one here - this migration changes which admin role somebody holds and
    must not take a buyer's GP identity away as a side effect."""
    user_repository._merge_public_metadata(user["id"], {"roles": roles})


def plan(users: list[dict]) -> int:
    """Print who holds the retired role and what `--strip` would leave them with. No writes."""
    holders = [u for u in users if RETIRED_ROLE in _roles(u)]
    print(f"{len(holders)} of {len(users)} Clerk accounts hold {RETIRED_ROLE!r}.")
    if not holders:
        print("Nothing to do.")
        return 0

    rows = [(_label(u), _fmt(_roles(u)), _fmt(_roles_after_strip(_roles(u)))) for u in holders]
    _print_table(rows, ("ACCOUNT", "ROLES NOW", "ROLES AFTER --strip"))
    print()
    print(f"These accounts would be granted {NEXUS_ADMIN_ROLE!r} by --grant:")
    for email in NEW_ADMIN_EMAILS:
        print(f"  {email}")
    e2e_id = (config.E2E_CLERK_USER_ID or "").strip()
    print(f"  {e2e_id or '(E2E_CLERK_USER_ID is not set)'}  (the e2e testing account)")
    print()
    print("No changes were made. Run --grant before the deploy and --strip after it.")
    return 0


def _grant_targets(users: list[dict]) -> tuple[list[dict], list[str]]:
    """The accounts `--grant` acts on, and the names of the ones Clerk does not have.

    Email matching is case-insensitive: Clerk stores what the person typed when the account was
    created, and a capital letter in an address must not silently skip an admin."""
    by_email = {(u.get("email") or "").strip().lower(): u for u in users}
    by_id = {u.get("id"): u for u in users}

    found: list[dict] = []
    missing: list[str] = []
    for email in NEW_ADMIN_EMAILS:
        user = by_email.get(email.lower())
        if user is None:
            missing.append(email)
        else:
            found.append(user)

    e2e_id = (config.E2E_CLERK_USER_ID or "").strip()
    if not e2e_id:
        missing.append("the e2e testing account (E2E_CLERK_USER_ID is not set)")
    elif e2e_id in by_id:
        found.append(by_id[e2e_id])
    else:
        missing.append(f"the e2e testing account ({e2e_id})")
    return found, missing


def grant(users: list[dict]) -> int:
    """Add UC Nexus Admin to the five accounts that keep cross-company authority.

    All five must exist before anything is written. A partial grant is the one outcome worth
    avoiding: it would leave the deploy with some of the admins carried across and some not, and
    working out which is which afterwards means reading Clerk account by account."""
    found, missing = _grant_targets(users)
    if missing:
        print(f"Refusing to write: {len(missing)} of the five accounts were not found in Clerk.")
        for name in missing:
            print(f"  {name}")
        return 1

    changed = 0
    rows: list[tuple[str, str, str]] = []
    for user in found:
        before = _roles(user)
        if NEXUS_ADMIN_ROLE in before:
            rows.append((_label(user), _fmt(before), "unchanged"))
            continue
        after = [*before, NEXUS_ADMIN_ROLE]
        _write_roles(user, after)
        rows.append((_label(user), _fmt(before), _fmt(after)))
        changed += 1

    _print_table(rows, ("ACCOUNT", "ROLES BEFORE", "ROLES AFTER"))
    print()
    print(f"Granted {NEXUS_ADMIN_ROLE!r} to {changed} account(s); {len(found) - changed} already had it.")
    print(f"{RETIRED_ROLE!r} is untouched, so these accounts keep working until the deploy lands.")
    return 0


def strip(users: list[dict]) -> int:
    """Remove the retired role from everyone, and any DB Admin the removal would strand."""
    rows: list[tuple[str, str, str]] = []
    stranded: list[str] = []
    changed = 0
    for user in users:
        before = _roles(user)
        after = _roles_after_strip(before)
        if after == before:
            continue
        if DB_ADMIN_ROLE in before and DB_ADMIN_ROLE not in after:
            stranded.append(_label(user))
        _write_roles(user, after)
        rows.append((_label(user), _fmt(before), _fmt(after)))
        changed += 1

    if not rows:
        print(f"No account holds {RETIRED_ROLE!r} or a standalone {DB_ADMIN_ROLE!r}. Nothing to do.")
        return 0

    _print_table(rows, ("ACCOUNT", "ROLES BEFORE", "ROLES AFTER"))
    print()
    print(f"Updated {changed} account(s).")
    if stranded:
        print()
        print(
            f"{DB_ADMIN_ROLE!r} was also removed from the following, because the tier stacks on "
            f"{NEXUS_ADMIN_ROLE!r} and they do not hold it:"
        )
        for name in stranded:
            print(f"  {name}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--plan", action="store_true", help="print what would change and write nothing (the default)")
    mode.add_argument("--grant", action="store_true", help=f"add {NEXUS_ADMIN_ROLE!r} to the five named accounts")
    mode.add_argument("--strip", action="store_true", help=f"remove {RETIRED_ROLE!r} from every account")
    args = parser.parse_args(argv)

    if not (config.CLERK_SECRET_KEY or "").strip():
        print("CLERK_SECRET_KEY is not set, so Clerk cannot be read or written. Refusing to run.")
        return 2

    users = user_repository.list_users()
    if args.grant:
        return grant(users)
    if args.strip:
        return strip(users)
    return plan(users)


if __name__ == "__main__":
    raise SystemExit(main())
