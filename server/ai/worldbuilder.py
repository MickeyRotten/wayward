"""The Chronicler — a world-building agent.

Runs as a second LLM pass *after* a narration turn. It reviews the new
narration plus the current world state and proposes create/update operations
for lorebook entries, quests, and party members. Tool calls are captured as
``WorldbuildingProposal`` rows rather than executed directly, so:

- Disabled:      the pass never runs.
- Confirmation:  proposals are stored 'pending' for the player to approve.
- Auto:          lore/quest proposals are applied immediately; party-member
                 proposals always stay 'pending' (recruiting needs approval).

Applying a proposal reuses the same ORM writes as the manual CRUD routes.
See CLAUDE.md > The Chronicler.
"""

import json
import logging
import re

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.ai.narrator_actions import (
    SLOT_COMPATIBILITY,
    VALID_EQUIPMENT_SLOTS,
    _is_slot_compatible,
    _resolve_character,
)
from server.ai.openrouter import chat_completion_agent_turn, provider_endpoint
from server.ai.species import compose_species_content, merge_species_fields
from server.db import events as event_ops
from server.db import inventory as inv_ops
from server.db import party as party_ops
from server.db.database import new_session
from server.db.models import (
    CampaignRules,
    ChatMessage,
    ItemInstance,
    LorebookEntry,
    OpenRouterSettings,
    Task,
    WorldbuildingProposal,
)

log = logging.getLogger("wayward.worldbuilder")

LORE_CATS = {"pillars", "world", "characters", "items", "species", "spells"}
# Display order for world-state listings (Pillars first, then Locations, ...).
LORE_CAT_ORDER = ("pillars", "world", "characters", "items", "species", "spells")
TASK_STATUSES = {"active", "completed", "failed"}

# Tool-emitting call — doesn't need the full narration budget.
_CHRONICLER_MAX_TOKENS = 1024

# Pending-proposal pruning: expire pending older than this many turns, and never
# keep more than this many pending at once (the player has moved on).
_PENDING_TURN_WINDOW = 15
_MAX_PENDING = 50

_BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
# Leading articles / generic role words that mark an *unnamed* character.
_ARTICLE_RE = re.compile(r"^(a|an|the|some|several|two|three|many)\b", re.IGNORECASE)

# Pre-filter signals: words that hint a goal/quest may have been established, and
# a proper-noun matcher for spotting names/places not already in the world.
_QUEST_HINTS_RE = re.compile(
    r"\b(quest|task|mission|objective|bounty|reward|retrieve|deliver|escort|"
    r"defeat|slay|rescue|recover|seek|swore|sworn|promised|agreed|vowed|"
    r"recruit|joins?|joined|accept(?:s|ed)?|must|venture)\b",
    re.IGNORECASE,
)
_PROPER_NOUN_RE = re.compile(r"\b([A-Z][a-zA-Z'’-]{2,})\b")
# Capitalised words that are usually sentence-starters/pronouns, not new names.
_CAP_STOPWORDS = frozenset(w.lower() for w in {
    "The", "A", "An", "And", "But", "Or", "So", "Yet", "Then", "Now", "Here",
    "There", "This", "That", "These", "Those", "When", "While", "With", "As",
    "At", "In", "On", "For", "To", "Of", "By", "From", "Into", "She", "He",
    "They", "You", "We", "It", "His", "Her", "Their", "Your", "My", "Our",
    "Its", "What", "Why", "How", "Who", "Where", "Yes", "No", "Not", "If",
    "Morning", "Day", "Afternoon", "Evening", "Night", "Today", "Tomorrow",
    "Yesterday", "Dawn", "Dusk", "Noon", "Midnight", "Suddenly", "Finally",
    "Perhaps", "Maybe", "Still", "Soon", "Once", "After", "Before", "Above",
    "Below", "Beyond", "Together", "Slowly", "Behind", "Around", "Inside",
})


def _worth_chronicling(narration: str, known_tokens: set[str]) -> bool:
    """Cheap deterministic gate: does the narration plausibly introduce anything
    worth recording? Biased toward running (a missed fact is worse than a wasted
    skip) — only skips when there's no bold, no quest-ish wording, and no
    capitalised name that isn't already part of the known world."""
    text = (narration or "").strip()
    if not text:
        return False
    if "**" in text:                     # a bolded item
        return True
    if _QUEST_HINTS_RE.search(text):     # a goal may have formed
        return True
    for m in _PROPER_NOUN_RE.finditer(text):
        word = m.group(1)
        low = word.lower()
        if low in _CAP_STOPWORDS or low in known_tokens:
            continue
        return True                       # a name/place not already in the world
    return False


_POSSESSION_HINTS_RE = re.compile(
    r"\b(pick(?:s|ed)? up|grab(?:s|bed)?|take(?:s|n)?|loot(?:s|ed)?|find(?:s)?|found|"
    r"pocket(?:s|ed)?|hand(?:s|ed)?|give(?:s)?|gave|receive(?:s|d)?|buy(?:s)?|bought|"
    r"equip(?:s|ped)?|wear(?:s)?|wore|wield(?:s|ed)?|don(?:s|ned)?|draw(?:s)?|drew|"
    r"drop(?:s|ped)?|discard(?:s|ed)?|lose(?:s)?|lost|use(?:s|d) up|consum(?:es|ed)|"
    r"sell(?:s)?|sold)\b", re.IGNORECASE,
)


def _worth_stewarding(narration: str) -> bool:
    """Cheap gate before spending an LLM call: does this beat plausibly involve
    an item changing hands, being worn, or being lost? Mirrors _worth_chronicling's
    philosophy — biased toward running, but most turns involve no possession
    change at all, and those should cost nothing."""
    return bool(_POSSESSION_HINTS_RE.search(narration or ""))


def _is_named_character(title: str) -> bool:
    """Heuristic backstop: a real character name is capitalised and not led by an
    article ('a guard', 'the innkeeper', 'some soldiers' → unnamed)."""
    t = title.strip()
    if not t or _ARTICLE_RE.match(t):
        return False
    return t[0].isupper()


def _bolded_phrases(narration: str) -> list[str]:
    return [m.strip().lower() for m in _BOLD_RE.findall(narration or "")]


def _is_bolded(title: str, narration: str) -> bool:
    """True if the item name appears inside a **bolded** span of the narration."""
    t = title.strip().lower()
    if not t:
        return False
    return any(t in phrase or phrase in t for phrase in _bolded_phrases(narration))


CHRONICLER_GUIDANCE = """You are the Chronicler: a quiet archivist who keeps the world's records as an adventure unfolds. You do NOT narrate. After each turn you review what just happened and record only what genuinely changed.

Use your tools to:
- create_lore / update_lore — record new world rules (pillars), places (world/locations), characters (NPCs), items, species (sapient peoples AND monsters/creatures), or spells that the fiction has established, or update an existing entry with new facts. Pick the right category.
- create_task — record a NEW goal/to-do the party has clearly taken on (big like "Reach the Sunken Chapel" or small like "Find someone who knows about the sigil"). Optionally add short notes with specifics the narrator should keep in mind (a name, a deadline, a condition). update_task — mark an existing task completed or failed when the fiction resolves it, and/or add a note when the fiction reveals something new about it.
- create_member — ONLY when a character has clearly and deliberately joined the party as a travelling companion.

Rules (strict — follow them exactly):
- Be conservative. Most turns establish nothing new — in that case, call NO tools at all.
- NAMED characters only. Only record a character who has a proper name (e.g. "Seraphine", "Old Marrow"). Never record unnamed or generic figures — "a guard", "the innkeeper", "the crowd", "two bandits" — they are not lore.
- BOLDED items only. Only record an item if the narration emphasised it in **bold**. If an item was not written in **bold**, do not record it.
- No duplicates. You are given the current world state — reuse those EXACT names. If something already exists, update it; never create a near-duplicate (same name, different capitalisation, plural/singular, etc.).
- Never record a PARTY MEMBER or the PLAYER CHARACTER as lore. The party roster is tracked separately; do not file companions or the player under characters (or any category).
- create_member ONLY when a NAMED character has clearly and deliberately joined the party as a travelling companion.
- Record only what the narration actually established as fact — do not invent. No transient mood or weather.
- Keep entries concise and concrete: a short descriptive paragraph, not a story.

Per-category rules (write the entry as a timeless world fact, NOT a diary of this turn):
- items — Describe the item ITSELF, generically: what it is, looks like, does. Do NOT mention who currently holds or wears it, or the scene it appeared in. ALWAYS set its "itemType" (Equipment, Tool, Consumable, Key Item, Artifact, or Other); for Equipment also set a body "slot" (Head, Neck, Torso, Hands, Waist, Legs, Feet, or Accessory); set "rarity" if the fiction implies one (c=common, u=uncommon, r=rare, e=epic, l=legendary; default common).
- pillars — A foundational RULE of the world/universe (how magic works, a law of nature, a societal absolute), not a place or thing. Only file one when the fiction firmly establishes such a rule. These are always in context, so keep them few and load-bearing.
- world (places / locations) — Describe the place generically and permanently. Nothing about the party, what they did there this turn, or transient events.
- species — Covers BOTH sapient peoples and monsters/creatures — one category. Record on first real appearance (encountering, fighting, or learning about them is itself worth recording; unlike characters, this doesn't require the player to interact with them). Use the "speciesFields" object instead of writing one blob into "content": overview, physicalAppearance, biologyReproduction, cultureBehavior, dangerCombat, typicalGear, archetypesVariants, nameExamples. Set ONLY the fields the fiction has actually established — leave the rest out rather than inventing detail. dangerCombat is narrative flavor only; there is no combat system yet.
- spells — Describe the spell's effect and limits in general, not who cast it just now.
- characters (NPCs) — Describe the person: who they are, appearance, role. Not the party's momentary interaction with them."""


_SPECIES_FIELDS_SCHEMA = {
    "type": "object",
    "description": "For cat='species' only. Structured fields — set only what the fiction has established; leave the rest out. content is ignored/overwritten when this is provided.",
    "properties": {
        "overview": {"type": "string"},
        "physicalAppearance": {"type": "string"},
        "biologyReproduction": {"type": "string"},
        "cultureBehavior": {"type": "string"},
        "dangerCombat": {"type": "string"},
        "typicalGear": {"type": "string"},
        "archetypesVariants": {"type": "string"},
        "nameExamples": {"type": "string"},
    },
}

TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "create_lore",
            "description": "Record a new lorebook entry for something the fiction has established. For cat='items', ALSO set itemType (and slot for Equipment). For cat='species', set speciesFields instead of writing one blob into content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cat": {"type": "string", "enum": sorted(LORE_CATS)},
                    "title": {"type": "string", "description": "Short name, e.g. 'Sunken Chapel'."},
                    "content": {"type": "string", "description": "A concise descriptive paragraph. For items, describe the item itself — not who holds it."},
                    "keywords": {"type": "array", "items": {"type": "string"}},
                    "itemType": {"type": "string", "enum": ["Equipment", "Tool", "Consumable", "Key Item", "Artifact", "Currency", "Other"], "description": "Items only. The kind of item."},
                    "slot": {"type": "string", "enum": ["Head", "Neck", "Torso", "Hands", "Waist", "Legs", "Feet", "Accessory"], "description": "Equipment items only. The body slot it's worn in."},
                    "rarity": {"type": "string", "enum": ["c", "u", "r", "e", "l"], "description": "Items only. c=common u=uncommon r=rare e=epic l=legendary."},
                    "speciesFields": _SPECIES_FIELDS_SCHEMA,
                },
                "required": ["cat", "title", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_lore",
            "description": "Add new facts to an existing lorebook entry, by its exact title.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "content": {"type": "string", "description": "The full updated description."},
                    "keywords": {"type": "array", "items": {"type": "string"}},
                    "speciesFields": _SPECIES_FIELDS_SCHEMA,
                },
                "required": ["title", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_task",
            "description": "Record a new goal/to-do the party has clearly taken on. Can be big ('Reach the Sunken Chapel') or small ('Find someone who knows about the sigil').",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "The task, phrased as a goal."},
                    "notes": {"type": "string", "description": "Optional short notes — specifics the narrator should remember for this task."},
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_task",
            "description": "Update an existing task, matched by its exact text: set its status (active/completed/failed) and/or append a note the narrator should remember.",
            "parameters": {
                "type": "object",
                "properties": {
                    "taskText": {"type": "string"},
                    "status": {"type": "string", "enum": sorted(TASK_STATUSES)},
                    "notes": {"type": "string", "description": "A note to append to the task (new information the fiction revealed)."},
                },
                "required": ["taskText"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_member",
            "description": "Record that a character has joined the party as a travelling companion.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "species": {"type": "string"},
                    "description": {"type": "string"},
                    "personality": {"type": "string"},
                    "fieldSkillName": {"type": "string"},
                    "fieldSkillDescription": {"type": "string"},
                },
                "required": ["name", "species", "description"],
            },
        },
    },
]


STEWARD_TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "take_item",
            "description": "The party has just physically taken possession of something. If it is not already a known item, this also records it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "itemName": {"type": "string"},
                    "count": {"type": "integer", "minimum": 1, "default": 1},
                    "description": {"type": "string", "description": "Required only if this item is not already known — a generic, timeless description of the item itself, not what just happened."},
                    "itemType": {"type": "string", "enum": ["Equipment", "Tool", "Consumable", "Key Item", "Artifact", "Currency", "Other"]},
                    "slot": {"type": "string", "enum": ["Head", "Neck", "Torso", "Hands", "Waist", "Legs", "Feet", "Accessory"]},
                    "equipOnCharacter": {"type": "string", "description": "Optional. First name of whoever is wearing/wielding it right now."},
                },
                "required": ["itemName"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "equip_item",
            "description": "A character equips something already in the party's possession (not a new acquisition).",
            "parameters": {
                "type": "object",
                "properties": {
                    "characterName": {"type": "string"},
                    "itemName": {"type": "string"},
                    "slot": {"type": "string", "enum": sorted(VALID_EQUIPMENT_SLOTS)},
                },
                "required": ["characterName", "itemName"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "drop_item",
            "description": "The party has lost, consumed, used up, given away, or unequipped something. For unequipping (item stays in the pack), pass unequipOnly=true.",
            "parameters": {
                "type": "object",
                "properties": {
                    "itemName": {"type": "string"},
                    "characterName": {"type": "string", "description": "Only for unequipping — who currently has it on."},
                    "count": {"type": "integer", "minimum": 1, "default": 1},
                    "unequipOnly": {"type": "boolean", "default": False},
                },
                "required": ["itemName"],
            },
        },
    },
]

STEWARD_GUIDANCE = """You are the Steward: you keep the party's possessions accurate after each beat. You do NOT narrate.

Rules (strict):
- Only record something as TAKEN if the prose says the party picked it up, was handed it, looted it, bought it, or otherwise now physically has it. Something merely SEEN, described, or offered-but-not-yet-taken is NOT an event — call no tool.
- If the item is already known (see CURRENT ITEMS / INVENTORY below), use its EXACT existing name — never invent a near-duplicate name for something that already exists.
- If it is genuinely new, take_item ALSO needs description, itemType, and (for Equipment) slot — describe the item itself, generically, not this scene.
- Never grant something the party already has unless the prose says they got MORE of it (a specific new count).
- Most turns nothing changes hands — in that case, call no tools at all."""


def _parse_args(raw: str) -> dict:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


async def _resolve_lore(session: AsyncSession, title: str) -> LorebookEntry | None:
    if not title:
        return None
    return (
        await session.execute(
            select(LorebookEntry).where(func.lower(LorebookEntry.title) == title.lower())
        )
    ).scalars().first()


async def _resolve_task(session: AsyncSession, text: str) -> Task | None:
    if not text:
        return None
    return (
        await session.execute(
            select(Task).where(func.lower(Task.text) == text.lower())
        )
    ).scalars().first()


async def _member_exists(session: AsyncSession, name: str) -> bool:
    members = await party_ops.load_party(session)
    return any(m.basic_info.get("name", "").lower() == name.lower() for m in members)


async def _absorb_lore_character(session: AsyncSession, name: str) -> str | None:
    """When a character is recruited into the party, remove their lorebook
    'characters' entry (they now live as a party member) and return its content
    so it can seed the member's description. Locked entries are left alone."""
    entry = await _resolve_lore(session, name)
    if entry is not None and entry.cat == "characters" and not entry.locked:
        content = entry.content
        await session.delete(entry)
        return content
    return None


async def _build_world_state(session: AsyncSession) -> str:
    """A compact inventory of current world state for dedup + name reuse."""
    lore = (await session.execute(select(LorebookEntry))).scalars().all()
    by_cat: dict[str, list[str]] = {}
    for e in lore:
        by_cat.setdefault(e.cat, []).append(e.title)
    tasks = (await session.execute(select(Task))).scalars().all()
    members = [m for m in await party_ops.load_party(session) if m.in_party]

    lines = ["CURRENT WORLD STATE (reuse these exact names; update rather than duplicate):"]
    for cat in LORE_CAT_ORDER:
        titles = by_cat.get(cat, [])
        lines.append(f"  {cat}: {', '.join(titles) if titles else '(none)'}")
    if tasks:
        lines.append("  tasks: " + ", ".join(f"{t.text} [{t.status}]" for t in tasks))
    else:
        lines.append("  tasks: (none)")
    member_names = [m.basic_info.get("name", "?") for m in members]
    lines.append(f"  party members: {', '.join(member_names) if member_names else '(none)'}")
    return "\n".join(lines)


async def _build_inventory_state(session: AsyncSession) -> str:
    """Current possessions, for the Steward's dedup + no-op judgment. Separate
    from _build_world_state (which lists the catalog, not who holds what)."""
    catalog = {
        e.id: e for e in
        (await session.execute(select(LorebookEntry).where(LorebookEntry.cat == "items"))).scalars().all()
    }
    equipped = await inv_ops.equipped_map(session)
    instances = (await session.execute(select(ItemInstance))).scalars().all()

    held_counts: dict[str, int] = {}
    equipped_lines: list[str] = []
    for inst in instances:
        info = equipped.get(inst.id)
        item = catalog.get(inst.item_id)
        name = item.title if item else inst.item_id
        if info:
            equipped_lines.append(f"{info['characterName']}: {info['slot']}={name}")
        else:
            held_counts[name] = held_counts.get(name, 0) + max(1, int(inst.count or 1))

    lines = ["CURRENT ITEMS / INVENTORY (the party's actual possessions — reuse exact names; do not re-grant what's already held):"]
    if held_counts:
        held = ", ".join(f"{n} x{c}" if c > 1 else n for n, c in sorted(held_counts.items()))
        lines.append(f"  held: {held}")
    else:
        lines.append("  held: (none)")
    if equipped_lines:
        lines.append("  equipped: " + " · ".join(sorted(equipped_lines)))
    else:
        lines.append("  equipped: (none)")
    return "\n".join(lines)


def _infer_equip_slot(item: LorebookEntry, character) -> str | None:
    """Given the item's catalog slot category, pick the first compatible
    Equipment field not already occupied on this character; if every compatible
    field is already occupied, fall back to the first one (an explicit equip
    still succeeds and displaces whatever was there — the same behavior
    ``inv_ops.equip_instance`` already has for the native tool path)."""
    compatible = SLOT_COMPATIBILITY.get(item.slot or "", [])
    if not compatible:
        return None
    equipment = character.equipment or {}
    for field in compatible:
        if not equipment.get(field):
            return field
    return compatible[0]


async def _latest_narration(session: AsyncSession, turn_number: int, since_turn: int | None = None) -> str:
    """The active narration across the span being chronicled (highest variant per
    turn), for the pre-filter and the bolded-item check."""
    low = turn_number if since_turn is None else since_turn + 1
    msgs = (await session.execute(
        select(ChatMessage).where(
            ChatMessage.turn_number >= low,
            ChatMessage.turn_number <= turn_number,
            ChatMessage.role == "assistant",
        )
    )).scalars().all()
    by_turn: dict[int, ChatMessage] = {}
    for m in msgs:
        cur = by_turn.get(m.turn_number)
        if cur is None or m.variant > cur.variant:
            by_turn[m.turn_number] = m
    return "\n\n".join(by_turn[t].content or "" for t in sorted(by_turn))


def _clip(text: str, limit: int) -> str:
    text = text or ""
    return text if len(text) <= limit else text[:limit].rstrip() + " …"


async def _known_name_tokens(session: AsyncSession) -> set[str]:
    """Lowercased word tokens of every known proper name (lore titles, party
    members, PC) — so the pre-filter doesn't re-trigger on names already recorded.
    Tasks are free-text goals, not proper names, so they're intentionally excluded."""
    lore = (await session.execute(select(LorebookEntry))).scalars().all()
    members = await party_ops.load_party(session)
    pc = await party_ops.load_pc(session)
    names = [e.title for e in lore]
    names += [m.basic_info.get("name", "") for m in members]
    if pc:
        names.append(pc.basic_info.get("name", ""))
    tokens: set[str] = set()
    for n in names:
        for tok in re.findall(r"[A-Za-z'’-]{2,}", n or ""):
            tokens.add(tok.lower())
    return tokens


async def _turn_context(session: AsyncSession, turn_number: int, since_turn: int) -> str:
    """The span of turns being recorded (player + active narration each) plus a
    little prior context. Content is clipped to keep this second pass lean.

    A span rather than a single turn: running every turn made the Chronicler
    judge "is this new?" from one beat, which is exactly when it re-proposes an
    entry it wrote two beats ago. Seeing the whole stretch at once is both
    cheaper and a better judge."""
    low = since_turn + 1
    span = (
        await session.execute(
            select(ChatMessage)
            .where(ChatMessage.turn_number >= low, ChatMessage.turn_number <= turn_number)
            .order_by(ChatMessage.id)
        )
    ).scalars().all()

    # Two prior messages for continuity, each clipped (targeted query — never
    # load the whole adventure for this second, lean LLM pass).
    prior = list(reversed((
        await session.execute(
            select(ChatMessage)
            .where(ChatMessage.turn_number < low)
            .order_by(ChatMessage.id.desc())
            .limit(2)
        )
    ).scalars().all()))
    lines = ["RECENT CONTEXT:"]
    for m in prior:
        who = "Player" if m.role == "user" else "Narrator"
        lines.append(f"  [{who}] {_clip(m.content, 280)}")
    lines.append("")
    lines.append("THE TURNS TO RECORD:" if turn_number > low else "THE TURN TO RECORD:")
    for t in range(low, turn_number + 1):
        msgs = [m for m in span if m.turn_number == t]
        player = next((m for m in msgs if m.role == "user"), None)
        variants = [m for m in msgs if m.role == "assistant"]
        if not player and not variants:
            continue
        if player:
            lines.append(f"  [Player] {_clip(player.content, 400)}")
        if variants:
            narration = max(variants, key=lambda m: m.variant).content
            lines.append(f"  [Narrator] {_clip(narration, 1600)}")
    return "\n".join(lines)


def _summary(kind: str, operation: str, payload: dict, target_title: str | None = None) -> str:
    if kind == "lore":
        verb = "Add lore" if operation == "create" else "Update lore"
        return f"{verb}: {payload.get('title') or target_title or '?'}"
    if kind == "task":
        if operation == "create":
            return f"New task: {payload.get('text', '?')[:48]}"
        if payload.get("status"):
            return f"Task {payload['status']}: {target_title or '?'}"
        return f"Task note: {target_title or '?'}"
    if kind == "member":
        return f"Recruit member: {payload.get('name', '?')}"
    return f"{kind} {operation}"


def _item_summary(op: str, args: dict) -> str:
    name = args.get("itemName", "?")
    if op == "take":
        count = args.get("count") or 1
        base = f"Took {name}" + (f" x{count}" if count and count > 1 else "")
        if args.get("equipOnCharacter"):
            base += f" (equipped by {args['equipOnCharacter']})"
        return base
    if op == "equip":
        who = args.get("characterName", "?")
        return f"{who} equipped {name}"
    if op == "drop":
        if args.get("unequipOnly"):
            who = args.get("characterName", "?")
            return f"{who} unequipped {name}"
        return f"Dropped {name}"
    return f"{op} {name}"


async def _proposal_from_call(
    session: AsyncSession, turn_number: int, name: str, args: dict,
    *, member_names: set[str], pc_name: str, narration: str,
) -> WorldbuildingProposal | None:
    """Convert one Chronicler tool call into a proposal, resolving names/dedup.

    Enforces the strict rules deterministically (the guidance can drift):
    named characters only, **bolded** items only, no duplicates, and never file
    a party member or the player character as lore.
    """
    if name == "create_lore":
        cat = args.get("cat")
        title = (args.get("title") or "").strip()
        if cat not in LORE_CATS or not title:
            return None
        low = title.lower()
        # Never file a party member or the player character as lore.
        if low in member_names or (pc_name and low == pc_name):
            return None
        existing = await _resolve_lore(session, title)
        if existing:
            if existing.locked:
                return None
            payload = {"content": args.get("content", ""), "keywords": args.get("keywords", [])}
            return WorldbuildingProposal(
                turn_number=turn_number, kind="lore", operation="update",
                target_id=existing.id, payload=payload,
                summary=_summary("lore", "update", payload, existing.title),
            )
        # Creating a NEW entry — apply the named/bolded gates.
        if cat == "characters" and not _is_named_character(title):
            return None
        if cat == "items" and not _is_bolded(title, narration):
            return None
        payload = {"cat": cat, "title": title, "content": args.get("content", ""), "keywords": args.get("keywords", [])}
        if cat == "items":
            payload["itemType"] = (args.get("itemType") or "Other")
            payload["rarity"] = (args.get("rarity") or "c")
            if args.get("slot"):
                payload["slot"] = args.get("slot")
        if cat == "species" and args.get("speciesFields"):
            payload["speciesFields"] = args["speciesFields"]
        return WorldbuildingProposal(
            turn_number=turn_number, kind="lore", operation="create",
            payload=payload, summary=_summary("lore", "create", payload),
        )

    if name == "update_lore":
        title = (args.get("title") or "").strip()
        if title.lower() in member_names or (pc_name and title.lower() == pc_name):
            return None
        existing = await _resolve_lore(session, title)
        if not existing or existing.locked:
            return None
        payload = {"content": args.get("content", ""), "keywords": args.get("keywords")}
        if existing.cat == "species" and args.get("speciesFields"):
            payload["speciesFields"] = args["speciesFields"]
        return WorldbuildingProposal(
            turn_number=turn_number, kind="lore", operation="update",
            target_id=existing.id, payload=payload,
            summary=_summary("lore", "update", payload, existing.title),
        )

    if name == "create_task":
        text = (args.get("text") or "").strip()
        if not text or await _resolve_task(session, text):
            return None
        payload = {"text": text}
        if (args.get("notes") or "").strip():
            payload["notes"] = args["notes"].strip()
        return WorldbuildingProposal(
            turn_number=turn_number, kind="task", operation="create",
            payload=payload, summary=_summary("task", "create", payload),
        )

    if name in ("update_task", "update_task_status"):
        task = await _resolve_task(session, (args.get("taskText") or "").strip())
        status = args.get("status")
        note = (args.get("notes") or "").strip()
        valid_status = status in TASK_STATUSES
        # Need at least one real change (a valid status, or a note to append).
        if not task or (not valid_status and not note):
            return None
        payload: dict = {}
        if valid_status:
            payload["status"] = status
        if note:
            payload["notesAppend"] = note
        return WorldbuildingProposal(
            turn_number=turn_number, kind="task", operation="update",
            target_id=task.id, payload=payload,
            summary=_summary("task", "update", payload, task.text),
        )

    if name == "create_member":
        mname = (args.get("name") or "").strip()
        if not mname or not _is_named_character(mname) or await _member_exists(session, mname):
            return None
        payload = {
            "name": mname,
            "species": args.get("species", ""),
            "description": args.get("description", ""),
            "personality": args.get("personality", ""),
            "fieldSkillName": args.get("fieldSkillName", ""),
            "fieldSkillDescription": args.get("fieldSkillDescription", ""),
        }
        return WorldbuildingProposal(
            turn_number=turn_number, kind="member", operation="create",
            payload=payload, summary=_summary("member", "create", payload),
        )

    return None


def _snapshot_prev(proposal: WorldbuildingProposal, prev: dict) -> None:
    """Record an entry's pre-update state on the proposal so a regenerate/delete
    of its turn can restore it. Stored under a reserved ``_prev`` payload key
    (stripped before the payload is sent to the client). Reassign the dict so
    SQLAlchemy tracks the JSON mutation."""
    proposal.payload = {**(proposal.payload or {}), "_prev": prev}


async def apply_proposal(proposal: WorldbuildingProposal, session: AsyncSession) -> tuple[bool, str | None]:
    """Execute a proposal's write against the DB. Returns (ok, note)."""
    p = proposal.payload or {}
    kind, op = proposal.kind, proposal.operation

    if kind == "lore" and op == "create":
        cat = p.get("cat", "world")
        entry = LorebookEntry(
            title=p.get("title", ""), content=p.get("content", ""),
            keywords=p.get("keywords") or [], cat=cat,
        )
        if cat == "items":
            entry.item_type = p.get("itemType") or "Other"
            entry.rarity = p.get("rarity") or "c"
            entry.slot = p.get("slot")
            entry.max_stack = 1
        if cat == "species":
            entry.species_fields = merge_species_fields(None, p.get("speciesFields"))
            entry.content = compose_species_content(entry.species_fields)
        session.add(entry)
        await session.flush()
        proposal.target_id = entry.id  # tie the created entry to this proposal/turn
        return True, None

    if kind == "lore" and op == "update":
        entry = await session.get(LorebookEntry, proposal.target_id)
        if not entry:
            return False, "Lore entry no longer exists."
        if entry.locked:
            return False, "Entry is locked."
        # Snapshot prior state so a regenerate/delete of this turn can restore it.
        prev_snapshot = {"content": entry.content, "keywords": list(entry.keywords or [])}
        if entry.cat == "species":
            prev_snapshot["speciesFields"] = dict(entry.species_fields or {})
        _snapshot_prev(proposal, prev_snapshot)
        if entry.cat == "species":
            if p.get("speciesFields"):
                entry.species_fields = merge_species_fields(entry.species_fields, p["speciesFields"])
            entry.content = compose_species_content(entry.species_fields or {})
        elif p.get("content") is not None:
            entry.content = p["content"]
        if p.get("keywords") is not None:
            entry.keywords = p["keywords"]
        return True, None

    if kind == "task" and op == "create":
        max_order = (await session.execute(
            select(func.coalesce(func.max(Task.sort_order), -1))
        )).scalar()
        task = Task(text=p.get("text", ""), status="active", notes=p.get("notes", ""),
                    sort_order=(max_order or 0) + 1)
        session.add(task)
        await session.flush()
        proposal.target_id = task.id  # tie the created task to this proposal/turn
        return True, None

    if kind == "task" and op == "update":
        task = await session.get(Task, proposal.target_id)
        if not task:
            return False, "Task no longer exists."
        _snapshot_prev(proposal, {"status": task.status, "notes": task.notes})
        if p.get("status"):
            task.status = p["status"]
        if p.get("notesAppend"):
            # Additive: append the new note on its own line, keeping prior notes.
            existing = (task.notes or "").rstrip()
            task.notes = f"{existing}\n{p['notesAppend']}" if existing else p["notesAppend"]
        return True, None

    if kind == "member" and op == "create":
        rules = (await session.execute(select(CampaignRules))).scalars().first()
        if rules:
            max_size = rules.party_size
        else:
            settings = (await session.execute(select(OpenRouterSettings))).scalars().first()
            max_size = settings.max_party_size if settings else 3
        if await party_ops.active_count(session) >= max_size:
            return False, "Party is full."
        # Promote a lorebook character into the party: if a matching lore
        # 'characters' entry exists, remove it (the character now lives as a
        # party member) and reuse its description if the proposal lacks one.
        absorbed = await _absorb_lore_character(session, p.get("name", ""))
        description = p.get("description", "") or (absorbed or "")
        await party_ops.add_member(
            session,
            basic_info={
                "name": p.get("name", ""), "species": p.get("species", ""),
                "description": description, "personality": p.get("personality", ""),
            },
            field_skill={"name": p.get("fieldSkillName", ""), "description": p.get("fieldSkillDescription", "")},
        )
        return True, None

    if kind == "item" and op == "take":
        item_name = (p.get("itemName") or "").strip()
        if not item_name:
            return False, "No item name given."
        item = await _resolve_lore(session, item_name)
        created_new = False
        if item is None:
            description = (p.get("description") or "").strip()
            if not description:
                return False, "New item with no description — refused."
            item = LorebookEntry(
                title=item_name, content=description, cat="items",
                item_type=p.get("itemType") or "Other", slot=p.get("slot"), max_stack=1,
            )
            session.add(item)
            await session.flush()
            created_new = True

        # A grant with no EXPLICIT count for something already stowed is a
        # restatement, not a second pickup — the same no-op rule the native
        # grant_item tool applies (see narrator_actions.tool_grant_item).
        raw_count = p.get("count")
        count = int(raw_count or 1)
        inv_deltas: list[dict] = []
        if raw_count is None and await inv_ops.find_stowed_instance(session, item.id) is not None:
            pass
        else:
            _msg, inv_deltas = await inv_ops.grant_items(session, item, count, "steward_grant")

        equip_changes: list[dict] = []
        equip_target = (p.get("equipOnCharacter") or "").strip()
        if equip_target:
            character, char_id = await _resolve_character(session, equip_target)
            if character and item.item_type == "Equipment":
                target_slot = _infer_equip_slot(item, character)
                if target_slot:
                    _msg, more_changes, more_deltas = await inv_ops.equip_instance(
                        session, character, char_id, target_slot, item
                    )
                    equip_changes.extend(more_changes)
                    inv_deltas.extend(more_deltas)

        proposal.target_id = item.id  # tie the (possibly new) entry to this proposal/turn
        proposal.payload = {**p, "_invDeltas": inv_deltas, "_equipChanges": equip_changes, "_createdNew": created_new}
        return True, None

    if kind == "item" and op == "equip":
        character, char_id = await _resolve_character(session, p.get("characterName", ""))
        item = await _resolve_lore(session, p.get("itemName", ""))
        if not character or not item or item.item_type != "Equipment":
            return False, "Could not resolve character/item, or item is not Equipment."
        slot = p.get("slot") or _infer_equip_slot(item, character)
        if not slot or slot not in VALID_EQUIPMENT_SLOTS or (item.slot and not _is_slot_compatible(item.slot, slot)):
            return False, "No compatible slot."

        # Already wearing exactly this in this slot — a no-op, not a change (or
        # reversal would replay a bogus equip forever).
        binding = await party_ops.binding_for(session, char_id)
        current_instance_id = (dict(getattr(binding, "equipment", None) or {})).get(slot)
        if current_instance_id:
            current = await session.get(ItemInstance, current_instance_id)
            if current is not None and current.item_id == item.id:
                proposal.payload = {**p, "_invDeltas": [], "_equipChanges": []}
                return True, None

        _msg, equip_changes, inv_deltas = await inv_ops.equip_instance(session, character, char_id, slot, item)
        proposal.payload = {**p, "_invDeltas": inv_deltas, "_equipChanges": equip_changes}
        return True, None

    if kind == "item" and op == "drop":
        item = await _resolve_lore(session, p.get("itemName", ""))
        if not item:
            return False, "Unknown item."

        inv_deltas: list[dict] = []
        equip_changes: list[dict] = []
        if p.get("unequipOnly") and p.get("characterName"):
            character, char_id = await _resolve_character(session, p["characterName"])
            binding = await party_ops.binding_for(session, char_id) if character else None
            if not character or binding is None:
                return False, "Could not resolve character."
            equipment = dict(binding.equipment or {})
            slot = None
            for s, instance_id in equipment.items():
                if not instance_id:
                    continue
                inst = await session.get(ItemInstance, instance_id)
                if inst is not None and inst.item_id == item.id:
                    slot = s
                    break
            if slot is None:
                # Already not equipped — a no-op, not a failure.
                proposal.payload = {**p, "_invDeltas": [], "_equipChanges": []}
                return True, None
            previous_instance_id = equipment[slot]
            equipment[slot] = None
            binding.equipment = equipment
            equip_changes.append({
                "characterId": char_id, "slot": slot,
                "previousItemId": previous_instance_id, "newItemId": None,
            })
        else:
            count = int(p.get("count") or 1)
            _msg, inv_deltas = await inv_ops.remove_items(session, item, count, "steward_drop")

        proposal.payload = {**p, "_invDeltas": inv_deltas, "_equipChanges": equip_changes}
        return True, None

    return False, f"Unknown proposal {kind}/{op}."


async def _reverse_accepted_proposal(p: WorldbuildingProposal, session: AsyncSession) -> bool:
    """Undo one accepted proposal's DB effect. Returns True if something changed.

    Members are never reversed (recruiting is deliberate); locked entries (e.g.
    the Scenario) are never touched. Updates restore the ``_prev`` snapshot
    recorded at apply time."""
    kind, op = p.kind, p.operation
    prev = (p.payload or {}).get("_prev") or {}

    if kind == "lore" and op == "create":
        entry = await session.get(LorebookEntry, p.target_id) if p.target_id else None
        if entry is not None and not entry.locked:
            await session.delete(entry)
            return True
        return False

    if kind == "lore" and op == "update":
        entry = await session.get(LorebookEntry, p.target_id) if p.target_id else None
        if entry is not None and not entry.locked and prev:
            if "content" in prev:
                entry.content = prev["content"]
            if "keywords" in prev:
                entry.keywords = prev["keywords"]
            if "speciesFields" in prev:
                entry.species_fields = prev["speciesFields"]
            return True
        return False

    if kind == "task" and op == "create":
        task = await session.get(Task, p.target_id) if p.target_id else None
        if task is not None:
            await session.delete(task)
            return True
        return False

    if kind == "task" and op == "update":
        task = await session.get(Task, p.target_id) if p.target_id else None
        if task is not None and prev:
            if "status" in prev:
                task.status = prev["status"]
            if "notes" in prev:
                task.notes = prev["notes"]
            return True
        return False

    if kind == "item":
        p_payload = p.payload or {}
        inv_deltas = p_payload.get("_invDeltas") or []
        equip_changes = p_payload.get("_equipChanges") or []
        changed = False
        if inv_deltas:
            from server.ai.item_detection import reverse_inventory_deltas
            await reverse_inventory_deltas(inv_deltas, session)
            changed = True
        if equip_changes:
            from server.ai.narrator_actions import reverse_equipment_changes
            await reverse_equipment_changes(equip_changes, session)
            changed = True
        # Only a NEWLY CREATED catalog entry is removed on reversal — granting
        # an item that already existed and reversing that grant must restore
        # inventory state without deleting the pre-existing catalog entry.
        if op == "take" and p.target_id and p_payload.get("_createdNew"):
            entry = await session.get(LorebookEntry, p.target_id)
            if entry is not None and not entry.locked:
                await session.delete(entry)
                changed = True
        return changed

    return False  # member creations and anything else are left in place


async def reverse_chronicler_effects(
    session: AsyncSession, from_turn: int, *, exact: bool = False
) -> int:
    """Undo the Chronicler's (and Steward's) effects on the given turn(s) and
    drop the turn's proposal rows.

    Chronicler/Steward proposals are tied to the message that triggered them:
    when that message is deleted, regenerated, or swiped, the entries/inventory
    they spawned (or the edits they made) are undone and their proposals
    cleared, so the re-run records a fresh set. We use the proposal rows as the
    link (turn_number + the target_id/deltas recorded at apply time).

    - *accepted* create/update proposals (lore, quests, objectives) are reversed
      — creates deleted, updates restored from their ``_prev`` snapshot;
    - *accepted* item proposals (take/equip/drop) are reversed by inverting the
      inventory deltas and equipment changes recorded at apply time; a newly
      created catalog entry (a brand-new item taken for the first time) is
      deleted too, but an item that already existed is left in the catalog;
    - *pending / rejected / failed* proposals for the turn are simply dropped
      (they belonged to the discarded telling);
    - accepted *member* recruitments are left intact (deliberate) and their
      proposal row is kept as the record;
    - locked entries (e.g. the Scenario) are never touched.

    Returns the number of entries reversed. ``exact`` restricts to a single turn
    (swipe/regenerate of that turn); otherwise it reverses that turn and
    everything after (delete-and-after).
    """
    turn_cond = (
        WorldbuildingProposal.turn_number == from_turn if exact
        else WorldbuildingProposal.turn_number >= from_turn
    )
    # Descending so that when several turns touch the same entry, the earliest
    # update's snapshot is restored last and therefore wins.
    proposals = (await session.execute(
        select(WorldbuildingProposal).where(turn_cond).order_by(
            WorldbuildingProposal.turn_number.desc(), WorldbuildingProposal.id.desc()
        )
    )).scalars().all()

    reversed_count = 0
    for p in proposals:
        # Keep the record of a deliberate recruitment; the member stays.
        if p.kind == "member" and p.status == "accepted":
            continue
        if p.status == "accepted":
            if await _reverse_accepted_proposal(p, session):
                reversed_count += 1
        await session.delete(p)  # drop the now-orphaned proposal record

    # Drop the tethered Chronicler toasts for the same turn(s).
    await event_ops.delete_tethered(session, from_turn, exact=exact)
    return reversed_count


def chronicler_span(turn_number: int, interval: int) -> int | None:
    """The turn this run should look back to, or None when it should not run.

    A cadence rather than every turn. The pass costs a whole second generation,
    and running it on every beat also made it judge "is this genuinely new?" from
    a single beat — which is when it re-proposes the entry it wrote two turns
    ago. Deterministic in the turn number, so it needs no bookkeeping and a
    swipe/regenerate of a covered turn lands on the same decision. An interval of
    1 is the old behaviour exactly."""
    interval = max(1, min(int(interval or 1), 10))
    if interval == 1:
        return turn_number - 1
    if turn_number % interval != 0:
        return None
    return turn_number - interval


_STEWARD_MAX_TOKENS = 512


async def _run_steward_pass(
    session: AsyncSession, turn_number: int, narration: str, settings: OpenRouterSettings,
) -> list[WorldbuildingProposal]:
    """The Steward: a second, tool-capable pass that reads the FINISHED narration
    and performs item-possession mutations via validated tool calls, instead of
    asking the (possibly non-tool-capable) narration model to emit both prose and
    precise state deltas in one pass.

    Runs on every turn (independent of the Chronicler's lore/task/member
    cadence) when the deterministic pre-filter finds a possession-change signal.
    Item proposals always auto-apply — a player who can't pick up or equip
    items has no game — regardless of the Confirmation/Auto ``worldbuilding_mode``
    setting (which governs only lore/task/member proposals)."""
    base_url, api_key, main_model = provider_endpoint(settings)
    model_id = settings.worldbuilding_model_id or main_model

    world_state = await _build_world_state(session)
    inventory_state = await _build_inventory_state(session)

    messages = [
        {"role": "system", "content": STEWARD_GUIDANCE},
        {"role": "system", "content": world_state},
        {"role": "system", "content": inventory_state},
        {"role": "user", "content": (
            "NEW NARRATION THIS TURN:\n" + narration +
            "\n\nRecord any possession changes. If nothing changed hands, call no tools."
        )},
    ]

    log.info("STEWARD REQUEST turn=%s | model=%s", turn_number, model_id)

    tool_calls: list[dict] = []
    try:
        async for ev in chat_completion_agent_turn(
            api_key=api_key, model_id=model_id, base_url=base_url, messages=messages,
            temperature=0.2,
            max_tokens=min(settings.max_tokens_response, _STEWARD_MAX_TOKENS),
            tools=STEWARD_TOOL_SCHEMAS,
        ):
            if ev["type"] == "result":
                tool_calls = ev["tool_calls"]
    except Exception:
        log.exception("Steward call failed")
        return []

    op_by_name = {"take_item": "take", "equip_item": "equip", "drop_item": "drop"}
    proposals: list[WorldbuildingProposal] = []
    for tc in tool_calls:
        op = op_by_name.get(tc["name"])
        args = _parse_args(tc["arguments"])
        if op is None or not (args.get("itemName") or "").strip():
            continue

        proposal = WorldbuildingProposal(
            turn_number=turn_number, kind="item", operation=op, payload=dict(args),
        )
        ok, note = await apply_proposal(proposal, session)
        proposal.status = "accepted" if ok else "failed"
        proposal.note = note
        proposal.summary = _item_summary(op, args)
        session.add(proposal)
        proposals.append(proposal)
        if ok:
            # Persistent in-chat toast, tethered to this turn (removed if the
            # turn is later deleted/regenerated/swiped) — same mechanism the
            # Chronicler's own auto-apply toasts use.
            await event_ops.add_event(
                session, turn_number=turn_number, kind="item",
                text=proposal.summary, tethered=True,
            )
        log.info("STEWARD PROPOSAL turn=%s %s [%s]", turn_number, proposal.summary, proposal.status)

    return proposals


async def run_worldbuilder(turn_number: int, force: bool = False) -> list[WorldbuildingProposal]:
    """Run the Steward (item possession, every turn) and the Chronicler (lore /
    task / member, on its own cadence) over the turns since it last ran. Returns
    the combined proposals.

    Clears any stale 'pending' proposals for this turn first (so swipe/regen
    don't accumulate duplicates). Both passes no-op when mode is 'disabled'; the
    Chronicler pass additionally no-ops when the cadence says this is not a
    Chronicler turn (``force`` overrides — the manual "run now" path). The
    Steward pass is unaffected by cadence/``force`` — it always looks at just
    the newest turn.
    """
    async with new_session() as session:
        settings = (await session.execute(select(OpenRouterSettings))).scalars().first()
        if not settings:
            return []
        base_url, api_key, main_model = provider_endpoint(settings)
        if not api_key or not main_model:
            return []
        mode = settings.worldbuilding_mode or "confirmation"
        if mode == "disabled":
            return []

        # ── The Steward: item possession changes, every turn ──────────────
        item_proposals: list[WorldbuildingProposal] = []
        this_turn_narration = await _latest_narration(session, turn_number, turn_number - 1)
        if _worth_stewarding(this_turn_narration):
            item_proposals = await _run_steward_pass(session, turn_number, this_turn_narration, settings)
            await session.commit()

        # ── The Chronicler: lore / task / member, on its own cadence ───────
        since_turn = turn_number - 1 if force else chronicler_span(
            turn_number, getattr(settings, "worldbuilding_interval", 2) or 2
        )
        if since_turn is None:
            log.info("CHRONICLER SKIP turn=%s (not a Chronicler turn)", turn_number)
            return item_proposals
        since_turn = max(0, since_turn)

        # Prune pending proposals so they don't accumulate forever: drop this
        # turn's stale pending (a re-run replaces them), anything older than the
        # turn window (the player has moved on), and anything beyond a hard cap.
        pending = (await session.execute(
            select(WorldbuildingProposal)
            .where(WorldbuildingProposal.status == "pending")
            .order_by(WorldbuildingProposal.turn_number.desc(), WorldbuildingProposal.id.desc())
        )).scalars().all()
        cutoff = turn_number - _PENDING_TURN_WINDOW
        for idx, p in enumerate(pending):
            if p.turn_number == turn_number or p.turn_number < cutoff or idx >= _MAX_PENDING:
                await session.delete(p)
        await session.flush()

        # Cheap deterministic pre-filter: skip the whole second LLM pass when the
        # turn plausibly introduced nothing new (the common case).
        narration = await _latest_narration(session, turn_number, since_turn)
        known_tokens = await _known_name_tokens(session)
        if not _worth_chronicling(narration, known_tokens):
            await session.commit()  # persist the stale-pending cleanup
            log.info("CHRONICLER SKIP turn=%s (no new signals)", turn_number)
            return item_proposals

        world_state = await _build_world_state(session)
        turn_ctx = await _turn_context(session, turn_number, since_turn)
        model_id = settings.worldbuilding_model_id or main_model

        # Guard data for the deterministic rule backstop: every party member
        # (incl. benched) and the PC must never be filed as lore, and item
        # entries are only allowed if the item was **bolded** in this narration.
        all_members = await party_ops.load_party(session)
        member_names = {m.basic_info.get("name", "").strip().lower() for m in all_members if m.basic_info.get("name")}
        pc = await party_ops.load_pc(session)
        pc_name = (pc.basic_info.get("name", "").strip().lower() if pc else "")

        messages = [
            {"role": "system", "content": CHRONICLER_GUIDANCE},
            {"role": "system", "content": world_state},
            {"role": "user", "content": turn_ctx + "\n\nRecord anything new or changed. If nothing, call no tools."},
        ]

        log.info("CHRONICLER REQUEST turn=%s | model=%s | mode=%s", turn_number, model_id, mode)

        tool_calls: list[dict] = []
        try:
            async for ev in chat_completion_agent_turn(
                api_key=api_key, model_id=model_id, base_url=base_url, messages=messages,
                temperature=0.4,
                max_tokens=min(settings.max_tokens_response, _CHRONICLER_MAX_TOKENS),
                tools=TOOL_SCHEMAS,
            ):
                if ev["type"] == "result":
                    tool_calls = ev["tool_calls"]
        except Exception:
            log.exception("Chronicler call failed")
            return item_proposals

        if not tool_calls:
            # The pre-filter passed (there were signals) but the model proposed
            # nothing — if this persists, the world-building model may not support
            # tool calling. Surface it for troubleshooting.
            log.info("CHRONICLER no proposals turn=%s | model=%s (check tool support if persistent)", turn_number, model_id)

        proposals: list[WorldbuildingProposal] = []
        for tc in tool_calls:
            args = _parse_args(tc["arguments"])
            proposal = await _proposal_from_call(
                session, turn_number, tc["name"], args,
                member_names=member_names, pc_name=pc_name, narration=narration,
            )
            if proposal is None:
                continue

            # Apply policy: auto applies lore/task now; members always pending.
            if mode == "auto" and proposal.kind != "member":
                ok, note = await apply_proposal(proposal, session)
                proposal.status = "accepted" if ok else "failed"
                proposal.note = note
                if ok:
                    # Persistent in-chat toast, tethered to this turn (removed if
                    # the turn is later deleted/regenerated/swiped).
                    await event_ops.add_event(
                        session, turn_number=turn_number, kind="chronicler",
                        text=proposal.summary, tethered=True,
                    )
            else:
                proposal.status = "pending"

            session.add(proposal)
            proposals.append(proposal)
            log.info("CHRONICLER PROPOSAL turn=%s %s [%s]", turn_number, proposal.summary, proposal.status)

        await session.commit()
        return item_proposals + proposals
