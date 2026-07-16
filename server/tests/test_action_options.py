from server.ai.action_suggester import (
    DEFAULT_OPTION_RULES,
    _to_first_person,
    normalize_option_rules,
    parse_inline_options,
)


# ── first-person backstop ─────────────────────────────────────────

def test_imperative_becomes_first_person():
    assert _to_first_person("Push the door open") == "I push the door open"


def test_already_first_person_passes_through():
    for phrase in ("I push the door", "I'm ready to fight", "I'll wait here", "I've seen enough"):
        assert _to_first_person(phrase) == phrase


# ── inline <<<OPTIONS>>> parsing ──────────────────────────────────

def test_parse_well_formed_block():
    text = 'The forest darkens.\n<<<OPTIONS>>>["I press on", "I turn back"]'
    clean, options = parse_inline_options(text)
    assert clean == "The forest darkens."
    assert options == ["I press on", "I turn back"]


def test_parse_truncated_block_salvages_complete_phrases():
    text = '...ends here.\n<<<OPTIONS>>>["I press on", "I turn back", "I clim'
    clean, options = parse_inline_options(text)
    assert clean == "...ends here."
    assert options == ["I press on", "I turn back"], "complete phrases salvaged, clipped tail dropped"


def test_parse_without_marker_is_untouched():
    clean, options = parse_inline_options("Just narration.")
    assert clean == "Just narration." and options == []


def test_parse_normalises_imperatives_to_first_person():
    _, options = parse_inline_options('beat.\n<<<OPTIONS>>>["Draw the sword"]')
    assert options == ["I draw the sword"]


# ── option rules ──────────────────────────────────────────────────

def test_rules_fall_back_to_defaults():
    assert normalize_option_rules(None) == list(DEFAULT_OPTION_RULES)
    assert normalize_option_rules(["", "  "]) == list(DEFAULT_OPTION_RULES)


def test_rules_are_trimmed_and_capped():
    rules = normalize_option_rules(["  brave  ", "cowardly"] + ["x"] * 10)
    assert rules[0] == "brave" and rules[1] == "cowardly"
    assert len(rules) <= 6
