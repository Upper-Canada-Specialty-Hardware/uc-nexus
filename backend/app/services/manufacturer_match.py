"""Normalize a manufacturer name and fuzzy-score it against GP vendor names (issue #232).

The same `normalize()` output feeds two things: the persisted mapping key (so case/whitespace/
punctuation/legal-suffix variants of one manufacturer collapse to a single row per company) and the
fuzzy comparison against the live vendor list (so a manufacturer with no saved mapping still ranks the
plausible vendors). Scoring prefers rapidfuzz.token_set_ratio and falls back to difflib when rapidfuzz
is not installed, so the module works with or without the optional dependency."""

import re

try:
    from rapidfuzz import fuzz as _rapidfuzz

    _HAVE_RAPIDFUZZ = True
except ImportError:  # pragma: no cover - exercised only where rapidfuzz is absent
    _rapidfuzz = None
    _HAVE_RAPIDFUZZ = False

# Punctuation -> space (then whitespace collapses), so "Acme, Inc." and "Acme Inc" normalize alike.
_PUNCTUATION = re.compile(r"[^A-Z0-9 ]+")
_WHITESPACE = re.compile(r"\s+")
# Trailing legal / geographic suffixes stripped so "Acme Inc" and "Acme" (and "Acme of Canada")
# collapse. Longest-first alternation matters: "OF CANADA" must be tried before bare "CANADA".
_LEGAL_SUFFIX = re.compile(r"\s+(?:OF\s+CANADA|CANADA|LTEE|CORP|LTD|INC|CO)$")


def normalize(name: str | None) -> str:
    """Canonical manufacturer key: uppercase, punctuation->space, whitespace collapsed, trailing legal
    suffixes (INC, LTD, LTEE, CORP, CO, OF CANADA, CANADA) stripped. Returns "" for empty/None."""
    if not name:
        return ""
    s = name.upper()
    s = _PUNCTUATION.sub(" ", s)
    s = _WHITESPACE.sub(" ", s).strip()
    # Strip stacked suffixes ("Acme Co Inc" -> "Acme"), re-collapsing after each removal.
    while True:
        stripped = _LEGAL_SUFFIX.sub("", s).strip()
        if stripped == s:
            break
        s = stripped
    return s


def score(a: str, b: str) -> float:
    """Fuzzy similarity in 0..100 between two (already normalized) names. token_set_ratio via rapidfuzz
    when available, else difflib.SequenceMatcher ratio scaled to 100."""
    if not a or not b:
        return 0.0
    if _HAVE_RAPIDFUZZ:
        return float(_rapidfuzz.token_set_ratio(a, b))
    from difflib import SequenceMatcher

    return SequenceMatcher(None, a, b).ratio() * 100.0


def rank_vendors(manufacturer: str, vendors: list[dict], top_n: int = 5) -> list[dict]:
    """Rank live GP vendors by fuzzy match of their name to `manufacturer`, best first, capped at
    top_n. Each vendor dict is expected to carry `vendor_id` + `vendor_name`. Returns a list of
    {"gp_vendor_id", "gp_vendor_name", "score"} dicts. An empty/blank manufacturer yields no
    candidates (nothing to rank against)."""
    key = normalize(manufacturer)
    if not key:
        return []
    scored = [
        {
            "gp_vendor_id": v["vendor_id"],
            "gp_vendor_name": v["vendor_name"],
            "score": score(key, normalize(v["vendor_name"])),
        }
        for v in vendors
    ]
    # Highest score first; break ties by name so the ordering is deterministic.
    scored.sort(key=lambda c: (-c["score"], c["gp_vendor_name"]))
    return scored[:top_n]
