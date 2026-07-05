"""Campaign templates — the starting content applied when a new campaign is
created. Each template is a plain JSON file under ``server/templates/``; the
applier below reads one and populates the (already-attached) campaign +
adventure DBs with its narrator config, scenario, lore, items, PC, party, and
inventory.

Item references are keyed: an ``items`` entry declares a ``key``, and the PC /
party ``equipment`` maps (fine slot → key) and ``inventory`` entries reference
that same key. Keys are resolved to freshly-minted catalog UUIDs at apply time.
Equipment is written as catalog ids + inventory as ``InventoryStack`` rows, then
``migrate_to_item_instances`` converts both into non-stacking ItemInstances —
exactly mirroring the demo seed path.

Universal defaults (feedback): the Narrator Instructions, Spotlight Rule, and
Editor Instructions are ALWAYS stored non-empty — a template may override them,
otherwise the built-in defaults are used.
"""

import json
import logging
import uuid
from pathlib import Path

from server.ai.narrator_actions import ACTION_INSTRUCTION
from server.ai.planner import PLANNER_GUIDANCE
from server.ai.scenario import compose_scenario_content
from server.ai.spotlight import DEFAULT_SPOTLIGHT_RULE
from server.db.database import migrate_characters_to_files, migrate_to_item_instances, new_session
from server.db.models import (
    InventoryStack,
    LorebookConfig,
    LorebookEntry,
    NarratorConfig,
    PartyMember,
    PlayerCharacter,
    StorySummary,
)

log = logging.getLogger("wayward.templates")

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

# Built-in default the Narrator Instructions fall back to (never left empty).
DEFAULT_NARRATOR_INSTRUCTIONS = (
    "You are the Narrator of an ongoing adventure. Describe the world vividly "
    "in second person, addressing the player character directly. Keep prose concise "
    "— two to four paragraphs per beat. Advance the scene with each response: "
    "describe what happens, what the player sees or feels, and leave a natural "
    "opening for their next action. Never speak for the player character or decide "
    "their actions. When voicing a party member, use a dialogue tag with their name "
    "and keep it to one or two sentences in character. "
    "Characters are wearing only what they have equipped — if an equipment slot is "
    "empty, they have nothing in that slot. Do not invent clothing or gear that is "
    "not listed in their equipment."
)

EMPTY_EQUIPMENT = {
    "head": None, "neck": None, "torsoOver": None, "torsoUnder": None,
    "leftHand": None, "rightHand": None, "waist": None,
    "legsOver": None, "legsUnder": None, "feet": None,
    "accessory1": None, "accessory2": None,
}

_DEFAULT_INJECTION_ORDER = {
    "world": 0, "characters": 10, "items": 20, "monsters": 30, "spells": 40,
}
_DEFAULT_INJECTION_POSITION = {
    "world": "top", "characters": "top", "items": "top",
    "monsters": "top", "spells": "top",
}


def list_templates() -> list[dict]:
    """Every template on disk, as ``{id, name, description}`` for the UI picker.
    Empty first, then alphabetical."""
    out: list[dict] = []
    for path in TEMPLATES_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            log.warning("Skipping unreadable template %s", path.name)
            continue
        out.append({
            "id": path.stem,
            "name": data.get("name") or path.stem.title(),
            "description": data.get("description", ""),
        })
    out.sort(key=lambda t: (t["id"] != "empty", t["name"].lower()))
    return out


def _load(name: str) -> dict:
    path = TEMPLATES_DIR / f"{name}.json"
    if not path.exists():
        path = TEMPLATES_DIR / "empty.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        log.exception("Failed to parse template %s", name)
        return {}


def _equipment_from(spec: dict | None, key_to_id: dict[str, str]) -> dict:
    equip = dict(EMPTY_EQUIPMENT)
    for slot, key in (spec or {}).items():
        if slot in equip and key in key_to_id:
            equip[slot] = key_to_id[key]
    return equip


async def apply_template(name: str) -> bool:
    """Populate the active campaign/adventure DBs from a template. Returns True
    if the template supplied a player character (so the caller can skip adding a
    blank one)."""
    tpl = _load(name)

    async with new_session() as s:
        # --- Catalog items (campaign scope) → map key -> new uuid ---
        key_to_id: dict[str, str] = {}
        for it in tpl.get("items", []):
            iid = str(uuid.uuid4())
            key_to_id[it["key"]] = iid
            s.add(LorebookEntry(
                id=iid, cat="items", title=it["name"],
                content=it.get("desc", ""), keywords=[], enabled=True,
                permanent=False, locked=False,
                item_type=it.get("type", "Equipment"),
                slot=it.get("slot"), max_stack=it.get("maxStack", 1),
                uses=it.get("uses"), rarity=it.get("rarity", "c"),
            ))

        # --- Freeform lore (campaign scope) ---
        for lo in tpl.get("lore", []):
            s.add(LorebookEntry(
                id=str(uuid.uuid4()), cat=lo.get("cat", "world"),
                title=lo["title"], content=lo.get("content", ""),
                keywords=lo.get("keywords", []), enabled=True,
                permanent=bool(lo.get("permanent", False)), locked=False,
            ))

        # --- Scenario (the locked, permanent World entry) ---
        scn = tpl.get("scenario") or {}
        s.add(LorebookEntry(
            id=str(uuid.uuid4()), cat="world", title="Scenario",
            content=compose_scenario_content(scn), keywords=[], enabled=True,
            permanent=True, locked=True, scenario_fields=scn,
        ))

        # --- Narrator config (universal non-empty defaults) ---
        nar = tpl.get("narrator") or {}
        s.add(NarratorConfig(
            instructions=nar.get("instructions") or DEFAULT_NARRATOR_INSTRUCTIONS,
            action_instruction=ACTION_INSTRUCTION,
            spotlight_rule=nar.get("spotlightRule") or DEFAULT_SPOTLIGHT_RULE,
            planner_instructions=nar.get("plannerInstructions") or PLANNER_GUIDANCE,
            post_history_instructions=nar.get("postHistoryInstructions", ""),
            first_message=nar.get("firstMessage", ""),
        ))

        # --- Lorebook injection config (campaign scope) ---
        s.add(LorebookConfig(
            injection_order=dict(_DEFAULT_INJECTION_ORDER),
            injection_position=dict(_DEFAULT_INJECTION_POSITION),
        ))

        # --- Story summary (adventure scope) ---
        s.add(StorySummary(content="", summary_up_to_turn=0))

        # --- Player character (adventure scope) ---
        pc_t = tpl.get("playerCharacter")
        if pc_t:
            s.add(PlayerCharacter(
                basic_info=pc_t.get("basicInfo", {}),
                equipment=_equipment_from(pc_t.get("equipment"), key_to_id),
            ))

        # --- Party members (adventure scope) ---
        for pm in tpl.get("partyMembers", []):
            s.add(PartyMember(
                basic_info=pm.get("basicInfo", {}),
                field_skill=pm.get("fieldSkill") or {},
                equipment=_equipment_from(pm.get("equipment"), key_to_id),
                in_party=True,
            ))

        # --- Starting inventory (adventure scope) ---
        for inv in tpl.get("inventory", []):
            key = inv.get("key")
            if key in key_to_id:
                s.add(InventoryStack(item_id=key_to_id[key], count=int(inv.get("count", 1))))

        await s.commit()

    # Convert catalog-id equipment + inventory stacks into item instances, then
    # move the PC/party rows into portable character files + adventure bindings.
    await migrate_to_item_instances()
    await migrate_characters_to_files()
    return bool(tpl.get("playerCharacter"))
