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

from server.db import inventory as inv_ops
from server.db import party as party_ops
from server.db.models import (
    ItemInstance,
    LorebookEntry,
    PartyBinding,
)

log = logging.getLogger("wayward.narrator_actions")

# Tolerant markers: weaker/older narrative models drift on the exact spelling
# (extra spaces, casing) and routinely forget the closing marker. Matching
# loosely — and salvaging the JSON even when the block is malformed — keeps the
# text-protocol path reliable on exactly the models that need it.
_ACTION_START_RE = re.compile(r"<<<\s*ACTIONS\s*>>>", re.IGNORECASE)
_ACTION_END_RE = re.compile(r"<<<\s*END\s+ACTIONS\s*>>>", re.IGNORECASE)


def _extract_json_object(s: str) -> str | None:
    """Return the first brace-balanced ``{...}`` object in ``s`` (string- and
    escape-aware), or None. Salvages a valid object even when the model appended
    trailing prose after it or wrapped it in stray characters."""
    start = s.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(s)):
        c = s[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return s[start:i + 1]
    return None


def _parse_actions_json(candidate: str) -> dict | None:
    """Parse the JSON between the action markers, tolerant of trailing prose or
    minor malformation: try the whole span, then a brace-matched object."""
    candidate = candidate.strip()
    if not candidate:
        return None
    for text in (candidate, _extract_json_object(candidate)):
        if not text:
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    log.warning("Failed to parse narrator action block JSON: %s", candidate[:200])
    return None

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

    Tolerant by design (weaker models are the ones that reach this path): a
    missing closing marker is accepted (the JSON runs to end-of-text), the JSON
    is salvaged via brace-matching when the model appended stray characters, and
    the ``<<<ACTIONS>>>`` span is ALWAYS stripped from the displayed prose — even
    when parsing fails — so a malformed block can never leak into the scene.
    """
    m = _ACTION_START_RE.search(raw_response)
    if not m:
        return raw_response, None

    before = raw_response[: m.start()]
    rest = raw_response[m.end():]
    end = _ACTION_END_RE.search(rest)
    if end:
        candidate = rest[: end.start()]
        after = rest[end.end():]
    else:
        # No closing marker — treat everything after <<<ACTIONS>>> as the block.
        candidate = rest
        after = ""

    clean = before.rstrip()
    if after.strip():
        clean = (clean + "\n" + after.strip()).strip()
    clean = clean.strip()

    return clean, _parse_actions_json(candidate)


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

async def tool_skill_check(
    args: dict, session: AsyncSession, turn_number: int = 0, variant: int = 0
) -> ToolEffect:
    """A d20 skill check the model narrates but never rolls.

    The roll is **seeded on the turn** (see ``server/ai/dice.py``), not random.
    An unseeded roll behind a regenerate button is an open save-scum hole: the
    player re-rolls until the answer is the one they wanted and no failure ever
    has to be lived with. Seeded, a regenerate re-*tells* the same result, while
    a swipe — a deliberate request for a different take — rolls fresh, and
    genuinely choosing another action earns a new roll on its own.

    The roll writes a tethered ChatEvent (the dice chip in chat) that vanishes
    with the turn on swipe/regenerate/delete."""
    from server.ai.dice import skill_check as roll_skill_check
    from server.db import events as event_ops

    who = (args.get("characterName") or "").strip() or "Someone"
    skill = (args.get("skill") or "").strip() or "a skill"
    result = roll_skill_check(turn_number, who, skill, args.get("difficulty"), variant)

    text = (f"{who} — {skill}: rolled {result['roll']} vs DC {result['dc']} "
            f"— {result['outcome'].title()}")
    await event_ops.add_event(
        session, turn_number=turn_number, kind="dice", text=text, tethered=True
    )
    return ToolEffect(result=json.dumps(result))


# Compound-location joiners. With any of these the TAIL is the narrower place,
# so "Boars Head Tavern - Damp Cellar" is the Damp Cellar. A comma is
# deliberately NOT a joiner ("Rodstroke, Mesmeria" nests the other way round),
# and a hyphen without surrounding spaces is part of a name ("Half-Moon Inn").
_LOCATION_JOINERS = (" - ", " \u2014 ", " \u2013 ", " / ", " > ", " | ", ": ")


def simplify_location(raw: str) -> str:
    """Keep the last segment of a narrator-stapled compound location.

    The location is the label the scene banner rules off and the backdrop
    matcher scores against, so "Tavern - Damp Cellar" and "Damp Cellar" read as
    two different rooms every time the model changes its mind about the prefix —
    and the art changes with them. Prompt wording alone was not enough. A value
    that is nothing but separators leaves the scene unchanged."""
    text = (raw or "").strip()
    for joiner in _LOCATION_JOINERS:
        if joiner in text:
            tail = text.rsplit(joiner, 1)[-1].strip()
            if tail:
                text = tail
    text = text.strip()
    # All separators and no name is not a place.
    return "" if not re.search(r"[A-Za-z0-9]", text) else text


def coerce_scene(args: dict, current_day: int | None = None) -> dict:
    """Validate a narrator scene declaration into storable fields.

    ``day`` is accepted only when it moves FORWARD. The narrator used to write it
    freely, which meant a value nothing checked: it could freeze, jump, or run
    backwards, and one confused beat desynced the calendar permanently. The
    ``duration`` ladder (server/ai/clock.py) is the supported way to move time;
    this guard is what stops the legacy field doing damage in the meantime."""
    scene: dict = {}
    loc = args.get("location")
    if isinstance(loc, str) and loc.strip():
        simple = simplify_location(loc)
        if simple:
            scene["location"] = simple
    tod = args.get("timeOfDay")
    if isinstance(tod, str) and tod.strip():
        scene["timeOfDay"] = tod.strip()
    wx = args.get("weather")
    if isinstance(wx, str) and wx.strip():
        scene["weather"] = wx.strip()

    day = args.get("day")
    if isinstance(day, str) and day.strip().isdigit():
        day = int(day.strip())
    if isinstance(day, int) and not isinstance(day, bool) and day > 0:
        if current_day is None or day >= current_day:
            scene["day"] = day
    return scene


async def tool_set_scene(args: dict, session: AsyncSession) -> ToolEffect:
    """Legacy text-protocol scene write. Not offered as a native tool any more —
    scene state rides the trailing turn block instead of buying a round-trip."""
    scene = coerce_scene(args)
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

    # Removal (count < 0) — stowed copies only. Removing something not held is a
    # no-op rather than a failure: the state asked for is the state already
    # there, and reporting it as an error invites the model to try again.
    msg, deltas = await inv_ops.remove_items(session, item, -count, source)
    if not deltas:
        return ToolEffect(
            result=(f"The party is not carrying a stowed {item.title} — nothing changed. "
                    "(Worn gear must be unequipped before it can be removed.)"),
        )
    return ToolEffect(result=msg, inv_deltas=deltas)


async def tool_grant_item(args: dict, session: AsyncSession) -> ToolEffect:
    """Add an item the party just acquired.

    A grant with **no explicit count** for something already stowed is read as a
    restatement, not a second pickup, and does nothing. A narrator shown the pack
    every turn and asked what changed answers with the state instead of the
    change — that reflex is how one rusty key becomes seven. An *explicit* count
    is always honoured, because "you pick up two more torches" is a real event.
    """
    raw_count = args.get("count")
    count = int(raw_count or 1)
    if count < 1:
        return ToolEffect(result="count must be at least 1.", ok=False)

    if raw_count is None:
        item = await _resolve_item(session, args.get("itemName", ""))
        if item is not None and await inv_ops.find_stowed_instance(session, item.id) is not None:
            return ToolEffect(
                result=(f"The party is already carrying {item.title} — nothing changed. "
                        "Only report an item the player just TOOK; do not restate the pack."),
            )
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

    # Already wearing exactly this, in this slot? Then nothing changed, and
    # saying so is more useful to the model than silently re-writing the slot:
    # a repeated equip is a restatement of the sheet, and it would otherwise
    # record a bogus equipment change that reversal replays forever.
    binding = await party_ops.binding_for(session, char_id)
    current_instance_id = (dict(getattr(binding, "equipment", None) or {})).get(slot)
    if current_instance_id:
        current = await session.get(ItemInstance, current_instance_id)
        if current is not None and current.item_id == item.id:
            return ToolEffect(
                result=(f"{char_name} already has {item.title} equipped in {slot} — "
                        "nothing changed. Do not re-state gear that is already worn."),
            )

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
        # A no-op, not a failure: the requested state is the state already there.
        return ToolEffect(
            result=f"{char_name}'s {slot} slot is already empty — nothing changed.",
        )
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
When your narration results in the party gaining or losing items, or a character equipping or unequipping something, append this block at the very end of your response, AFTER all prose and BEFORE the turn block:

<<<ACTIONS>>>
{
  "addItems": [{ "itemName": "Item Name", "count": 1 }],
  "removeItems": [{ "itemName": "Item Name", "count": 1 }],
  "equip": [{ "characterName": "Tifa", "slot": "rightHand", "itemName": "Comet Wand" }],
  "unequip": [{ "characterName": "Seraphine", "slot": "head" }]
}
<<<END ACTIONS>>>

Rules:
- The scene is NOT in this block. Location, weather and how long the beat took ride the trailing turn block instead (see the OUTPUT PROTOCOL). Never write a day number, a date or a clock time anywhere — the game keeps the calendar.
- Only include the keys that apply. If nothing was gained, lost, equipped or unequipped, do not include the block at all.
- Every entry is a change your prose JUST made. Do not re-report something from an earlier turn, and do not confirm what you can already see in INVENTORY — setting something to what it already is will be discarded. An item merely SEEN (in a chest, held by someone else, or waiting behind an option you are about to offer) has not been taken: change nothing.
- Use the character's first name for characterName.
- Valid equipment slots: head, neck, torsoOver, torsoUnder, leftHand, rightHand, waist, legsOver, legsUnder, feet, accessory1, accessory2.
- Use exact item names as they appear in the world context.
- Only grant items that have been established in the world. Do not invent new items.
- The action block is stripped before displaying your response — the player never sees it."""
