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
import re

from sqlalchemy import select

from server.ai.openrouter import chat_completion_agent_turn, provider_endpoint
from server.db.database import new_session
from server.db import party as party_ops
from server.db.models import ChatMessage, NarratorConfig, OpenRouterSettings, Task

log = logging.getLogger("wayward.action_suggester")

# Tool-emitting call for a handful of short phrases. Kept modest, but with enough
# head-room that the tool-call JSON is never clipped mid-array — a truncated
# arguments blob is unparseable and used to drop the whole set (suggestions
# "cut off" or vanishing entirely). _extract_actions also salvages a clipped tail.
_MAX_TOKENS = 700
_MAX_OPTION_RULES = 6

# One generated option per rule, in order — the text-adventure choice spread.
# NarratorConfig.action_option_rules (Config → Agents & Tools) overrides these;
# blank/missing falls back here.
DEFAULT_OPTION_RULES: list[str] = [
    "A good-hearted, selfless, or merciful course of action.",
    "A neutral, practical, or cautious course of action.",
    "A self-serving, ruthless, or morally grey course of action.",
    "A bold, unexpected, or creative wildcard — any morality.",
]

ACTION_SUGGESTIONS_GUIDANCE = """You write the player's choices for a text adventure: short, concrete actions they could take next, based on the current scene.

Call suggest_actions with EXACTLY one phrase per OPTION RULE listed below, in that order. Each phrase must:
- Be written in the FIRST PERSON, starting with "I" — the player speaking as their character ("I push open the heavy door", "I ask Tifa about the ruins").
- Be short — 10 words or fewer.
- Be grounded in something specific just mentioned in the narration (an object, a person, a place, a choice) — not generic.
- Follow its own OPTION RULE — the rules exist so the choices feel meaningfully different from each other.
- Sound like THIS player character: when a PLAYER CHARACTER personality and drive are given, the options are that person's impulses — phrase them in their voice, and when the scene allows, let one speak to their drive.
- Not duplicate the always-available actions: waiting/continuing, looking around, resting, talking to the party, or using an item. Don't suggest attacking or fighting — there is no combat system.

Always call the tool — never reply with prose."""


# ── Inline mode ───────────────────────────────────────────────────
# When NarratorConfig.action_suggestions_mode == "inline", the options ride the
# main narration call instead of a separate one: the narrator is told to end
# its reply with a machine-read <<<OPTIONS>>> JSON line, which the stream
# drivers parse off and send in the `done` event. The separate suggester agent
# still serves reroll and the client's self-healing fetch.

INLINE_OPTIONS_MARKER = "<<<OPTIONS>>>"


def build_inline_options_guidance(rules: list[str]) -> str:
    return f"""ACTION OPTIONS: End your reply with one final line containing exactly {INLINE_OPTIONS_MARKER} immediately followed by a JSON array of {len(rules)} short choice phrases for the player — one per OPTION RULE below, in order. Each phrase: FIRST PERSON starting with "I", 10 words or fewer, grounded in what you just narrated, never attacking or fighting, and never duplicating the always-available actions (waiting, looking around, resting, talking to the party, using an item). The options are the PLAYER CHARACTER's impulses — phrase them in that character's voice, shaped by their Personality and Drive, and when the scene allows, let one speak to their drive.

OPTION RULES:
{_rules_block(rules)}

Example ending:
{INLINE_OPTIONS_MARKER}["I follow the smoky trail.", "I wait for nightfall.", "I pocket the coin purse.", "I climb the watchtower."]

The {INLINE_OPTIONS_MARKER} line is machine-read and never shown to the player. It must be the very last line of the reply — after it, write nothing."""


def parse_inline_options(text: str) -> tuple[str, list[str]]:
    """Strip a trailing ``<<<OPTIONS>>>[...]`` block from narration text.

    Returns ``(clean_text, options)``. Tolerant of malformed JSON (salvages the
    complete quoted strings) and of a missing block (returns the text as-is)."""
    if not text or INLINE_OPTIONS_MARKER not in text:
        return text, []
    head, _, tail = text.rpartition(INLINE_OPTIONS_MARKER)
    options: list[str] = []
    try:
        data = json.loads(tail.strip())
        if isinstance(data, list):
            options = [str(a) for a in data]
    except json.JSONDecodeError:
        options = [
            s.replace('\\"', '"').replace("\\\\", "\\")
            for s in re.findall(r'"((?:[^"\\]|\\.)*)"', tail)
        ]
    cleaned = [_to_first_person(str(a)) for a in options if str(a).strip()]
    return head.rstrip(), cleaned[:_MAX_OPTION_RULES]


def normalize_option_rules(raw) -> list[str]:
    """Player-configured rules → a clean list (non-blank, capped), falling back
    to the defaults."""
    rules = [str(r).strip() for r in raw if str(r).strip()] if isinstance(raw, list) else []
    return rules[:_MAX_OPTION_RULES] or list(DEFAULT_OPTION_RULES)


def _rules_block(rules: list[str]) -> str:
    return "\n".join(f"OPTION {i + 1} must be: {r}" for i, r in enumerate(rules))


def _tool_schema(n: int) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": "suggest_actions",
                "description": "Propose the player's next choices — one short action phrase per option rule, in order.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "actions": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": n,
                            "maxItems": n,
                            "description": f"Exactly {n} short first-person action phrases starting with 'I', option i following option rule i.",
                        },
                    },
                    "required": ["actions"],
                },
            },
        },
    ]


def _extract_actions(raw: str) -> list[str]:
    """Best-effort list of phrases from a ``suggest_actions`` arguments blob.

    The happy path is well-formed JSON. But if the tool call was clipped by the
    token budget the JSON is truncated and unparseable — rather than lose every
    suggestion, salvage the complete double-quoted strings from the ``actions``
    array so the phrases that DID come through survive."""
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, dict) and isinstance(data.get("actions"), list):
            return [str(a) for a in data["actions"]]
    except json.JSONDecodeError:
        pass
    # Salvage: pull complete "..."-quoted literals following the actions key.
    m = re.search(r'"actions"\s*:\s*\[(.*)', raw, re.DOTALL)
    segment = m.group(1) if m else raw
    return [
        s.replace('\\"', '"').replace("\\\\", "\\")
        for s in re.findall(r'"((?:[^"\\]|\\.)*)"', segment)
    ]


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
    async def _latest(col):
        return (
            await session.execute(
                select(col)
                .where(
                    ChatMessage.turn_number <= turn_number,
                    ChatMessage.mode == "narrator",
                    col.is_not(None),
                )
                .order_by(ChatMessage.id.desc())
            )
        ).scalars().first()

    return {
        "location": await _latest(ChatMessage.location),
        "timeOfDay": await _latest(ChatMessage.time_of_day),
        "weather": await _latest(ChatMessage.weather),
    }


async def _recent_exchanges(session, turn_number: int, prior_turns: int = 2) -> list[str]:
    """The last few player↔narrator exchanges (a little history for continuity),
    each clipped. Uses the active variant per turn, narrator thread only."""
    start_turn = max(1, turn_number - prior_turns + 1)
    msgs = (
        await session.execute(
            select(ChatMessage)
            .where(
                ChatMessage.turn_number >= start_turn,
                ChatMessage.turn_number <= turn_number,
                ChatMessage.mode == "narrator",
            )
            .order_by(ChatMessage.id)
        )
    ).scalars().all()

    lines: list[str] = []
    for t in range(start_turn, turn_number + 1):
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

    # The PC's personality and drive are MAJOR context — options are the
    # character's impulses, so they should sound like this specific person.
    lines: list[str] = []
    pc = await party_ops.load_pc(session)
    if pc is not None:
        info = pc.basic_info or {}
        pc_lines = [f"PLAYER CHARACTER: {info.get('name') or 'Unknown'}"]
        if info.get("personality"):
            pc_lines.append(f"  Personality: {info['personality']}")
        if info.get("drive"):
            pc_lines.append(f"  Drive (what pushes them forward): {info['drive']}")
        if len(pc_lines) > 1:
            lines.extend(pc_lines)
            lines.append("")

    lines.append("CURRENT SCENE:")
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
        if not settings:
            return []
        base_url, api_key, main_model = provider_endpoint(settings)
        if not api_key or not main_model:
            return []

        model_id = settings.action_suggestions_model_id or main_model
        # Custom guidance (Config → Agents & Tools) overrides the built-in
        # preamble; the per-slot OPTION RULES are always appended after it.
        preamble = getattr(narrator, "action_suggestions_instructions", "") or ACTION_SUGGESTIONS_GUIDANCE
        rules = normalize_option_rules(getattr(narrator, "action_option_rules", None))
        guidance = f"{preamble}\n\nOPTION RULES:\n{_rules_block(rules)}"
        context = await _build_context(session, turn_number)

        messages = [
            {"role": "system", "content": guidance},
            {"role": "user", "content": context},
        ]

        log.info("ACTION-SUGGEST REQUEST turn=%s | model=%s", turn_number, model_id)

        # The panel is the primary interaction, so a flaky response (no tool
        # call, empty list) gets one automatic retry at a lower temperature
        # before we give up and let the client's REROLL take over.
        for attempt, temperature in enumerate((0.9, 0.7)):
            tool_calls: list[dict] = []
            try:
                async for ev in chat_completion_agent_turn(
                    api_key=api_key,
                    model_id=model_id,
                    base_url=base_url,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=_MAX_TOKENS,
                    tools=_tool_schema(len(rules)),
                ):
                    if ev["type"] == "result":
                        tool_calls = ev["tool_calls"]
            except Exception:
                log.exception("Action-suggester call failed (attempt %s)", attempt + 1)
                continue

            for tc in tool_calls:
                if tc["name"] != "suggest_actions":
                    continue
                actions = _extract_actions(tc["arguments"])
                cleaned = [_to_first_person(a) for a in actions if a.strip()]
                if cleaned:
                    return cleaned[: len(rules)]

            log.info(
                "ACTION-SUGGEST no usable tool call turn=%s | model=%s | attempt=%s",
                turn_number, model_id, attempt + 1,
            )

        return []
