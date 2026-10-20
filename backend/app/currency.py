"""The currency a cost is in (#1557).

GP keeps each purchase order in a currency (CURNCYID). Blank there is the company's functional currency,
which for every GP company Nexus serves is CAD; the only foreign currency they buy in is USD. Nexus
records the PO's currency as GP reports it, and a unit cost carried off the PO onto an inventory row or
a pool row carries its currency with it (`cost_currency`), stored only when it is foreign: null means
CAD. Storing CAD as null rather than as 'CAD' keeps a pool row received off a CAD PO identical to one
moved in from a project or a migration, so the pool's merge key does not split rows that are the same.
"""

FUNCTIONAL_CURRENCY = "CAD"
USD = "USD"


def normalize_currency(value: str | None) -> str:
    """A GP currency id as Nexus stores it on a PO: trimmed, upper case, blank read as CAD."""
    return (value or "").strip().upper() or FUNCTIONAL_CURRENCY


def cost_currency_of(value: str | None) -> str | None:
    """The `cost_currency` a row takes for a cost in this currency: None for CAD, else the currency."""
    currency = normalize_currency(value)
    return None if currency == FUNCTIONAL_CURRENCY else currency
