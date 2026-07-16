"""manufacturer_match.normalize / score / rank_vendors (issue #232). Pure functions - no DB."""

from app.services import manufacturer_match as m


def test_normalize_uppercases_and_collapses_whitespace():
    assert m.normalize("  Acme   Hardware  ") == "ACME HARDWARE"


def test_normalize_strips_punctuation():
    assert m.normalize("Acme, Inc.") == "ACME"
    assert m.normalize("Smith & Sons") == "SMITH SONS"


def test_normalize_strips_trailing_legal_suffixes():
    assert m.normalize("Acme Inc") == "ACME"
    assert m.normalize("Acme Ltd") == "ACME"
    assert m.normalize("Acme Ltee") == "ACME"
    assert m.normalize("Acme Corp") == "ACME"
    assert m.normalize("Best Lock Co") == "BEST LOCK"


def test_normalize_strips_multiword_of_canada_suffix():
    assert m.normalize("Acme of Canada") == "ACME"
    # a bare trailing "Canada" is also a stripped suffix when it follows another token
    assert m.normalize("Acme Canada") == "ACME"


def test_normalize_strips_stacked_suffixes():
    assert m.normalize("Acme Co Inc") == "ACME"


def test_normalize_variants_collapse_to_same_key():
    assert m.normalize("ACME, INC.") == m.normalize("acme inc") == m.normalize("  Acme   ")


def test_normalize_empty_and_none():
    assert m.normalize("") == ""
    assert m.normalize(None) == ""
    assert m.normalize("   ") == ""


def test_score_identical_is_max():
    assert m.score("ACME", "ACME") == 100.0


def test_score_zero_for_empty_side():
    assert m.score("", "ACME") == 0.0
    assert m.score("ACME", "") == 0.0


def test_rank_vendors_orders_best_first_and_caps():
    # All three are token-subset matches (score 100 under token_set_ratio); ties break by name so
    # the ordering is deterministic, and top_n caps the list.
    vendors = [
        {"vendor_id": "V1", "vendor_name": "Acme Inc"},
        {"vendor_id": "V2", "vendor_name": "Acme Hardware Group"},
        {"vendor_id": "V3", "vendor_name": "Acme Hardware Group of Canada"},
    ]
    ranked = m.rank_vendors("ACME", vendors, top_n=2)
    assert len(ranked) == 2
    assert ranked[0]["score"] >= ranked[1]["score"] >= m.MIN_SCORE
    assert [c["gp_vendor_name"] for c in ranked] == sorted(c["gp_vendor_name"] for c in ranked)


def test_rank_vendors_blank_manufacturer_returns_nothing():
    vendors = [{"vendor_id": "V1", "vendor_name": "Acme Inc"}]
    assert m.rank_vendors("", vendors) == []
    assert m.rank_vendors("   ", vendors) == []


def test_rank_vendors_drops_weak_matches_below_the_floor():
    # Issue #236: the 44%-style coincidental overlap must yield NO candidates, not a junk
    # pre-select (seen on prod: ZZQX WIDGETWORKS INC -> BRIDGEPORT WORLDWIDE at 44).
    vendors = [
        {"vendor_id": "V1", "vendor_name": "Bridgeport Worldwide"},
        {"vendor_id": "V2", "vendor_name": "Best Access"},
    ]
    assert m.rank_vendors("ZZQX WIDGETWORKS INC", vendors) == []


def test_rank_vendors_keeps_genuine_partial_matches():
    # token_set_ratio scores subset-token names at/near 100, so real partials survive the floor.
    vendors = [{"vendor_id": "V1", "vendor_name": "Schlage Lock Company"}]
    ranked = m.rank_vendors("SCHLAGE", vendors)
    assert len(ranked) == 1
    assert ranked[0]["gp_vendor_id"] == "V1"
    assert ranked[0]["score"] >= m.MIN_SCORE
