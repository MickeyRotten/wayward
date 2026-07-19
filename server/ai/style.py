"""Story Style — the Campaign Builder's guided narration options.

The option catalog (fields, options, and each option's prompt snippet) lives in
an editable JSON file (``style_catalog.json``), read at runtime and cached by
file mtime, so tuning a snippet or adding a Genre/Tone/Style option takes effect
on the next request with no rebuild and no code change. This module is a thin
loader + composer over that JSON — no catalog data lives here.

The player's *selections* are stored as a flat ``{key: value}`` dict in
``NarratorConfig.style_fields`` (campaign scope). A value matching a known option
id uses that option's prompt snippet; any other non-empty string is a free-text
custom value, rendered as ``"Label: <text>"``. ``compose_style_block`` folds the
selections into a ``STORY STYLE`` system block for the narrator prompt — the same
shape as ``compose_rules_block`` (ai/rules.py), injected once in build_prompt.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

log = logging.getLogger("wayward.style")

_DEFAULT_CATALOG_PATH = Path(__file__).resolve().parent / "style_catalog.json"

# The freeform "additional custom instructions" field — not part of the catalog
# (no options), appended verbatim at the end of the composed block.
CUSTOM_INSTRUCTIONS_KEY = "custom_instructions"

# camelCase API keys ↔ snake_case storage keys. Storage keys match the catalog
# field keys; the wire uses camelCase like every other schema. This pairing is
# the one place a *new field* (not option) would need touching — adding options
# to an existing field stays rebuild-free.
WIRE_TO_KEY = {
    "genre": "genre",
    "tone": "tone",
    "writingStyle": "writing_style",
    "verbosity": "verbosity",
    "contentLimit": "content_limit",
    "perspective": "perspective",
    "structure": "structure",
    "customInstructions": CUSTOM_INSTRUCTIONS_KEY,
}
KEY_TO_WIRE = {v: k for k, v in WIRE_TO_KEY.items()}


def to_wire(fields: dict | None) -> dict:
    """Storage dict (snake_case keys) → camelCase response dict, every wire key
    present (defaulting to "")."""
    stored = normalize_style_fields(fields)
    return {wire: stored.get(key, "") for wire, key in WIRE_TO_KEY.items()}


def from_wire(payload: dict) -> dict:
    """Partial camelCase update dict → snake_case storage dict, keeping only keys
    that were provided (non-None). Values are normalized (stripped) downstream."""
    out: dict = {}
    for wire, key in WIRE_TO_KEY.items():
        if payload.get(wire) is not None:
            out[key] = payload[wire]
    return out

# mtime-keyed cache so hand-edits to the JSON are picked up without a restart,
# while avoiding a disk read on every call.
_cache: dict | None = None
_cache_mtime: float | None = None
_cache_path: str | None = None


def _catalog_path() -> Path:
    override = os.environ.get("WAYWARD_STYLE_CATALOG")
    return Path(override) if override else _DEFAULT_CATALOG_PATH


def load_catalog() -> dict:
    """Read the style catalog JSON, cached by (path, mtime). Tolerant of a
    missing/malformed file — logs and returns an empty catalog (``{"fields": []}``)
    so the feature degrades to "no style options" rather than raising."""
    global _cache, _cache_mtime, _cache_path
    path = _catalog_path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        log.warning("Style catalog not found at %s", path)
        return {"fields": []}
    if _cache is not None and _cache_path == str(path) and _cache_mtime == mtime:
        return _cache
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("fields"), list):
            raise ValueError("catalog must be an object with a 'fields' list")
    except Exception:
        log.exception("Failed to parse style catalog %s", path)
        return {"fields": []}
    _cache, _cache_mtime, _cache_path = data, mtime, str(path)
    return data


def _fields() -> list[dict]:
    return [f for f in load_catalog().get("fields", []) if isinstance(f, dict) and f.get("key")]


def valid_keys() -> list[str]:
    """Field keys the catalog defines, plus the freeform custom-instructions key."""
    return [f["key"] for f in _fields()] + [CUSTOM_INSTRUCTIONS_KEY]


def normalize_style_fields(raw) -> dict:
    """Coerce arbitrary input into a clean ``{key: str}`` dict: keep only known
    keys (catalog fields + custom_instructions), stringify + strip values, and
    drop blanks. Returns ``{}`` when nothing usable is present."""
    if not isinstance(raw, dict):
        return {}
    allowed = set(valid_keys())
    out: dict = {}
    for key, value in raw.items():
        if key not in allowed:
            continue
        text = str(value or "").strip()
        if text:
            out[key] = text
    return out


def _option_prompt(field: dict, value: str) -> str:
    """The prompt snippet for a selected value: an option's ``prompt`` when the
    value matches an option id, else a ``"Label: <custom text>"`` line."""
    for opt in field.get("options", []):
        if isinstance(opt, dict) and opt.get("id") == value:
            return str(opt.get("prompt") or f"{field.get('label', field['key'])}: {opt.get('label', value)}")
    label = field.get("label") or field["key"]
    return f"{label}: {value}"


def compose_style_block(fields: dict) -> str:
    """Render the STORY STYLE system block from the player's selections, or ``""``
    when nothing is set. Catalog fields render in catalog order; the freeform
    custom instructions are appended verbatim at the end."""
    selections = normalize_style_fields(fields)
    if not selections:
        return ""
    parts: list[str] = []
    for field in _fields():
        value = selections.get(field["key"])
        if value:
            parts.append(_option_prompt(field, value))
    custom = selections.get(CUSTOM_INSTRUCTIONS_KEY)
    if custom:
        parts.append(custom)
    if not parts:
        return ""
    return "STORY STYLE\n" + "\n\n".join(parts)


def migrate_legacy_tone(style_fields, rules_tone: str) -> dict | None:
    """One-time, non-destructive tone reconciliation: if the player has no style
    selections yet but the campaign carries a legacy ``CampaignRules.tone``, seed
    the style ``tone`` field from it (as a custom value). Returns the seeded dict
    when a migration is warranted, else ``None`` (caller persists + clears the
    old tone only when a dict is returned). Pure function."""
    current = normalize_style_fields(style_fields)
    tone = (rules_tone or "").strip()
    if current or not tone:
        return None
    return {"tone": tone}


def options_payload() -> dict:
    """The catalog shaped for the client picker — labels + hints only, never the
    prompt snippets (those stay server-side). Field ``key`` is the camelCase wire
    key (matching StoryStyleFields), so the client binds a select straight to a
    selection value with no extra mapping."""
    fields = []
    for field in _fields():
        options = [
            {"id": o.get("id"), "label": o.get("label", o.get("id")), "hint": o.get("hint", "")}
            for o in field.get("options", [])
            if isinstance(o, dict) and o.get("id")
        ]
        fields.append({
            "key": KEY_TO_WIRE.get(field["key"], field["key"]),
            "label": field.get("label", field["key"]),
            "allowCustom": bool(field.get("allow_custom", False)),
            "options": options,
        })
    return {"fields": fields}


def option_ids(key: str) -> list[str]:
    """Valid option ids for a field key (for tool-schema descriptions)."""
    for field in _fields():
        if field["key"] == key:
            return [o.get("id") for o in field.get("options", []) if isinstance(o, dict) and o.get("id")]
    return []


# ── Core Narrator instructions + always-on guides ─────────────────
#
# These are the narrator's fixed instruction blocks — everything that is NOT a
# Story Style option or the player's custom instructions. Their canonical,
# editable copies live in style_catalog.json under the top-level "narrator" key
# and are read live (mtime cache) so they can be tuned with no rebuild. The
# constants below are the safety fallback used only when that JSON is missing or
# blank, so narration never loses its role or formatting conventions.

# The core role + behavior preamble — leads the narrator prompt so it always
# begins with a clear role definition (perspective/length are Story Style
# options and deliberately NOT stated here).
_CORE_FALLBACK = (
    "You are the Narrator of this interactive adventure — the storyteller and "
    "game master who brings the world to life and voices every character in it "
    "except the player character. Describe the world vividly, immersing the "
    "player in the scene. Advance the scene with each response: describe what "
    "happens, what the player sees or feels, and leave a natural opening for "
    "their next action. Never speak for the player character or decide their "
    "actions. When voicing a party member, use a dialogue tag with their name "
    "and keep it to one or two sentences in character. Characters are wearing "
    "only what they have equipped — if an equipment slot is empty, they have "
    "nothing in that slot. Do not invent clothing or gear that is not listed in "
    "their equipment."
)

_TOOL_GUIDANCE_FALLBACK = """You have tools for changing and reading game state. Use them like this:
- Call tools FIRST, in their own messages. Do NOT write narration in the same message as a tool call.
- When you grant or equip an item, it must already exist in the world. If unsure, call lookup_item or search_items before grant_item/equip — guessing a name that doesn't exist does nothing.
- Use set_scene whenever the location, time of day, or weather is first established or changes. Also set the in-game `day` (starting at 1) when a new day begins — e.g. after the party sleeps or time skips to the next morning — incrementing by 1 each new day.
- Use consume_item when the player uses up an item they carry (e.g. drinks a potion).
- The inventory is the PLAYER PARTY's inventory only — NPCs and monsters do not have inventories you track.
  - The player giving/handing/selling an item to an NPC (anyone NOT in the player's party) is a single remove_item — it leaves the party's inventory. Do NOT grant_item then remove_item (that nets to zero and is wrong). If the party never actually had that item, change no inventory at all — just narrate.
  - Only grant_item when the party GAINS an item (found, bought, looted, received as a gift). Handing between party members changes nothing — the party still owns it.
- Once all needed tool calls are done, write the narration in a final message with NO tool calls. That final message is the only text the player sees.
- Most turns need no tools at all — just narrate."""

_DICE_GUIDANCE_FALLBACK = """- skill_check: when the player or a party member attempts something meaningfully UNCERTAIN and CONSEQUENTIAL (leaping a chasm, picking a lock, persuading a hostile guard, spotting an ambush), call skill_check BEFORE narrating the outcome, then narrate the result you were given — a failure must actually fail. Pick the skill label from the action or the character's Field Skill. Choose difficulty honestly: easy / normal / hard / heroic. NEVER roll for trivial or guaranteed actions, for ordinary conversation, or more than once per player action."""

_FORMATTING_GUIDE_FALLBACK = """Format the narration for a stylised RPG chat:
- When ANY CHARACTER speaks, give them their own paragraph that begins with their name, a colon, then ONLY their spoken words in quotes — e.g.  Tifa: "We should move before the light fails."  This renders as a portrait dialogue box. Put nothing else on that line: any description of how they said it, their expression, or what happens next goes in a SEPARATE narration paragraph (a blank line after the quote), NOT on the dialogue line. One speaker per paragraph; only do this for party members and characters in focus.
- Use *italics* for emphasis, whispers, or inner thoughts, and **bold** for the names of notable items the first time they appear.
- Put meta information, letters, signs, inscriptions, or prophecies in a blockquote: start each such line with "> ".
- Separate a hard scene or time jump with a line containing only "* * *".
- Keep ordinary narration as normal prose paragraphs."""


def _narrator_text(key: str, fallback: str) -> str:
    block = load_catalog().get("narrator")
    if isinstance(block, dict):
        value = block.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return fallback


def core_instructions() -> str:
    """The core Narrator role + behavior preamble (always the first system
    message, so the prompt begins with a clear role definition)."""
    return _narrator_text("core_instructions", _CORE_FALLBACK)


def tool_guidance() -> str:
    """How the agentic narrator should use its state tools (always injected)."""
    return _narrator_text("tool_guidance", _TOOL_GUIDANCE_FALLBACK)


def dice_guidance() -> str:
    """skill_check usage guidance (appended only when dice are enabled)."""
    return _narrator_text("dice_guidance", _DICE_GUIDANCE_FALLBACK)


def formatting_guide() -> str:
    """Chat-formatting conventions the client renderer recognises (always
    injected)."""
    return _narrator_text("formatting_guide", _FORMATTING_GUIDE_FALLBACK)
