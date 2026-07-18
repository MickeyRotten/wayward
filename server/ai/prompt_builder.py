from server.ai.lore_injector import format_lore_block, group_by_position, match_entries
from server.ai.narrator_actions import ACTION_INSTRUCTION
from server.ai.rules import compose_rules_block
from server.ai.style import compose_style_block, core_instructions
from server.db.models import (
    ChatMessage,
    LorebookConfig,
    LorebookEntry,
    NarratorConfig,
    Task,
)
from server.db.party import RuntimeCharacter

# Frozen copies of the built-in narrator instructions that older campaigns baked
# into NarratorConfig.instructions (before the core moved to style_catalog.json).
# A per-campaign `instructions` equal to one of these is treated as "no override"
# so the editable JSON core supersedes it instead of double-injecting. Custom
# (non-default) instructions are still layered in. Keep these strings verbatim.
_LEGACY_DEFAULT_INSTRUCTIONS = {
    # Current (post-Story-Style) trimmed default.
    "You are the Narrator of an ongoing adventure. Describe the world vividly, "
    "immersing the player in the scene. Advance the scene with each response: "
    "describe what happens, what the player sees or feels, and leave a natural "
    "opening for their next action. Never speak for the player character or decide "
    "their actions. When voicing a party member, use a dialogue tag with their name "
    "and keep it to one or two sentences in character. "
    "Characters are wearing only what they have equipped — if an equipment slot is "
    "empty, they have nothing in that slot. Do not invent clothing or gear that is "
    "not listed in their equipment.",
    # Original (pre-Story-Style) default, with the perspective/length clauses.
    "You are the Narrator of an ongoing adventure. Describe the world vividly "
    "in second person, addressing the player character directly. Keep prose concise "
    "— two to four paragraphs per beat. Advance the scene with each response: "
    "describe what happens, what the player sees or feels, and leave a natural "
    "opening for their next action. Never speak for the player character or decide "
    "their actions. When voicing a party member, use a dialogue tag with their name "
    "and keep it to one or two sentences in character. "
    "Characters are wearing only what they have equipped — if an equipment slot is "
    "empty, they have nothing in that slot. Do not invent clothing or gear that is "
    "not listed in their equipment.",
}


def augment_user_content(content: str, image_description: str | None, has_image: bool = True) -> str:
    """Fold a vision-agent image description into a user message's text for the
    LLM (display keeps the clean content + the image itself; the model sees
    this). When an image was attached but the vision agent couldn't describe
    it, the model is still told one exists."""
    if image_description:
        return f"{content}\n\n[The player attached an image. It shows: {image_description}]"
    if has_image:
        return f"{content}\n\n[The player attached an image; no description is available.]"
    return content


def _augment_message(m: ChatMessage) -> str:
    if m.role == "user" and getattr(m, "image_path", None):
        return augment_user_content(m.content, getattr(m, "image_description", None) or None)
    return m.content


def _format_equipment(
    equip: dict,
    catalog_lookup: dict[str, tuple[str, str]],
    instance_lookup: dict[str, str] | None = None,
) -> str:
    """Format an equipment dict into a prompt string including item descriptions.

    Equipment slots hold an ItemInstance id; ``instance_lookup`` maps that to the
    catalog item id (with a fallback to treating the value as a catalog id
    directly, for legacy/unmigrated data). Each equipped slot renders as
    ``slot: Name — description`` so the Narrator knows what each worn item
    actually is. Returns "nothing equipped" when empty.
    """
    instance_lookup = instance_lookup or {}
    parts: list[str] = []
    for slot, value in equip.items():
        if not value:
            continue
        item_id = instance_lookup.get(value, value)  # instance id → catalog id
        entry = catalog_lookup.get(item_id)
        if entry:
            name, desc = entry
            parts.append(f"{slot}: {name} — {desc}" if desc else f"{slot}: {name}")
        else:
            parts.append(f"{slot}: (unknown item)")
    return "; ".join(parts) if parts else "nothing equipped"


def build_prompt(
    narrator_config: NarratorConfig,
    player_character: RuntimeCharacter,
    party_members: list[RuntimeCharacter],
    chat_history: list[ChatMessage],
    player_message: str,
    spotlight_block: str | None = None,
    story_summary: str | None = None,
    item_catalog: list[LorebookEntry] | None = None,
    tasks: list[Task] | None = None,
    lore_entries: list[LorebookEntry] | None = None,
    lore_config: LorebookConfig | None = None,
    max_context_tokens: int = 128000,
    max_response_tokens: int = 1000,
    include_action_protocol: bool = True,
    first_message_override: str | None = None,
    campaign_rules: dict | None = None,
) -> list[dict]:
    messages: list[dict] = []

    # Build catalog lookup: id -> (name, description)
    catalog_lookup: dict[str, tuple[str, str]] = {}
    if item_catalog:
        for cat_item in item_catalog:
            catalog_lookup[cat_item.id] = (cat_item.title, cat_item.content or "")

    # 1. System: core Narrator instructions (role + core behavior) from the
    #    editable style_catalog.json — always first, so the prompt begins with a
    #    clear role definition. (Falls back to a code constant if the JSON is gone.)
    messages.append({"role": "system", "content": core_instructions()})

    # 1a'. System: optional per-campaign instruction override (the Editor's
    #      set_narrator_instructions). Injected only when it's a genuine custom
    #      value — a stored built-in default is skipped so the JSON core (which now
    #      owns that text) isn't duplicated.
    base_instructions = (getattr(narrator_config, "instructions", "") or "").strip()
    if base_instructions and base_instructions not in _LEGACY_DEFAULT_INSTRUCTIONS:
        messages.append({"role": "system", "content": base_instructions})

    # 1a. System: Story Style — the Campaign Builder's guided narration options
    #     (genre/tone/writing style/verbosity/content limit/perspective/structure
    #     + custom instructions), composed into a STORY STYLE block. Empty when the
    #     campaign has no selections (pre-builder campaigns) → prompts unchanged.
    style_block = compose_style_block(getattr(narrator_config, "style_fields", None) or {})
    if style_block:
        messages.append({"role": "system", "content": style_block})

    # 1b. System: Narrator action protocol — the legacy text-block path. Skipped
    #     in the agentic tool loop (the narrator drives state through tool calls
    #     instead). Falls back to the built-in default when not customized.
    if include_action_protocol:
        messages.append({
            "role": "system",
            "content": getattr(narrator_config, "action_instruction", "") or ACTION_INSTRUCTION,
        })

    # 1c. System: World Rules (R21) — the campaign's ruleset (party size,
    #     currency, declared attributes, tone). Compact; only non-empty facts.
    if campaign_rules:
        rules_block = compose_rules_block(campaign_rules)
        if rules_block:
            messages.append({"role": "system", "content": rules_block})

    # 2. Scenario context now lives as a permanent World lorebook entry and is
    #    injected through the lorebook (see steps 7–8).

    # 3. Player character summary
    pc_info = player_character.basic_info
    pc_equip = player_character.equipment

    equip_str = _format_equipment(pc_equip, catalog_lookup)

    pc_lines = [
        f"PLAYER CHARACTER: {pc_info.get('name', 'Unknown')}, "
        f"a {pc_info.get('species', 'unknown')} {pc_info.get('gender', '').lower()}. "
        f"{pc_info.get('description', '')}"
    ]
    if pc_info.get('personality'):
        pc_lines.append(f"Personality: {pc_info['personality']}")
    if pc_info.get('drive'):
        pc_lines.append(f"Drive (what pushes them forward): {pc_info['drive']}")
    pc_lines.append(f"Carrying: {equip_str}")
    messages.append({"role": "system", "content": "\n".join(pc_lines)})

    # 4. Party roster
    if party_members:
        roster_lines = ["PARTY ROSTER:"]
        for pm in party_members:
            info = pm.basic_info
            skill = pm.field_skill
            equip_pm_str = _format_equipment(pm.equipment, catalog_lookup)
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
            if info.get('other'):
                lines.append(f"    Other: {info['other']}")
            lines.append(f"    Field Skill: {skill.get('name', 'None')} — {skill.get('description', '')}")
            lines.append(f"    Carrying: {equip_pm_str}")
            roster_lines.append("\n".join(lines))
        messages.append({"role": "system", "content": "\n".join(roster_lines)})

    # 5–6. Active task list (the party's open to-dos)
    if tasks:
        active_tasks = [t for t in tasks if t.status == "active"]
        if active_tasks:
            task_lines = ["ACTIVE TASKS:"]
            for t in active_tasks:
                task_lines.append(f"  [ ] {t.text}")
            messages.append({"role": "system", "content": "\n".join(task_lines)})

    # Story summary
    if story_summary:
        messages.append({
            "role": "system",
            "content": f"STORY SO FAR:\n{story_summary}",
        })

    # 6. Spotlight block
    if spotlight_block:
        messages.append({"role": "system", "content": spotlight_block})

    # 7. Lorebook — match entries and group by injection position. The scan
    #    window is the new player message PLUS the last `scan_depth` turns of
    #    history (both roles, ~2 messages per turn), so lore the narrator just
    #    introduced still injects when the player's reply doesn't repeat the
    #    keyword ("tell me more about it").
    lore_groups: dict[str, list[LorebookEntry]] = {"top": [], "before_input": [], "bottom": []}
    if lore_entries and lore_config:
        scan_depth = max(0, int(getattr(lore_config, "scan_depth", 3) or 0))
        recent = [m.content or "" for m in chat_history[-(scan_depth * 2):]] if scan_depth else []
        scan_text = "\n".join([*recent, player_message])
        matched = match_entries(scan_text, lore_entries)
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

    # The editable opening narration is prepended to history below and is ALWAYS
    # kept, so it must be reserved here or it can push the prompt over budget.
    # An adventure that anchored an alternate greeting overrides the primary.
    first_message = (
        first_message_override
        if (first_message_override and first_message_override.strip())
        else (getattr(narrator_config, "first_message", "") or "")
    )
    first_msg_tokens = (len(first_message) // 4 + 4) if first_message.strip() else 0

    budget = max_context_tokens - max_response_tokens - preamble_tokens - player_msg_tokens - lore_extra_tokens - first_msg_tokens
    # Safety margin: the chars/4 estimate under-counts for many tokenizers, so
    # leave ~10% headroom rather than trimming right up to the hard limit.
    budget = int(budget * 0.9)

    history_messages = [
        {"role": m.role, "content": _augment_message(m)}
        for m in chat_history
    ]
    history_messages = _trim_to_budget(history_messages, budget)

    # Prepend the opening narration as the first turn of the conversation —
    # always present in context, even on the player's first message.
    if first_message.strip():
        history_messages.insert(0, {"role": "assistant", "content": first_message})

    messages.extend(history_messages)

    # 10. Lorebook entries with injectionPosition = 'before_input'
    if lore_groups["before_input"]:
        messages.append({"role": "system", "content": format_lore_block(lore_groups["before_input"])})

    # 10b. Post-history instructions — always last, right before the user's
    #      message (user-editable in Config, empty by default).
    post_history = getattr(narrator_config, "post_history_instructions", "") or ""
    if post_history.strip():
        messages.append({"role": "system", "content": post_history})

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
