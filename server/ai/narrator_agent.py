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

from sqlalchemy import select

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
from server.db.models import StorySummary

log = logging.getLogger("wayward.narrator_agent")


TOOL_GUIDANCE = """You have tools for changing and reading game state. Use them like this:
- Call tools FIRST, in their own messages. Do NOT write narration in the same message as a tool call.
- When you grant or equip an item, it must already exist in the world. If unsure, call lookup_item or search_items before grant_item/equip — guessing a name that doesn't exist does nothing.
- Use set_scene whenever the location, time of day, or weather is first established or changes. Also set the in-game `day` (starting at 1) when a new day begins — e.g. after the party sleeps or time skips to the next morning — incrementing by 1 each new day.
- Use consume_item when the player uses up an item they carry (e.g. drinks a potion).
- Once all needed tool calls are done, write the narration in a final message with NO tool calls. That final message is the only text the player sees.
- Most turns need no tools at all — just narrate."""

SUMMARY_HINT = (
    "CONTEXT NOTICE: the conversation is getting long. Consider calling "
    "update_summary with a dense past-tense recap of older events so the "
    "earliest turns can be dropped from context."
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
            "description": "Add an existing world item to the party inventory.",
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
            "description": "Remove an item from the party inventory (lost, given away, destroyed).",
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
    {
        "type": "function",
        "function": {
            "name": "update_summary",
            "description": "Replace the running story summary with a dense past-tense recap, letting older turns drop from context.",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
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
    # Inject tool-use guidance (and optional summarize hint) right after the
    # narrator-instructions system message.
    messages = list(base_messages)
    insert_at = 1 if messages and messages[0].get("role") == "system" else 0
    guidance = [{"role": "system", "content": TOOL_GUIDANCE}]
    if summarize_hint:
        guidance.append({"role": "system", "content": SUMMARY_HINT})
    messages[insert_at:insert_at] = guidance

    inv_deltas: list[dict] = []
    equip_changes: list[dict] = []
    scene: dict = {}
    final_content = ""

    max_rounds = max(1, settings.max_tool_rounds or 6)

    async with new_session() as agent_session:
        for round_idx in range(max_rounds):
            # On the last allowed round, drop tools so the model is forced to
            # produce final narration instead of requesting more tool calls.
            offer_tools = round_idx < max_rounds - 1
            result = None
            streamed = False

            async for ev in chat_completion_agent_turn(
                api_key=settings.api_key,
                model_id=settings.model_id,
                messages=messages,
                temperature=settings.temperature,
                max_tokens=settings.max_tokens_response,
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
                effect = await _execute_tool(name, args, current_turn, agent_session)
                inv_deltas.extend(effect.inv_deltas)
                equip_changes.extend(effect.equip_changes)
                scene.update(effect.scene)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": effect.result,
                })
                log.info("AGENT TOOL turn=%s %s(%s) -> %s", current_turn, name, args, effect.result)
                yield {"type": "tool", "name": name, "result": effect.result}

            await agent_session.commit()

    yield {
        "type": "final",
        "content": final_content,
        "scene": scene,
        "inv_deltas": inv_deltas,
        "equip_changes": equip_changes,
    }


async def _execute_tool(name: str, args: dict, current_turn: int, session) -> ToolEffect:
    if name == "update_summary":
        text = (args.get("text", "") or "").strip()
        if not text:
            return ToolEffect(result="No summary text provided; nothing changed.")
        summ = (await session.execute(select(StorySummary))).scalars().first()
        if not summ:
            summ = StorySummary()
            session.add(summ)
        summ.content = text
        summ.summary_up_to_turn = max(summ.summary_up_to_turn or 0, current_turn - 1)
        return ToolEffect(result="Story summary updated; older turns will drop from context.")

    handler = _HANDLERS.get(name)
    if not handler:
        return ToolEffect(result=f"Unknown tool '{name}'.")
    return await handler(args, session)
