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

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.ai.openrouter import chat_completion_agent_turn
from server.db.database import new_session
from server.db.models import (
    ChatMessage,
    LorebookEntry,
    OpenRouterSettings,
    PartyMember,
    Quest,
    QuestObjective,
    WorldbuildingProposal,
)

log = logging.getLogger("wayward.worldbuilder")

LORE_CATS = {"world", "characters", "items", "monsters", "spells"}
QUEST_STATUSES = {"active", "completed", "failed"}


CHRONICLER_GUIDANCE = """You are the Chronicler: a quiet archivist who keeps the world's records as an adventure unfolds. You do NOT narrate. After each turn you review what just happened and record only what genuinely changed.

Use your tools to:
- create_lore / update_lore — record new places, characters (NPCs), items, monsters, or spells that the fiction has established, or update an existing entry with new facts. Pick the right category.
- create_quest / add_objective / update_objective / update_quest_status — capture goals the party has taken on and their progress.
- create_member — ONLY when a character has clearly and deliberately joined the party as a travelling companion.

Rules:
- Be conservative. Most turns establish nothing new — in that case, call no tools at all.
- Prefer updating an existing entry over creating a near-duplicate. You are given the current world state; reuse those exact names.
- Record only things the narration actually established as fact — do not invent.
- Never record the player character or transient mood as lore.
- Keep entries concise and concrete: a short descriptive paragraph, not a story."""


TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "create_lore",
            "description": "Record a new lorebook entry for something the fiction has established.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cat": {"type": "string", "enum": sorted(LORE_CATS)},
                    "title": {"type": "string", "description": "Short name, e.g. 'Sunken Chapel'."},
                    "content": {"type": "string", "description": "A concise descriptive paragraph."},
                    "keywords": {"type": "array", "items": {"type": "string"}},
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


async def _turn_context(session: AsyncSession, turn_number: int) -> str:
    """The just-played turn (player + latest narration) plus a little prior context."""
    msgs = (
        await session.execute(select(ChatMessage).order_by(ChatMessage.id))
    ).scalars().all()

    player = next((m for m in msgs if m.turn_number == turn_number and m.role == "user"), None)
    variants = [m for m in msgs if m.turn_number == turn_number and m.role == "assistant"]
    narration = max(variants, key=lambda m: m.variant).content if variants else ""

    # A couple of prior turns for continuity.
    prior = [m for m in msgs if m.turn_number < turn_number][-4:]
    lines = ["RECENT CONTEXT:"]
    for m in prior:
        who = "Player" if m.role == "user" else "Narrator"
        lines.append(f"  [{who}] {m.content}")
    lines.append("")
    lines.append("THE TURN TO RECORD:")
    if player:
        lines.append(f"  [Player] {player.content}")
    lines.append(f"  [Narrator] {narration}")
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
    session: AsyncSession, turn_number: int, name: str, args: dict
) -> WorldbuildingProposal | None:
    """Convert one Chronicler tool call into a proposal, resolving names/dedup."""
    if name == "create_lore":
        cat = args.get("cat")
        title = (args.get("title") or "").strip()
        if cat not in LORE_CATS or not title:
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
        payload = {"cat": cat, "title": title, "content": args.get("content", ""), "keywords": args.get("keywords", [])}
        return WorldbuildingProposal(
            turn_number=turn_number, kind="lore", operation="create",
            payload=payload, summary=_summary("lore", "create", payload),
        )

    if name == "update_lore":
        title = (args.get("title") or "").strip()
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
        if not mname or await _member_exists(session, mname):
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


async def apply_proposal(proposal: WorldbuildingProposal, session: AsyncSession) -> tuple[bool, str | None]:
    """Execute a proposal's write against the DB. Returns (ok, note)."""
    p = proposal.payload or {}
    kind, op = proposal.kind, proposal.operation

    if kind == "lore" and op == "create":
        session.add(LorebookEntry(
            title=p.get("title", ""), content=p.get("content", ""),
            keywords=p.get("keywords") or [], cat=p.get("cat", "world"),
        ))
        return True, None

    if kind == "lore" and op == "update":
        entry = await session.get(LorebookEntry, proposal.target_id)
        if not entry:
            return False, "Lore entry no longer exists."
        if entry.locked:
            return False, "Entry is locked."
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
        return True, None

    if kind == "quest" and op == "update":
        quest = await session.get(Quest, proposal.target_id)
        if not quest:
            return False, "Quest no longer exists."
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
        session.add(PartyMember(
            basic_info={
                "name": p.get("name", ""), "species": p.get("species", ""),
                "description": p.get("description", ""), "personality": p.get("personality", ""),
                "gender": "", "age": 0, "heightCm": 0, "weightKg": 0,
                "portrait": "", "likes": "", "dislikes": "",
            },
            equipment={},
            field_skill={"name": p.get("fieldSkillName", ""), "description": p.get("fieldSkillDescription", "")},
        ))
        return True, None

    return False, f"Unknown proposal {kind}/{op}."


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

        # Clear stale pending proposals for this turn.
        stale = (await session.execute(
            select(WorldbuildingProposal).where(
                WorldbuildingProposal.turn_number == turn_number,
                WorldbuildingProposal.status == "pending",
            )
        )).scalars().all()
        for s in stale:
            await session.delete(s)
        await session.flush()

        world_state = await _build_world_state(session)
        turn_ctx = await _turn_context(session, turn_number)
        model_id = settings.worldbuilding_model_id or settings.model_id

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
                temperature=0.4, max_tokens=settings.max_tokens_response,
                tools=TOOL_SCHEMAS,
            ):
                if ev["type"] == "result":
                    tool_calls = ev["tool_calls"]
        except Exception:
            log.exception("Chronicler call failed")
            return []

        proposals: list[WorldbuildingProposal] = []
        for tc in tool_calls:
            args = _parse_args(tc["arguments"])
            proposal = await _proposal_from_call(session, turn_number, tc["name"], args)
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
