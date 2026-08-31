from server.ai.action_suggester import (
    DEFAULT_OPTION_RULES,
    DEFAULT_SUGGESTIONS_COUNT,
    _to_first_person,
    normalize_option_rules,
    normalize_suggestions_count,
)
from server.ai.turn_block import build_turn_block_guidance, parse_turn_block


# ── first-person backstop ─────────────────────────────────────────

def test_imperative_becomes_first_person():
    assert _to_first_person("Push the door open") == "I push the door open"


def test_already_first_person_passes_through():
    for phrase in ("I push the door", "I'm ready to fight", "I'll wait here", "I've seen enough"):
        assert _to_first_person(phrase) == phrase


# ── inline options, now read out of the trailing turn block ───────
# The legacy <<<OPTIONS>>> marker is still accepted by parse_turn_block, so
# histories written before the block still parse; there is one reader, not two.

def test_parse_well_formed_block():
    text = 'The forest darkens.\n<<<OPTIONS>>>["I press on", "I turn back"]'
    clean, block = parse_turn_block(text)
    assert clean == "The forest darkens."
    assert block["options"] == ["I press on", "I turn back"]


def test_parse_truncated_block_salvages_complete_phrases():
    text = '...ends here.\n<<<OPTIONS>>>["I press on", "I turn back", "I clim'
    clean, block = parse_turn_block(text)
    assert clean == "...ends here."
    assert block["options"] == ["I press on", "I turn back"], "complete phrases salvaged, clipped tail dropped"


def test_parse_without_marker_is_untouched():
    clean, block = parse_turn_block("Just narration.")
    assert clean == "Just narration." and block == {}


def test_parse_normalises_imperatives_to_first_person():
    _, block = parse_turn_block('beat.\n<<<OPTIONS>>>["Draw the sword"]')
    assert block["options"] == ["I draw the sword"]


# ── option rules ──────────────────────────────────────────────────

def test_rules_fall_back_to_defaults():
    assert normalize_option_rules(None) == list(DEFAULT_OPTION_RULES)
    assert normalize_option_rules(["", "  "]) == list(DEFAULT_OPTION_RULES)


def test_rules_are_trimmed_and_capped():
    rules = normalize_option_rules(["  brave  ", "cowardly"] + ["x"] * 10)
    assert rules[0] == "brave" and rules[1] == "cowardly"
    assert len(rules) <= 6


# ── suggestion count (single shared instruction) ──────────────────

def test_suggestions_count_defaults_and_clamps():
    assert normalize_suggestions_count(None) == DEFAULT_SUGGESTIONS_COUNT
    assert normalize_suggestions_count("nonsense") == DEFAULT_SUGGESTIONS_COUNT
    assert normalize_suggestions_count(0) == 1      # clamped up to the min
    assert normalize_suggestions_count(99) == 6     # clamped down to the cap
    assert normalize_suggestions_count(3) == 3


def test_inline_guidance_requests_the_count_and_has_no_per_slot_rules():
    guidance = build_turn_block_guidance(5)
    assert "exactly 5 short choice phrases" in guidance
    assert "OPTION RULES" not in guidance


def test_a_field_nothing_reads_is_never_named():
    # A named field is an invitation, so the protocol — and the worked example
    # built from it — documents only what is switched on.
    options_only = build_turn_block_guidance(3, include_scene=False, include_clock=False)
    assert "duration" not in options_only and "location" not in options_only
    assert "options" in options_only
    assert build_turn_block_guidance(None, include_scene=False, include_clock=False) == ""
