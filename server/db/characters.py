"""Character identity — ONE PNG file per character (SillyTavern-compatible
card format), replacing the old folder-of-4-files layout.

``server/data/characters/<id>.png`` holds everything:
  - standard V2 (`chara`) + V3 (`ccv3`) tEXt chunks — the composed sheet under
    `description` etc, so the file opens sanely in any SillyTavern-family tool.
  - `data.extensions.wayward` — the REAL data: name, the toggleable block tree
    (see server/ai/character_blocks.py), schema version.
  - `chara-ext-asset_:{path}` chunks (the V3 spec's asset mechanism) hold every
    binary blob: `full.<ext>` (full portrait), `crop.<ext>` (chat crop),
    `voice.<ext>` (TTS sample), `img/<id>.<ext>` (extra reference images the
    block tree's image blocks point at).

Portrait/crop/voice are ALWAYS read asset-first (`_find_asset` glob by stem) —
the outer PNG pixel data is only a best-effort preview for non-Wayward tools,
swapped in when the uploaded bytes already happen to be a valid PNG. This
means no image format conversion is ever needed: Wayward's own reads never
touch the container pixels, so a JPEG/WebP upload works identically to a PNG
one — only a plain SillyTavern-style viewer opening the raw file sees the
default placeholder instead of that JPEG (a real but narrow compatibility gap,
not a data-loss one).
"""

import datetime
import io
import json
import re
import shutil
import uuid
import zipfile
from pathlib import Path

from server.ai import character_blocks as blocks_ai
from server.db import database as db
from server.db import png_card

SCHEMA_VERSION = 3
_PNG_SIG = b"\x89PNG\r\n\x1a\n"

_BASIC_KEYS = (
    "name", "species", "sex", "apparentAge",
    "description", "personality", "instinct", "strengths", "other",
)
_LEGACY_KEY_MAP = {"gender": "sex", "drive": "instinct"}


def migrate_basic_info(basic_info: dict | None, field_skill: dict | None = None) -> dict:
    """Old flat basicInfo shapes (gender/age/likes/dislikes/heightCm/weightKg,
    a separate fieldSkill object) -> the unified flat shape blocks_from_legacy
    expects. Pure, idempotent — safe to call on an already-new-shape dict too.
    Still used by the legacy DB-row backfill (database.py) and callers holding
    old-format data (seed.py/templates.py feed the OLD PlayerCharacter/
    PartyMember SQLAlchemy rows, converted here on migration)."""
    src = dict(basic_info or {})
    for old, new in _LEGACY_KEY_MAP.items():
        if old in src and new not in src:
            src[new] = src[old]
    if "apparentAge" not in src and src.get("age"):
        src["apparentAge"] = str(src["age"])
    if not (src.get("strengths") or "").strip():
        fs = dict(field_skill or {})
        n, d = str(fs.get("name") or "").strip(), str(fs.get("description") or "").strip()
        src["strengths"] = f"{n} — {d}" if n and d else (d or n)
    return {k: str(src.get(k) or "") for k in _BASIC_KEYS}

_default_avatar_cache: bytes | None = None


def _default_avatar() -> bytes:
    global _default_avatar_cache
    if _default_avatar_cache is None:
        _default_avatar_cache = png_card.make_solid_png(512, 512, (38, 32, 22))  # --bg2-ish
    return _default_avatar_cache


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


# ── Paths ─────────────────────────────────────────────────────────

def characters_dir() -> Path:
    return db.DATA_DIR / "characters"


def path(cid: str) -> Path:
    return characters_dir() / f"{cid}.png"


def char_dir(cid: str) -> Path:
    """Legacy folder path — kept ONLY so old-format zip imports/backfills
    (pre single-PNG) can still be located and converted."""
    return characters_dir() / cid


def exists(cid: str) -> bool:
    return path(cid).exists()


_BUNDLED_CARDS_DIR = Path(__file__).resolve().parent.parent / "templates" / "cards"


def install_bundled_cards() -> None:
    """One-time-per-id: convert repo-shipped starter cards (old folder shape:
    character.json + full.<ext> + crop.jpg) into the new single-PNG format."""
    if not _BUNDLED_CARDS_DIR.exists():
        return
    for src in sorted(_BUNDLED_CARDS_DIR.iterdir()):
        if not src.is_dir():
            continue
        try:
            legacy = json.loads((src / "character.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        cid = legacy.get("id")
        if not cid or exists(cid):
            continue
        char_type = legacy.get("type", "character")
        basic = migrate_basic_info(legacy.get("basicInfo"), legacy.get("fieldSkill"))
        blist = blocks_ai.blocks_from_legacy_basic_info(basic)
        create_character(char_type, cid=cid, name=basic.get("name", ""), blocks=blist,
                          created_at=legacy.get("createdAt"))
        full = src / "full.jpg"
        if not full.exists():
            full = next(src.glob("full.*"), None)
        if full and full.exists():
            set_full(cid, full.read_bytes(), full.suffix)
        crop = src / "crop.jpg"
        if crop.exists():
            set_crop(cid, crop.read_bytes())


# ── Legacy folder → single PNG (one-time, on first read) ───────────

def _migrate_legacy_folder(cid: str) -> bool:
    """If an OLD-format character folder exists for `cid` and no PNG yet,
    convert it in place. Returns True if a migration happened."""
    old_dir = char_dir(cid)
    old_json = old_dir / "character.json"
    if path(cid).exists() or not old_json.exists():
        return False
    try:
        legacy = json.loads(old_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    basic = migrate_basic_info(legacy.get("basicInfo"), legacy.get("fieldSkill"))
    blist = blocks_ai.blocks_from_legacy_basic_info(basic)
    create_character(
        legacy.get("type", "character"), cid=cid, name=basic.get("name", ""),
        blocks=blist, created_at=legacy.get("createdAt"),
    )
    full = next(old_dir.glob("full.*"), None)
    if full:
        set_full(cid, full.read_bytes(), full.suffix)
    crop = old_dir / "crop.jpg"
    if crop.exists():
        set_crop(cid, crop.read_bytes())
    voice = next(old_dir.glob("voice.*"), None)
    if voice:
        set_voice(cid, voice.read_bytes(), voice.suffix)
    shutil.rmtree(old_dir, ignore_errors=True)
    return True


# ── Asset helpers (crop/voice/extra images all live as embedded assets) ──

def _find_asset(png: bytes, stem: str) -> tuple[str, bytes] | None:
    """First asset path starting with `stem` (e.g. "full", "crop", "voice") —
    returns (path, raw_bytes), or None."""
    for p in png_card.list_asset_paths(png):
        if p == stem or p.startswith(stem + "."):
            raw = png_card.read_asset(png, p)
            if raw is not None:
                return p, raw
    return None


def _set_asset(cid: str, stem: str, data: bytes, ext: str) -> None:
    png = path(cid).read_bytes()
    card = png_card.read_card_json(png) or {}
    fields = (card.get("data") or {})
    assets = {p: png_card.read_asset(png, p) for p in png_card.list_asset_paths(png)}
    assets = {p: b for p, b in assets.items() if not (p == stem or p.startswith(stem + "."))}
    ext = ext if ext.startswith(".") else f".{ext}"
    assets[f"{stem}{ext}"] = data
    container = data if data[:8] == _PNG_SIG and stem == "full" else png
    new_png = png_card.write_card(container, fields, assets)
    path(cid).write_bytes(new_png)
    _read_cache.pop(cid, None)


def _clear_asset(cid: str, stem: str) -> None:
    png = path(cid).read_bytes()
    card = png_card.read_card_json(png) or {}
    fields = (card.get("data") or {})
    assets = {p: png_card.read_asset(png, p) for p in png_card.list_asset_paths(png)}
    assets = {p: b for p, b in assets.items() if not (p == stem or p.startswith(stem + "."))}
    new_png = png_card.write_card(png, fields, assets)
    path(cid).write_bytes(new_png)
    _read_cache.pop(cid, None)


def portrait_bytes(cid: str) -> bytes | None:
    if not exists(cid):
        return None
    png = path(cid).read_bytes()
    found = _find_asset(png, "full")
    if found:
        return found[1]
    return png  # container pixels (uploaded PNG, or the default placeholder)


def crop_bytes(cid: str) -> bytes | None:
    if not exists(cid):
        return None
    found = _find_asset(path(cid).read_bytes(), "crop")
    return found[1] if found else None


def voice_bytes(cid: str) -> bytes | None:
    if not exists(cid):
        return None
    found = _find_asset(path(cid).read_bytes(), "voice")
    return found[1] if found else None


def has_full(cid: str) -> bool:
    if not exists(cid):
        return False
    png = path(cid).read_bytes()
    return _find_asset(png, "full") is not None or png != _default_avatar()


def has_crop(cid: str) -> bool:
    return exists(cid) and _find_asset(path(cid).read_bytes(), "crop") is not None


def has_voice(cid: str) -> bool:
    return exists(cid) and _find_asset(path(cid).read_bytes(), "voice") is not None


def set_full(cid: str, data: bytes, ext: str) -> None:
    _set_asset(cid, "full", data, ext or ".png")


def set_crop(cid: str, data: bytes) -> None:
    _set_asset(cid, "crop", data, ".jpg")


def clear_portrait(cid: str) -> None:
    _clear_asset(cid, "full")
    _clear_asset(cid, "crop")


def set_voice(cid: str, data: bytes, ext: str) -> None:
    _set_asset(cid, "voice", data, ext or ".wav")


def clear_voice(cid: str) -> None:
    _clear_asset(cid, "voice")


def voice_path_for_tts(cid: str) -> Path | None:
    """TTS needs a real file (it hashes the sample for its cache key and feeds
    it to the cloning model) but the sample now lives embedded in the card —
    materialize it into a small on-disk cache, content-addressed by character
    id, rewritten whenever the embedded bytes actually change."""
    data = voice_bytes(cid)
    if data is None:
        return None
    cache_dir = db.DATA_DIR / "tts-voice-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    p = cache_dir / f"{cid}.wav"
    if not p.exists() or p.stat().st_size != len(data) or p.read_bytes() != data:
        p.write_bytes(data)
    return p


def set_image_asset(cid: str, asset_id: str, data: bytes, ext: str) -> str:
    """Extra reference image (an `image`-type block's `file`) — returns the
    stored asset path (`img/<asset_id><ext>`)."""
    stem = f"img/{asset_id}"
    _set_asset(cid, stem, data, ext or ".jpg")
    return f"{stem}{ext if ext.startswith('.') else '.' + ext}"


def image_asset_bytes(cid: str, file_path: str) -> bytes | None:
    if not exists(cid):
        return None
    return png_card.read_asset(path(cid).read_bytes(), file_path)


def remove_image_asset(cid: str, file_path: str) -> None:
    _clear_asset(cid, file_path.rsplit(".", 1)[0])


# ── Identity read/write ─────────────────────────────────────────────

_read_cache: dict[str, tuple[float, dict]] = {}


def read_character(cid: str) -> dict | None:
    _migrate_legacy_folder(cid)
    p = path(cid)
    try:
        mtime = p.stat().st_mtime
    except OSError:
        return None
    cached = _read_cache.get(cid)
    if cached and cached[0] == mtime:
        return dict(cached[1])
    try:
        png = p.read_bytes()
        card = png_card.read_card_json(png) or {}
        fields = card.get("data") or {}
        wayward = fields.get("extensions", {}).get("wayward", {})
        name = wayward.get("name") or fields.get("name") or ""
        blist = wayward.get("blocks") or []
        data = {
            "id": cid,
            "type": wayward.get("type", "character"),
            "schemaVersion": SCHEMA_VERSION,
            "createdAt": wayward.get("createdAt", ""),
            "name": name,
            "blocks": blist,
            # Compatibility projection for call sites not yet block-aware.
            "basicInfo": blocks_ai.project_legacy_basic_info(blist, name),
        }
        _read_cache[cid] = (mtime, data)
        return dict(data)
    except (OSError, ValueError, json.JSONDecodeError):
        _read_cache.pop(cid, None)
        return None


def _card_data_fields(name: str, char_type: str, blist: list[dict], created_at: str) -> dict:
    composed = blocks_ai.compose_blocks(blist, name or "Unknown")
    legacy = blocks_ai.project_legacy_basic_info(blist, name)
    return {
        "name": name,
        "description": composed,
        "personality": legacy.get("personality", ""),
        "first_mes": "",
        "mes_example": "",
        "extensions": {
            "wayward": {
                "type": char_type, "name": name, "blocks": blist,
                "createdAt": created_at, "schemaVersion": SCHEMA_VERSION,
            }
        },
    }


def write_character(cid: str, *, name: str, char_type: str, blocks: list[dict],
                     created_at: str | None = None) -> None:
    characters_dir().mkdir(parents=True, exist_ok=True)
    p = path(cid)
    if p.exists():
        png = p.read_bytes()
        assets = {a: png_card.read_asset(png, a) for a in png_card.list_asset_paths(png)}
        existing = png_card.read_card_json(png) or {}
        created_at = created_at or (existing.get("data", {}).get("extensions", {})
                                     .get("wayward", {}).get("createdAt")) or _now()
        container = png
    else:
        assets, created_at, container = {}, created_at or _now(), _default_avatar()
    fields = _card_data_fields(name, char_type, blocks, created_at)
    p.write_bytes(png_card.write_card(container, fields, assets))
    _read_cache.pop(cid, None)


def create_character(type: str = "character", basic_info: dict | None = None,
                      cid: str | None = None, created_at: str | None = None,
                      name: str | None = None, blocks: list[dict] | None = None) -> dict:
    cid = cid or str(uuid.uuid4())
    char_type = "persona" if type == "persona" else "character"
    norm = migrate_basic_info(basic_info) if basic_info else None
    resolved_name = name if name is not None else (norm or {}).get("name", "")
    blist = blocks if blocks is not None else (
        blocks_ai.blocks_from_legacy_basic_info(norm) if norm
        else blocks_ai.default_blocks(resolved_name)
    )
    write_character(cid, name=resolved_name, char_type=char_type, blocks=blist, created_at=created_at)
    return read_character(cid)


def update_identity(cid: str, basic_info: dict | None = None) -> dict | None:
    """Legacy-shaped patch — merges each provided flat field into its matching
    block (by name), creating the block if missing. Real editing should move
    to update_blocks() once the block-tree UI exists."""
    cur = read_character(cid)
    if cur is None:
        return None
    blist = cur["blocks"]
    name = cur["name"]
    if basic_info:
        norm = migrate_basic_info(basic_info)
        if (basic_info.get("name") or "").strip():
            name = basic_info["name"]
        # Callers always pass a FULL basicInfo dict (a Pydantic model_dump()
        # with defaults, or the current projection merged with changes), so an
        # empty value here is a genuine clear, not "field omitted".
        for key, label in blocks_ai._LEGACY_LABELS:
            blist = blocks_ai.upsert_legacy_field(blist, label, norm.get(key, ""))
    write_character(cid, name=name, char_type=cur["type"], blocks=blist)
    return read_character(cid)


def update_blocks(cid: str, blocks: list[dict], name: str | None = None) -> dict | None:
    cur = read_character(cid)
    if cur is None:
        return None
    write_character(cid, name=name if name is not None else cur["name"],
                     char_type=cur["type"], blocks=blocks)
    return read_character(cid)


def list_characters() -> list[dict]:
    root = characters_dir()
    out: list[dict] = []
    if not root.exists():
        return out
    seen = set()
    for child in list(root.glob("*.png")) + [d for d in root.iterdir() if d.is_dir()]:
        cid = child.stem if child.suffix == ".png" else child.name
        if cid in seen:
            continue
        seen.add(cid)
        data = read_character(cid)
        if data:
            out.append({**data, "hasFull": has_full(cid), "hasCrop": has_crop(cid),
                        "hasVoice": has_voice(cid)})
    out.sort(key=lambda d: d.get("createdAt", ""))
    return out


def delete_character(cid: str) -> bool:
    _read_cache.pop(cid, None)
    found = False
    if path(cid).exists():
        path(cid).unlink()
        found = True
    if char_dir(cid).exists():  # stray pre-migration folder
        shutil.rmtree(char_dir(cid), ignore_errors=True)
        found = True
    return found


def duplicate_character(cid: str) -> dict | None:
    src = read_character(cid)
    if src is None:
        return None
    new = create_character(type=src["type"], name=src["name"], blocks=src["blocks"])
    fb = portrait_bytes(cid)
    if fb:
        set_full(new["id"], fb, ".png" if fb[:8] == _PNG_SIG else ".jpg")
    cb = crop_bytes(cid)
    if cb:
        set_crop(new["id"], cb)
    vb = voice_bytes(cid)
    if vb:
        set_voice(new["id"], vb, ".wav")
    return read_character(new["id"])


# ── Portability ──────────────────────────────────────────────────

def export_zip(cid: str) -> bytes | None:
    """A single-file card is just... the file. Zipped for a stable download
    name/mimetype regardless (matches the pre-existing /export contract)."""
    if not exists(cid):
        return None
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{cid}.png", path(cid).read_bytes())
    return buf.getvalue()


def import_zip(raw: bytes) -> dict | None:
    try:
        z = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        return import_png(raw)  # maybe it's a bare card, not a zip
    pngs = [n for n in z.namelist() if n.lower().endswith(".png")]
    if pngs:
        return import_png(z.read(pngs[0]))
    try:  # very old export shape: character.json + loose portrait files
        identity = json.loads(z.read("character.json"))
    except (KeyError, json.JSONDecodeError):
        return None
    blist = blocks_ai.blocks_from_legacy_basic_info(identity.get("basicInfo") or {})
    new = create_character(type=identity.get("type", "character"),
                            name=(identity.get("basicInfo") or {}).get("name", ""), blocks=blist)
    for n in z.namelist():
        base = n.rsplit("/", 1)[-1]
        if base.startswith("full."):
            set_full(new["id"], z.read(n), Path(base).suffix)
        elif base == "crop.jpg":
            set_crop(new["id"], z.read(n))
        elif base.startswith("voice."):
            set_voice(new["id"], z.read(n), Path(base).suffix)
    return read_character(new["id"])


def import_png(raw: bytes) -> dict | None:
    """Import ANY character card PNG — a Wayward one (round-trips the block
    tree exactly) or a plain SillyTavern V2/V3 card (synthesizes a fresh block
    tree from its standard fields, wrapped in the open/close tags)."""
    if raw[:8] != _PNG_SIG:
        return None
    card = png_card.read_card_json(raw)
    if card is None:
        return None
    fields = card.get("data") or card  # V1 cards have no {spec,data} envelope
    wayward = (fields.get("extensions") or {}).get("wayward")
    if wayward:
        blist = wayward.get("blocks") or []
        name = wayward.get("name") or fields.get("name", "")
        char_type = wayward.get("type", "character")
    else:
        blist = blocks_ai.blocks_from_sillytavern(fields)
        name = fields.get("name", "Imported Character")
        char_type = "character"
    new = create_character(type=char_type, name=name, blocks=blist)
    assets = {p: png_card.read_asset(raw, p) for p in png_card.list_asset_paths(raw)}
    stems = {p.rsplit(".", 1)[0] for p in assets}
    if "full" not in stems:
        # Plain SillyTavern-style card (no V3 assets) — its own pixels ARE the
        # portrait; a Wayward-exported card with no full asset has none either
        # way, so this is a safe no-op there.
        set_full(new["id"], raw, ".png")
    for asset_path, raw_bytes in assets.items():
        stem, _, ext = asset_path.rpartition(".")
        _set_asset(new["id"], stem or asset_path, raw_bytes, f".{ext}" if ext else "")
    return read_character(new["id"])
