"""Character identity files — the portable, DB-free character library.

Each character is a folder under ``DATA_DIR/characters/<id>/`` holding:
  - ``character.json`` : identity (type, basicInfo, fieldSkill)
  - ``full.<ext>``     : the original uploaded art (shown in the Inspector)
  - ``crop.jpg``       : the framed 3:4 crop (chat dialogue cards + small avatars)
  - ``voice.<ext>``    : optional ~10s speech sample used for TTS voice cloning

Identity lives on disk (not the DB) so a character is reusable across
adventures/campaigns and shareable. Per-adventure state (equipment, in_party,
last_spoke_turn) lives in the adventure DB as a ``PartyBinding`` that references
the character by id (see server/db/party.py). Only ever ONE full + one crop per
character — replacing a portrait deletes the old files.
"""

import datetime
import io
import json
import shutil
import uuid
import zipfile
from pathlib import Path

from server.db import database as db

SCHEMA_VERSION = 2
_CROP_NAME = "crop.jpg"
_FULL_STEM = "full"
_VOICE_STEM = "voice"
_JSON_NAME = "character.json"

# Identity fields carried by a character.json's basicInfo (portrait is NOT one —
# the portrait is the sibling image files). All strings — the schema is
# narrative-first (apparentAge is descriptive text, not a number). `strengths`
# replaces the old separate fieldSkill object (1-3 GM-facing moves as text).
_BASIC_KEYS = (
    "name", "species", "sex", "apparentAge",
    "description", "personality", "instinct", "strengths", "other",
)

# Legacy basicInfo keys mapped into the new schema by migrate_basic_info.
_LEGACY_KEY_MAP = {"gender": "sex", "drive": "instinct"}
_DROPPED_KEYS = ("likes", "dislikes", "heightCm", "weightKg")


def migrate_basic_info(basic_info: dict | None, field_skill: dict | None = None) -> dict:
    """Upgrade an old-shape ``basicInfo`` (+ the old separate ``fieldSkill``) into
    the unified new schema. Pure and idempotent:

    - gender → sex, drive → instinct (renamed)
    - age (int) → apparentAge (str; 0/absent → "")
    - likes/dislikes/heightCm/weightKg → dropped
    - fieldSkill {name, description} → strengths "Name — description" (either alone
      if only one is set); an existing non-empty ``strengths`` is kept as-is
    - every key coerced to a string

    Callers persist the result themselves if they choose to.
    """
    src = dict(basic_info or {})
    for old, new in _LEGACY_KEY_MAP.items():
        if old in src and new not in src:
            src[new] = src[old]
    # apparentAge from a legacy numeric age (only when apparentAge isn't set).
    if "apparentAge" not in src and src.get("age"):
        src["apparentAge"] = str(src["age"])
    # strengths from a legacy fieldSkill (only when strengths isn't already set).
    if not (src.get("strengths") or "").strip():
        fs = dict(field_skill or {})
        n, d = str(fs.get("name") or "").strip(), str(fs.get("description") or "").strip()
        src["strengths"] = f"{n} — {d}" if n and d else (d or n)
    return {k: str(src.get(k) or "") for k in _BASIC_KEYS}


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


# ── Paths ─────────────────────────────────────────────────────────

def characters_dir() -> Path:
    return db.DATA_DIR / "characters"


# Built-in starter cards shipped in the repo (installed into the library on boot).
_BUNDLED_CARDS_DIR = Path(__file__).resolve().parent.parent / "templates" / "cards"


def install_bundled_cards() -> None:
    """Copy repo-shipped starter character cards into the library, keyed by their
    stable id. Idempotent — skips a card whose id folder already exists."""
    if not _BUNDLED_CARDS_DIR.exists():
        return
    for src in sorted(_BUNDLED_CARDS_DIR.iterdir()):
        if not src.is_dir():
            continue
        try:
            data = json.loads((src / _JSON_NAME).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        cid = data.get("id")
        if not cid or exists(cid):
            continue
        dest = char_dir(cid)
        dest.mkdir(parents=True, exist_ok=True)
        for f in src.iterdir():
            if f.is_file():
                shutil.copy(f, dest / f.name)


def char_dir(cid: str) -> Path:
    return characters_dir() / cid


def char_json_path(cid: str) -> Path:
    return char_dir(cid) / _JSON_NAME


def full_path(cid: str) -> Path | None:
    """The character's full-art image (any extension), or None."""
    d = char_dir(cid)
    if not d.exists():
        return None
    for p in sorted(d.glob(f"{_FULL_STEM}.*")):
        if p.is_file():
            return p
    return None


def crop_path(cid: str) -> Path | None:
    p = char_dir(cid) / _CROP_NAME
    return p if p.exists() else None


def voice_path(cid: str) -> Path | None:
    """The character's TTS voice sample (any extension), or None."""
    d = char_dir(cid)
    if not d.exists():
        return None
    for p in sorted(d.glob(f"{_VOICE_STEM}.*")):
        if p.is_file():
            return p
    return None


def exists(cid: str) -> bool:
    return char_json_path(cid).exists()


# ── Identity read/write ───────────────────────────────────────────

def _clean_basic_info(basic_info: dict | None) -> dict:
    # migrate_basic_info both maps any legacy keys and coerces to the new schema,
    # so a caller may pass either an old- or new-shape dict.
    return migrate_basic_info(basic_info)


# Identity-file cache keyed on the json's mtime — party/PC composites are
# loaded several times per chat turn (narrator, Chronicler, suggester), and
# each load was a disk read + json parse per member without this.
_read_cache: dict[str, tuple[float, dict]] = {}


def read_character(cid: str) -> dict | None:
    path = char_json_path(cid)
    try:
        mtime = path.stat().st_mtime
        cached = _read_cache.get(cid)
        if cached and cached[0] == mtime:
            return dict(cached[1])
        data = json.loads(path.read_text(encoding="utf-8"))
        # Upgrade legacy files to the unified schema on read (idempotent): fold
        # the old separate fieldSkill into basicInfo.strengths, map renamed keys.
        data["basicInfo"] = migrate_basic_info(data.get("basicInfo"), data.get("fieldSkill"))
        data.pop("fieldSkill", None)
        data["schemaVersion"] = SCHEMA_VERSION
        _read_cache[cid] = (mtime, data)
        return dict(data)
    except (OSError, json.JSONDecodeError):
        _read_cache.pop(cid, None)
        return None


def write_character(cid: str, data: dict) -> None:
    char_dir(cid).mkdir(parents=True, exist_ok=True)
    char_json_path(cid).write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    _read_cache.pop(cid, None)


def create_character(
    type: str = "character",
    basic_info: dict | None = None,
    cid: str | None = None,
    created_at: str | None = None,
) -> dict:
    """Create + persist a new character identity file. Returns the identity dict."""
    cid = cid or str(uuid.uuid4())
    data = {
        "id": cid,
        "type": "persona" if type == "persona" else "character",
        "schemaVersion": SCHEMA_VERSION,
        "createdAt": created_at or _now(),
        "basicInfo": _clean_basic_info(basic_info),
    }
    write_character(cid, data)
    return data


def update_identity(cid: str, basic_info: dict | None = None) -> dict | None:
    """Patch a character's basicInfo. Returns the updated identity, or None if the
    character doesn't exist."""
    data = read_character(cid)
    if data is None:
        return None
    if basic_info is not None:
        data["basicInfo"] = _clean_basic_info(basic_info)
    write_character(cid, data)
    return data


def list_characters() -> list[dict]:
    """All character identities (each with a ``hasPortrait`` flag), newest last."""
    root = characters_dir()
    out: list[dict] = []
    if not root.exists():
        return out
    for child in root.iterdir():
        if not child.is_dir():
            continue
        data = read_character(child.name)
        if data:
            data = {**data, "hasFull": full_path(child.name) is not None,
                    "hasCrop": crop_path(child.name) is not None,
                    "hasVoice": voice_path(child.name) is not None}
            out.append(data)
    out.sort(key=lambda d: d.get("createdAt", ""))
    return out


def delete_character(cid: str) -> bool:
    _read_cache.pop(cid, None)
    d = char_dir(cid)
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
        return True
    return False


def duplicate_character(cid: str) -> dict | None:
    """Fork a character into a new independent copy (new id, copied portraits)."""
    src = read_character(cid)
    if src is None:
        return None
    new = create_character(
        type=src.get("type", "character"),
        basic_info=src.get("basicInfo"),
    )
    fp = full_path(cid)
    if fp:
        set_full(new["id"], fp.read_bytes(), fp.suffix)
    cp = crop_path(cid)
    if cp:
        set_crop(new["id"], cp.read_bytes())
    vp = voice_path(cid)
    if vp:
        set_voice(new["id"], vp.read_bytes(), vp.suffix)
    return new


# ── Portraits (only ever one full + one crop; replacing deletes the old) ──

def set_full(cid: str, data: bytes, ext: str) -> None:
    d = char_dir(cid)
    d.mkdir(parents=True, exist_ok=True)
    for old in d.glob(f"{_FULL_STEM}.*"):
        old.unlink(missing_ok=True)
    ext = ext if ext.startswith(".") else f".{ext}"
    (d / f"{_FULL_STEM}{ext or '.png'}").write_bytes(data)


def set_crop(cid: str, data: bytes) -> None:
    d = char_dir(cid)
    d.mkdir(parents=True, exist_ok=True)
    (d / _CROP_NAME).write_bytes(data)


def clear_portrait(cid: str) -> None:
    d = char_dir(cid)
    if not d.exists():
        return
    for old in d.glob(f"{_FULL_STEM}.*"):
        old.unlink(missing_ok=True)
    (d / _CROP_NAME).unlink(missing_ok=True)


# ── Voice sample (only ever one; replacing deletes the old) ───────

def set_voice(cid: str, data: bytes, ext: str) -> None:
    d = char_dir(cid)
    d.mkdir(parents=True, exist_ok=True)
    for old in d.glob(f"{_VOICE_STEM}.*"):
        old.unlink(missing_ok=True)
    ext = ext if ext.startswith(".") else f".{ext}"
    (d / f"{_VOICE_STEM}{ext or '.wav'}").write_bytes(data)


def clear_voice(cid: str) -> None:
    d = char_dir(cid)
    if not d.exists():
        return
    for old in d.glob(f"{_VOICE_STEM}.*"):
        old.unlink(missing_ok=True)


# ── Portability (zip a folder; import as a new character) ─────────

def export_zip(cid: str) -> bytes | None:
    """Bundle a character folder (json + portraits) for sharing/download."""
    d = char_dir(cid)
    if not exists(cid):
        return None
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in d.iterdir():
            if p.is_file():
                z.write(p, p.name)
    return buf.getvalue()


def import_zip(raw: bytes) -> dict | None:
    """Unpack an uploaded character zip into a NEW library character (fresh id)."""
    try:
        z = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        return None
    try:
        identity = json.loads(z.read(_JSON_NAME))
    except (KeyError, json.JSONDecodeError):
        return None
    # A zip may carry a legacy-shaped card — migrate_basic_info (via
    # create_character's _clean_basic_info) folds fieldSkill into strengths.
    new = create_character(
        type=identity.get("type", "character"),
        basic_info=migrate_basic_info(identity.get("basicInfo"), identity.get("fieldSkill")),
    )
    for name in z.namelist():
        base = name.rsplit("/", 1)[-1]
        if base.startswith(f"{_FULL_STEM}."):
            set_full(new["id"], z.read(name), Path(base).suffix)
        elif base == _CROP_NAME:
            set_crop(new["id"], z.read(name))
        elif base.startswith(f"{_VOICE_STEM}."):
            set_voice(new["id"], z.read(name), Path(base).suffix)
    return new
