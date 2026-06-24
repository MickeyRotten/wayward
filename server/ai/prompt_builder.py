from server.ai.lore_injector import format_lore_block, group_by_position, match_entries
from server.ai.narrator_actions import ACTION_INSTRUCTION
from server.db.models import (
    ChatMessage,
    LorebookConfig,
    LorebookEntry,
    NarratorConfig,
    PartyMember,
    PlayerCharacter,
    Quest,
    QuestObjective,
)


def _resolve_equip_name(item_id: str | None, catalog_lookup: dict[str, str]) -> str | None:
    """Resolve an equipment slot value to an item name using the catalog lookup dict.

    Returns the item name if found, the raw value as fallback (backwards compat),
    or None if the slot is empty.
    """
    if not item_id:
        return None
    return catalog_lookup.get(item_id, item_id)


def build_prompt(
    narrator_config: NarratorConfig,
    player_character: PlayerCharacter,
    party_members: list[PartyMember],
    chat_history: list[ChatMessage],
    player_message: str,
    spotlight_block: str | None = None,
    story_summary: str | None = None,
    item_catalog: list[LorebookEntry] | None = None,
    quests: list[Quest] | None = None,
    quest_objectives: list[QuestObjective] | None = None,
    lore_entries: list[LorebookEntry] | None = None,
    lore_config: LorebookConfig | None = None,
    max_context_tokens: int = 128000,
    max_response_tokens: int = 1000,
) -> list[dict]:
    messages: list[dict] = []

    # Build catalog lookup: id -> name
    catalog_lookup: dict[str, str] = {}
    if item_catalog:
        for cat_item in item_catalog:
            catalog_lookup[cat_item.id] = cat_item.title

    # 1. System: Narrator instructions
    messages.append({"role": "system", "content": narrator_config.instructions})

    # 1b. System: Narrator action protocol (editable in Config; falls back to
    #     the built-in default when not customized)
    messages.append({
        "role": "system",
        "content": getattr(narrator_config, "action_instruction", "") or ACTION_INSTRUCTION,
    })

    # 2. Scenario context now lives as a permanent World lorebook entry and is
    #    injected through the lorebook (see steps 7–8).

    # 3. Player character summary
    pc_info = player_character.basic_info
    pc_equip = player_character.equipment

    equipped = [
        f"{slot}: {resolved}"
        for slot, item_id in pc_equip.items()
        if item_id
        for resolved in [_resolve_equip_name(item_id, catalog_lookup)]
        if resolved
    ]
    equip_str = ", ".join(equipped) if equipped else "nothing equipped"

    pc_summary = (
        f"PLAYER CHARACTER: {pc_info.get('name', 'Unknown')}, "
        f"a {pc_info.get('species', 'unknown')} {pc_info.get('gender', '').lower()}. "
        f"{pc_info.get('description', '')}\n"
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
                f"{slot}: {resolved}"
                for slot, item_id in pm.equipment.items()
                if item_id
                for resolved in [_resolve_equip_name(item_id, catalog_lookup)]
                if resolved
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

    # 5–6. Active quest summary
    if quests:
        # Group objectives by quest_id
        obj_by_quest: dict[str, list[QuestObjective]] = {}
        if quest_objectives:
            for o in quest_objectives:
                obj_by_quest.setdefault(o.quest_id, []).append(o)

        active_quests = [q for q in quests if q.status == "active"]
        if active_quests:
            quest_lines = ["ACTIVE QUESTS:"]
            for q in active_quests:
                quest_lines.append(f"  {q.title}")
                objs = sorted(obj_by_quest.get(q.id, []), key=lambda o: o.sort_order)
                for o in objs:
                    mark = "x" if o.done else " "
                    quest_lines.append(f"    [{mark}] {o.text}")
            messages.append({"role": "system", "content": "\n".join(quest_lines)})

    # Story summary
    if story_summary:
        messages.append({
            "role": "system",
            "content": f"STORY SO FAR:\n{story_summary}",
        })

    # 6. Spotlight block
    if spotlight_block:
        messages.append({"role": "system", "content": spotlight_block})

    # 7. Lorebook — match entries and group by injection position
    lore_groups: dict[str, list[LorebookEntry]] = {"top": [], "before_input": [], "bottom": []}
    if lore_entries and lore_config:
        matched = match_entries(player_message, lore_entries)
        if matched:
            lore_groups = group_by_position(matched, lore_config)

    # 8. Lorebook entries with injectionPosition = 'top'
    if lore_groups["top"]:
        messages.append({"role": "system", "content": format_lore_block(lore_groups["top"])})

    # 9. Chat history (with context trimming)
    preamble_tokens = _estimate_tokens(messages)
    player_msg_tokens = len(player_message) // 4 + 10
    # Reserve space for before_input and bottom lore blocks
    lore_extra_tokens = 0
    for pos in ("before_input", "bottom"):
        if lore_groups[pos]:
            lore_extra_tokens += len(format_lore_block(lore_groups[pos])) // 4 + 4
    budget = max_context_tokens - max_response_tokens - preamble_tokens - player_msg_tokens - lore_extra_tokens

    history_messages = [
        {"role": m.role, "content": m.content}
        for m in chat_history
    ]
    history_messages = _trim_to_budget(history_messages, budget)

    # The editable opening narration is the first turn of the conversation —
    # always present in context, even on the player's first message.
    first_message = getattr(narrator_config, "first_message", "") or ""
    if first_message.strip():
        history_messages.insert(0, {"role": "assistant", "content": first_message})

    messages.extend(history_messages)

    # 10. Lorebook entries with injectionPosition = 'before_input'
    if lore_groups["before_input"]:
        messages.append({"role": "system", "content": format_lore_block(lore_groups["before_input"])})

    # 11. Player's new message
    messages.append({"role": "user", "content": player_message})

    # 12. Lorebook entries with injectionPosition = 'bottom'
    if lore_groups["bottom"]:
        messages.append({"role": "system", "content": format_lore_block(lore_groups["bottom"])})

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
