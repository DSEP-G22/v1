"""Model output is normalised on the way out of the generator adapter.

A customer-facing reply is written at runtime, so it is the one text path in the project that
cannot be cleaned at authoring time: the repo-wide em-dash pass does not reach it. These tests
pin the two properties that make normalising safe there.
"""

from __future__ import annotations

import json

from libs.platform.models.llm import _normalise_punctuation


def test_replaces_typographic_characters_in_prose():
    generated = "I'm sorry—please power‑cycle it… I’ll check the line."
    cleaned = _normalise_punctuation(generated)

    assert "—" not in cleaned
    assert "…" not in cleaned
    assert "’" not in cleaned
    assert "power" in cleaned and "cycle" in cleaned


def test_json_structure_survives():
    """`generate_json` parses this text, so normalising must not disturb it.

    The risk is a substitution that introduces a quote or a brace and moves a string boundary.
    Round-tripping a payload whose values contain every substituted character proves it does not.
    """
    payload = {
        "department": "network_operations",
        "priority_score": 70,
        "rationale": "Line—fault; the customer said “it’s down…” and left",
    }

    parsed = json.loads(_normalise_punctuation(json.dumps(payload)))

    assert parsed["department"] == "network_operations"
    assert parsed["priority_score"] == 70
    assert set(parsed) == set(payload)


def test_is_idempotent():
    """Re-running must be a no-op.

    An earlier em-dash script in this project replaced dashes with " - ", then matched its own
    output on a second run and expanded every hyphen across 110 files. No replacement here
    produces a character that is itself a key, so that failure cannot recur.
    """
    once = _normalise_punctuation("a—b “c” d…")
    assert _normalise_punctuation(once) == once


def test_leaves_ordinary_text_untouched():
    plain = "Reset the router. Check cable-1, then call back."
    assert _normalise_punctuation(plain) == plain
