"""Action Suggestions — a lightweight one-shot agent.

Runs after a narrator turn (opt-in, per campaign) to propose a handful of
short, scene-specific action phrases the player might want to try next.
Unlike the Chronicler (``worldbuilder.py``) this makes no database writes and
keeps no state: it's a single tool call that returns a plain list of strings,
displayed as buttons for the current turn only. A page refresh or a new turn
simply regenerates them.

See CLAUDE.md > The Chronicler (this feature follows the same one-shot
``chat_completion_agent_turn`` pattern, scaled down).
"""

import json
import logging

from sqlalchemy import select

from server.ai.openrouter import chat_completion_agent_turn
from server.db.database import new_session
from server.db import party as party_ops
from server.db.models import ChatMessage, NarratorConfig, OpenRouterSettings, Task

log = logging.getLogger("wayward.action_suggester")

# Tool-emitting call for a handful of short phrases — small budget by design.
_MAX_TOKENS = 300
_MAX_SUGGESTIONS = 4

GUIDANCE = """You suggest short, concrete actions the player could try next, based on the current scene.

Call suggest_actions with 0-4 phrases. Each phrase should:
- Be written in the FIRST PERSON, starting with "I" — the player speaking as their character ("I push open the heavy door", "I ask Tifa about the ruins").
- Be short — under 8 words.
- Be grounded in something specific just mentioned in the narration (an object, a person, a place, a choice) — not generic.
- Never duplicate these already-available buttons: looking around, resting, talking to the party, or using an item. Don't suggest attacking or fighting — there is no combat system.

If the scene doesn't support any good specific suggestions, call suggest_actions with an empty list. Always call the tool — never reply with prose."""

TOOL_SCHEMA: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "suggest_actions",
            "description": "Propose short, scene-specific action phrases for the player to choose from.",
            "parameters": {
                "type": "object",
                "properties": {
                    "actions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": _MAX_SUGGESTIONS,
                        "description": "0-4 short first-person action phrases starting with 'I', e.g. 'I ask Tifa about the ruins'.",
                    },
                },
                "required": ["actions"],
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


def _clip(text: str, limit: int) -> str:
    text = text or ""
    return text if len(text) <= limit else text[:limit].rstrip() + " …"


def _to_first_person(phrase: str) -> str:
    """Deterministic backstop so every suggestion reads as the player speaking:
    ensure it starts with a first-person "I". Already-first-person phrases ("I",
    "I'm", "I'll", "I've") are left alone; an imperative ("Push the door") becomes
    "I push the door" (first letter lowercased so it reads naturally)."""
    p = (phrase or "").strip()
    if not p:
        return p
    # Already first-person: "I ...", "I'm ...", "I'll ...", or a bare "I".
    if p == "I" or p[:2] in ("I ", "I'") or (p[0] == "I" and (len(p) == 1 or not p[1].isalpha())):
        return p
    first, rest = p[0], p[1:]
    # Lowercase the leading letter of a normal word (keep all-caps/proper-ish
    # openings like acronyms untouched — rare for these short phrases).
    lead = first.lower() if first.isalpha() and not rest[:1].isupper() else first
    return f"I {lead}{rest}"


async def _latest_scene_fields(session, turn_number: int) -> dict:
    """Latest non-null location/time/weather declared up to this turn — same
    'most recent wins' rule the client uses in lib/location.ts."""
    msgs = (
        await session.execute(
            select(ChatMessage)
            .where(ChatMessage.turn_number <= turn_number, ChatMessage.mode == "narrator")
            .order_by(ChatMessage.id)
        )
    ).scalars().all()
    location = time_of_day = weather = None
    for m in msgs:
        if m.location:
            location = m.location
        if m.time_of_day:
            time_of_day = m.time_of_day
        if m.weather:
            weather = m.weather
    return {"location": location, "timeOfDay": time_of_day, "weather": weather}


async def _recent_exchanges(session, turn_number: int, prior_turns: int = 2) -> list[str]:
    """The last few player↔narrator exchanges (a little history for continuity),
    each clipped. Uses the active variant per turn, narrator thread only."""
    msgs = (
        await session.execute(
            select(ChatMessage)
            .where(ChatMessage.turn_number <= turn_number, ChatMessage.mode == "narrator")
            .order_by(ChatMessage.id)
        )
    ).scalars().all()

    lines: list[str] = []
    for t in range(max(1, turn_number - prior_turns + 1), turn_number + 1):
        player = next((m for m in msgs if m.turn_number == t and m.role == "user"), None)
        variants = [m for m in msgs if m.turn_number == t and m.role == "assistant"]
        narration = max(variants, key=lambda m: m.variant).content if variants else ""
        # The just-played turn gets more room; older turns are summarised tighter.
        narr_budget = 900 if t == turn_number else 300
        if player:
            lines.append(f"  [Player] {_clip(player.content, 300)}")
        if narration:
            lines.append(f"  [Narrator] {_clip(narration, narr_budget)}")
    return lines


async def _build_context(session, turn_number: int) -> str:
    """A compact scene snapshot plus a couple of recent exchanges for continuity
    — deliberately not a full world-state dump."""
    scene = await _latest_scene_fields(session, turn_number)

    members = [m for m in await party_ops.load_party(session) if m.in_party]
    member_names = [m.basic_info.get("name", "") for m in members if m.basic_info.get("name")]

    tasks = (
        await session.execute(select(Task).where(Task.status == "active"))
    ).scalars().all()
    task_texts = [t.text for t in tasks if t.text]

    lines = ["CURRENT SCENE:"]
    if scene["location"]:
        lines.append(f"  Location: {scene['location']}")
    if scene["timeOfDay"]:
        lines.append(f"  Time: {scene['timeOfDay']}")
    if scene["weather"]:
        lines.append(f"  Weather: {scene['weather']}")
    if member_names:
        lines.append(f"  Party: {', '.join(member_names)}")
    if task_texts:
        lines.append(f"  Active tasks: {', '.join(task_texts)}")
    lines.append("")
    lines.append("RECENT EXCHANGES (oldest first; suggest what fits the latest beat):")
    lines.extend(await _recent_exchanges(session, turn_number))
    return "\n".join(lines)


async def run_action_suggester(turn_number: int) -> list[str]:
    """Run the action-suggestion agent for a turn. Returns a plain list of
    short action strings (possibly empty). Never raises — any failure
    (disabled, missing key, bad/missing tool call, HTTP error) yields []."""
    if turn_number <= 0:
        return []

    async with new_session() as session:
        narrator = (await session.execute(select(NarratorConfig))).scalars().first()
        if not narrator or not narrator.action_suggestions_enabled:
            return []

        settings = (await session.execute(select(OpenRouterSettings))).scalars().first()
        if not settings or not settings.api_key or not settings.model_id:
            return []

        model_id = settings.action_suggestions_model_id or settings.model_id
        context = await _build_context(session, turn_number)

        messages = [
            {"role": "system", "content": GUIDANCE},
            {"role": "user", "content": context},
        ]

        log.info("ACTION-SUGGEST REQUEST turn=%s | model=%s", turn_number, model_id)

        tool_calls: list[dict] = []
        try:
            async for ev in chat_completion_agent_turn(
                api_key=settings.api_key,
                model_id=model_id,
                messages=messages,
                temperature=0.9,
                max_tokens=_MAX_TOKENS,
                tools=TOOL_SCHEMA,
            ):
                if ev["type"] == "result":
                    tool_calls = ev["tool_calls"]
        except Exception:
            log.exception("Action-suggester call failed")
            return []

        for tc in tool_calls:
            if tc["name"] != "suggest_actions":
                continue
            args = _parse_args(tc["arguments"])
            actions = args.get("actions")
            if isinstance(actions, list):
                cleaned = [_to_first_person(str(a)) for a in actions if str(a).strip()]
                return cleaned[:_MAX_SUGGESTIONS]

        log.info("ACTION-SUGGEST no tool call turn=%s | model=%s", turn_number, model_id)
        return []
