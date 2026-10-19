"""Who can drive a shipment (#1726).

A driver is a signed-in account holding the Driver role, so the shipment names a person the app knows
rather than a name typed into a box: the driver page (#1727) finds a driver's own deliveries by it. The
slip keeps the id and a snapshot of the name, the way it snapshots the shipment method, so a reprint
years later still says who drove even if the account is gone.

A driver drives for the company their account is in. The demo company has no accounts of its own -
everybody in it is a UBC or TUBC account role-playing (#1658) - so a demo shipment's drivers are theirs.
"""

from app.auth import DRIVER_ROLE
from app.demo import DEMO_ALLOWED_COMPANIES, is_demo_company
from app.errors import ValidationError
from app.repositories.user_repository import normalize_company


def _companies_for(company: str) -> frozenset[str]:
    return DEMO_ALLOWED_COMPANIES if is_demo_company(company) else frozenset({company})


def display_name(entry: dict) -> str:
    """The name a roster entry goes by: full name, else email, else the id - the same order the rest of
    the app stamps actors in."""
    full = f"{entry.get('first_name') or ''} {entry.get('last_name') or ''}".strip()
    return full or entry.get("email") or entry["id"]


def drivers_for(roster: list[dict], company: str) -> list[dict]:
    """The roster entries that may drive `company`'s shipments, by name."""
    companies = _companies_for(company)
    found = [
        u for u in roster if DRIVER_ROLE in (u.get("roles") or []) and normalize_company(u.get("company")) in companies
    ]
    return sorted(found, key=lambda u: display_name(u).lower())


def resolve_driver(roster: list[dict], company: str, driver_user_id: str | None) -> tuple[str, str] | None:
    """The driver a write names, as (user id, name), or None for no driver. Refused when the id is not
    one of the company's drivers - an account without the role, or another company's."""
    if not driver_user_id:
        return None
    for u in drivers_for(roster, company):
        if u["id"] == driver_user_id:
            return u["id"], display_name(u)
    raise ValidationError("That person is not one of this company's drivers.", field="driver_user_id")
