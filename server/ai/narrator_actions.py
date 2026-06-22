"""Narrator action block parsing and execution.

The Narrator LLM can optionally append a structured action block to its response
to grant items to the party inventory or equip/unequip party member equipment.
This module handles parsing, validation, and execution of those actions.

See CLAUDE.md > Narrator Actions for the full design.
"""

import json
import logging
import re

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.db.models import (
    InventoryStack,
    ItemCatalogEntry,
    OpenRouterSettings,
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
                select(ItemCatalogEntry).where(
                    func.lower(ItemCatalogEntry.name) == item_name.lower()
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
            # Adding to existing stack is always fine
            existing.count += count
        else:
            # Check carry capacity before creating new stack
            total_stacks = (
                await session.execute(
                    select(func.count()).select_from(InventoryStack)
                )
            ).scalar()
            settings = (
                await session.execute(select(OpenRouterSettings))
            ).scalars().first()
            max_slots = settings.max_carry_slots if settings else 12

            if total_stacks >= max_slots:
                log.info(
                    "Narrator addItems: inventory full (%d/%d), dropping '%s'",
                    total_stacks, max_slots, item_name,
                )
                continue

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
                select(ItemCatalogEntry).where(
                    func.lower(ItemCatalogEntry.name) == item_name.lower()
                )
            )
        ).scalars().first()

        if not item:
            log.info("Narrator equip: unresolved item '%s', skipping", item_name)
            continue

        # Validate: item must be Equipment type
        if item.type != "Equipment":
            log.info(
                "Narrator equip: item '%s' is type '%s', not Equipment, skipping",
                item_name, item.type,
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


# ---------------------------------------------------------------------------
# Instruction block appended to every prompt (not user-editable)
# ---------------------------------------------------------------------------

ACTION_INSTRUCTION = """NARRATOR ACTION PROTOCOL (system — not part of your creative instructions):
When your narration results in the party gaining or losing items, or a character equipping or unequipping something, append this block at the very end of your response, AFTER all prose:

<<<ACTIONS>>>
{
  "addItems": [{ "itemName": "Item Name", "count": 1 }],
  "equip": [{ "characterName": "Tifa", "slot": "rightHand", "itemName": "Comet Wand" }],
  "unequip": [{ "characterName": "Seraphine", "slot": "head" }]
}
<<<END ACTIONS>>>

Rules:
- Only include the keys that apply (addItems, equip, unequip). If nothing changes, do not include the block.
- Use the character's first name for characterName.
- Valid equipment slots: head, neck, torsoOver, torsoUnder, leftHand, rightHand, waist, legsOver, legsUnder, feet, accessory1, accessory2.
- Use exact item names as they appear in the world context.
- Only grant items that have been established in the world. Do not invent new items.
- The action block is stripped before displaying your response — the player never sees it."""
