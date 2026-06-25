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


def test_use_hostname_when_enabled_and_unmapped():
    cfg = BuyersCfg(use_hostname=True)
    assert resolve_buyer(cfg, "Tagging3W10") == "Tagging3W10"


def test_use_hostname_off_falls_through_to_default():
    cfg = BuyersCfg(use_hostname=False, default="fallback")
    assert resolve_buyer(cfg, "Tagging3W10") == "fallback"


def test_by_host_overrides_use_hostname():
    cfg = BuyersCfg(use_hostname=True, by_host={"Tagging3W10": "Real Person"})
    assert resolve_buyer(cfg, "Tagging3W10") == "Real Person"


def test_use_hostname_truncated_to_char_15():
    cfg = BuyersCfg(use_hostname=True)
    assert resolve_buyer(cfg, "VeryLongHostnameABCDEF") == "VeryLongHostnam"  # 15 chars
