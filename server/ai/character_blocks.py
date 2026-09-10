"""Character block tree — the TavernAI-style toggleable/reorderable prompt
builder that replaced the fixed basicInfo fields. A character's ``blocks``
list lives inside the card PNG's ``extensions.wayward`` (see
server/db/characters.py). Same pattern as scenario.py/species.py: fields are
the source of truth, composed into plain text for the prompt.

Block shape: {id, type, name, enabled, locked?, content?, children?}
  - text      — content is prose, `{{name}}` resolves to the character's name.
  - folder    — groups children (one level deep only); folder OFF disables
                every descendant too.
  - equipment — virtual: rendered from LIVE PartyBinding/catalog state, never
                stored — see `render_equipment_block` in prompt_builder.py.
  - image     — content is unused; points at an embedded asset (see
                characters.py `assets`). Composition here just skips it (the
                caller pulls enabled image blocks separately for vision).

`locked` (default False) marks a block as mandatory — editable, but the
client won't let it be moved, deleted, or disabled (Open Tag/Close Tag/
Equipment). Purely a UI-level convention; not enforced server-side.
"""

import re
import uuid

TAG_OPEN_NAME = "Open Tag"
TAG_CLOSE_NAME = "Close Tag"

_NAME_PLACEHOLDER_RE = re.compile(r"\{\{\s*name\s*\}\}", re.IGNORECASE)


def _uid() -> str:
    return uuid.uuid4().hex[:12]


def _block(type_: str, name: str, content: str = "", enabled: bool = True, locked: bool = False) -> dict:
    b = {"id": _uid(), "type": type_, "name": name, "enabled": enabled, "locked": locked}
    if type_ == "text":
        b["content"] = content
    elif type_ == "folder":
        b["children"] = []
    return b


def _mandatory_locked(type_: str, name: str, content: str = "") -> dict:
    """Open Tag / Close Tag / Equipment are always seeded locked."""
    return _block(type_, name, content, locked=True)


def default_blocks(name: str = "") -> list[dict]:
    """Seed set for a brand-new character — open/close tags always present,
    a handful of starter text blocks, the equipment slot pre-placed."""
    return [
        _mandatory_locked("text", TAG_OPEN_NAME, "<{{name}}>"),
        _block("text", "Description", ""),
        _block("text", "Personality", ""),
        _block("text", "Instinct", ""),
        _block("text", "Strengths", ""),
        _mandatory_locked("equipment", "Equipment"),
        _block("text", "Other", ""),
        _mandatory_locked("text", TAG_CLOSE_NAME, "</{{name}}>"),
    ]


# ── Legacy basicInfo → blocks (one-time, in-memory migration) ──────

_LEGACY_LABELS = (
    ("species", "Species"), ("sex", "Sex"), ("apparentAge", "Apparent Age"),
    ("description", "Description"), ("personality", "Personality"),
    ("instinct", "Instinct"), ("strengths", "Strengths"), ("other", "Other"),
)


def blocks_from_legacy_basic_info(basic_info: dict) -> list[dict]:
    """Old flat {species, sex, apparentAge, description, ...} → a block per
    non-empty field, wrapped in the same open/close tags new characters get."""
    out = [_mandatory_locked("text", TAG_OPEN_NAME, "<{{name}}>")]
    for key, label in _LEGACY_LABELS:
        val = str((basic_info or {}).get(key) or "").strip()
        if val:
            out.append(_block("text", label, val))
    out.append(_mandatory_locked("equipment", "Equipment"))
    out.append(_mandatory_locked("text", TAG_CLOSE_NAME, "</{{name}}>"))
    return out


# ── SillyTavern V2/V3 card → blocks (import) ───────────────────────

_ST_FIELD_LABELS = (
    ("description", "Description"), ("personality", "Personality"),
    ("scenario", "Scenario"), ("mes_example", "Example Dialogue"),
    ("system_prompt", "System Prompt (imported)"),
    ("post_history_instructions", "Post-History Instructions (imported)"),
    ("creator_notes", "Creator Notes"), ("first_mes", "Opening Line (imported)"),
)


def blocks_from_sillytavern(card_data: dict) -> list[dict]:
    """Every non-empty standard V2/V3 field becomes its own block, between the
    open/close tags — per spec, `character_book` (an embedded lorebook) is
    NOT mapped here (would need real Lorebook entries — future work)."""
    out = [_mandatory_locked("text", TAG_OPEN_NAME, "<{{name}}>")]
    for key, label in _ST_FIELD_LABELS:
        val = str(card_data.get(key) or "").strip()
        if val:
            out.append(_block("text", label, val))
    out.append(_mandatory_locked("equipment", "Equipment"))
    out.append(_mandatory_locked("text", TAG_CLOSE_NAME, "</{{name}}>"))
    return out


# ── Composition (blocks → prompt text) ─────────────────────────────

def compose_blocks(
    blocks: list[dict],
    name: str,
    equipment_text: str | None = None,
) -> str:
    """Flatten enabled blocks (folders recursed, disabled folders skip their
    whole subtree) into one text blob, `{{name}}` resolved. `equipment_text`
    is pre-rendered by the caller (live game state — see prompt_builder.py).
    Labeled text blocks are prefixed with a markdown header — `##` at root,
    `###` one level into a folder — so nesting is legible in the prompt too."""
    parts: list[str] = []

    def walk(items: list[dict], depth: int = 0) -> None:
        heading = "#" * (2 + depth)
        for b in items or []:
            if not b.get("enabled", True):
                continue
            btype = b.get("type")
            if btype == "folder":
                walk(b.get("children") or [], depth + 1)
            elif btype == "text":
                content = (b.get("content") or "").strip()
                if not content:
                    continue
                content = _NAME_PLACEHOLDER_RE.sub(name, content)
                label = (b.get("name") or "").strip()
                # Description and the tag blocks read as bare prose (a tag's
                # whole point IS to be an unlabeled delimiter); everything
                # else gets its block name as a heading, same info the old
                # fixed PC/party sheet gave as "Personality: ...", "Other: ...".
                if label and label not in ("Description", TAG_OPEN_NAME, TAG_CLOSE_NAME):
                    content = f"{heading} {label}\n{content}"
                parts.append(content)
            elif btype == "equipment":
                if equipment_text:
                    parts.append(f"Wearing/carrying: {equipment_text}")
            # image blocks contribute nothing to TEXT composition.

    walk(blocks)
    return "\n".join(parts)


def image_block_paths(blocks: list[dict]) -> list[str]:
    """Enabled image blocks' asset paths (folders honored), in order."""
    out: list[str] = []

    def walk(items: list[dict]) -> None:
        for b in items or []:
            if not b.get("enabled", True):
                continue
            if b.get("type") == "folder":
                walk(b.get("children") or [])
            elif b.get("type") == "image" and b.get("file"):
                out.append(b["file"])

    walk(blocks)
    return out


# ── Compatibility projection (blocks → old flat basicInfo shape) ───
# A lot of call sites (Editor tools, Chronicler, seed data, templates) still
# talk in the old flat field names. Rather than rewrite every one of them in
# this pass, project the block tree back onto that shape — first block whose
# NAME matches (case-insensitive) a legacy label wins. Real content is always
# the blocks; this is read-only sugar for the old call sites.

_LEGACY_KEYS_BY_LABEL = {label.lower(): key for key, label in _LEGACY_LABELS}


def project_legacy_basic_info(blocks: list[dict], name: str) -> dict:
    out = {k: "" for k, _ in _LEGACY_LABELS}
    out["name"] = name

    def walk(items: list[dict]) -> None:
        for b in items or []:
            if b.get("type") == "folder":
                walk(b.get("children") or [])
            elif b.get("type") == "text":
                key = _LEGACY_KEYS_BY_LABEL.get((b.get("name") or "").strip().lower())
                if key and not out.get(key):
                    out[key] = b.get("content") or ""

    walk(blocks)
    return out


def upsert_legacy_field(blocks: list[dict], label: str, value: str) -> list[dict]:
    """Set (or create) the text block matching `label` — used by
    update_identity() so old flat-shaped PUTs still land somewhere sane."""
    target = label.lower()
    blocks = list(blocks or [])
    for b in blocks:
        if b.get("type") == "text" and (b.get("name") or "").strip().lower() == target:
            b["content"] = value
            return blocks
    # Not found — insert before the close tag (or at the end).
    new_block = _block("text", label, value)
    for i, b in enumerate(blocks):
        if b.get("name") == TAG_CLOSE_NAME:
            blocks.insert(i, new_block)
            return blocks
    blocks.append(new_block)
    return blocks
