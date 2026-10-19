"""Who can drive a shipment (#1726).

Pinned because a shipment names its driver by account, and the driver page (#1727) finds a driver's own
deliveries by that account: a slip naming somebody who is not a driver, or another company's, is a
delivery nobody sees.
"""

import pytest

from app.errors import ValidationError
from app.repositories import drivers


def _user(uid, *, roles=("Driver",), company="TUBC", first="", last="", email=""):
    return {"id": uid, "roles": list(roles), "company": company, "first_name": first, "last_name": last, "email": email}


ROSTER = [
    _user("u_dan", first="Dan", last="Driver"),
    _user("u_ann", first="Ann", last="Able"),
    _user("u_clerk", roles=("Shipping Out",), first="Not", last="Driver"),
    _user("u_other", company="UCSH", first="Other", last="Company"),
    _user("u_mail", company=" tubc ", email="driver@example.com"),
    _user("u_ubc", company="UBC", first="Ubc", last="Driver"),
]


def test_a_companys_drivers_are_its_driver_accounts_by_name():
    names = [drivers.display_name(u) for u in drivers.drivers_for(ROSTER, "TUBC")]
    # A company stored with odd casing or spaces is still that company; a nameless account goes by email.
    assert names == ["Ann Able", "Dan Driver", "driver@example.com"]


def test_a_demo_shipment_is_driven_by_the_ubc_companies_accounts():
    ids = {u["id"] for u in drivers.drivers_for(ROSTER, "DEMO")}
    assert ids == {"u_dan", "u_ann", "u_mail", "u_ubc"}


def test_resolving_a_driver_gives_the_id_and_the_name_to_keep():
    assert drivers.resolve_driver(ROSTER, "TUBC", "u_dan") == ("u_dan", "Dan Driver")
    assert drivers.resolve_driver(ROSTER, "TUBC", None) is None
    assert drivers.resolve_driver(ROSTER, "TUBC", "") is None


@pytest.mark.parametrize("uid", ["u_clerk", "u_other", "u_missing"])
def test_an_account_that_is_not_one_of_the_companys_drivers_is_refused(uid):
    with pytest.raises(ValidationError, match="not one of this company's drivers"):
        drivers.resolve_driver(ROSTER, "TUBC", uid)


# --- what a driver-only account may do (#1727) -------------------------------------------------


def _info(*roles):
    from types import SimpleNamespace

    from app.auth import _ROLES_KEY

    return SimpleNamespace(context={_ROLES_KEY: list(roles)})


def test_a_driver_only_account_is_refused_the_shipping_departments_changes():
    from app.auth import ForbiddenError
    from app.schemas.shipping import _refuse_driver_only

    with pytest.raises(ForbiddenError, match="booking and changing shipments"):
        _refuse_driver_only(_info("Driver"))


@pytest.mark.parametrize("roles", [("Driver", "Shipping Out"), ("Shipping Out",), ("Warehouse Staff",)])
def test_anybody_else_keeps_what_they_had(roles):
    from app.schemas.shipping import _refuse_driver_only

    _refuse_driver_only(_info(*roles))
