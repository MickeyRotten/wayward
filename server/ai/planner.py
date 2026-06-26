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
from server.ai.openrouter import chat_completion_agent_turn
from server.ai.worldbuilder import LORE_CATS, QUEST_STATUSES, _resolve_lore, _resolve_quest
from server.db.database import new_session
from server.db.models import (
    ChatMessage,
    LorebookEntry,
    NarratorConfig,
    OpenRouterSettings,
    PartyMember,
    PlayerCharacter,
    Quest,
    QuestObjective,
)

log = logging.getLogger("wayward.planner")

ITEM_TYPES = ["Equipment", "Tool", "Consumable", "Key Item", "Artifact", "Other"]
RARITIES = ["c", "u", "r", "e", "l"]
SLOT_CATEGORIES = list(SLOT_COMPATIBILITY.keys())  # Head, Neck, Torso, Hands, Waist, Legs, Feet, Accessory
EQUIP_SLOTS = [
    "head", "neck", "torsoOver", "torsoUnder", "leftHand", "rightHand",
    "waist", "legsOver", "legsUnder", "feet", "accessory1", "accessory2",
]


PLANNER_GUIDANCE = """You are the Editor: a collaborative world-building assistant. You are NOT the narrator — you do not narrate scenes or play the adventure. Your job is to help the player build and shape their adventure: places, characters, items, monsters, spells, quests, the party, the player character, the Scenario, and even the Narrator's instructions.

How you work:
- Use your tools to create, edit, and remove world content. You may make several changes in one turn (within reason) — e.g. a region plus a few NPCs plus a quest, or a character's full set of gear.
- Prefer updating an existing entry over creating a duplicate; you are given the current world state.
- Pick the right lore category for lore (world, characters, monsters, spells). For NPCs use 'characters'.
- ITEMS: always use create_item (NOT create_lore) so the item gets a proper type, slot, and rarity. Choose the type deliberately — 'Equipment' for wearable/wieldable gear, 'Consumable' for potions/food, plus 'Tool', 'Key Item', 'Artifact', 'Other'. For Equipment, set the body slot (Head, Neck, Torso, Hands, Waist, Legs, Feet, Accessory) and a fitting rarity (c=Common is the default for ordinary gear; reserve u/r/e/l for genuinely special items). Give each item a vivid one-line description.
- EQUIPPING: when you outfit a character, actually equip the gear with the equip tool, using the precise equipment slot (head, neck, torsoOver, torsoUnder, leftHand, rightHand, waist, legsOver, legsUnder, feet, accessory1, accessory2). Creating an item does NOT equip it — call equip too.
- Deletions are not applied immediately — they are queued for the player to confirm, so feel free to propose them when asked.
- After making changes, reply briefly and conversationally: say what you did and offer sensible next steps ("Forged and equipped Tifa's kit — want the gauntlets bumped to Rare?").
- If the player is just chatting or asking questions, answer normally without calling tools.

Keep entries concise and concrete. Write in the established tone of the world."""


# ── Tool schemas ──────────────────────────────────────────────────

_LORE_CAT_ENUM = sorted(LORE_CATS)


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
    _fn("create_quest", "Create a quest with optional objectives.",
        {"title": {"type": "string"}, "desc": {"type": "string"},
         "objectives": {"type": "array", "items": {"type": "string"}}}, ["title"]),
    _fn("update_quest", "Edit a quest's description or status, by exact title.",
        {"title": {"type": "string"}, "desc": {"type": "string"},
         "status": {"type": "string", "enum": sorted(QUEST_STATUSES)}}, ["title"]),
    _fn("delete_quest", "Remove a quest (queued for confirmation), by exact title.",
        {"title": {"type": "string"}}, ["title"]),
    _fn("add_objective", "Add an objective to a quest, by quest title.",
        {"questTitle": {"type": "string"}, "text": {"type": "string"}}, ["questTitle", "text"]),
    _fn("update_objective", "Edit/complete an objective, matched by quest title + objective text.",
        {"questTitle": {"type": "string"}, "objectiveText": {"type": "string"},
         "done": {"type": "boolean"}, "newText": {"type": "string"}}, ["questTitle", "objectiveText"]),
    _fn("delete_objective", "Remove an objective (queued for confirmation), by quest title + text.",
        {"questTitle": {"type": "string"}, "objectiveText": {"type": "string"}}, ["questTitle", "objectiveText"]),
    _fn("create_member", "Add a party member.",
        {"name": {"type": "string"}, "species": {"type": "string"}, "description": {"type": "string"},
         "personality": {"type": "string"}, "fieldSkillName": {"type": "string"},
         "fieldSkillDescription": {"type": "string"}}, ["name"]),
    _fn("update_member", "Edit a party member's details/field skill, by name.",
        {"name": {"type": "string"}, "species": {"type": "string"}, "description": {"type": "string"},
         "personality": {"type": "string"}, "fieldSkillName": {"type": "string"},
         "fieldSkillDescription": {"type": "string"}}, ["name"]),
    _fn("delete_member", "Remove a party member entirely (queued for confirmation), by name.",
        {"name": {"type": "string"}}, ["name"]),
    _fn("set_in_party", "Bench or re-add a member to the active party, by name.",
        {"name": {"type": "string"}, "inParty": {"type": "boolean"}}, ["name", "inParty"]),
    _fn("update_pc", "Edit the player character's details.",
        {"name": {"type": "string"}, "species": {"type": "string"}, "description": {"type": "string"},
         "personality": {"type": "string"}, "gender": {"type": "string"}}, []),
    _fn("set_scenario", "Rewrite the Scenario — the framing context for the whole adventure.",
        {"content": {"type": "string"}}, ["content"]),
    _fn("set_narrator_instructions", "Replace the Narrator's core system instructions (tone/rules of narration).",
        {"content": {"type": "string"}}, ["content"]),
    _fn("list_world", "List the current world: lore by category, quests, party members, and the PC.", {}, []),
    _fn("get_entry", "Read the full content of a lore entry, quest, or member by name.",
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
    quests = (await session.execute(select(Quest))).scalars().all()
    members = (await session.execute(select(PartyMember))).scalars().all()
    pc = (await session.execute(select(PlayerCharacter))).scalars().first()

    lines = ["CURRENT WORLD STATE (reuse exact names; edit rather than duplicate):"]
    for cat in ("world", "characters", "items", "monsters", "spells"):
        titles = by_cat.get(cat, [])
        lines.append(f"  {cat}: {', '.join(titles) if titles else '(none)'}")
    if quests:
        lines.append("  quests: " + ", ".join(f"{q.title} [{q.status}]" for q in quests))
    else:
        lines.append("  quests: (none)")
    if members:
        lines.append("  party members: " + ", ".join(
            f"{m.basic_info.get('name', '?')}{'' if m.in_party else ' (benched)'}" for m in members
        ))
    else:
        lines.append("  party members: (none)")
    if pc:
        lines.append(f"  player character: {pc.basic_info.get('name', '(unnamed)')} — {pc.basic_info.get('species', '')}")
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
        effect = await tool_equip(args, session)
        return effect.result, None

    if name == "unequip":
        effect = await tool_unequip(args, session)
        return effect.result, None

    # ---- Quests ----
    if name == "create_quest":
        title = (args.get("title") or "").strip()
        if not title or await _resolve_quest(session, title):
            return f"Quest '{title}' is empty or already exists.", None
        quest = Quest(title=title, desc=args.get("desc", ""), status="active")
        session.add(quest)
        await session.flush()
        for i, text in enumerate(args.get("objectives", []) or []):
            session.add(QuestObjective(quest_id=quest.id, text=text, sort_order=i))
        return f"Created quest: {title}.", None

    if name == "update_quest":
        quest = await _resolve_quest(session, (args.get("title") or "").strip())
        if not quest:
            return f"No quest named '{args.get('title', '')}'.", None
        if args.get("desc") is not None:
            quest.desc = args["desc"]
        if args.get("status") in QUEST_STATUSES:
            quest.status = args["status"]
        return f"Updated quest: {quest.title}.", None

    if name == "delete_quest":
        quest = await _resolve_quest(session, (args.get("title") or "").strip())
        if not quest:
            return f"No quest named '{args.get('title', '')}'.", None
        return f"Queued deletion of quest '{quest.title}' for confirmation.", \
            {"kind": "quest", "targetId": quest.id, "label": quest.title}

    if name in ("add_objective", "update_objective", "delete_objective"):
        quest = await _resolve_quest(session, (args.get("questTitle") or "").strip())
        if not quest:
            return f"No quest named '{args.get('questTitle', '')}'.", None
        if name == "add_objective":
            text = (args.get("text") or "").strip()
            if not text:
                return "Objective text is empty.", None
            max_order = (await session.execute(
                select(func.coalesce(func.max(QuestObjective.sort_order), -1))
                .where(QuestObjective.quest_id == quest.id))).scalar()
            session.add(QuestObjective(quest_id=quest.id, text=text, sort_order=(max_order or 0) + 1))
            return f"Added objective to {quest.title}.", None
        # find the objective by text
        objs = (await session.execute(
            select(QuestObjective).where(QuestObjective.quest_id == quest.id))).scalars().all()
        target = (args.get("objectiveText") or "").strip().lower()
        match = next((o for o in objs if o.text.lower() == target), None)
        if not match:
            return f"No objective matching '{args.get('objectiveText', '')}' on {quest.title}.", None
        if name == "update_objective":
            if args.get("done") is not None:
                match.done = bool(args["done"])
            if args.get("newText"):
                match.text = args["newText"]
            return f"Updated objective on {quest.title}.", None
        return f"Queued deletion of an objective on '{quest.title}' for confirmation.", \
            {"kind": "quest_objective", "targetId": match.id, "label": f"{quest.title}: {match.text[:40]}"}

    # ---- Members ----
    if name == "create_member":
        mname = (args.get("name") or "").strip()
        if not mname:
            return "Member name is required.", None
        existing, _ = await _resolve_character(session, mname)
        if existing is not None:
            return f"'{mname}' already exists — use update_member.", None
        session.add(PartyMember(
            basic_info={"name": mname, "species": args.get("species", ""),
                        "description": args.get("description", ""), "personality": args.get("personality", ""),
                        "gender": "", "age": 0, "heightCm": 0, "weightKg": 0,
                        "portrait": "", "likes": "", "dislikes": ""},
            equipment={},
            field_skill={"name": args.get("fieldSkillName", ""), "description": args.get("fieldSkillDescription", "")},
        ))
        return f"Created party member: {mname}.", None

    if name in ("update_member", "delete_member", "set_in_party"):
        member, _ = await _resolve_character(session, (args.get("name") or "").strip())
        if member is None or not isinstance(member, PartyMember):
            return f"No party member named '{args.get('name', '')}'.", None
        if name == "update_member":
            bi = dict(member.basic_info)
            for k in ("species", "description", "personality"):
                if args.get(k) is not None:
                    bi[k] = args[k]
            member.basic_info = bi
            fs = dict(member.field_skill or {})
            if args.get("fieldSkillName") is not None:
                fs["name"] = args["fieldSkillName"]
            if args.get("fieldSkillDescription") is not None:
                fs["description"] = args["fieldSkillDescription"]
            member.field_skill = fs
            return f"Updated member: {member.basic_info.get('name')}.", None
        if name == "set_in_party":
            member.in_party = bool(args.get("inParty"))
            return f"{member.basic_info.get('name')} is now {'in the party' if member.in_party else 'benched'}.", None
        return f"Queued deletion of member '{member.basic_info.get('name')}' for confirmation.", \
            {"kind": "member", "targetId": member.id, "label": member.basic_info.get("name", "?")}

    # ---- Player character ----
    if name == "update_pc":
        pc = (await session.execute(select(PlayerCharacter))).scalars().first()
        if not pc:
            return "No player character exists.", None
        bi = dict(pc.basic_info)
        for k in ("name", "species", "description", "personality", "gender"):
            if args.get(k) is not None:
                bi[k] = args[k]
        pc.basic_info = bi
        return f"Updated the player character ({bi.get('name', '')}).", None

    # ---- Scenario / Narrator ----
    if name == "set_scenario":
        scn = (await session.execute(
            select(LorebookEntry).where(func.lower(LorebookEntry.title) == "scenario"))).scalars().first()
        if not scn:
            scn = LorebookEntry(title="Scenario", cat="world", permanent=True, locked=True)
            session.add(scn)
        scn.content = args.get("content", "")
        return "Rewrote the Scenario.", None

    if name == "set_narrator_instructions":
        cfg = (await session.execute(select(NarratorConfig))).scalars().first()
        if not cfg:
            cfg = NarratorConfig()
            session.add(cfg)
        cfg.instructions = args.get("content", "")
        return "Updated the Narrator's instructions.", None

    # ---- Read ----
    if name == "list_world":
        return await _build_planner_context(session), None

    if name == "get_entry":
        q = (args.get("name") or "").strip()
        entry = await _resolve_lore(session, q)
        if entry:
            return json.dumps({"title": entry.title, "cat": entry.cat, "content": entry.content}, ensure_ascii=False), None
        quest = await _resolve_quest(session, q)
        if quest:
            objs = (await session.execute(
                select(QuestObjective).where(QuestObjective.quest_id == quest.id))).scalars().all()
            return json.dumps({"quest": quest.title, "status": quest.status, "desc": quest.desc,
                               "objectives": [o.text for o in objs]}, ensure_ascii=False), None
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

        messages: list[dict] = [
            {"role": "system", "content": instructions},
            {"role": "system", "content": world},
        ]
        for m in history:
            messages.append({"role": m.role, "content": m.content})

        max_rounds = max(1, (settings.max_tool_rounds if settings else 6) or 6)
        pending_deletes: list[dict] = []
        # Accumulate the Editor's prose across every round so a multi-step reply
        # (e.g. "let me check… [acts] …done") is preserved in the chat log as one
        # growing message, rather than each round replacing the last.
        content_parts: list[str] = []

        log.info("EDITOR REQUEST turn=%s | model=%s", turn_number, settings.model_id if settings else "?")

        for round_idx in range(max_rounds):
            offer_tools = round_idx < max_rounds - 1
            result = None
            _round_started = False
            async for ev in chat_completion_agent_turn(
                api_key=settings.api_key, model_id=settings.model_id, messages=messages,
                temperature=settings.temperature, max_tokens=settings.max_tokens_response,
                tools=TOOL_SCHEMAS if offer_tools else None,
                top_p=settings.top_p, min_p=settings.min_p, top_k=settings.top_k,
                frequency_penalty=settings.frequency_penalty, presence_penalty=settings.presence_penalty,
                repetition_penalty=settings.repetition_penalty,
            ):
                if ev["type"] == "content":
                    # Separate this round's prose from the previous round's.
                    if content_parts and not _round_started:
                        yield {"type": "content", "text": "\n\n"}
                    _round_started = True
                    yield {"type": "content", "text": ev["text"]}
                elif ev["type"] == "result":
                    result = ev

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
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": text})
                log.info("EDITOR TOOL turn=%s %s -> %s", turn_number, tc["name"], text)
                yield {"type": "tool", "name": tc["name"], "result": text}
            await session.commit()

    yield {"type": "final", "content": "\n\n".join(content_parts), "pendingDeletes": pending_deletes}
