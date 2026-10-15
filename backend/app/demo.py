"""Demo mode (#1608): synthesized data so every workflow can be tried end to end without live data.

Demo data lives in one reserved GP company, `DEMO`. Everything Nexus already scopes by company -
projects, warehouses, POs, item types, doors on hand, shipment methods - is scoped by it, so the
tenant checks that keep one real company out of another's rows keep demo rows out of all of them,
with no extra filter on any query.

How a caller ends up in it:

  - an account carries `demoMode: true` in its Clerk publicMetadata;
  - a scoped caller in demo mode is pinned to `DEMO` by `app.auth.tenant_scope`, whatever company
    the account is assigned to;
  - a UC NEXUS ADMIN in demo mode sends `DEMO` as the `X-Nexus-Company` header, which the backend
    accepts only from an account whose demo flag is on.

GP for `DEMO` is simulated (app/services/demo_gp.py): the relay gateway answers a call for `DEMO`
itself and never puts it on the socket, so nothing reaches a real GP.

What is in it is built from UBC (app/services/demo_mirror.py): UBC's jobs as its projects, the legacy
inventory list as its warehouse, UBC's open POs, and GP's masters behind the simulated GP. It is built
once and kept - everybody in demo mode works in the same copy - and only an admin rebuilds it.

Only an account of a UBC company turns demo mode on (#1658): UBC and its test company TUBC. Whichever of
the two it is, the demo it lands in is the copy of UBC.

`DEMO` is never a real company. It cannot be assigned to an account, is not offered in the admin
switcher, and is skipped by every loop that walks the relay's real companies.
"""

import threading

DEMO_COMPANY = "DEMO"

# What GP calls the company, for the pickers that label a code with its name.
DEMO_COMPANY_NAME = "Demo Company (simulated)"

# The GP buyer everybody registers demo POs as. A real BUYERID belongs to a real company's buyer
# master, so in demo mode the account's own is set aside for this one, which the simulated GP knows.
DEMO_BUYER_ID = "DEMOBUYER"

# The company the demo is a copy of (#1657).
MIRROR_COMPANY = "UBC"

# The companies whose accounts may turn demo mode on (#1658): UBC and its test company. UCSH and any
# other company may not, however the account is set up.
DEMO_ALLOWED_COMPANIES = frozenset({"UBC", "TUBC"})

# The publicMetadata key the flag lives under.
DEMO_MODE_METADATA_KEY = "demoMode"


def may_use_demo_mode(company: str | None) -> bool:
    """Whether an account working in `company` may turn demo mode on (#1658)."""
    return (company or "").strip().upper() in DEMO_ALLOWED_COMPANIES


def is_demo_company(company: str | None) -> bool:
    """Whether `company` is the demo company. Normalized the way every company code is compared."""
    return (company or "").strip().upper() == DEMO_COMPANY


# Set while a reset is wiping and reseeding the demo company (app/services/demo_reset.py). In-process on
# purpose: the backend runs as one process - the relay socket lives in its memory - and the reset holds
# its own advisory lock across the whole of it, so this is the same fact read without a query (#1635).
_reset_running = threading.Event()


def demo_reset_running() -> bool:
    """Whether a demo reset is under way in this process."""
    return _reset_running.is_set()
