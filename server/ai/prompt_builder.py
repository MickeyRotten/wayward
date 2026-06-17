from server.db.models import (
    ChatMessage,
    NarratorConfig,
    PartyMember,
    PlayerCharacter,
    Scenario,
)


def build_prompt(
    narrator_config: NarratorConfig,
    scenario: Scenario,
    player_character: PlayerCharacter,
    party_members: list[PartyMember],
    chat_history: list[ChatMessage],
    player_message: str,
    spotlight_block: str | None = None,
    story_summary: str | None = None,
    max_context_tokens: int = 128000,
    max_response_tokens: int = 1000,
) -> list[dict]:
    messages: list[dict] = []

    # 1. System: Narrator instructions
    messages.append({"role": "system", "content": narrator_config.instructions})

    # 2. Scenario context
    if scenario.description:
        messages.append({
            "role": "system",
            "content": f"CURRENT SCENARIO:\n{scenario.description}",
        })

    # 3. Player character summary
    pc_info = player_character.basic_info
    pc_attrs = player_character.attributes
    pc_equip = player_character.equipment

    equipped = [
        f"{slot}: {item}"
        for slot, item in pc_equip.items()
        if item
    ]
    equip_str = ", ".join(equipped) if equipped else "nothing equipped"

    pc_summary = (
        f"PLAYER CHARACTER: {pc_info.get('name', 'Unknown')}, "
        f"a {pc_info.get('species', 'unknown')} {pc_info.get('gender', '').lower()}. "
        f"{pc_info.get('description', '')}\n"
        f"Attributes: STR {pc_attrs.get('STR', 10)} / CON {pc_attrs.get('CON', 10)} / "
        f"DEX {pc_attrs.get('DEX', 10)} / INT {pc_attrs.get('INT', 10)} / "
        f"WIS {pc_attrs.get('WIS', 10)} / CHA {pc_attrs.get('CHA', 10)}\n"
        f"Carrying: {equip_str}"
    )
    messages.append({"role": "system", "content": pc_summary})

    # 4. Party roster
    if party_members:
        roster_lines = ["PARTY ROSTER:"]
        for pm in party_members:
            info = pm.basic_info
            skill = pm.field_skill
            equipped_pm = [
                f"{slot}: {item}"
                for slot, item in pm.equipment.items()
                if item
            ]
            equip_pm_str = ", ".join(equipped_pm) if equipped_pm else "nothing equipped"
            lines = [
                f"  {info.get('name', 'Unknown')} — {info.get('species', 'unknown')}. "
                f"{info.get('description', '')}",
            ]
            if info.get('personality'):
                lines.append(f"    Personality: {info['personality']}")
            if info.get('likes'):
                lines.append(f"    Likes: {info['likes']}")
            if info.get('dislikes'):
                lines.append(f"    Dislikes: {info['dislikes']}")
            lines.append(f"    Field Skill: {skill.get('name', 'None')} — {skill.get('description', '')}")
            lines.append(f"    Carrying: {equip_pm_str}")
            roster_lines.append("\n".join(lines))
        messages.append({"role": "system", "content": "\n".join(roster_lines)})

    # 5. Story summary
    if story_summary:
        messages.append({
            "role": "system",
            "content": f"STORY SO FAR:\n{story_summary}",
        })

    # 6. Spotlight block
    if spotlight_block:
        messages.append({"role": "system", "content": spotlight_block})

    # 6. Chat history (with context trimming)
    preamble_tokens = _estimate_tokens(messages)
    player_msg_tokens = len(player_message) // 4 + 10
    budget = max_context_tokens - max_response_tokens - preamble_tokens - player_msg_tokens

    history_messages = [
        {"role": m.role, "content": m.content}
        for m in chat_history
    ]
    history_messages = _trim_to_budget(history_messages, budget)
    messages.extend(history_messages)

    # 7. Player's new message
    messages.append({"role": "user", "content": player_message})

    return messages


def estimate_prompt_tokens(messages: list[dict]) -> int:
    return _estimate_tokens(messages)


def _estimate_tokens(messages: list[dict]) -> int:
    return sum(len(m.get("content", "")) for m in messages) // 4 + len(messages) * 4


def _trim_to_budget(messages: list[dict], token_budget: int) -> list[dict]:
    total = _estimate_tokens(messages)
    while messages and total > token_budget:
        removed = messages.pop(0)
        total -= len(removed.get("content", "")) // 4 + 4
    return messages
