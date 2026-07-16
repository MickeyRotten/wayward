from types import SimpleNamespace as NS

from server.ai.spotlight import (
    _member_spoke,
    _name_mentioned,
    compute_spotlight_signals,
    detect_speakers,
    format_spotlight_block,
)


def _member(name, skill_name="", skill_desc="", last_spoke=0):
    return NS(
        id=f"id-{name.lower()}",
        basic_info={"name": name},
        field_skill={"name": skill_name, "description": skill_desc},
        last_spoke_turn=last_spoke,
    )


# ── name matching (N1/N2 regressions) ─────────────────────────────

def test_name_mentioned_is_word_boundary():
    assert _name_mentioned("Al", "I talk to Al about it")
    assert not _name_mentioned("Al", "I also went home")


def test_first_name_of_full_name_matches():
    assert _name_mentioned("Tifa Lockhart", "I ask Tifa about the ruins")


def test_bare_mention_is_not_speaking():
    assert not _member_spoke("Tifa", "Tifa was asleep by the fire.")


def test_dialogue_convention_counts_as_speaking():
    assert _member_spoke("Tifa", 'Tifa: "We should move before the light fails."')


def test_said_verb_attribution_counts_as_speaking():
    assert _member_spoke("Tifa", '"Not yet," Tifa whispered.')


def test_detect_speakers_returns_only_attributed_members():
    tifa, rosa = _member("Tifa"), _member("Rosalina")
    # Note: a name directly adjacent to a closing quote counts as attribution
    # by design ('"Stay close," Tifa said') — so Rosalina's silent beat lives
    # on its own line to be a bare mention.
    text = 'Tifa: "Stay close."\nRosalina watches the stars in silence.'
    assert detect_speakers(text, [tifa, rosa]) == [tifa.id]


# ── signals ───────────────────────────────────────────────────────

def test_group_address_flags_everyone():
    tifa, rosa = _member("Tifa"), _member("Rosalina")
    signals = compute_spotlight_signals(
        player_message="Everyone, get ready!", recent_context="",
        party_members=[tifa, rosa], current_turn=5,
    )
    assert all(s.directly_addressed for s in signals)


def test_direct_address_only_flags_the_named_member():
    tifa, rosa = _member("Tifa"), _member("Rosalina")
    signals = compute_spotlight_signals(
        player_message="Tifa, can you break this door?", recent_context="",
        party_members=[tifa, rosa], current_turn=5,
    )
    by_name = {s.member_name: s for s in signals}
    assert by_name["Tifa"].directly_addressed
    assert not by_name["Rosalina"].directly_addressed


def test_field_skill_relevance_matches_skill_name_tokens():
    rosa = _member("Rosalina", skill_name="Luma Swarm", skill_desc="Commands star sprites.")
    signals = compute_spotlight_signals(
        player_message="Could a luma scout the passage ahead?", recent_context="",
        party_members=[rosa], current_turn=3,
    )
    assert signals[0].field_skill_relevant


def test_turns_since_last_spoke():
    tifa = _member("Tifa", last_spoke=2)
    (sig,) = compute_spotlight_signals(
        player_message="I walk on.", recent_context="", party_members=[tifa], current_turn=7,
    )
    assert sig.turns_since_last_spoke == 5


def test_format_block_marks_direct_address_loudly():
    tifa = _member("Tifa")
    signals = compute_spotlight_signals(
        player_message="Tifa, hold the line", recent_context="",
        party_members=[tifa], current_turn=1,
    )
    block = format_spotlight_block(signals)
    assert "DIRECTLY ADDRESSED" in block and "PARTY SPOTLIGHT" in block


def test_format_block_uses_custom_rule():
    tifa = _member("Tifa")
    signals = compute_spotlight_signals(
        player_message="hi", recent_context="", party_members=[tifa], current_turn=1,
    )
    assert "MY CUSTOM RULE" in format_spotlight_block(signals, "MY CUSTOM RULE")
