"""The Planner — a foreground, conversational world-builder (Planning mode).

When Planning mode is toggled on, the chat's primary agent becomes the Planner:
its own core instructions and full CRUD over lore, quests, party members, the
player character, the Scenario, and the Narrator's instructions. The player
talks to it directly and it creates/edits many things per turn, then replies
conversationally.

Create/edit tools apply immediately (committed each round). Delete/remove tools
are NOT executed — they are queued and returned to the client, which confirms
them via a dialog before /planner/deletes/apply runs them.

Planner messages live in their own chat thread (ChatMessage.mode == 'planner')
and never enter narration context. See CLAUDE.md > Planning Mode.
"""

import json
import logging
from collections.abc import AsyncGenerator

from sqlalchemy import func, select

from server.ai.narrator_actions import (
    SLOT_COMPATIBILITY,
    _resolve_character,
    _resolve_item,
    tool_equip,
    tool_unequip,
)
from server.ai.openrouter import agent_turn_with_retry, chat_completion_agent_turn, provider_endpoint
from server.ai.prompt_builder import _augment_message, _estimate_tokens, _trim_to_budget
from server.ai.rules import normalize_attributes
from server.ai.scenario import SCENARIO_FIELDS, compose_scenario_content, migrate_legacy_fields, normalize_openings
from server.ai import style
from server.ai.worldbuilder import LORE_CAT_ORDER, LORE_CATS, TASK_STATUSES, _resolve_lore, _resolve_task
from server.db.database import new_session
from server.db.models import (
    CampaignRules,
    ChatMessage,
    LorebookEntry,
    NarratorConfig,
    OpenRouterSettings,
    Task,
)
from server.db import party as party_ops

log = logging.getLogger("wayward.planner")

ITEM_TYPES = ["Equipment", "Tool", "Consumable", "Key Item", "Artifact", "Currency", "Other"]
RARITIES = ["c", "u", "r", "e", "l"]
SLOT_CATEGORIES = list(SLOT_COMPATIBILITY.keys())  # Head, Neck, Torso, Hands, Waist, Legs, Feet, Accessory
EQUIP_SLOTS = [
    "head", "neck", "torsoOver", "torsoUnder", "leftHand", "rightHand",
    "waist", "legsOver", "legsUnder", "feet", "accessory1", "accessory2",
]


PLANNER_GUIDANCE = """You are the Editor: a collaborative world-building assistant. You are NOT the narrator — you do not narrate scenes or play the adventure. Your job is to help the player build and shape their adventure: places, characters, items, monsters, spells, tasks, the party, the player character, the Scenario, and even the Narrator's instructions.

How you work:
- Use your tools to create, edit, and remove world content. You may make several changes in one turn (within reason) — e.g. a region plus a few NPCs plus a task, or a character's full set of gear.
- Prefer updating an existing entry over creating a duplicate; you are given the current world state.
- Pick the right lore category for lore (pillars, world, characters, monsters, spells). For NPCs use 'characters'. Use 'world' for places/locations. Use 'pillars' for foundational RULES of the world/universe (how magic works, laws of nature, societal absolutes) — these are always kept in the narrator's context, so reserve them for load-bearing rules, not ordinary facts.
- WHO is being referred to: the player will usually name someone without saying what they are. Use the current world state to resolve the name. There are three distinct kinds, and only the first two have equipment:
    1. The PLAYER CHARACTER and 2. PARTY MEMBERS — real sheets with equipment slots. Edit them with update_pc / update_member, and give them gear with create_item + equip.
    3. LOREBOOK CHARACTERS (NPCs in lore → characters) — descriptive entries only, with NO equipment system. If asked to give an NPC gear or change their appearance, write it into their lore entry with update_lore. NEVER call equip on a lorebook NPC, and don't invent equipment slots for them.
  If a name isn't a party member or the PC, treat it as a lorebook character (edit its lore) — do not recruit them into the party unless the player clearly asks to.
- ITEMS: always use create_item (NOT create_lore) so the item gets a proper type, slot, and rarity. Choose the type deliberately — 'Equipment' for wearable/wieldable gear, 'Consumable' for potions/food, plus 'Tool', 'Key Item', 'Artifact', 'Other'. For Equipment, set the body slot (Head, Neck, Torso, Hands, Waist, Legs, Feet, Accessory) and a fitting rarity (c=Common is the default for ordinary gear; reserve u/r/e/l for genuinely special items). Give each item a vivid one-line description.
- EQUIPPING — STRICT ORDER: an item must EXIST before it can be equipped. To outfit the PC or a party member, for each piece: (1) create_item first (type Equipment, with a slot), THEN (2) equip it into the precise slot (head, neck, torsoOver, torsoUnder, leftHand, rightHand, waist, legsOver, legsUnder, feet, accessory1, accessory2). Never call equip on an item you have not created — it will fail. Creating an item does NOT equip it; you must call equip as the second step.
- TIMELESS ENTRIES: write every lore/item entry as a permanent world fact, not a note about the current scene or party. Items — describe the item itself, generically (what it is/does), never who currently holds or wears it, and always give it a proper type (and slot for Equipment). World/places — describe the place generically; nothing about the party or what they're doing there. Monsters — the creature in general. Spells — the effect and its limits. Characters (NPCs) — who they are, not the party's momentary interaction with them.
- HONESTY: never tell the player something succeeded if the tool result was an error. If equip says the item doesn't exist, create it and retry; if something can't be done, say so plainly rather than claiming success.
- CONSISTENCY: the Scenario is included in your context — keep new content consistent with it. You can also read the Narrator's instructions (get_narrator_instructions) to match the intended tone, and edit the Scenario, the Narrator's instructions, or the opening narration (set_first_message) when asked.
- READ BEFORE YOU EDIT: your world list shows only NAMES. Before changing an existing lore entry, task, or character, call get_entry first to read its current content, then extend it — don't blindly overwrite facts you haven't seen.
- SENSITIVE OVERWRITES: set_narrator_instructions and set_first_message REPLACE the whole existing text and take effect immediately — only do them when the player clearly asks. set_scenario and set_story_style are PARTIAL updates instead: pass only the field(s) you're changing and omit the rest — omitted fields are left untouched. Call get_scenario / get_story_style first if you need to see the current values before editing one. set_story_style is the right tool when the player asks to change the narration's genre, tone, writing style, verbosity, content rating, perspective, or structure ("make it darker", "write more like Pratchett", "third person"). Always tell the player explicitly in your reply what you changed.
- Deletions are not applied immediately — they are queued for the player to confirm, so feel free to propose them when asked.
- After making changes, reply briefly and conversationally: say what you did and offer sensible next steps ("Forged and equipped Tifa's kit — want the gauntlets bumped to Rare?").
- If the player is just chatting or asking questions, answer normally without calling tools.

Keep entries concise and concrete. Write in the established tone of the world."""

# Injected on the final (forced) round when tools are no longer offered.
PLANNER_FINAL_NUDGE = (
    "You can no longer call tools this turn. Wrap up: reply conversationally about "
    "what you did (and what's left to do), without claiming any change you didn't "
    "already make with a tool."
)


# ── Tool schemas ──────────────────────────────────────────────────

_LORE_CAT_ENUM = sorted(LORE_CATS)


def _story_style_props() -> dict:
    """Build set_story_style's parameters from the live catalog: each field lists
    its valid option ids (as an enum when custom text isn't allowed, else in the
    description); customInstructions is freeform."""
    props: dict = {}
    for f in style.options_payload()["fields"]:
        ids = [o["id"] for o in f["options"]]
        desc = f"{f['label']}. Options: {', '.join(ids)}."
        prop = {"type": "string", "description": desc}
        if f["allowCustom"]:
            prop["description"] += " Or a short custom value of your own."
        else:
            prop["enum"] = ids
        props[f["key"]] = prop
    props["customInstructions"] = {
        "type": "string",
        "description": "Freeform extra narration guidance, appended to the Story Style block.",
    }
    return props


def _fn(name: str, desc: str, props: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name, "description": desc,
            "parameters": {"type": "object", "properties": props, "required": required},
        },
    }


TOOL_SCHEMAS: list[dict] = [
    _fn("create_lore", "Create a lorebook entry (place, character/NPC, item, monster, or spell).",
        {"cat": {"type": "string", "enum": _LORE_CAT_ENUM}, "title": {"type": "string"},
         "content": {"type": "string"}, "keywords": {"type": "array", "items": {"type": "string"}}},
        ["cat", "title", "content"]),
    _fn("update_lore", "Edit an existing lorebook entry, by its exact title.",
        {"title": {"type": "string"}, "content": {"type": "string"},
         "keywords": {"type": "array", "items": {"type": "string"}},
         "cat": {"type": "string", "enum": _LORE_CAT_ENUM}},
        ["title"]),
    _fn("delete_lore", "Remove a lorebook entry (queued for player confirmation), by exact title.",
        {"title": {"type": "string"}}, ["title"]),
    _fn("create_item", "Create an item with its proper type, slot, and rarity (use this for ALL items, not create_lore).",
        {"name": {"type": "string"}, "type": {"type": "string", "enum": ITEM_TYPES},
         "slot": {"type": "string", "enum": SLOT_CATEGORIES, "description": "Body slot for Equipment; omit for non-equipment."},
         "rarity": {"type": "string", "enum": RARITIES, "description": "c=Common u=Uncommon r=Rare e=Epic l=Legendary."},
         "maxStack": {"type": "integer"}, "uses": {"type": "integer"},
         "desc": {"type": "string"}},
        ["name", "type"]),
    _fn("update_item", "Edit an existing item's type/slot/rarity/description, by exact name.",
        {"name": {"type": "string"}, "type": {"type": "string", "enum": ITEM_TYPES},
         "slot": {"type": "string", "enum": SLOT_CATEGORIES}, "rarity": {"type": "string", "enum": RARITIES},
         "maxStack": {"type": "integer"}, "uses": {"type": "integer"}, "desc": {"type": "string"}},
        ["name"]),
    _fn("equip", "Equip an existing Equipment item onto a character in a specific slot.",
        {"characterName": {"type": "string", "description": "Character's first name (PC or party member)."},
         "slot": {"type": "string", "enum": EQUIP_SLOTS}, "itemName": {"type": "string"}},
        ["characterName", "slot", "itemName"]),
    _fn("unequip", "Remove whatever is in a character's equipment slot; it returns to inventory.",
        {"characterName": {"type": "string"}, "slot": {"type": "string", "enum": EQUIP_SLOTS}},
        ["characterName", "slot"]),
    _fn("create_task", "Create a task (a single goal/to-do — big or small).",
        {"text": {"type": "string"}}, ["text"]),
    _fn("update_task", "Edit a task's text or status, matched by its exact current text.",
        {"text": {"type": "string", "description": "The task's current text (to find it)."},
         "newText": {"type": "string", "description": "New text, to reword the task."},
         "status": {"type": "string", "enum": sorted(TASK_STATUSES)}}, ["text"]),
    _fn("delete_task", "Remove a task (queued for confirmation), by exact text.",
        {"text": {"type": "string"}}, ["text"]),
    _fn("create_member", "Add a party member.",
        {"name": {"type": "string"}, "species": {"type": "string"}, "gender": {"type": "string"},
         "age": {"type": "integer"}, "heightCm": {"type": "integer"}, "weightKg": {"type": "integer"},
         "description": {"type": "string"}, "personality": {"type": "string"},
         "likes": {"type": "string"}, "dislikes": {"type": "string"},
         "other": {"type": "string", "description": "Anything that doesn't fit the other fields — quirks, history, relationships."},
         "fieldSkillName": {"type": "string"}, "fieldSkillDescription": {"type": "string"}}, ["name"]),
    _fn("update_member", "Edit a party member's details/field skill, by name. Pass newName to rename.",
        {"name": {"type": "string", "description": "Which member to edit (their current name)."},
         "newName": {"type": "string", "description": "New name, to rename the member."},
         "species": {"type": "string"}, "gender": {"type": "string"},
         "age": {"type": "integer"}, "heightCm": {"type": "integer"}, "weightKg": {"type": "integer"},
         "description": {"type": "string"}, "personality": {"type": "string"},
         "likes": {"type": "string"}, "dislikes": {"type": "string"},
         "other": {"type": "string", "description": "Anything that doesn't fit the other fields — quirks, history, relationships."},
         "fieldSkillName": {"type": "string"}, "fieldSkillDescription": {"type": "string"}}, ["name"]),
    _fn("delete_member", "Remove a party member entirely (queued for confirmation), by name.",
        {"name": {"type": "string"}}, ["name"]),
    _fn("set_in_party", "Bench or re-add a member to the active party, by name.",
        {"name": {"type": "string"}, "inParty": {"type": "boolean"}}, ["name", "inParty"]),
    _fn("update_pc", "Edit the player character's details.",
        {"name": {"type": "string"}, "species": {"type": "string"}, "gender": {"type": "string"},
         "age": {"type": "integer"}, "heightCm": {"type": "integer"}, "weightKg": {"type": "integer"},
         "description": {"type": "string"}, "personality": {"type": "string"},
         "drive": {"type": "string", "description": "What pushes the character forward — their goal, want, or need. Shapes the generated action options."},
         "likes": {"type": "string"}, "dislikes": {"type": "string"}}, []),
    _fn(
        "set_scenario",
        "Edit the Scenario's structured fields — the framing context for the whole adventure. "
        "PARTIAL update: only the fields you provide are changed; fields you omit are left untouched.",
        {
            "setting": {"type": "string", "description": "The core setting/premise."},
            "historyBrief": {"type": "string", "description": "Brief history of the world."},
            "species": {"type": "string", "description": "Notable species/peoples."},
            "geography": {"type": "string", "description": "Geography/regions."},
            "techAndMagic": {"type": "string", "description": "Technology and/or magic systems."},
            "other": {"type": "string", "description": "Anything else that frames the world."},
        },
        [],
    ),
    _fn("get_scenario", "Read the Scenario's current structured fields (setting, historyBrief, species, geography, techAndMagic, other).", {}, []),
    _fn(
        "set_story_style",
        "Edit the campaign's Story Style — the guided narration options composed into the narrator's STORY STYLE block (genre, tone, writing style, verbosity, content limit, perspective, structure, plus custom instructions). "
        "PARTIAL update: only the fields you provide are changed; omit the rest. Pass an empty string to clear a field. Prefer a listed option id; a short custom value is allowed where noted.",
        _story_style_props(),
        [],
    ),
    _fn("get_story_style", "Read the campaign's current Story Style selections (genre, tone, writing style, verbosity, content limit, perspective, structure, custom instructions).", {}, []),
    _fn("set_narrator_instructions", "Replace the Narrator's core system instructions (tone/rules of narration).",
        {"content": {"type": "string"}}, ["content"]),
    _fn("get_narrator_instructions", "Read the Narrator's current core instructions (to keep your edits consistent with them).", {}, []),
    _fn("set_first_message", "Set the opening narration shown before the player's first turn (the campaign's First Message).",
        {"content": {"type": "string"}}, ["content"]),
    _fn("set_first_message_alternates", "Set the ALTERNATE opening narrations (like alternate greetings): the full list of additional openings the player can swipe between at turn 0, besides the primary First Message. Each has its own narration and its own scripted options. Pass the complete list (replaces the existing one); pass [] to clear.",
        {"alternates": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "The opening narration for this alternate."},
                "options": {"type": "array", "items": {"type": "string"}, "description": "Scripted choice options shown with this opening (optional)."},
            },
            "required": ["message"],
        }}}, ["alternates"]),
    _fn("get_world_rules", "Read the campaign's World Rules: party size, currency (name/abbrev/symbol), declared attributes, and tone.", {}, []),
    _fn("set_world_rules", "Update the campaign's World Rules — the world's ruleset knobs. Pass only the field(s) you're changing; others are left untouched. Use this when the player defines their world's currency, stats/attributes, party size, or tone.",
        {
            "partySize": {"type": "integer", "description": "Max active companions (excluding the PC)."},
            "currencyName": {"type": "string", "description": "e.g. 'Gold', 'Credits'."},
            "currencyAbbrev": {"type": "string", "description": "e.g. 'gp'."},
            "currencySymbol": {"type": "string", "description": "e.g. '$'."},
            "tone": {"type": "string", "description": "Tone/rating guidance (grim vs heroic, content limits)."},
            "attributes": {"type": "array", "description": "Declared attribute/stat vocabulary.", "items": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "description": {"type": "string"}},
                "required": ["name"],
            }},
        }, []),
    _fn("list_world", "List the current world: lore by category, tasks, party members, and the PC.", {}, []),
    _fn("get_entry", "Read the full content of a lore entry, task, or member by name.",
        {"name": {"type": "string"}}, ["name"]),
]


def _parse_args(raw: str) -> dict:
    if not raw:
        return {}
    try:
        v = json.loads(raw)
        return v if isinstance(v, dict) else {}
    except json.JSONDecodeError:
        return {}


# ── Context ───────────────────────────────────────────────────────

async def _build_planner_context(session) -> str:
    lore = (await session.execute(select(LorebookEntry))).scalars().all()
    by_cat: dict[str, list[str]] = {}
    for e in lore:
        by_cat.setdefault(e.cat, []).append(e.title + (" [locked]" if e.locked else ""))
    tasks = (await session.execute(select(Task))).scalars().all()
    members = await party_ops.load_party(session)
    pc = await party_ops.load_pc(session)

    lines = ["CURRENT WORLD STATE (reuse exact names; edit rather than duplicate):"]
    for cat in LORE_CAT_ORDER:
        titles = by_cat.get(cat, [])
        lines.append(f"  {cat}: {', '.join(titles) if titles else '(none)'}")
    if tasks:
        lines.append("  tasks: " + ", ".join(f"{t.text} [{t.status}]" for t in tasks))
    else:
        lines.append("  tasks: (none)")
    if members:
        lines.append("  party members: " + ", ".join(
            f"{m.basic_info.get('name', '?')}{'' if m.in_party else ' (benched)'}" for m in members
        ))
    else:
        lines.append("  party members: (none)")
    if pc:
        lines.append(f"  player character: {pc.basic_info.get('name', '(unnamed)')} — {pc.basic_info.get('species', '')}")

    # Always give the Editor the Scenario so anything it creates fits the world.
    scenario = next((e for e in lore if e.title.lower() == "scenario"), None)
    if scenario and (scenario.content or "").strip():
        lines.append("")
        lines.append("SCENARIO (the framing context for this world — keep new content consistent with it):")
        lines.append(scenario.content.strip())
    return "\n".join(lines)


# ── Tool execution ────────────────────────────────────────────────

async def _exec_tool(name: str, args: dict, session) -> tuple[str, dict | None]:
    """Execute one planner tool. Returns (result_text, pending_delete | None).

    Create/edit/read tools act immediately. Delete tools resolve the target and
    return a pending-delete dict instead of executing.
    """
    # ---- Lore ----
    if name == "create_lore":
        cat = args.get("cat")
        title = (args.get("title") or "").strip()
        if cat not in LORE_CATS or not title:
            return "create_lore needs a valid cat and title.", None
        if cat == "items":
            return "Use create_item for items so type/slot/rarity are set correctly.", None
        if await _resolve_lore(session, title):
            return f"'{title}' already exists — use update_lore instead.", None
        session.add(LorebookEntry(title=title, content=args.get("content", ""),
                                  keywords=args.get("keywords") or [], cat=cat))
        return f"Created {cat} lore: {title}.", None

    if name == "update_lore":
        entry = await _resolve_lore(session, (args.get("title") or "").strip())
        if not entry:
            return f"No lore entry named '{args.get('title', '')}'.", None
        if entry.locked and args.get("cat"):
            return f"'{entry.title}' is locked; its category can't change.", None
        if args.get("content") is not None:
            entry.content = args["content"]
        if args.get("keywords") is not None:
            entry.keywords = args["keywords"]
        if args.get("cat") in LORE_CATS and not entry.locked:
            entry.cat = args["cat"]
        return f"Updated lore: {entry.title}.", None

    if name == "delete_lore":
        entry = await _resolve_lore(session, (args.get("title") or "").strip())
        if not entry:
            return f"No lore entry named '{args.get('title', '')}'.", None
        if entry.locked:
            return f"'{entry.title}' is locked and cannot be deleted.", None
        return f"Queued deletion of lore '{entry.title}' for confirmation.", \
            {"kind": "lore", "targetId": entry.id, "label": entry.title}

    # ---- Items ----
    if name == "create_item":
        title = (args.get("name") or "").strip()
        itype = args.get("type")
        if not title or itype not in ITEM_TYPES:
            return "create_item needs a name and a valid type.", None
        if await _resolve_item(session, title):
            return f"Item '{title}' already exists — use update_item.", None
        slot = args.get("slot") if args.get("slot") in SLOT_CATEGORIES else None
        rarity = args.get("rarity") if args.get("rarity") in RARITIES else "c"
        session.add(LorebookEntry(
            title=title, content=args.get("desc", ""), cat="items",
            item_type=itype, slot=slot, rarity=rarity,
            max_stack=int(args.get("maxStack", 1) or 1), uses=args.get("uses"),
        ))
        return f"Created item: {title} ({itype}{', ' + slot if slot else ''}, rarity {rarity}).", None

    if name == "update_item":
        item = await _resolve_item(session, (args.get("name") or "").strip())
        if not item:
            return f"No item named '{args.get('name', '')}'.", None
        if args.get("type") in ITEM_TYPES:
            item.item_type = args["type"]
        if args.get("slot") in SLOT_CATEGORIES:
            item.slot = args["slot"]
        if args.get("rarity") in RARITIES:
            item.rarity = args["rarity"]
        if args.get("maxStack") is not None:
            item.max_stack = int(args["maxStack"])
        if args.get("uses") is not None:
            item.uses = args["uses"]
        if args.get("desc") is not None:
            item.content = args["desc"]
        return f"Updated item: {item.title}.", None

    if name == "equip":
        # Guard the two common Editor mistakes before delegating: (1) equipping a
        # lorebook NPC (only the PC and party members have gear), and (2) equipping
        # an item that hasn't been created yet (must create_item first).
        char_name = (args.get("characterName") or "").strip()
        character, _ = await _resolve_character(session, char_name)
        if character is None:
            npc = await _resolve_lore(session, char_name)
            if npc is not None and npc.cat == "characters":
                return (f"'{npc.title}' is a lorebook character (an NPC) — only the player "
                        f"character and party members have equipment. Don't equip them; "
                        f"describe their gear in their lore entry with update_lore instead."), None
            return (f"No player character or party member named '{char_name}'. "
                    f"If they're a lorebook NPC, edit their lore entry; if they should join "
                    f"the party, create_member first."), None
        item_name = (args.get("itemName") or "").strip()
        if not await _resolve_item(session, item_name):
            return (f"No item named '{item_name}' exists yet — you must create_item first "
                    f"(type Equipment, with a slot), THEN equip. Do NOT report it as equipped."), None
        effect = await tool_equip(args, session)
        return effect.result, None

    if name == "unequip":
        effect = await tool_unequip(args, session)
        return effect.result, None

    # ---- Tasks ----
    if name == "create_task":
        text = (args.get("text") or "").strip()
        if not text or await _resolve_task(session, text):
            return f"Task '{text}' is empty or already exists.", None
        max_order = (await session.execute(
            select(func.coalesce(func.max(Task.sort_order), -1)))).scalar()
        session.add(Task(text=text, status="active", sort_order=(max_order or 0) + 1))
        return f"Created task: {text}.", None

    if name == "update_task":
        task = await _resolve_task(session, (args.get("text") or "").strip())
        if not task:
            return f"No task matching '{args.get('text', '')}'.", None
        if args.get("newText"):
            task.text = args["newText"]
        if args.get("status") in TASK_STATUSES:
            task.status = args["status"]
        return f"Updated task: {task.text}.", None

    if name == "delete_task":
        task = await _resolve_task(session, (args.get("text") or "").strip())
        if not task:
            return f"No task matching '{args.get('text', '')}'.", None
        return f"Queued deletion of task '{task.text}' for confirmation.", \
            {"kind": "task", "targetId": task.id, "label": task.text[:40]}

    # ---- Members ----
    if name == "create_member":
        mname = (args.get("name") or "").strip()
        if not mname:
            return "Member name is required.", None
        existing, _ = await _resolve_character(session, mname)
        if existing is not None:
            return f"'{mname}' already exists — use update_member.", None
        await party_ops.add_member(
            session,
            basic_info={"name": mname, "species": args.get("species", ""),
                        "description": args.get("description", ""), "personality": args.get("personality", ""),
                        "gender": args.get("gender", ""), "age": args.get("age", 0) or 0,
                        "heightCm": args.get("heightCm", 0) or 0, "weightKg": args.get("weightKg", 0) or 0,
                        "likes": args.get("likes", ""), "dislikes": args.get("dislikes", ""),
                        "other": args.get("other", "")},
            field_skill={"name": args.get("fieldSkillName", ""), "description": args.get("fieldSkillDescription", "")},
        )
        return f"Created party member: {mname}.", None

    if name in ("update_member", "delete_member", "set_in_party"):
        member, _ = await _resolve_character(session, (args.get("name") or "").strip())
        if member is None or member.role != "member":
            return f"No party member named '{args.get('name', '')}'.", None
        if name == "update_member":
            bi = dict(member.basic_info)
            if args.get("newName"):
                bi["name"] = args["newName"]
            for k in ("species", "gender", "age", "heightCm", "weightKg",
                      "description", "personality", "likes", "dislikes", "other"):
                if args.get(k) is not None:
                    bi[k] = args[k]
            fs = dict(member.field_skill or {})
            if args.get("fieldSkillName") is not None:
                fs["name"] = args["fieldSkillName"]
            if args.get("fieldSkillDescription") is not None:
                fs["description"] = args["fieldSkillDescription"]
            await party_ops.update_member_identity(session, member.id, bi, fs)
            return f"Updated member: {bi.get('name')}.", None
        if name == "set_in_party":
            await party_ops.set_in_party(session, member.id, bool(args.get("inParty")))
            return f"{member.basic_info.get('name')} is now {'in the party' if args.get('inParty') else 'benched'}.", None
        return f"Queued deletion of member '{member.basic_info.get('name')}' for confirmation.", \
            {"kind": "member", "targetId": member.id, "label": member.basic_info.get("name", "?")}

    # ---- Player character ----
    if name == "update_pc":
        pc = await party_ops.load_pc(session)
        if not pc:
            return "No player character exists.", None
        bi = dict(pc.basic_info)
        for k in ("name", "species", "gender", "age", "heightCm", "weightKg",
                  "description", "personality", "drive", "likes", "dislikes"):
            if args.get(k) is not None:
                bi[k] = args[k]
        await party_ops.set_pc_identity(session, bi)
        return f"Updated the player character ({bi.get('name', '')}).", None

    # ---- Scenario / Narrator ----
    if name == "set_scenario":
        scn = (await session.execute(
            select(LorebookEntry).where(func.lower(LorebookEntry.title) == "scenario"))).scalars().first()
        if not scn:
            scn = LorebookEntry(title="Scenario", cat="world", permanent=True, locked=True)
            session.add(scn)
        fields = dict(scn.scenario_fields or {})
        changed = []
        for key, _label in SCENARIO_FIELDS:
            if args.get(key) is not None:
                fields[key] = args[key]
                changed.append(key)
        if not changed:
            return "No Scenario fields were provided to update.", None
        scn.scenario_fields = fields
        scn.content = compose_scenario_content(fields)
        return f"Updated the Scenario ({', '.join(changed)}).", None

    if name == "get_scenario":
        scn = (await session.execute(
            select(LorebookEntry).where(func.lower(LorebookEntry.title) == "scenario"))).scalars().first()
        if not scn:
            return "(no Scenario set)", None
        fields = migrate_legacy_fields(scn.scenario_fields, scn.content)
        if fields != (scn.scenario_fields or {}):
            scn.scenario_fields = fields  # one-time migration; persisted by the outer per-round commit
        lines = [f"{label}: {fields.get(key) or '(empty)'}" for key, label in SCENARIO_FIELDS]
        return "\n".join(lines), None

    if name == "set_story_style":
        cfg = (await session.execute(select(NarratorConfig))).scalars().first()
        if not cfg:
            cfg = NarratorConfig()
            session.add(cfg)
        updates = style.from_wire(args)
        if not updates:
            return "No Story Style fields were provided to update.", None
        merged = style.normalize_style_fields(cfg.style_fields)
        merged.update(updates)
        cfg.style_fields = style.normalize_style_fields(merged) or None
        return f"Updated the Story Style ({', '.join(updates.keys())}).", None

    if name == "get_story_style":
        cfg = (await session.execute(select(NarratorConfig))).scalars().first()
        wire = style.to_wire(getattr(cfg, "style_fields", None) if cfg else None)
        return "\n".join(f"{k}: {v or '(empty)'}" for k, v in wire.items()), None

    if name == "set_narrator_instructions":
        cfg = (await session.execute(select(NarratorConfig))).scalars().first()
        if not cfg:
            cfg = NarratorConfig()
            session.add(cfg)
        cfg.instructions = args.get("content", "")
        return "Updated the Narrator's instructions.", None

    if name == "get_narrator_instructions":
        cfg = (await session.execute(select(NarratorConfig))).scalars().first()
        return (cfg.instructions or "(using the built-in default)") if cfg else "(none)", None

    if name == "set_first_message":
        cfg = (await session.execute(select(NarratorConfig))).scalars().first()
        if not cfg:
            cfg = NarratorConfig()
            session.add(cfg)
        cfg.first_message = args.get("content", "")
        return "Set the opening narration (First Message).", None

    if name == "set_first_message_alternates":
        cfg = (await session.execute(select(NarratorConfig))).scalars().first()
        if not cfg:
            cfg = NarratorConfig()
            session.add(cfg)
        alts = normalize_openings(args.get("alternates"))
        cfg.first_message_alternates = alts or None
        return f"Set {len(alts)} alternate opening(s).", None

    if name == "get_world_rules":
        r = (await session.execute(select(CampaignRules))).scalars().first()
        if not r:
            return "Party size 3; currency Gold (gp); no attributes; no tone set.", None
        attrs = normalize_attributes(getattr(r, "attributes", None))
        attr_str = ", ".join(a["name"] for a in attrs) if attrs else "none"
        return (f"Party size {r.party_size}; currency {r.currency_name} "
                f"({r.currency_abbrev}{(' ' + r.currency_symbol) if r.currency_symbol else ''}); "
                f"attributes: {attr_str}; tone: {r.tone or '(none)'}."), None

    if name == "set_world_rules":
        r = (await session.execute(select(CampaignRules))).scalars().first()
        if not r:
            r = CampaignRules(id=1)
            session.add(r)
        if args.get("partySize") is not None:
            r.party_size = max(0, min(int(args["partySize"]), 20))
        if args.get("currencyName") is not None:
            r.currency_name = str(args["currencyName"]).strip()
        if args.get("currencyAbbrev") is not None:
            r.currency_abbrev = str(args["currencyAbbrev"]).strip()
        if args.get("currencySymbol") is not None:
            r.currency_symbol = str(args["currencySymbol"]).strip()
        if args.get("tone") is not None:
            r.tone = str(args["tone"]).strip()
        if args.get("attributes") is not None:
            r.attributes = normalize_attributes(args["attributes"]) or None
        return "Updated the World Rules.", None

    # ---- Read ----
    if name == "list_world":
        return await _build_planner_context(session), None

    if name == "get_entry":
        q = (args.get("name") or "").strip()
        entry = await _resolve_lore(session, q)
        if entry:
            return json.dumps({"title": entry.title, "cat": entry.cat, "content": entry.content}, ensure_ascii=False), None
        task = await _resolve_task(session, q)
        if task:
            return json.dumps({"task": task.text, "status": task.status, "notes": task.notes},
                              ensure_ascii=False), None
        character, _ = await _resolve_character(session, q)
        if character is not None:
            equipped = {}
            for slot, item_id in (character.equipment or {}).items():
                if not item_id:
                    continue
                it = await session.get(LorebookEntry, item_id)
                equipped[slot] = it.title if it else item_id
            return json.dumps({
                "name": character.basic_info.get("name"), "info": character.basic_info,
                "fieldSkill": getattr(character, "field_skill", {}),
                "equipped": equipped,
                "emptySlots": [s for s in EQUIP_SLOTS if not (character.equipment or {}).get(s)],
            }, ensure_ascii=False), None
        return f"Nothing named '{q}' found.", None

    return f"Unknown tool '{name}'.", None


# ── Loop ──────────────────────────────────────────────────────────

async def run_planner_agent(turn_number: int) -> AsyncGenerator[dict, None]:
    """Drive the Planner for one planning turn.

    Yields {"type":"content","text"}, {"type":"tool","name","result"}, and a
    terminal {"type":"final","content","pendingDeletes"}.
    """
    async with new_session() as session:
        settings = (await session.execute(select(OpenRouterSettings))).scalars().first()
        narrator = (await session.execute(select(NarratorConfig))).scalars().first()
        instructions = (getattr(narrator, "planner_instructions", "") or PLANNER_GUIDANCE) if narrator else PLANNER_GUIDANCE
        world = await _build_planner_context(session)

        history = (await session.execute(
            select(ChatMessage).where(ChatMessage.mode == "planner").order_by(ChatMessage.id)
        )).scalars().all()

        sys_msgs = [
            {"role": "system", "content": instructions},
            {"role": "system", "content": world},
        ]
        # Trim oldest planner history to the context budget — a long Edit-Mode
        # session would otherwise grow unbounded and eventually overflow context.
        # (_augment_message folds an attached image's vision description in.)
        hist_msgs = [{"role": m.role, "content": _augment_message(m)} for m in history]
        max_ctx = settings.max_context_tokens if settings else 128000
        max_resp = settings.max_tokens_response if settings else 1000
        budget = int((max_ctx - max_resp) * 0.9) - _estimate_tokens(sys_msgs) - 200
        hist_msgs = _trim_to_budget(hist_msgs, budget)
        messages: list[dict] = sys_msgs + hist_msgs

        max_rounds = max(1, (settings.max_tool_rounds if settings else 6) or 6)
        pending_deletes: list[dict] = []
        # Accumulate the Editor's prose across every round so a multi-step reply
        # (e.g. "let me check… [acts] …done") is preserved in the chat log as one
        # growing message, rather than each round replacing the last.
        content_parts: list[str] = []
        tool_results: list[str] = []  # for an empty-reply fallback

        base_url, api_key, main_model = provider_endpoint(settings)
        log.info("EDITOR REQUEST turn=%s | model=%s", turn_number, main_model or "?")

        for round_idx in range(max_rounds):
            offer_tools = round_idx < max_rounds - 1
            if not offer_tools and max_rounds > 1:
                messages.append({"role": "system", "content": PLANNER_FINAL_NUDGE})
            result = None
            _round_started = False

            def _make_call(_offer=offer_tools):
                return chat_completion_agent_turn(
                    api_key=api_key, model_id=main_model, base_url=base_url, messages=messages,
                    temperature=settings.temperature, max_tokens=settings.max_tokens_response,
                    tools=TOOL_SCHEMAS if _offer else None,
                    top_p=settings.top_p, min_p=settings.min_p, top_k=settings.top_k,
                    frequency_penalty=settings.frequency_penalty, presence_penalty=settings.presence_penalty,
                    repetition_penalty=settings.repetition_penalty,
                )

            # Auto-retry on error/safety block (configurable; per-call, so the
            # Editor's already-committed tool actions are never re-run).
            async for ev in agent_turn_with_retry(
                _make_call, getattr(settings, "auto_retry_count", 0) or 0,
                log_ctx=f" editor turn={turn_number} round={round_idx}",
            ):
                if ev["type"] == "content":
                    # Separate this round's prose from the previous round's.
                    if content_parts and not _round_started:
                        yield {"type": "content", "text": "\n\n"}
                    _round_started = True
                    yield {"type": "content", "text": ev["text"]}
                elif ev["type"] == "result":
                    result = ev
                elif ev["type"] in ("discard", "retry"):
                    yield ev

            tool_calls = (result or {}).get("tool_calls") or []
            content = ((result or {}).get("content") or "").strip()
            if content:
                content_parts.append(content)

            if not tool_calls:
                break

            messages.append({
                "role": "assistant", "content": content or None,
                "tool_calls": [{"id": tc["id"], "type": "function",
                                "function": {"name": tc["name"], "arguments": tc["arguments"]}}
                               for tc in tool_calls],
            })
            for tc in tool_calls:
                args = _parse_args(tc["arguments"])
                text, pending = await _exec_tool(tc["name"], args, session)
                if pending:
                    pending_deletes.append(pending)
                tool_results.append(text)
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": text})
                log.info("EDITOR TOOL turn=%s %s -> %s", turn_number, tc["name"], text)
                yield {"type": "tool", "name": tc["name"], "result": text}
            await session.commit()

        # The model occasionally calls tools but never writes a closing line —
        # never leave an empty reply. Summarise what was done (or prompt the user).
        final_content = "\n\n".join(content_parts).strip()
        if not final_content:
            if tool_results:
                final_content = "Done:\n" + "\n".join(f"- {t}" for t in tool_results)
            else:
                final_content = (
                    "I didn't make any changes that turn. Tell me what you'd like me to "
                    "build or edit — a place, character, item, task, or party member."
                )
            yield {"type": "content", "text": final_content}

    yield {"type": "final", "content": final_content, "pendingDeletes": pending_deletes}
