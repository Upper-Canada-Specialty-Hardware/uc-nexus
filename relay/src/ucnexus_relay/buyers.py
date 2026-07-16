"""Fallback resolution of the GP BUYERID when a /po omits buyer_id.

Normally the Create PO dropdown sends a buyer_id picked from GP's registered buyers (POP00101, via
GET /buyers). This is just the fallback when the request omits it. The value MUST be a REGISTERED GP
buyer: eConnect taPoHdr validates BUYERID against POP00101 and rejects an unregistered one (error
269) - a device hostname is NOT a registered buyer, which is why there's no use_hostname option.

Resolution order: by_host (device hostname -> registered buyer) -> by_login (SSPI login -> registered
buyer) -> default. Matching is case-insensitive. The result is truncated to GP's char(15) width.
"""

from .config import BuyersCfg

_MAX_BUYERID = 15  # POP10100.BUYERID is char(15)


def resolve_buyer(cfg: BuyersCfg, hostname: str, login: str | None = None) -> str | None:
    """Return the buyer name for this workstation, or None if nothing matches and no default is set."""
    by_host = {k.upper(): v for k, v in cfg.by_host.items()}
    buyer = by_host.get((hostname or "").upper())
    if not buyer and login:
        by_login = {k.upper(): v for k, v in cfg.by_login.items()}
        buyer = by_login.get(login.upper())
    if not buyer:
        buyer = cfg.default
    if buyer:
        buyer = buyer.strip()[:_MAX_BUYERID]
    return buyer or None
