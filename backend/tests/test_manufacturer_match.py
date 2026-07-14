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
    vendors = [
        {"vendor_id": "V1", "vendor_name": "Acme Inc"},
        {"vendor_id": "V2", "vendor_name": "Schlage Lock Company"},
        {"vendor_id": "V3", "vendor_name": "Best Access"},
    ]
    ranked = m.rank_vendors("ACME", vendors, top_n=2)
    assert len(ranked) == 2
    assert ranked[0]["gp_vendor_id"] == "V1"
    assert ranked[0]["score"] == 100.0
    assert ranked[0]["score"] >= ranked[1]["score"]


def test_rank_vendors_blank_manufacturer_returns_nothing():
    vendors = [{"vendor_id": "V1", "vendor_name": "Acme Inc"}]
    assert m.rank_vendors("", vendors) == []
    assert m.rank_vendors("   ", vendors) == []
