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
