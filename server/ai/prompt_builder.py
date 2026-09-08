from server.ai.character_blocks import compose_blocks
from server.ai.clock import phase_of
from server.ai.lore_injector import format_lore_block, group_by_position, match_entries
from server.ai.narrator_actions import ACTION_INSTRUCTION
from server.ai.roster import compose_roll_call
from server.ai.rules import compose_rules_block
from server.ai.style import compose_style_block, core_instructions
from server.db.models import (
    ChatMessage,
    LorebookConfig,
    LorebookEntry,
    NarratorConfig,
    Objective,
    Task,
    Wish,
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


# How many recent turns every keyword-gated block scans. ONE window, shared by
# lore matching, the spotlight and gear relevance — three matchers that share a
# keyword helper and then disagreed about how much text to look at, so
# "mentioned" quietly meant three different things.
CONTEXT_TURNS = 3

# The single authority line over the state tier. Three blocks each claiming to
# override the beats read as three arguments and the model picks one.
_STATE_AUTHORITY = (
    "STATE OF PLAY — this is what is true RIGHT NOW, re-read from the game this "
    "turn. Where the beats above disagree with anything below, the beats are out "
    "of date and this block wins."
)


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
    objectives: list[Objective] | None = None,
    wishes: list[Wish] | None = None,
    lore_entries: list[LorebookEntry] | None = None,
    lore_config: LorebookConfig | None = None,
    max_context_tokens: int = 128000,
    max_response_tokens: int = 1000,
    include_action_protocol: bool = True,
    first_message_override: str | None = None,
    campaign_rules: dict | None = None,
    benched_members: list[RuntimeCharacter] | None = None,
    scene: dict | None = None,
    inventory_lines: list[str] | None = None,
) -> list[dict]:
    """Assemble one narration call, in five tiers.

    The tiers run oldest-and-general to newest-and-specific, so nothing the
    model reads is contradicted by something it read earlier. Two rules hold the
    shape together and both are easy to break by adding "one more block":

    **Every fact is stated once.** A model shown the same fact twice re-states
    it, and a re-statement costs a state write, a chat event and a line of
    transcript. Equipment is in the sheets; conditions of the world are in the
    state tier; nothing is in both.

    **Anything the history can contradict is stated AFTER the history.** That is
    the entire reason tier 4 exists. It is also a performance property, not only
    a correctness one: tier 1 is the same bytes on every turn of an adventure,
    so it stays a stable prompt prefix that providers can cache, where the old
    ordering put the roster and the task list — which change constantly — ahead
    of everything and invalidated the prefix every single turn.

    Tier 1 standing context · 2 turn context (keyword-gated, skipped whole on a
    quiet turn) · 3 history · 4 state of play · 5 this turn, then the ask.
    """
    messages: list[dict] = []
    benched_members = benched_members or []

    # Build catalog lookup: id -> (name, description)
    catalog_lookup: dict[str, tuple[str, str]] = {}
    if item_catalog:
        for cat_item in item_catalog:
            catalog_lookup[cat_item.id] = (cat_item.title, cat_item.content or "")

    # ── TIER 1 · STANDING CONTEXT ──────────────────────────────────────────
    # The slow-changing half, first, so it is a stable cacheable prefix.

    # Core Narrator instructions (role + core behaviour) from the editable
    # style_catalog.json. Falls back to a code constant if the JSON is gone.
    messages.append({"role": "system", "content": core_instructions()})

    # Optional per-campaign instruction override — a legacy field. Injected only
    # when it is a genuine custom value; a stored built-in default is skipped so
    # the JSON core (which now owns that text) is not duplicated.
    base_instructions = (getattr(narrator_config, "instructions", "") or "").strip()
    if base_instructions and base_instructions not in _LEGACY_DEFAULT_INSTRUCTIONS:
        messages.append({"role": "system", "content": base_instructions})

    # Story Style — the Campaign Builder's guided narration options. Empty when
    # the campaign has no selections, so pre-builder campaigns are unchanged.
    style_block = compose_style_block(getattr(narrator_config, "style_fields", None) or {})
    if style_block:
        messages.append({"role": "system", "content": style_block})

    # The legacy text action protocol. The trailing turn block supersedes it in
    # both narration paths; kept for callers that still ask for it.
    if include_action_protocol:
        messages.append({
            "role": "system",
            "content": getattr(narrator_config, "action_instruction", "") or ACTION_INSTRUCTION,
        })

    # World Rules — party size, currency, declared attributes, tone.
    if campaign_rules:
        rules_block = compose_rules_block(campaign_rules)
        if rules_block:
            messages.append({"role": "system", "content": rules_block})

    # Player character sheet — composed from the character's own toggleable
    # block tree (see server/ai/character_blocks.py), open/close-tagged by
    # <Name>...</Name> blocks so a model can't blur it into the party sheets
    # that follow. Equipment is stated HERE and nowhere else — it's a virtual
    # block rendered live from the current binding, never stored.
    pc_name = getattr(player_character, "name", None) or player_character.basic_info.get("name", "Unknown")
    pc_equip = _format_equipment(player_character.equipment, catalog_lookup)
    pc_sheet = compose_blocks(player_character.blocks, pc_name, equipment_text=pc_equip)
    if pc_sheet:
        messages.append({"role": "system", "content": f"PLAYER CHARACTER:\n{pc_sheet}"})

    # Party sheets — the slow half of a companion (who they are). Who is
    # actually present is re-stated in tier 4, after the history.
    if party_members:
        roster_parts = ["PARTY SHEETS — who these companions are:"]
        for pm in party_members:
            pm_name = pm.basic_info.get("name", "Unknown")
            pm_equip = _format_equipment(pm.equipment, catalog_lookup)
            sheet = compose_blocks(pm.blocks, pm_name, equipment_text=pm_equip)
            if sheet:
                roster_parts.append(sheet)
        messages.append({"role": "system", "content": "\n\n".join(roster_parts)})

    # ── TIER 2 · TURN CONTEXT ──────────────────────────────────────────────
    # The keyword-gated material THIS action pulled in, as one message, skipped
    # entirely on a quiet turn. One scan text, shared by every gate.
    scan_depth = CONTEXT_TURNS
    if lore_config is not None:
        scan_depth = max(0, int(getattr(lore_config, "scan_depth", CONTEXT_TURNS) or 0))
    recent = [m.content or "" for m in chat_history[-(scan_depth * 2):]] if scan_depth else []
    scan_text = "\n".join([*recent, player_message])

    lore_groups: dict[str, list[LorebookEntry]] = {"top": [], "before_input": [], "bottom": []}
    if lore_entries and lore_config:
        matched = match_entries(scan_text, lore_entries)
        if matched:
            lore_groups = group_by_position(matched, lore_config)

    turn_context: list[str] = []
    if lore_groups["top"]:
        turn_context.append(format_lore_block(lore_groups["top"]))
    if spotlight_block:
        turn_context.append(spotlight_block)
    if turn_context:
        messages.append({"role": "system", "content": "\n\n".join(turn_context)})

    # ── TIER 3 · HISTORY ───────────────────────────────────────────────────
    # Reserve room for everything still to be appended, then trim.
    preamble_tokens = _estimate_tokens(messages)
    player_msg_tokens = len(player_message) // 4 + 10

    state_blocks: list[str] = []
    if scene:
        bits = []
        if scene.get("location"):
            bits.append(f"Location: {scene['location']}")
        if scene.get("day"):
            bits.append(f"Day {scene['day']}")
        if scene.get("minutes") is not None:
            bits.append(f"Time: {phase_of(scene['minutes'])}")
        elif scene.get("timeOfDay"):
            bits.append(f"Time: {scene['timeOfDay']}")
        if scene.get("weather"):
            bits.append(f"Weather: {scene['weather']}")
        if bits:
            state_blocks.append("CURRENT SCENE — " + " · ".join(bits))

    state_blocks.append(compose_roll_call(
        player_character, party_members, benched_members,
        (campaign_rules or {}).get("partySize"),
    ))

    if inventory_lines:
        state_blocks.append(
            "INVENTORY — everything the party is carrying. Use these labels "
            "exactly as written; nothing else is in the pack.\n"
            + "\n".join(f"  · {ln}" for ln in inventory_lines)
        )

    if objectives:
        active_objectives = [o for o in objectives if o.status == "active"]
        if active_objectives:
            obj_lines = [
                "OVERARCHING OBJECTIVES (the adventure's guiding goals — steer the "
                "story toward these; don't resolve them cheaply):"
            ]
            for o in active_objectives:
                obj_lines.append(f"  \u25c6 {o.text}")
                if (o.detail or "").strip():
                    obj_lines.append(f"      {o.detail.strip()}")
            state_blocks.append("\n".join(obj_lines))

    if tasks:
        active_tasks = [t for t in tasks if t.status == "active"]
        if active_tasks:
            task_lines = ["ACTIVE TASKS:"]
            for t in active_tasks:
                task_lines.append(f"  [ ] {t.text}")
                if (t.notes or "").strip():
                    task_lines.append(f"      Notes: {t.notes.strip()}")
            state_blocks.append("\n".join(task_lines))

    if wishes:
        wish_lines = [
            "PLAYER WISHLIST (things the player hopes to see happen — weave them in "
            "naturally when the story allows; never force them):"
        ]
        _PRIORITY_LABEL = {3: "high", 2: "medium", 1: "low"}
        for w in wishes:
            if not (w.text or "").strip():
                continue
            label = _PRIORITY_LABEL.get(int(w.priority or 0))
            suffix = f" (priority: {label})" if label else ""
            wish_lines.append(f"  \u2022 {w.text.strip()}{suffix}")
        if len(wish_lines) > 1:
            state_blocks.append("\n".join(wish_lines))

    state_message = _STATE_AUTHORITY + "\n\n" + "\n\n".join(state_blocks)

    tail_tokens = len(state_message) // 4 + 8
    if story_summary:
        tail_tokens += len(story_summary) // 4 + 8
    for pos in ("before_input", "bottom"):
        if lore_groups[pos]:
            tail_tokens += len(format_lore_block(lore_groups[pos])) // 4 + 4

    # The editable opening narration is prepended to history and ALWAYS kept, so
    # it must be reserved here or it can push the prompt over budget.
    first_message = (
        first_message_override
        if (first_message_override and first_message_override.strip())
        else (getattr(narrator_config, "first_message", "") or "")
    )
    first_msg_tokens = (len(first_message) // 4 + 4) if first_message.strip() else 0

    budget = (max_context_tokens - max_response_tokens - preamble_tokens
              - player_msg_tokens - tail_tokens - first_msg_tokens)
    # Safety margin: the chars/4 estimate under-counts for many tokenizers, so
    # leave ~10% headroom rather than trimming right up to the hard limit.
    budget = int(budget * 0.9)

    history_messages = [
        {"role": m.role, "content": _augment_message(m)}
        for m in chat_history
    ]
    history_messages = _trim_to_budget(history_messages, budget)

    if first_message.strip():
        history_messages.insert(0, {"role": "assistant", "content": first_message})

    messages.extend(history_messages)

    # ── TIER 3b · THE STRETCH BEHIND THE WINDOW ────────────────────────────
    # After the history because it is the OLDER material: the window holds the
    # last few beats verbatim, this is what the window has already dropped.
    if story_summary:
        messages.append({
            "role": "system",
            "content": f"STORY SO FAR (what happened before the beats above):\n{story_summary}",
        })

    # ── TIER 4 · STATE OF PLAY ─────────────────────────────────────────────
    messages.append({"role": "system", "content": state_message})

    # ── TIER 5 · THIS TURN, THEN THE ASK ───────────────────────────────────
    if lore_groups["before_input"]:
        messages.append({"role": "system", "content": format_lore_block(lore_groups["before_input"])})

    post_history = getattr(narrator_config, "post_history_instructions", "") or ""
    if post_history.strip():
        messages.append({"role": "system", "content": post_history})

    messages.append({"role": "user", "content": player_message})

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
