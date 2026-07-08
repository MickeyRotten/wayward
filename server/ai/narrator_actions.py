"""Narrator action block parsing and execution.

The Narrator LLM can optionally append a structured action block to its response
to grant items to the party inventory or equip/unequip party member equipment.
This module handles parsing, validation, and execution of those actions.

See CLAUDE.md > Narrator Actions for the full design.
"""

import json
import logging
import random
import re
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.db import inventory as inv_ops
from server.db import party as party_ops
from server.db.models import (
    ItemInstance,
    LorebookEntry,
    PartyBinding,
)

log = logging.getLogger("wayward.narrator_actions")

ACTION_BLOCK_RE = re.compile(
    r"<<<ACTIONS>>>\s*(.*?)\s*<<<END ACTIONS>>>", re.DOTALL
)

# Maps catalog slot categories to the Equipment field names they can be equipped into.
# The catalog uses broad categories ("Head", "Hands", "Torso", etc.)
# while Equipment has specific slots ("head", "leftHand", "rightHand", etc.).
SLOT_COMPATIBILITY: dict[str, list[str]] = {
    "Head": ["head"],
    "Neck": ["neck"],
    "Torso": ["torsoOver", "torsoUnder"],
    "Hands": ["leftHand", "rightHand"],
    "Waist": ["waist"],
    "Legs": ["legsOver", "legsUnder"],
    "Feet": ["feet"],
    "Accessory": ["accessory1", "accessory2"],
}

# All valid equipment slot field names
VALID_EQUIPMENT_SLOTS = {
    "head", "neck", "torsoOver", "torsoUnder",
    "leftHand", "rightHand", "waist",
    "legsOver", "legsUnder", "feet",
    "accessory1", "accessory2",
}


def parse_action_block(raw_response: str) -> tuple[str, dict | None]:
    """Parse and strip the <<<ACTIONS>>>...<<<END ACTIONS>>> block from a raw LLM response.

    Returns:
        (clean_text, actions_dict | None) -- the prose with the block removed,
        and the parsed JSON actions dict if valid, else None.
    """
    match = ACTION_BLOCK_RE.search(raw_response)
    if not match:
        return raw_response, None

    clean = raw_response[: match.start()].rstrip() + raw_response[match.end() :]
    clean = clean.strip()

    try:
        actions = json.loads(match.group(1))
    except json.JSONDecodeError:
        log.warning("Failed to parse narrator action block JSON: %s", match.group(1)[:200])
        return clean, None

    if not isinstance(actions, dict):
        log.warning("Narrator action block is not a dict: %s", type(actions))
        return clean, None

    return clean, actions


async def execute_actions(
    actions: dict,
    session: AsyncSession,
) -> tuple[list[dict], list[dict]]:
    """Execute parsed narrator actions against the database.

    Returns:
        (inventory_deltas, equipment_changes) -- lists of dicts recording
        what changed, for storage on the ChatMessage and later reversal.
    """
    inv_deltas: list[dict] = []
    equip_changes: list[dict] = []

    # --- addItems ---
    for add in actions.get("addItems", []):
        item_name = add.get("itemName", "")
        count = add.get("count", 1)
        if not item_name or count < 1:
            continue

        # Resolve name -> catalog entry (case-insensitive exact match)
        item = (
            await session.execute(
                select(LorebookEntry).where(
                    LorebookEntry.cat == "items",
                    func.lower(LorebookEntry.title) == item_name.lower(),
                )
            )
        ).scalars().first()

        if not item:
            log.info("Narrator addItems: unresolved item name '%s', skipping", item_name)
            continue

        _msg, deltas = await inv_ops.grant_items(session, item, count, "narrator_grant")
        inv_deltas.extend(deltas)

    # --- equip ---
    for eq in actions.get("equip", []):
        char_name = eq.get("characterName", "")
        slot = eq.get("slot", "")
        item_name = eq.get("itemName", "")
        if not char_name or not slot or not item_name:
            continue

        if slot not in VALID_EQUIPMENT_SLOTS:
            log.info("Narrator equip: invalid slot '%s', skipping", slot)
            continue

        # Resolve character by name (case-insensitive)
        character, char_id = await _resolve_character(session, char_name)
        if character is None:
            log.info("Narrator equip: unresolved character '%s', skipping", char_name)
            continue

        # Resolve item by name
        item = (
            await session.execute(
                select(LorebookEntry).where(
                    LorebookEntry.cat == "items",
                    func.lower(LorebookEntry.title) == item_name.lower(),
                )
            )
        ).scalars().first()

        if not item:
            log.info("Narrator equip: unresolved item '%s', skipping", item_name)
            continue

        # Validate: item must be Equipment type
        if item.item_type != "Equipment":
            log.info(
                "Narrator equip: item '%s' is type '%s', not Equipment, skipping",
                item_name, item.item_type,
            )
            continue

        # Validate: item's catalog slot must be compatible with the target Equipment slot
        if item.slot and not _is_slot_compatible(item.slot, slot):
            log.info(
                "Narrator equip: item '%s' (slot=%s) incompatible with target slot '%s', skipping",
                item_name, item.slot, slot,
            )
            continue

        # Equip an ItemInstance (slots hold instance ids, not catalog ids): reuse
        # a stowed copy or mint one.
        _msg, changes, deltas = await inv_ops.equip_instance(
            session, character, char_id, slot, item
        )
        equip_changes.extend(changes)
        inv_deltas.extend(deltas)

    # --- unequip ---
    for ueq in actions.get("unequip", []):
        char_name = ueq.get("characterName", "")
        slot = ueq.get("slot", "")
        if not char_name or not slot:
            continue

        if slot not in VALID_EQUIPMENT_SLOTS:
            log.info("Narrator unequip: invalid slot '%s', skipping", slot)
            continue

        character, char_id = await _resolve_character(session, char_name)
        if character is None:
            log.info("Narrator unequip: unresolved character '%s', skipping", char_name)
            continue

        binding = await party_ops.binding_for(session, char_id)
        if binding is None:
            continue
        equipment = dict(binding.equipment or {})
        previous_instance_id = equipment.get(slot)

        if not previous_instance_id:
            log.info("Narrator unequip: slot '%s' already empty for '%s', skipping", slot, char_name)
            continue

        # Clear the slot; the instance is now unreferenced → derived as stowed.
        # No InventoryStack / delta needed.
        equipment[slot] = None
        binding.equipment = equipment

        equip_changes.append({
            "characterId": char_id,
            "slot": slot,
            "previousItemId": previous_instance_id,
            "newItemId": None,
        })

    return inv_deltas, equip_changes


async def reverse_equipment_changes(
    changes: list[dict],
    session: AsyncSession,
) -> None:
    """Reverse a list of previously-applied equipment changes.

    Each change is ``{characterId, slot, previousItemId, newItemId}``. Reversing
    means restoring the slot to ``previousItemId`` (whatever was there before the
    narrator's change). The inventory side of an unequip (the returned item) is
    handled separately by reversing the inventory deltas — see
    item_detection.reverse_inventory_deltas — so this only restores slot state.

    Changes are reversed in reverse order so that multiple changes to the same
    slot in one turn unwind correctly.
    """
    for change in reversed(changes):
        char_id = change.get("characterId")
        slot = change.get("slot")
        previous_item_id = change.get("previousItemId")
        if not char_id or not slot:
            continue
        if slot not in VALID_EQUIPMENT_SLOTS:
            continue

        binding = (await session.execute(
            select(PartyBinding).where(PartyBinding.character_id == char_id)
        )).scalars().first()
        if binding is None:
            log.info(
                "reverse_equipment_changes: unresolved character '%s', skipping",
                char_id,
            )
            continue

        equipment = dict(binding.equipment or {})
        equipment[slot] = previous_item_id
        binding.equipment = equipment


async def _resolve_character(
    session: AsyncSession, name: str
) -> tuple[object | None, str | None]:
    """Resolve a character by name (case-insensitive), PC first then party.

    Returns a ``RuntimeCharacter`` (identity + equipment composite) and its
    character id, or (None, None)."""
    if not name:
        return None, None
    pc = await party_ops.load_pc(session)
    if pc and pc.basic_info.get("name", "").lower() == name.lower():
        return pc, pc.id
    for m in await party_ops.load_party(session):
        if m.basic_info.get("name", "").lower() == name.lower():
            return m, m.id
    return None, None


def _is_slot_compatible(catalog_slot: str, equipment_field: str) -> bool:
    """Check if a catalog item's slot category is compatible with an Equipment field name."""
    compatible_fields = SLOT_COMPATIBILITY.get(catalog_slot, [])
    return equipment_field in compatible_fields


async def _resolve_item(session: AsyncSession, name: str) -> LorebookEntry | None:
    """Resolve an item by name (case-insensitive exact match) from Lore → Items."""
    if not name:
        return None
    return (
        await session.execute(
            select(LorebookEntry).where(
                LorebookEntry.cat == "items",
                func.lower(LorebookEntry.title) == name.lower(),
            )
        )
    ).scalars().first()


# ---------------------------------------------------------------------------
# Agentic tool handlers
#
# Each handler executes one narrator tool call against the DB (or reads state)
# and returns a ToolEffect: a short natural-language ``result`` fed back to the
# model, plus any deltas/changes to record on the ChatMessage for later
# reversal. Unlike the legacy ``execute_actions`` text-block path, these run
# *inside* the turn's agent loop so the model sees the outcome and can react.
# ---------------------------------------------------------------------------


@dataclass
class ToolEffect:
    result: str
    inv_deltas: list[dict] = field(default_factory=list)
    equip_changes: list[dict] = field(default_factory=list)
    scene: dict = field(default_factory=dict)
    # False when a mutating tool could not do what was asked (bad args, missing
    # item/character, wrong slot, …) — surfaced to the player as a graceful
    # "the world stayed safe" notice. Read-only lookups leave this True.
    ok: bool = True


# ── Skill checks (dice) ───────────────────────────────────────────

_DICE_DCS = {"easy": 8, "normal": 12, "hard": 16, "heroic": 19}


async def tool_skill_check(args: dict, session: AsyncSession, turn_number: int = 0) -> ToolEffect:
    """Server-rolled d20 skill check — the model narrates the outcome it is
    GIVEN, so it can never fudge the dice. The roll is recorded as a tethered
    ChatEvent (a dice chip in the chat) that vanishes with the turn on
    swipe/regenerate/delete, and a fresh re-roll happens on the retelling."""
    from server.db import events as event_ops

    who = (args.get("characterName") or "").strip() or "Someone"
    skill = (args.get("skill") or "").strip() or "a skill"
    difficulty = (args.get("difficulty") or "normal").strip().lower()
    dc = _DICE_DCS.get(difficulty, _DICE_DCS["normal"])
    roll = random.randint(1, 20)
    if roll == 20:
        outcome = "critical success"
    elif roll == 1:
        outcome = "critical failure"
    elif roll >= dc:
        outcome = "success"
    else:
        outcome = "failure"

    text = f"{who} — {skill}: rolled {roll} vs DC {dc} — {outcome.title()}"
    await event_ops.add_event(
        session, turn_number=turn_number, kind="dice", text=text, tethered=True
    )
    return ToolEffect(result=json.dumps({
        "roll": roll, "dc": dc, "difficulty": difficulty, "outcome": outcome,
    }))


async def tool_set_scene(args: dict, session: AsyncSession) -> ToolEffect:
    scene: dict = {}
    loc = args.get("location")
    if isinstance(loc, str) and loc.strip():
        scene["location"] = loc.strip()
    tod = args.get("timeOfDay")
    if isinstance(tod, str) and tod.strip():
        scene["timeOfDay"] = tod.strip()
    wx = args.get("weather")
    if isinstance(wx, str) and wx.strip():
        scene["weather"] = wx.strip()
    day = args.get("day")
    if isinstance(day, int) and day > 0:
        scene["day"] = day
    elif isinstance(day, str) and day.strip().isdigit():
        scene["day"] = int(day.strip())
    if not scene:
        return ToolEffect(result="No scene fields provided; nothing changed.")
    bits = ", ".join(f"{k}={v}" for k, v in scene.items())
    return ToolEffect(result=f"Scene updated ({bits}).", scene=scene)


async def _change_inventory(
    session: AsyncSession, item_name: str, count: int, source: str
) -> ToolEffect:
    """Shared add/remove for grant_item / remove_item / consume_item.

    Operates on ``ItemInstance`` rows via the shared inventory helpers (Equipment
    → one instance per copy; stackables → a single counted instance), so the
    party's owned copies stay consistent with the manual routes and the derived
    equipped/stowed view."""
    item = await _resolve_item(session, item_name)
    if not item:
        return ToolEffect(result=f"No item named '{item_name}' exists in the world. Use lookup_item or search_items first.", ok=False)

    if count > 0:
        msg, deltas = await inv_ops.grant_items(session, item, count, source)
        return ToolEffect(result=msg, inv_deltas=deltas)

    # Removal (count < 0) — stowed copies only.
    msg, deltas = await inv_ops.remove_items(session, item, -count, source)
    return ToolEffect(result=msg, inv_deltas=deltas, ok=bool(deltas))


async def tool_grant_item(args: dict, session: AsyncSession) -> ToolEffect:
    count = int(args.get("count", 1) or 1)
    if count < 1:
        return ToolEffect(result="count must be at least 1.", ok=False)
    return await _change_inventory(session, args.get("itemName", ""), count, "narrator_grant")


async def tool_remove_item(args: dict, session: AsyncSession) -> ToolEffect:
    count = int(args.get("count", 1) or 1)
    if count < 1:
        return ToolEffect(result="count must be at least 1.", ok=False)
    return await _change_inventory(session, args.get("itemName", ""), -count, "narrator_grant")


async def tool_consume_item(args: dict, session: AsyncSession) -> ToolEffect:
    count = int(args.get("count", 1) or 1)
    if count < 1:
        return ToolEffect(result="count must be at least 1.", ok=False)
    return await _change_inventory(session, args.get("itemName", ""), -count, "player_action")


async def tool_equip(args: dict, session: AsyncSession) -> ToolEffect:
    char_name = args.get("characterName", "")
    slot = args.get("slot", "")
    item_name = args.get("itemName", "")
    if not char_name or not slot or not item_name:
        return ToolEffect(result="equip requires characterName, slot, and itemName.", ok=False)
    if slot not in VALID_EQUIPMENT_SLOTS:
        return ToolEffect(result=f"'{slot}' is not a valid equipment slot.", ok=False)

    character, char_id = await _resolve_character(session, char_name)
    if character is None:
        return ToolEffect(result=f"No character named '{char_name}'.", ok=False)

    item = await _resolve_item(session, item_name)
    if not item:
        return ToolEffect(result=f"No item named '{item_name}' exists in the world.", ok=False)
    if item.item_type != "Equipment":
        return ToolEffect(result=f"'{item.title}' is type '{item.item_type}', not Equipment; it cannot be equipped.", ok=False)
    if item.slot and not _is_slot_compatible(item.slot, slot):
        return ToolEffect(result=f"'{item.title}' ({item.slot}) cannot go in slot '{slot}'.", ok=False)

    # Equipment slots reference an ItemInstance id (not the catalog id): reuse a
    # stowed copy or mint one. This keeps the derived equipped/stowed view — and
    # so the party sheet + Inventory panel — in sync.
    msg, equip_changes, inv_deltas = await inv_ops.equip_instance(
        session, character, char_id, slot, item
    )
    return ToolEffect(
        result=f"{char_name} {msg}",
        equip_changes=equip_changes,
        inv_deltas=inv_deltas,
    )


async def tool_unequip(args: dict, session: AsyncSession) -> ToolEffect:
    char_name = args.get("characterName", "")
    slot = args.get("slot", "")
    if not char_name or not slot:
        return ToolEffect(result="unequip requires characterName and slot.", ok=False)
    if slot not in VALID_EQUIPMENT_SLOTS:
        return ToolEffect(result=f"'{slot}' is not a valid equipment slot.", ok=False)

    character, char_id = await _resolve_character(session, char_name)
    if character is None:
        return ToolEffect(result=f"No character named '{char_name}'.", ok=False)

    binding = await party_ops.binding_for(session, char_id)
    if binding is None:
        return ToolEffect(result=f"No character named '{char_name}'.", ok=False)
    equipment = dict(binding.equipment or {})
    previous_instance_id = equipment.get(slot)
    if not previous_instance_id:
        return ToolEffect(result=f"{char_name}'s {slot} slot is already empty.", ok=False)
    equipment[slot] = None
    binding.equipment = equipment

    # Clearing the slot is all that's needed: the instance is now unreferenced,
    # so it's *derived* as stowed in the pack. No InventoryStack / delta.
    return ToolEffect(
        result=f"{char_name} unequipped {slot}; the item returned to the pack.",
        equip_changes=[{
            "characterId": char_id, "slot": slot,
            "previousItemId": previous_instance_id, "newItemId": None,
        }],
    )


async def tool_lookup_item(args: dict, session: AsyncSession) -> ToolEffect:
    item = await _resolve_item(session, args.get("name", ""))
    if not item:
        return ToolEffect(result=f"No item named '{args.get('name', '')}' exists in the world.")
    return ToolEffect(result=json.dumps({
        "name": item.title, "type": item.item_type, "slot": item.slot,
        "rarity": item.rarity, "description": item.content or "",
    }, ensure_ascii=False))


async def tool_search_items(args: dict, session: AsyncSession) -> ToolEffect:
    query = (args.get("query", "") or "").lower().strip()
    items = (
        await session.execute(select(LorebookEntry).where(LorebookEntry.cat == "items"))
    ).scalars().all()
    matches = [
        it.title for it in items
        if not query or query in it.title.lower() or query in (it.content or "").lower()
    ][:20]
    if not matches:
        return ToolEffect(result="No matching items found.")
    return ToolEffect(result="Matching items: " + ", ".join(matches))


async def tool_list_inventory(args: dict, session: AsyncSession) -> ToolEffect:
    # List STOWED copies (unequipped instances), aggregated by catalog item, so
    # the narrator sees what's actually in the pack — not gear that's worn.
    equipped = set((await inv_ops.equipped_map(session)).keys())
    instances = (await session.execute(select(ItemInstance))).scalars().all()
    counts: dict[str, int] = {}
    for inst in instances:
        if inst.id in equipped:
            continue
        counts[inst.item_id] = counts.get(inst.item_id, 0) + (inst.count or 1)
    if not counts:
        return ToolEffect(result="The party inventory is empty.")
    lines = []
    for item_id, n in counts.items():
        item = await session.get(LorebookEntry, item_id)
        name = item.title if item else item_id
        lines.append(f"{name} ×{n}")
    return ToolEffect(result="Inventory: " + "; ".join(lines))


async def tool_get_character(args: dict, session: AsyncSession) -> ToolEffect:
    character, _ = await _resolve_character(session, args.get("name", ""))
    if character is None:
        return ToolEffect(result=f"No character named '{args.get('name', '')}'.")
    equipment = character.equipment or {}
    equipped = {}
    for slot, value in equipment.items():
        if not value:
            continue
        # Equipment slots hold an ItemInstance id → resolve to the catalog entry
        # for the item's name + description. Fall back to treating the value as a
        # catalog id directly (legacy/unmigrated data).
        instance = await session.get(ItemInstance, value)
        item = await session.get(LorebookEntry, instance.item_id) if instance else await session.get(LorebookEntry, value)
        if item is not None:
            equipped[slot] = {"name": item.title, "description": item.content or ""}
        else:
            equipped[slot] = {"name": "Unknown item", "description": ""}
    info = character.basic_info or {}
    payload = {
        "name": info.get("name", "Unknown"),
        "species": info.get("species", ""),
        "description": info.get("description", ""),
        "equipped": equipped,
    }
    field_skill = getattr(character, "field_skill", None)
    if field_skill:
        payload["fieldSkill"] = field_skill
    return ToolEffect(result=json.dumps(payload, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Instruction block appended to every prompt (not user-editable)
# ---------------------------------------------------------------------------

ACTION_INSTRUCTION = """NARRATOR ACTION PROTOCOL (system — not part of your creative instructions):
When your narration results in the party gaining or losing items, or a character equipping or unequipping something, append this block at the very end of your response, AFTER all prose:

<<<ACTIONS>>>
{
  "location": "The Moonlit Clearing",
  "timeOfDay": "Night",
  "weather": "Clear and cold",
  "day": 1,
  "addItems": [{ "itemName": "Item Name", "count": 1 }],
  "equip": [{ "characterName": "Tifa", "slot": "rightHand", "itemName": "Comet Wand" }],
  "unequip": [{ "characterName": "Seraphine", "slot": "head" }]
}
<<<END ACTIONS>>>

Rules:
- Only include the keys that apply (location, timeOfDay, weather, day, addItems, equip, unequip). If nothing changes AND the location/time/weather/day are unchanged, do not include the block.
- "location": a short place name (2–4 words) for where the scene is taking place. Include it whenever the location is first established or changes — even if no items change. Omit it on turns where the party stays in the same place.
- "timeOfDay": one of exactly Morning, Day, Afternoon, Evening, Night. Include it when the time of day is first established or changes.
- "weather": a short weather descriptor (1–4 words, e.g. "Light rain", "Clear skies", "Fog"). Include it when the weather is first established or changes.
- "day": the in-game day number as an integer, starting at 1. Include it when a new day begins (e.g. after the party sleeps or time skips to the next morning); increment it by 1 each new day. Omit it while the same day continues.
- Use the character's first name for characterName.
- Valid equipment slots: head, neck, torsoOver, torsoUnder, leftHand, rightHand, waist, legsOver, legsUnder, feet, accessory1, accessory2.
- Use exact item names as they appear in the world context.
- Only grant items that have been established in the world. Do not invent new items.
- The action block is stripped before displaying your response — the player never sees it."""
