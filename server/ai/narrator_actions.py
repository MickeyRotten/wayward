"""Narrator action block parsing and execution.

The Narrator LLM can optionally append a structured action block to its response
to grant items to the party inventory or equip/unequip party member equipment.
This module handles parsing, validation, and execution of those actions.

See CLAUDE.md > Narrator Actions for the full design.
"""

import json
import logging
import re
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.db.models import (
    InventoryStack,
    ItemInstance,
    LorebookEntry,
    PartyMember,
    PlayerCharacter,
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

        # Check if already in inventory
        existing = (
            await session.execute(
                select(InventoryStack).where(InventoryStack.item_id == item.id)
            )
        ).scalars().first()

        if existing:
            existing.count += count
        else:
            session.add(InventoryStack(item_id=item.id, count=count))

        inv_deltas.append({
            "itemId": item.id,
            "delta": count,
            "source": "narrator_grant",
        })

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

        # Get current equipment and record previous value
        equipment = dict(character.equipment) if character.equipment else {}
        previous_item_id = equipment.get(slot)

        # Set the new item
        equipment[slot] = item.id
        character.equipment = equipment

        equip_changes.append({
            "characterId": char_id,
            "slot": slot,
            "previousItemId": previous_item_id,
            "newItemId": item.id,
        })

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

        equipment = dict(character.equipment) if character.equipment else {}
        previous_item_id = equipment.get(slot)

        if not previous_item_id:
            log.info("Narrator unequip: slot '%s' already empty for '%s', skipping", slot, char_name)
            continue

        # Unequip: clear the slot
        equipment[slot] = None
        character.equipment = equipment

        # Return the item to inventory
        # Per CLAUDE.md: allow overflow by one rather than blocking the unequip
        existing_stack = (
            await session.execute(
                select(InventoryStack).where(InventoryStack.item_id == previous_item_id)
            )
        ).scalars().first()

        if existing_stack:
            existing_stack.count += 1
        else:
            # Create a new stack -- allow overflow by one if inventory is full
            session.add(InventoryStack(item_id=previous_item_id, count=1))

        equip_changes.append({
            "characterId": char_id,
            "slot": slot,
            "previousItemId": previous_item_id,
            "newItemId": None,
        })

        # Also record the inventory addition from the returned item
        inv_deltas.append({
            "itemId": previous_item_id,
            "delta": 1,
            "source": "narrator_grant",
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

        character = await session.get(PlayerCharacter, char_id)
        if character is None:
            character = await session.get(PartyMember, char_id)
        if character is None:
            log.info(
                "reverse_equipment_changes: unresolved character '%s', skipping",
                char_id,
            )
            continue

        equipment = dict(character.equipment) if character.equipment else {}
        equipment[slot] = previous_item_id
        character.equipment = equipment


async def _resolve_character(
    session: AsyncSession, name: str
) -> tuple[PlayerCharacter | PartyMember | None, str | None]:
    """Resolve a character by name (case-insensitive).

    Checks the player character first, then party members.
    Returns (model_instance, id) or (None, None).
    """
    # Check player character
    pc = (await session.execute(select(PlayerCharacter))).scalars().first()
    if pc and pc.basic_info.get("name", "").lower() == name.lower():
        return pc, pc.id

    # Check party members
    members = (await session.execute(select(PartyMember))).scalars().all()
    for pm in members:
        if pm.basic_info.get("name", "").lower() == name.lower():
            return pm, pm.id

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
    """Shared add/remove for grant_item / remove_item / consume_item."""
    item = await _resolve_item(session, item_name)
    if not item:
        return ToolEffect(result=f"No item named '{item_name}' exists in the world. Use lookup_item or search_items first.", ok=False)

    existing = (
        await session.execute(
            select(InventoryStack).where(InventoryStack.item_id == item.id)
        )
    ).scalars().first()

    if count > 0:
        if existing:
            existing.count += count
        else:
            session.add(InventoryStack(item_id=item.id, count=count))
        return ToolEffect(
            result=f"Added {count}× {item.title} to the party inventory.",
            inv_deltas=[{"itemId": item.id, "delta": count, "source": source}],
        )

    # Removal (count < 0)
    if not existing:
        return ToolEffect(result=f"'{item.title}' is not in the inventory; nothing removed.", ok=False)
    removed = min(existing.count, -count)
    existing.count -= removed
    if existing.count <= 0:
        await session.delete(existing)
    return ToolEffect(
        result=f"Removed {removed}× {item.title} from the party inventory.",
        inv_deltas=[{"itemId": item.id, "delta": -removed, "source": source}],
    )


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

    equipment = dict(character.equipment) if character.equipment else {}
    previous_item_id = equipment.get(slot)
    equipment[slot] = item.id
    character.equipment = equipment
    return ToolEffect(
        result=f"{char_name} equipped {item.title} in {slot}.",
        equip_changes=[{
            "characterId": char_id, "slot": slot,
            "previousItemId": previous_item_id, "newItemId": item.id,
        }],
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

    equipment = dict(character.equipment) if character.equipment else {}
    previous_item_id = equipment.get(slot)
    if not previous_item_id:
        return ToolEffect(result=f"{char_name}'s {slot} slot is already empty.", ok=False)
    equipment[slot] = None
    character.equipment = equipment

    existing_stack = (
        await session.execute(
            select(InventoryStack).where(InventoryStack.item_id == previous_item_id)
        )
    ).scalars().first()
    if existing_stack:
        existing_stack.count += 1
    else:
        session.add(InventoryStack(item_id=previous_item_id, count=1))

    return ToolEffect(
        result=f"{char_name} unequipped {slot}; the item returned to inventory.",
        equip_changes=[{
            "characterId": char_id, "slot": slot,
            "previousItemId": previous_item_id, "newItemId": None,
        }],
        inv_deltas=[{"itemId": previous_item_id, "delta": 1, "source": "narrator_grant"}],
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
    stacks = (await session.execute(select(InventoryStack))).scalars().all()
    if not stacks:
        return ToolEffect(result="The party inventory is empty.")
    lines = []
    for s in stacks:
        item = await session.get(LorebookEntry, s.item_id)
        name = item.title if item else s.item_id
        lines.append(f"{name} ×{s.count}")
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
