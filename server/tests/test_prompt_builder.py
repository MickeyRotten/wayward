from types import SimpleNamespace as NS

from server.ai.prompt_builder import build_prompt, estimate_prompt_tokens


def _pc(**info):
    base = {"name": "Hero", "species": "Human", "gender": "Male", "description": "A hero."}
    base.update(info)
    return NS(basic_info=base, equipment={})


def _cfg(**kw):
    base = dict(instructions="You are the Narrator.", action_instruction="",
                first_message="", post_history_instructions="")
    base.update(kw)
    return NS(**base)


def _msg(role, content, turn=1):
    return NS(role=role, content=content, turn_number=turn, image_path=None)


def _lore_cfg(depth=3):
    return NS(injection_order={}, injection_position={}, scan_depth=depth)


def test_player_message_is_last_by_default():
    msgs = build_prompt(narrator_config=_cfg(), player_character=_pc(), party_members=[],
                        chat_history=[], player_message="Hello", include_action_protocol=False)
    assert msgs[-1] == {"role": "user", "content": "Hello"}


def test_post_history_lands_right_before_user_message():
    msgs = build_prompt(narrator_config=_cfg(post_history_instructions="STAY IN CHARACTER"),
                        player_character=_pc(), party_members=[], chat_history=[],
                        player_message="Hello", include_action_protocol=False)
    assert msgs[-1]["role"] == "user"
    assert msgs[-2] == {"role": "system", "content": "STAY IN CHARACTER"}


def test_first_message_prepends_history_and_survives_trimming():
    cfg = _cfg(first_message="The opening beat.")
    history = [_msg("user", "x" * 4000, t) for t in range(1, 40)]
    msgs = build_prompt(narrator_config=cfg, player_character=_pc(), party_members=[],
                        chat_history=history, player_message="Hi",
                        max_context_tokens=4000, max_response_tokens=500,
                        include_action_protocol=False)
    assistants = [m for m in msgs if m["role"] == "assistant"]
    assert assistants and assistants[0]["content"] == "The opening beat."
    # Trimming kept the prompt inside the context budget.
    assert estimate_prompt_tokens(msgs) <= 4000


def test_first_message_override_anchors_alternate_opening():
    # R13: an anchored alternate greeting replaces the campaign's primary.
    cfg = _cfg(first_message="Primary opening.")
    msgs = build_prompt(narrator_config=cfg, player_character=_pc(), party_members=[],
                        chat_history=[], player_message="Hi",
                        include_action_protocol=False,
                        first_message_override="An alternate opening.")
    assistants = [m for m in msgs if m["role"] == "assistant"]
    assert assistants and assistants[0]["content"] == "An alternate opening."
    # A blank/None override falls back to the primary first_message.
    msgs2 = build_prompt(narrator_config=cfg, player_character=_pc(), party_members=[],
                         chat_history=[], player_message="Hi",
                         include_action_protocol=False, first_message_override=None)
    assert [m for m in msgs2 if m["role"] == "assistant"][0]["content"] == "Primary opening."


def test_prompt_begins_with_core_role_definition():
    # msg 0 is the editable JSON core (role + behavior), regardless of the
    # per-campaign instructions — so the prompt always opens with a role def.
    msgs = build_prompt(narrator_config=_cfg(instructions=""), player_character=_pc(),
                        party_members=[], chat_history=[], player_message="Hi",
                        include_action_protocol=False)
    assert msgs[0]["role"] == "system"
    assert msgs[0]["content"].startswith("You are the Narrator")


def test_style_block_follows_core_and_base_override():
    # A genuinely custom base override is layered right after the core; the
    # STORY STYLE block follows.
    cfg = _cfg(instructions="Always rhyme.", style_fields={"genre": "high_fantasy", "tone": "epic"})
    msgs = build_prompt(narrator_config=cfg, player_character=_pc(), party_members=[],
                        chat_history=[], player_message="Hi", include_action_protocol=False)
    assert msgs[0]["content"].startswith("You are the Narrator")
    assert msgs[1] == {"role": "system", "content": "Always rhyme."}
    style_msg = next(m for m in msgs if m["content"].startswith("STORY STYLE"))
    assert "High Fantasy" in style_msg["content"]
    assert msgs.index(style_msg) > 1  # after core + base override


def test_legacy_default_instructions_not_double_injected():
    from server.ai.prompt_builder import _LEGACY_DEFAULT_INSTRUCTIONS
    legacy = next(iter(_LEGACY_DEFAULT_INSTRUCTIONS))
    msgs = build_prompt(narrator_config=_cfg(instructions=legacy), player_character=_pc(),
                        party_members=[], chat_history=[], player_message="Hi",
                        include_action_protocol=False)
    assert sum(1 for m in msgs if m["content"] == legacy) == 0
    assert msgs[0]["content"].startswith("You are the Narrator")


def test_no_story_style_block_without_selections():
    msgs = build_prompt(narrator_config=_cfg(), player_character=_pc(), party_members=[],
                        chat_history=[], player_message="Hi", include_action_protocol=False)
    assert not any(m["content"].startswith("STORY STYLE") for m in msgs if m["role"] == "system")


def test_trimming_drops_oldest_history_first():
    history = [_msg("user", f"turn {t} " + "x" * 2000, t) for t in range(1, 30)]
    msgs = build_prompt(narrator_config=_cfg(), player_character=_pc(), party_members=[],
                        chat_history=history, player_message="Hi",
                        max_context_tokens=4000, max_response_tokens=500,
                        include_action_protocol=False)
    joined = "\n".join(m["content"] for m in msgs)
    assert "turn 29" in joined, "newest history must survive"
    assert "turn 1 " not in joined, "oldest history must be trimmed"


def test_party_roster_includes_personality_and_other():
    pm = NS(
        basic_info={"name": "Varena", "species": "Elf", "description": "An elf.",
                    "personality": "Wry", "other": "Collects teeth"},
        field_skill={"name": "Marksmanship", "description": "Shoots well."},
        equipment={},
    )
    msgs = build_prompt(narrator_config=_cfg(), player_character=_pc(), party_members=[pm],
                        chat_history=[], player_message="Hi", include_action_protocol=False)
    roster = next(m["content"] for m in msgs if "PARTY ROSTER" in m["content"])
    assert "Personality: Wry" in roster and "Other: Collects teeth" in roster


def test_lore_scan_window_reaches_recent_history():
    lore = NS(id="1", enabled=True, permanent=False, title="Kal-Toth",
              keywords=["kal-toth"], cat="world", content="An ancient ruin.")
    history = [
        _msg("user", "I look at the hill."),
        _msg("assistant", "Atop it looms Kal-Toth, silent."),
    ]
    common = dict(narrator_config=_cfg(), player_character=_pc(), party_members=[],
                  chat_history=history, player_message="Tell me more about it",
                  lore_entries=[lore], include_action_protocol=False)

    joined = "\n".join(m["content"] for m in build_prompt(lore_config=_lore_cfg(3), **common))
    assert "An ancient ruin." in joined, "narrator-introduced keyword should inject"

    joined0 = "\n".join(m["content"] for m in build_prompt(lore_config=_lore_cfg(0), **common))
    assert "An ancient ruin." not in joined0, "scan_depth=0 scans only the new message"


def test_equipment_renders_names_and_descriptions():
    sword = NS(id="itm-sword", title="Sword", content="A trusty blade.")
    pc = _pc()
    pc.equipment = {"rightHand": "itm-sword", "head": None}
    msgs = build_prompt(narrator_config=_cfg(), player_character=pc, party_members=[],
                        chat_history=[], player_message="Hi",
                        item_catalog=[sword], include_action_protocol=False)
    pc_block = next(m["content"] for m in msgs if "PLAYER CHARACTER" in m["content"])
    assert "rightHand: Sword — A trusty blade." in pc_block
