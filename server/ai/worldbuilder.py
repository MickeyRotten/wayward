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

from server.ai.openrouter import chat_completion_agent_turn
from server.db.database import new_session
from server.db.models import (
    ChatMessage,
    LorebookEntry,
    OpenRouterSettings,
    PartyMember,
    PlayerCharacter,
    Quest,
    QuestObjective,
    WorldbuildingProposal,
)

log = logging.getLogger("wayward.worldbuilder")

LORE_CATS = {"world", "characters", "items", "monsters", "spells"}
QUEST_STATUSES = {"active", "completed", "failed"}

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
- create_lore / update_lore — record new places, characters (NPCs), items, monsters, or spells that the fiction has established, or update an existing entry with new facts. Pick the right category.
- create_quest / add_objective / update_objective / update_quest_status — capture goals the party has taken on and their progress.
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
- world (places) — Describe the place generically and permanently. Nothing about the party, what they did there this turn, or transient events.
- monsters — Describe the creature/type in general (appearance, behaviour, danger), not this one encounter's outcome.
- spells — Describe the spell's effect and limits in general, not who cast it just now.
- characters (NPCs) — Describe the person: who they are, appearance, role. Not the party's momentary interaction with them."""


TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "create_lore",
            "description": "Record a new lorebook entry for something the fiction has established. For cat='items', ALSO set itemType (and slot for Equipment).",
            "parameters": {
                "type": "object",
                "properties": {
                    "cat": {"type": "string", "enum": sorted(LORE_CATS)},
                    "title": {"type": "string", "description": "Short name, e.g. 'Sunken Chapel'."},
                    "content": {"type": "string", "description": "A concise descriptive paragraph. For items, describe the item itself — not who holds it."},
                    "keywords": {"type": "array", "items": {"type": "string"}},
                    "itemType": {"type": "string", "enum": ["Equipment", "Tool", "Consumable", "Key Item", "Artifact", "Other"], "description": "Items only. The kind of item."},
                    "slot": {"type": "string", "enum": ["Head", "Neck", "Torso", "Hands", "Waist", "Legs", "Feet", "Accessory"], "description": "Equipment items only. The body slot it's worn in."},
                    "rarity": {"type": "string", "enum": ["c", "u", "r", "e", "l"], "description": "Items only. c=common u=uncommon r=rare e=epic l=legendary."},
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
                },
                "required": ["title", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_quest",
            "description": "Record a new goal the party has taken on.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "desc": {"type": "string"},
                    "objectives": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_objective",
            "description": "Add an objective to an existing quest, by the quest's exact title.",
            "parameters": {
                "type": "object",
                "properties": {
                    "questTitle": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["questTitle", "text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_objective",
            "description": "Mark an existing objective done/undone, matched by quest title + objective text.",
            "parameters": {
                "type": "object",
                "properties": {
                    "questTitle": {"type": "string"},
                    "objectiveText": {"type": "string"},
                    "done": {"type": "boolean"},
                },
                "required": ["questTitle", "objectiveText", "done"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_quest_status",
            "description": "Set a quest's status (active/completed/failed), by its exact title.",
            "parameters": {
                "type": "object",
                "properties": {
                    "questTitle": {"type": "string"},
                    "status": {"type": "string", "enum": sorted(QUEST_STATUSES)},
                },
                "required": ["questTitle", "status"],
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


async def _resolve_quest(session: AsyncSession, title: str) -> Quest | None:
    if not title:
        return None
    return (
        await session.execute(
            select(Quest).where(func.lower(Quest.title) == title.lower())
        )
    ).scalars().first()


async def _member_exists(session: AsyncSession, name: str) -> bool:
    members = (await session.execute(select(PartyMember))).scalars().all()
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
    quests = (await session.execute(select(Quest))).scalars().all()
    members = (await session.execute(select(PartyMember).where(PartyMember.in_party == True))).scalars().all()  # noqa: E712

    lines = ["CURRENT WORLD STATE (reuse these exact names; update rather than duplicate):"]
    for cat in ("world", "characters", "items", "monsters", "spells"):
        titles = by_cat.get(cat, [])
        lines.append(f"  {cat}: {', '.join(titles) if titles else '(none)'}")
    if quests:
        lines.append("  quests: " + ", ".join(f"{q.title} [{q.status}]" for q in quests))
    else:
        lines.append("  quests: (none)")
    member_names = [m.basic_info.get("name", "?") for m in members]
    lines.append(f"  party members: {', '.join(member_names) if member_names else '(none)'}")
    return "\n".join(lines)


async def _latest_narration(session: AsyncSession, turn_number: int) -> str:
    """The active narration for this turn (highest variant), for the bolded-item check."""
    msgs = (await session.execute(
        select(ChatMessage).where(
            ChatMessage.turn_number == turn_number, ChatMessage.role == "assistant"
        )
    )).scalars().all()
    return max(msgs, key=lambda m: m.variant).content if msgs else ""


def _clip(text: str, limit: int) -> str:
    text = text or ""
    return text if len(text) <= limit else text[:limit].rstrip() + " …"


async def _known_name_tokens(session: AsyncSession) -> set[str]:
    """Lowercased word tokens of every known proper name (lore/quest titles, party
    members, PC) — so the pre-filter doesn't re-trigger on names already recorded."""
    lore = (await session.execute(select(LorebookEntry))).scalars().all()
    quests = (await session.execute(select(Quest))).scalars().all()
    members = (await session.execute(select(PartyMember))).scalars().all()
    pc = (await session.execute(select(PlayerCharacter))).scalars().first()
    names = [e.title for e in lore] + [q.title for q in quests]
    names += [m.basic_info.get("name", "") for m in members]
    if pc:
        names.append(pc.basic_info.get("name", ""))
    tokens: set[str] = set()
    for n in names:
        for tok in re.findall(r"[A-Za-z'’-]{2,}", n or ""):
            tokens.add(tok.lower())
    return tokens


async def _turn_context(session: AsyncSession, turn_number: int) -> str:
    """The just-played turn (player + latest narration) plus a little prior
    context. Content is clipped to keep this second LLM pass lean."""
    msgs = (
        await session.execute(select(ChatMessage).order_by(ChatMessage.id))
    ).scalars().all()

    player = next((m for m in msgs if m.turn_number == turn_number and m.role == "user"), None)
    variants = [m for m in msgs if m.turn_number == turn_number and m.role == "assistant"]
    narration = max(variants, key=lambda m: m.variant).content if variants else ""

    # Two prior turns for continuity, each clipped.
    prior = [m for m in msgs if m.turn_number < turn_number][-2:]
    lines = ["RECENT CONTEXT:"]
    for m in prior:
        who = "Player" if m.role == "user" else "Narrator"
        lines.append(f"  [{who}] {_clip(m.content, 280)}")
    lines.append("")
    lines.append("THE TURN TO RECORD:")
    if player:
        lines.append(f"  [Player] {_clip(player.content, 400)}")
    lines.append(f"  [Narrator] {_clip(narration, 1600)}")
    return "\n".join(lines)


def _summary(kind: str, operation: str, payload: dict, target_title: str | None = None) -> str:
    if kind == "lore":
        verb = "Add lore" if operation == "create" else "Update lore"
        return f"{verb}: {payload.get('title') or target_title or '?'}"
    if kind == "quest":
        if operation == "create":
            return f"New quest: {payload.get('title', '?')}"
        return f"Quest {payload.get('status', 'update')}: {target_title or '?'}"
    if kind == "quest_objective":
        if operation == "create":
            return f"Objective on {target_title or '?'}: {payload.get('text', '')[:40]}"
        return f"Objective {'done' if payload.get('done') else 'reopened'} on {target_title or '?'}"
    if kind == "member":
        return f"Recruit member: {payload.get('name', '?')}"
    return f"{kind} {operation}"


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
        return WorldbuildingProposal(
            turn_number=turn_number, kind="lore", operation="update",
            target_id=existing.id, payload=payload,
            summary=_summary("lore", "update", payload, existing.title),
        )

    if name == "create_quest":
        title = (args.get("title") or "").strip()
        if not title or await _resolve_quest(session, title):
            return None
        payload = {"title": title, "desc": args.get("desc", ""), "objectives": args.get("objectives", [])}
        return WorldbuildingProposal(
            turn_number=turn_number, kind="quest", operation="create",
            payload=payload, summary=_summary("quest", "create", payload),
        )

    if name == "add_objective":
        quest = await _resolve_quest(session, (args.get("questTitle") or "").strip())
        text = (args.get("text") or "").strip()
        if not quest or not text:
            return None
        payload = {"text": text}
        return WorldbuildingProposal(
            turn_number=turn_number, kind="quest_objective", operation="create",
            target_id=quest.id, payload=payload,
            summary=_summary("quest_objective", "create", payload, quest.title),
        )

    if name == "update_objective":
        quest = await _resolve_quest(session, (args.get("questTitle") or "").strip())
        if not quest:
            return None
        obj_text = (args.get("objectiveText") or "").strip().lower()
        objs = (
            await session.execute(select(QuestObjective).where(QuestObjective.quest_id == quest.id))
        ).scalars().all()
        match = next((o for o in objs if o.text.lower() == obj_text), None)
        if not match:
            return None
        payload = {"done": bool(args.get("done"))}
        return WorldbuildingProposal(
            turn_number=turn_number, kind="quest_objective", operation="update",
            target_id=match.id, payload=payload,
            summary=_summary("quest_objective", "update", payload, quest.title),
        )

    if name == "update_quest_status":
        quest = await _resolve_quest(session, (args.get("questTitle") or "").strip())
        status = args.get("status")
        if not quest or status not in QUEST_STATUSES:
            return None
        payload = {"status": status}
        return WorldbuildingProposal(
            turn_number=turn_number, kind="quest", operation="update",
            target_id=quest.id, payload=payload,
            summary=_summary("quest", "update", payload, quest.title),
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
        _snapshot_prev(proposal, {"content": entry.content, "keywords": list(entry.keywords or [])})
        if p.get("content") is not None:
            entry.content = p["content"]
        if p.get("keywords") is not None:
            entry.keywords = p["keywords"]
        return True, None

    if kind == "quest" and op == "create":
        quest = Quest(title=p.get("title", ""), desc=p.get("desc", ""), status="active")
        session.add(quest)
        await session.flush()
        for i, text in enumerate(p.get("objectives", []) or []):
            session.add(QuestObjective(quest_id=quest.id, text=text, sort_order=i))
        proposal.target_id = quest.id  # tie the created quest to this proposal/turn
        return True, None

    if kind == "quest" and op == "update":
        quest = await session.get(Quest, proposal.target_id)
        if not quest:
            return False, "Quest no longer exists."
        _snapshot_prev(proposal, {"status": quest.status, "desc": quest.desc})
        if p.get("status"):
            quest.status = p["status"]
        if p.get("desc") is not None:
            quest.desc = p["desc"]
        return True, None

    if kind == "quest_objective" and op == "create":
        quest = await session.get(Quest, proposal.target_id)
        if not quest:
            return False, "Quest no longer exists."
        max_order = (await session.execute(
            select(func.coalesce(func.max(QuestObjective.sort_order), -1))
            .where(QuestObjective.quest_id == quest.id)
        )).scalar()
        session.add(QuestObjective(quest_id=quest.id, text=p.get("text", ""), sort_order=(max_order or 0) + 1))
        return True, None

    if kind == "quest_objective" and op == "update":
        obj = await session.get(QuestObjective, proposal.target_id)
        if not obj:
            return False, "Objective no longer exists."
        _snapshot_prev(proposal, {"done": obj.done, "text": obj.text})
        if p.get("done") is not None:
            obj.done = bool(p["done"])
        if p.get("text") is not None:
            obj.text = p["text"]
        return True, None

    if kind == "member" and op == "create":
        settings = (await session.execute(select(OpenRouterSettings))).scalars().first()
        max_size = settings.max_party_size if settings else 3
        active = (await session.execute(
            select(func.count()).select_from(PartyMember).where(PartyMember.in_party == True)  # noqa: E712
        )).scalar()
        if active >= max_size:
            return False, "Party is full."
        # Promote a lorebook character into the party: if a matching lore
        # 'characters' entry exists, remove it (the character now lives as a
        # party member) and reuse its description if the proposal lacks one.
        absorbed = await _absorb_lore_character(session, p.get("name", ""))
        description = p.get("description", "") or (absorbed or "")
        session.add(PartyMember(
            basic_info={
                "name": p.get("name", ""), "species": p.get("species", ""),
                "description": description, "personality": p.get("personality", ""),
                "gender": "", "age": 0, "heightCm": 0, "weightKg": 0,
                "portrait": "", "likes": "", "dislikes": "",
            },
            equipment={},
            field_skill={"name": p.get("fieldSkillName", ""), "description": p.get("fieldSkillDescription", "")},
        ))
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
            return True
        return False

    if kind == "quest" and op == "create":
        quest = await session.get(Quest, p.target_id) if p.target_id else None
        if quest is not None:
            objs = (await session.execute(
                select(QuestObjective).where(QuestObjective.quest_id == quest.id)
            )).scalars().all()
            for o in objs:
                await session.delete(o)
            await session.delete(quest)
            return True
        return False

    if kind == "quest" and op == "update":
        quest = await session.get(Quest, p.target_id) if p.target_id else None
        if quest is not None and prev:
            if "status" in prev:
                quest.status = prev["status"]
            if "desc" in prev:
                quest.desc = prev["desc"]
            return True
        return False

    if kind == "quest_objective" and op == "create":
        obj = await session.get(QuestObjective, p.target_id) if p.target_id else None
        if obj is not None:
            await session.delete(obj)
            return True
        return False

    if kind == "quest_objective" and op == "update":
        obj = await session.get(QuestObjective, p.target_id) if p.target_id else None
        if obj is not None and prev:
            if "done" in prev:
                obj.done = bool(prev["done"])
            if "text" in prev:
                obj.text = prev["text"]
            return True
        return False

    return False  # member creations and anything else are left in place


async def reverse_chronicler_effects(
    session: AsyncSession, from_turn: int, *, exact: bool = False
) -> int:
    """Undo the Chronicler's lore/quest effects on the given turn(s) and drop the
    turn's proposal rows.

    Chronicler suggestions are tied to the message that triggered them: when that
    message is deleted, regenerated, or swiped, the entries it spawned (or the
    edits it made) are undone and its proposals cleared, so the re-run records a
    fresh set. We use the proposal rows as the link (turn_number + the target_id
    recorded at apply time).

    - *accepted* create/update proposals (lore, quests, objectives) are reversed
      — creates deleted, updates restored from their ``_prev`` snapshot;
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
    return reversed_count


async def run_worldbuilder(turn_number: int) -> list[WorldbuildingProposal]:
    """Run the Chronicler for a turn. Returns the proposals it produced.

    Clears any stale 'pending' proposals for this turn first (so swipe/regen
    don't accumulate duplicates). No-op when mode is 'disabled'.
    """
    async with new_session() as session:
        settings = (await session.execute(select(OpenRouterSettings))).scalars().first()
        if not settings or not settings.api_key or not settings.model_id:
            return []
        mode = settings.worldbuilding_mode or "confirmation"
        if mode == "disabled":
            return []

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
        narration = await _latest_narration(session, turn_number)
        known_tokens = await _known_name_tokens(session)
        if not _worth_chronicling(narration, known_tokens):
            await session.commit()  # persist the stale-pending cleanup
            log.info("CHRONICLER SKIP turn=%s (no new signals)", turn_number)
            return []

        world_state = await _build_world_state(session)
        turn_ctx = await _turn_context(session, turn_number)
        model_id = settings.worldbuilding_model_id or settings.model_id

        # Guard data for the deterministic rule backstop: every party member
        # (incl. benched) and the PC must never be filed as lore, and item
        # entries are only allowed if the item was **bolded** in this narration.
        all_members = (await session.execute(select(PartyMember))).scalars().all()
        member_names = {m.basic_info.get("name", "").strip().lower() for m in all_members if m.basic_info.get("name")}
        pc = (await session.execute(select(PlayerCharacter))).scalars().first()
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
                api_key=settings.api_key, model_id=model_id, messages=messages,
                temperature=0.4,
                max_tokens=min(settings.max_tokens_response, _CHRONICLER_MAX_TOKENS),
                tools=TOOL_SCHEMAS,
            ):
                if ev["type"] == "result":
                    tool_calls = ev["tool_calls"]
        except Exception:
            log.exception("Chronicler call failed")
            return []

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

            # Apply policy: auto applies lore/quest now; members always pending.
            if mode == "auto" and proposal.kind != "member":
                ok, note = await apply_proposal(proposal, session)
                proposal.status = "accepted" if ok else "failed"
                proposal.note = note
            else:
                proposal.status = "pending"

            session.add(proposal)
            proposals.append(proposal)
            log.info("CHRONICLER PROPOSAL turn=%s %s [%s]", turn_number, proposal.summary, proposal.status)

        await session.commit()
        return proposals
