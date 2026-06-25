"""Pure unit tests for workstation -> BUYERID resolution. No config file, no SQL."""

from ucnexus_relay.buyers import resolve_buyer
from ucnexus_relay.config import BuyersCfg


def test_resolve_by_host_case_insensitive():
    cfg = BuyersCfg(default="fallback", by_host={"WS-ALICE": "Alice Smith"})
    assert resolve_buyer(cfg, "ws-alice") == "Alice Smith"


def test_resolve_by_login_when_host_misses():
    cfg = BuyersCfg(by_host={}, by_login={"DOMAIN\\bob": "Bob Jones"})
    assert resolve_buyer(cfg, "unknown-host", "domain\\bob") == "Bob Jones"


def test_host_wins_over_login():
    cfg = BuyersCfg(by_host={"H": "FromHost"}, by_login={"L": "FromLogin"})
    assert resolve_buyer(cfg, "h", "l") == "FromHost"


def test_falls_back_to_default():
    cfg = BuyersCfg(default="Default Buyer", by_host={"x": "y"})
    assert resolve_buyer(cfg, "other") == "Default Buyer"


def test_none_when_nothing_matches_and_no_default():
    assert resolve_buyer(BuyersCfg(), "host", None) is None


def test_truncates_to_char_15():
    cfg = BuyersCfg(by_host={"H": "ThisNameIsWayTooLong"})
    assert resolve_buyer(cfg, "H") == "ThisNameIsWayTo"  # GP BUYERID is char(15)
