"""Hardened legacy ``<<<ACTIONS>>>`` parser.

The text-protocol path is what weaker/older narrative models fall back to, so
the parser tolerates a missing closing marker, salvages malformed JSON, and
always strips the block from the displayed prose (no raw-JSON leak)."""

from server.ai.narrator_actions import parse_action_block


def test_wellformed_block_with_end_marker():
    raw = (
        "The chest opens.\n"
        '<<<ACTIONS>>>\n{"addItems": [{"itemName": "Ruby", "count": 1}]}\n<<<END ACTIONS>>>'
    )
    clean, actions = parse_action_block(raw)
    assert clean == "The chest opens."
    assert actions == {"addItems": [{"itemName": "Ruby", "count": 1}]}


def test_missing_end_marker_still_parses():
    raw = 'You find a sword.\n<<<ACTIONS>>>\n{"addItems": [{"itemName": "Sword"}]}'
    clean, actions = parse_action_block(raw)
    assert clean == "You find a sword."
    assert actions == {"addItems": [{"itemName": "Sword"}]}


def test_salvages_json_with_trailing_prose_and_no_end():
    # Model forgot the end marker AND kept narrating after the JSON.
    raw = 'A gift.\n<<<ACTIONS>>>\n{"addItems": [{"itemName": "Cloak"}]}\nThanks, it said.'
    clean, actions = parse_action_block(raw)
    assert actions == {"addItems": [{"itemName": "Cloak"}]}
    assert "<<<ACTIONS>>>" not in clean


def test_malformed_json_is_dropped_but_block_never_leaks():
    raw = 'The scene shifts.\n<<<ACTIONS>>>\n{this is not json]<<<END ACTIONS>>>'
    clean, actions = parse_action_block(raw)
    assert actions is None
    assert clean == "The scene shifts."
    assert "<<<ACTIONS>>>" not in clean
    assert "not json" not in clean


def test_tolerant_marker_spacing_and_casing():
    raw = 'Hi.\n<<< actions >>>{"day": 2}<<< END  ACTIONS >>>'
    clean, actions = parse_action_block(raw)
    assert clean == "Hi."
    assert actions == {"day": 2}


def test_no_block_is_passthrough():
    raw = "Just narration, nothing structured here."
    clean, actions = parse_action_block(raw)
    assert clean == raw
    assert actions is None


def test_prose_after_end_marker_is_kept():
    raw = 'Before.\n<<<ACTIONS>>>{"day": 1}<<<END ACTIONS>>>\nAfter.'
    clean, actions = parse_action_block(raw)
    assert actions == {"day": 1}
    assert "Before." in clean and "After." in clean
    assert "<<<ACTIONS>>>" not in clean
