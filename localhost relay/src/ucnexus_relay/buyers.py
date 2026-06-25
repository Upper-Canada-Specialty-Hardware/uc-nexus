"""Resolve the GP BUYERID from the workstation identity.

GP has no buyer-master at this customer — BUYERID is a free-text human name written straight to
POP10100 (verified in the GP discovery: "Buyers are free-text human names ... No buyer-master
enforcement"). So there is nothing to validate against; the relay just maps the device to a name.

The relay fills the buyer when the /po request omits it, because the machine that knows the device
is the relay, not the cloud frontend. Company device names are traceable to individuals via an
internal system, so the device name itself is a valid buyer handle. Resolution order:
  by_host (explicit map) -> by_login (SSPI login) -> use_hostname (the device's own name) -> default.
Matching is case-insensitive (Windows hostnames/logins are). The result is truncated to GP's
char(15) BUYERID width.
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
    if not buyer and cfg.use_hostname and hostname:
        buyer = hostname  # the device name is itself a traceable buyer identity
    if not buyer:
        buyer = cfg.default
    if buyer:
        buyer = buyer.strip()[:_MAX_BUYERID]
    return buyer or None
