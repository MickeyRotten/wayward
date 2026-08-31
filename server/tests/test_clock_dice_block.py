"""The three deterministic seams added to take state back from the narrator:
the clock, the dice, and the trailing turn block."""

import collections

from server.ai.clock import (
    MINUTES_PER_DAY,
    advance_clock,
    normalize_duration,
    phase_of,
)
from server.ai.dice import roll_dice, seed_hash, skill_check
from server.ai.narrator_actions import coerce_scene, simplify_location
from server.ai.roster import compose_roll_call
from server.ai.turn_block import normalize_options, parse_turn_block


# ── Clock ──────────────────────────────────────────────────────────────────

def test_unknown_duration_falls_to_the_smallest_step():
    # An unrepresentable value must cost two minutes, not a guess.
    for junk in (None, "", "3 days", 7, "forever", {"x": 1}):
        assert normalize_duration(junk) == "moment"


def test_a_turn_with_no_duration_still_ages_the_world():
    day, minutes, rested = advance_clock(1, 0, None)
    assert (day, rested) == (1, False)
    assert minutes > 0, "an unparseable turn must never freeze the clock"


def test_night_anchors_to_morning_and_sets_rested():
    day, minutes, rested = advance_clock(4, 22 * 60, "night")
    assert (day, minutes, rested) == (5, 7 * 60, True)


def test_a_night_too_far_out_degrades_to_a_nap():
    # 08:00 to the next 07:00 is 23 hours — that is a nap, not a night.
    day, minutes, rested = advance_clock(3, 8 * 60, "night")
    assert rested is False and day == 3 and minutes == 14 * 60


def test_the_clock_rolls_over_midnight():
    day, minutes, _ = advance_clock(2, MINUTES_PER_DAY - 5, "brief")
    assert day == 3 and minutes == 5


def test_time_reaches_the_world_only_as_a_phase_word():
    assert [phase_of(m) for m in (0, 330, 480, 700, 900, 1080, 1200, 1300)] == [
        "late night", "dawn", "morning", "midday",
        "afternoon", "evening", "dusk", "night",
    ]


# ── Dice ───────────────────────────────────────────────────────────────────

def test_the_same_turn_re_tells_the_same_roll():
    a = skill_check(7, "Tifa", "climb", "hard")
    b = skill_check(7, "Tifa", "climb", "hard")
    assert a == b, "a regenerate must re-tell, not re-roll"


def test_a_swipe_is_a_genuinely_new_take_and_rolls_fresh():
    rolls = {skill_check(7, "Tifa", "climb", "hard", v)["roll"] for v in range(8)}
    assert len(rolls) > 1


def test_a_d20_reaches_every_face_with_both_parities():
    # Regression: a raw FNV hash fed to `% sides` leaks its low bit, so a die's
    # parity became a function of the seed's characters — a d20 that could only
    # roll odd.
    counts = collections.Counter(
        roll_dice(seed_hash(t, "actor", "skill"), 1, 20)[0] for t in range(4000)
    )
    assert len(counts) == 20, "every face must be reachable"
    odd = sum(v for k, v in counts.items() if k % 2)
    assert 0.45 < odd / sum(counts.values()) < 0.55


def test_2d6_can_roll_seven():
    # Regression: hashing `seed|i` for extra dice — seeds a suffix apart — locked
    # them into opposite parities, so 2d6 produced only even sums. Each die
    # looked uniform alone; only the joint distribution was wrong.
    sums = collections.Counter(sum(roll_dice(seed_hash(t), 2, 6)) for t in range(3000))
    assert sums[7] > 0
    assert sums[7] == max(sums.values()), "7 is the mode of 2d6"


# ── Scene guards ───────────────────────────────────────────────────────────

def test_a_compound_location_keeps_its_narrowest_segment():
    assert simplify_location("Boars Head Tavern - Damp Cellar") == "Damp Cellar"
    assert simplify_location("Keep / Undercroft / Vault") == "Vault"
    assert simplify_location("The Deep: Third Gallery") == "Third Gallery"


def test_the_joiners_that_are_deliberately_not_joiners():
    # A comma nests the other way round; a hyphen without spaces is a name.
    assert simplify_location("Rodstroke, Mesmeria") == "Rodstroke, Mesmeria"
    assert simplify_location("Half-Moon Inn") == "Half-Moon Inn"


def test_a_location_of_pure_separators_changes_nothing():
    assert coerce_scene({"location": " - "}) == {}


def test_the_day_may_only_move_forward():
    assert coerce_scene({"day": 3}, current_day=5) == {}
    assert coerce_scene({"day": 7}, current_day=5) == {"day": 7}
    assert coerce_scene({"day": True}) == {}, "a bool is not a day number"


# ── Turn block ─────────────────────────────────────────────────────────────

def test_the_canonical_block_parses():
    prose, block = parse_turn_block(
        'The door groans open.\n\n<<<TURN>>>'
        '{"location": "Damp Cellar", "duration": "scene", "options": ["I run.", "I hide."]}'
    )
    assert prose == "The door groans open."
    assert block == {"location": "Damp Cellar", "duration": "scene",
                     "options": ["I run.", "I hide."]}


def test_marker_variants_are_accepted():
    for marker in ("<<TURN>>", "[TURN]", "<<<turn>>>", "<<<OPTIONS>>>"):
        prose, block = parse_turn_block(f'Beat.\n{marker}{{"location": "Hall"}}')
        assert prose == "Beat." and block == {"location": "Hall"}, marker


def test_the_word_turn_in_prose_never_truncates_a_beat():
    text = "He turned. It was his turn to speak, and the turn was long."
    assert parse_turn_block(text) == (text, {})


def test_a_dropped_marker_still_strips_the_json():
    # Without this the raw object was rendered into the reading pane as prose.
    prose, block = parse_turn_block('Beat.\n{"location": "Hall", "duration": "hour"}')
    assert prose == "Beat." and block["location"] == "Hall"


def test_malformed_json_costs_the_state_not_the_prose():
    prose, block = parse_turn_block("Beat.\n<<<TURN>>>{ this is not json")
    assert prose == "Beat." and block == {}


def test_a_raw_newline_inside_a_string_is_repaired():
    prose, block = parse_turn_block('Beat.\n<<<TURN>>>{"location": "A hall\nwith pillars"}')
    assert prose == "Beat." and block["location"] == "A hall\nwith pillars"


def test_the_four_shapes_of_options_all_become_a_list_of_strings():
    assert normalize_options(["I run.", "I hide."]) == ["I run.", "I hide."]
    assert normalize_options("I run.\nI hide.") == ["I run.", "I hide."]
    assert normalize_options([{"action": "I run."}, {"text": "I hide."}]) == ["I run.", "I hide."]
    assert normalize_options({"1": "1. I run.", "2": "**I hide.**"}) == ["I run.", "I hide."]


# ── Roll call ──────────────────────────────────────────────────────────────

class _C:
    def __init__(self, name):
        self.basic_info = {"name": name}


def test_an_empty_party_is_stated_explicitly():
    # The empty case is exactly where the history drifts, so it is never silent.
    out = compose_roll_call(_C("Seraphine"), [], [], 4)
    assert "ALONE" in out and "Seraphine" in out


def test_the_bench_is_named_as_not_present():
    out = compose_roll_call(_C("Seraphine"), [_C("Tifa")], [_C("Rosalina")], 4)
    assert "(1/4)" in out and "Tifa" in out
    assert "NOT in this scene" in out and "Rosalina" in out


# ── Chronicler cadence ─────────────────────────────────────────────────────

def test_the_chronicler_runs_on_a_cadence_and_covers_the_whole_span():
    from server.ai.worldbuilder import chronicler_span

    # Interval 1 is the old every-turn behaviour, exactly.
    assert [chronicler_span(t, 1) for t in (1, 2, 3)] == [0, 1, 2]

    # Interval 2: half the runs, each covering both turns since the last.
    assert chronicler_span(1, 2) is None
    assert chronicler_span(2, 2) == 0
    assert chronicler_span(3, 2) is None
    assert chronicler_span(4, 2) == 2


def test_the_cadence_is_deterministic_in_the_turn_number():
    from server.ai.worldbuilder import chronicler_span

    # No bookkeeping: a swipe or regenerate of a turn lands on the same decision.
    assert chronicler_span(6, 3) == chronicler_span(6, 3) == 3
    # And a nonsense interval is clamped rather than dividing by zero.
    assert chronicler_span(4, 0) == 3
    assert chronicler_span(40, 999) == 30
