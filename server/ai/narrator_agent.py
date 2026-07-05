"""Agentic narrator loop.

Instead of asking the model to append a parseable ``<<<ACTIONS>>>`` text block,
the narrator runs as a multi-step agent: it can call tools (look items up,
grant/equip, set the scene, consume an item, update the summary), see the
results, and continue over several round-trips before writing the final prose.

One agent run == one player turn, but possibly several model round-trips. The
``max_tool_rounds`` setting caps the loop. Tool execution mutates the DB *during*
the loop (so the model sees real outcomes); the accumulated deltas are returned
so the route can record them on the ChatMessage for swipe/regenerate reversal —
exactly like the legacy path.

See CLAUDE.md > The Narrator Agent Loop.
"""

import json
import logging
from collections.abc import AsyncGenerator

from server.ai.narrator_actions import (
    ToolEffect,
    tool_consume_item,
    tool_equip,
    tool_get_character,
    tool_grant_item,
    tool_list_inventory,
    tool_lookup_item,
    tool_remove_item,
    tool_search_items,
    tool_set_scene,
    tool_unequip,
)
from server.ai.openrouter import chat_completion_agent_turn
from server.db.database import new_session

log = logging.getLogger("wayward.narrator_agent")


TOOL_GUIDANCE = """You have tools for changing and reading game state. Use them like this:
- Call tools FIRST, in their own messages. Do NOT write narration in the same message as a tool call.
- When you grant or equip an item, it must already exist in the world. If unsure, call lookup_item or search_items before grant_item/equip — guessing a name that doesn't exist does nothing.
- Use set_scene whenever the location, time of day, or weather is first established or changes. Also set the in-game `day` (starting at 1) when a new day begins — e.g. after the party sleeps or time skips to the next morning — incrementing by 1 each new day.
- Use consume_item when the player uses up an item they carry (e.g. drinks a potion).
- The inventory is the PLAYER PARTY's inventory only — NPCs and monsters do not have inventories you track.
  - The player giving/handing/selling an item to an NPC (anyone NOT in the player's party) is a single remove_item — it leaves the party's inventory. Do NOT grant_item then remove_item (that nets to zero and is wrong). If the party never actually had that item, change no inventory at all — just narrate.
  - Only grant_item when the party GAINS an item (found, bought, looted, received as a gift). Handing between party members changes nothing — the party still owns it.
- Once all needed tool calls are done, write the narration in a final message with NO tool calls. That final message is the only text the player sees.
- Most turns need no tools at all — just narrate."""

# Always injected, so the narration renders nicely in the JRPG-styled chat even
# if the user cleared their editable narrator instructions. The conventions here
# are recognised by the client renderer (party dialogue → portrait dialogue box;
# *italics*/**bold**; "> " → inscription inset; "* * *" → scene-break divider).
FORMATTING_GUIDE = """Format the narration for a stylised RPG chat:
- When a PARTY MEMBER speaks, give them their own paragraph that begins with their name, a colon, then ONLY their spoken words in quotes — e.g.  Tifa: "We should move before the light fails."  This renders as a portrait dialogue box. Put nothing else on that line: any description of how they said it, their expression, or what happens next goes in a SEPARATE narration paragraph (a blank line after the quote), NOT on the dialogue line. One speaker per paragraph; only do this for actual party members.
- Use *italics* for emphasis, whispers, or inner thoughts, and **bold** for the names of notable items the first time they appear.
- Put letters, signs, inscriptions, or prophecies in a blockquote: start each such line with "> ".
- Separate a hard scene or time jump with a line containing only "* * *".
- Keep ordinary narration as normal prose paragraphs."""

# Injected on the final (forced) round, when tools are no longer offered, so the
# model doesn't narrate an action it never actually carried out with a tool.
FINAL_ROUND_NUDGE = (
    "You can no longer call tools this turn. Write the final narration now, "
    "describing only what has actually happened — do not claim any item grant, "
    "equip, or scene change that wasn't already carried out by a tool above."
)

# --- Tool schemas (OpenAI/OpenRouter function-calling format) ---------------

_SLOT_ENUM = [
    "head", "neck", "torsoOver", "torsoUnder", "leftHand", "rightHand",
    "waist", "legsOver", "legsUnder", "feet", "accessory1", "accessory2",
]

TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "set_scene",
            "description": "Declare the current location, time of day, weather, and/or in-game day. Include only the fields that are being established or changed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {"type": "string", "description": "Short place name, 2-4 words."},
                    "timeOfDay": {"type": "string", "enum": ["Morning", "Day", "Afternoon", "Evening", "Night"]},
                    "weather": {"type": "string", "description": "Short descriptor, e.g. 'Light rain'."},
                    "day": {"type": "integer", "description": "In-game day number (starts at 1). Set when a new day begins, e.g. after sleeping or a time skip."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grant_item",
            "description": "Add an existing world item to the party inventory (the party GAINED it: found/bought/looted/received). Do NOT call this when the party gives an item away.",
            "parameters": {
                "type": "object",
                "properties": {
                    "itemName": {"type": "string"},
                    "count": {"type": "integer", "minimum": 1, "default": 1},
                },
                "required": ["itemName"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_item",
            "description": "Remove an item the party owns from its inventory (given to an NPC, sold, lost, destroyed). This is the ONLY tool needed when the party gives an item away — never pair it with grant_item.",
            "parameters": {
                "type": "object",
                "properties": {
                    "itemName": {"type": "string"},
                    "count": {"type": "integer", "minimum": 1, "default": 1},
                },
                "required": ["itemName"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consume_item",
            "description": "The player or party uses up a carried item this turn (e.g. drinks a potion).",
            "parameters": {
                "type": "object",
                "properties": {
                    "itemName": {"type": "string"},
                    "count": {"type": "integer", "minimum": 1, "default": 1},
                },
                "required": ["itemName"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "equip",
            "description": "Equip an existing Equipment item onto a character in a specific slot.",
            "parameters": {
                "type": "object",
                "properties": {
                    "characterName": {"type": "string", "description": "Character's first name."},
                    "slot": {"type": "string", "enum": _SLOT_ENUM},
                    "itemName": {"type": "string"},
                },
                "required": ["characterName", "slot", "itemName"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "unequip",
            "description": "Remove whatever is in a character's equipment slot; it returns to inventory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "characterName": {"type": "string"},
                    "slot": {"type": "string", "enum": _SLOT_ENUM},
                },
                "required": ["characterName", "slot"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_item",
            "description": "Check whether an item exists in the world and read its type/slot/rarity/description.",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_items",
            "description": "Find world items whose name or description matches a query.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_inventory",
            "description": "List the items currently in the party inventory.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_character",
            "description": "Read a character's currently equipped items by slot.",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        },
    },
]

_HANDLERS = {
    "set_scene": tool_set_scene,
    "grant_item": tool_grant_item,
    "remove_item": tool_remove_item,
    "consume_item": tool_consume_item,
    "equip": tool_equip,
    "unequip": tool_unequip,
    "lookup_item": tool_lookup_item,
    "search_items": tool_search_items,
    "list_inventory": tool_list_inventory,
    "get_character": tool_get_character,
}


def _parse_args(raw: str) -> dict:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


async def run_narrator_agent(
    *,
    settings,
    base_messages: list[dict],
    current_turn: int,
    summarize_hint: bool = False,
) -> AsyncGenerator[dict, None]:
    """Drive the agentic narrator loop for one turn.

    Yields:
        {"type": "content", "text": str}  -- final-narration content deltas
        {"type": "discard"}               -- clear streamed content (preamble on a tool turn)
        {"type": "tool", "name": str, "result": str} -- a tool was executed
        {"type": "final", "content": str, "scene": dict,
         "inv_deltas": list, "equip_changes": list} -- terminal
    """
    # Inject tool-use guidance right after the narrator-instructions system
    # message. (``summarize_hint`` is retained for call-site compatibility but is
    # unused — history summarisation is handled deterministically server-side.)
    messages = list(base_messages)
    insert_at = 1 if messages and messages[0].get("role") == "system" else 0
    messages[insert_at:insert_at] = [
        {"role": "system", "content": TOOL_GUIDANCE},
        {"role": "system", "content": FORMATTING_GUIDE},
    ]

    inv_deltas: list[dict] = []
    equip_changes: list[dict] = []
    scene: dict = {}
    final_content = ""
    tool_failures: list[str] = []

    max_rounds = max(1, settings.max_tool_rounds or 6)
    full_max_tokens = settings.max_tokens_response

    async with new_session() as agent_session:
        for round_idx in range(max_rounds):
            # On the last allowed round, drop tools so the model is forced to
            # produce final narration instead of requesting more tool calls.
            offer_tools = round_idx < max_rounds - 1
            if not offer_tools and max_rounds > 1:
                # Forced narration round — make clear no more actions can happen.
                messages.append({"role": "system", "content": FINAL_ROUND_NUDGE})
            # Every round gets the full response budget. A short cap on tool rounds
            # saves nothing (a genuine tool round stops early at the tool call) but
            # would clip a final narration that lands on a tool-offering round,
            # forcing a wasteful discard-and-regenerate.

            result = None
            streamed = False

            async for ev in chat_completion_agent_turn(
                api_key=settings.api_key,
                model_id=settings.model_id,
                messages=messages,
                temperature=settings.temperature,
                max_tokens=full_max_tokens,
                tools=TOOL_SCHEMAS if offer_tools else None,
                top_p=settings.top_p,
                min_p=settings.min_p,
                top_k=settings.top_k,
                frequency_penalty=settings.frequency_penalty,
                presence_penalty=settings.presence_penalty,
                repetition_penalty=settings.repetition_penalty,
            ):
                if ev["type"] == "content":
                    streamed = True
                    yield {"type": "content", "text": ev["text"]}
                elif ev["type"] == "result":
                    result = ev

            tool_calls = (result or {}).get("tool_calls") or []
            content = (result or {}).get("content") or ""

            if not tool_calls:
                # No tool calls → this is the final narration (streamed live above).
                final_content = content
                break

            # This was a tool round — any content it streamed was preamble; drop it.
            if streamed:
                yield {"type": "discard"}

            # Record the assistant's tool-call message in the running transcript.
            messages.append({
                "role": "assistant",
                "content": content or None,
                "tool_calls": [
                    {"id": tc["id"], "type": "function",
                     "function": {"name": tc["name"], "arguments": tc["arguments"]}}
                    for tc in tool_calls
                ],
            })

            for tc in tool_calls:
                name = tc["name"]
                args = _parse_args(tc["arguments"])
                effect = await _execute_tool(name, args, agent_session)
                inv_deltas.extend(effect.inv_deltas)
                equip_changes.extend(effect.equip_changes)
                scene.update(effect.scene)
                if not effect.ok:
                    note = _failure_note(name, args)
                    if note:
                        tool_failures.append(note)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": effect.result,
                })
                log.info("AGENT TOOL turn=%s %s(%s) -> %s", current_turn, name, args, effect.result)
                yield {"type": "tool", "name": name, "result": effect.result, "ok": effect.ok}

            await agent_session.commit()

    yield {
        "type": "final",
        "content": final_content,
        "scene": scene,
        "inv_deltas": inv_deltas,
        "equip_changes": equip_changes,
        "tool_failures": tool_failures,
    }


async def _execute_tool(name: str, args: dict, session) -> ToolEffect:
    handler = _HANDLERS.get(name)
    if not handler:
        return ToolEffect(result=f"Unknown tool '{name}'.")
    return await handler(args, session)


def _failure_note(name: str, args: dict) -> str | None:
    """A short, spoiler-safe player-facing note for a mutating tool that failed,
    so a bad tool call is visible ("the world stayed safe") rather than silent."""
    item = args.get("itemName") or ""
    who = args.get("characterName") or ""
    if name == "equip":
        target = f" onto {who}" if who else ""
        return f"The narrator tried to equip a nonexistent item{(' (' + item + ')') if item else ''}{target}, but the world stayed safe."
    if name == "unequip":
        return f"The narrator tried to unequip an empty slot{(' on ' + who) if who else ''}, but nothing changed."
    if name in ("grant_item", "remove_item", "consume_item"):
        verb = {"grant_item": "grant", "remove_item": "remove", "consume_item": "use"}[name]
        return f"The narrator tried to {verb} an item that isn't in the world{(' (' + item + ')') if item else ''}, but the world stayed safe."
    return None
