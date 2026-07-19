# Character & Party Member Unification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the PC, party members, and lore "Characters" (NPCs) one shared identity schema, move character storage from a global folder to per-campaign folders, and make lorebook Characters thin pointers into character files so promote/demote (party ↔ NPC) is non-destructive.

**Architecture:** The spec is large and touches core storage, so it is split into **three sequential phases**, each of which leaves the app fully working and tested:

- **Phase A — Unified identity schema (this plan, fully specified below).** Replace the old `basicInfo` field set (`gender`/`age`/`heightCm`/`weightKg`/`likes`/`dislikes`/`drive`) and the separate `fieldSkill` object with the leaner PbtA-flavored schema (`sex`, `apparentAge`, `instinct`, `strengths`, keeping `name`/`species`/`description`/`personality`/`other`). A single pure `migrate_basic_info()` helper upgrades every existing character file on read, and every consumer (prompt builder, spotlight, action suggester, narrator/Chronicler/Editor tools, client sheets) is updated. Storage location and the lore-pointer model are unchanged in this phase.
- **Phase B — Storage relocation (roadmap below).** Move character folders from global `server/data/characters/` to campaign-scoped `server/data/campaigns/<cid>/characters/`, with a one-time migration and export/import/template rewiring.
- **Phase C — Lore Characters as pointers + promote/demote + Bond (roadmap below).** Give `cat=="characters"` lore entries a `character_id` pointer, compose their `content` from the linked character, add the non-destructive promote/demote flow, the per-adventure `Bond` field, and the non-PM `equipment` text field, and rewire the Chronicler/Editor.

**Only Phase A is task-broken-down for execution here.** Phases B and C are scoped as roadmaps at the end; write each as its own plan (via `superpowers:writing-plans`) once the preceding phase merges. This mirrors the Species feature's one-focused-plan cadence and keeps each phase independently shippable and reviewable.

**Tech Stack:** Python + FastAPI + SQLAlchemy (async, aiosqlite) on the server; React + TypeScript + Zustand on the client. No new dependencies. Character identity lives in portable JSON files (`server/db/characters.py`), per-adventure state on `PartyBinding` rows (`server/db/party.py`).

## Global Constraints

- **Full replacement, not additive.** The old `basicInfo` keys `gender`, `age`, `heightCm`, `weightKg`, `likes`, `dislikes`, `drive` and the separate `fieldSkill` object are removed. Every consumer of those names must be updated in the same phase.
- **New unified `basicInfo` keys (all strings):** `name`, `species`, `sex`, `apparentAge`, `description`, `personality`, `instinct`, `strengths`, `other`. `apparentAge` is **freeform text** (e.g. "looks mid-20s", "ageless"), not a number. `strengths` is a **single freeform string** (1-3 GM-facing moves, Perilous-Wilds-Follower style) that replaces the old `fieldSkill` name+description object.
- **Migration is one-time, idempotent, non-destructive** — matches the existing `migrate_*` helpers in `server/db/database.py`. Old files are upgraded on read via a pure function; running twice changes nothing further.
- **The PC uses the exact same schema** as party members and NPCs, including `instinct` and `strengths`.
- **Bond and the non-PM `equipment` text field are Phase C**, not Phase A — they need the promote/demote UI to have a home. Do not add them in Phase A.
- **Storage location is unchanged in Phase A** — character files stay at the current global `server/data/characters/<id>/`. Relocation is Phase B.
- Follow existing conventions exactly: file locations, docstring style, and the test patterns in `server/tests/test_spotlight.py`, `server/tests/test_prompt_builder.py`, and `server/tests/test_app_integration.py`. `WAYWARD_DATA_DIR` (set by `server/tests/conftest.py`) must never be bypassed.
- One pre-existing test failure is unrelated to this work: `server/tests/test_story_style.py::test_core_and_guides_default_to_fallbacks` fails on Windows due to a console-encoding mismatch of an em-dash. It fails identically on `master` before any change here. Treat "full suite green except that one" as passing.

---

# Phase A — Unified Identity Schema

### Task A1: `migrate_basic_info` + new character-file schema

**Files:**
- Modify: `server/db/characters.py` (`SCHEMA_VERSION`, `_BASIC_KEYS`, `_clean_basic_info`, add `migrate_basic_info`, drop `_clean_field_skill` and all `field_skill` params, `read_character`, `create_character`, `update_identity`, `duplicate_character`, `import_zip`)
- Modify: `server/db/party.py` (`RuntimeCharacter`, `_compose`, `add_member`, `update_member_identity`, `set_pc_identity` — drop `field_skill`)
- Modify: `server/db/database.py` (`migrate_characters_to_files` — fold legacy `field_skill` into `basicInfo.strengths`)
- Test: `server/tests/test_character_identity.py` (new)

**Interfaces:**
- Produces: `migrate_basic_info(basic_info: dict | None, field_skill: dict | None = None) -> dict` in `server.db.characters` — pure, idempotent; maps old keys → new and folds `field_skill` into `strengths`. `char_files.create_character(type, basic_info, cid=None, created_at=None)` and `char_files.update_identity(cid, basic_info)` no longer take `field_skill`. `RuntimeCharacter` no longer has a `field_skill` attribute; `strengths` lives in `basic_info`.

> **Note on green state:** ending this task, the server data layer is consistent, but the AI consumers (`prompt_builder.py`, `spotlight.py`, etc.) still read the removed `field_skill` — so `test_prompt_builder.py` and `test_spotlight.py` will FAIL until Task A2 lands. This is an intentional, documented red window (same pattern the Species plan used between its client-rename tasks). Task A1's own new test file must pass; the two named legacy test files are restored to green in Task A2.

- [ ] **Step 1: Write the failing test**

Create `server/tests/test_character_identity.py`:

```python
"""Unified character identity schema — the migrate_basic_info seam and the
character-file read/write round-trip (see the Character Unification plan)."""

from server.db import characters as char_files
from server.db.characters import migrate_basic_info


# ── Pure: old-shape → new-shape migration ──────────────────────────

def test_migrate_maps_old_keys_to_new():
    got = migrate_basic_info(
        {
            "name": "Varena", "gender": "female", "species": "elf",
            "age": 120, "heightCm": 170, "weightKg": 60,
            "description": "Tall and watchful.", "personality": "Wry.",
            "drive": "Protect the weak.", "likes": "rain", "dislikes": "liars",
            "other": "Left-handed.",
        },
        {"name": "Sharpshooter", "description": "Never misses at range."},
    )
    assert got == {
        "name": "Varena",
        "species": "elf",
        "sex": "female",
        "apparentAge": "120",
        "description": "Tall and watchful.",
        "personality": "Wry.",
        "instinct": "Protect the weak.",
        "strengths": "Sharpshooter — Never misses at range.",
        "other": "Left-handed.",
    }
    # No leftover legacy keys.
    for dead in ("gender", "age", "heightCm", "weightKg", "likes", "dislikes", "drive"):
        assert dead not in got


def test_migrate_is_idempotent_on_new_shape():
    new = {
        "name": "Hero", "species": "human", "sex": "", "apparentAge": "",
        "description": "", "personality": "", "instinct": "",
        "strengths": "Brawler — hits hard.", "other": "",
    }
    assert migrate_basic_info(new) == new


def test_migrate_strengths_combine_variants():
    assert migrate_basic_info({}, {"name": "Scout", "description": ""})["strengths"] == "Scout"
    assert migrate_basic_info({}, {"name": "", "description": "Sneaky."})["strengths"] == "Sneaky."
    assert migrate_basic_info({}, {"name": "", "description": ""})["strengths"] == ""
    # An existing strengths string wins over a (stale) field_skill.
    assert migrate_basic_info({"strengths": "Keep this."}, {"name": "X", "description": "Y"})["strengths"] == "Keep this."


def test_migrate_empty_age_is_blank_not_zero():
    assert migrate_basic_info({"age": 0})["apparentAge"] == ""
    assert migrate_basic_info({"age": 30})["apparentAge"] == "30"


# ── Integration: character files read back in the new shape ─────────

def test_create_and_read_uses_new_schema():
    ch = char_files.create_character("character", {
        "name": "Test NPC", "sex": "nonbinary", "apparentAge": "ageless",
        "species": "spirit", "description": "A drifting light.",
        "personality": "Curious.", "instinct": "Wander toward warmth.",
        "strengths": "Phasewalk — slips through walls.", "other": "Hums.",
    })
    read = char_files.read_character(ch["id"])
    assert read["basicInfo"]["sex"] == "nonbinary"
    assert read["basicInfo"]["apparentAge"] == "ageless"
    assert read["basicInfo"]["strengths"] == "Phasewalk — slips through walls."
    assert "fieldSkill" not in read
    assert read["schemaVersion"] == 2
    char_files.delete_character(ch["id"])


def test_legacy_file_is_migrated_on_read():
    import json
    ch = char_files.create_character("character", {"name": "Legacy"})
    # Hand-write a legacy-shaped file (old keys + top-level fieldSkill).
    char_files.write_character(ch["id"], {
        "id": ch["id"], "type": "character", "schemaVersion": 1,
        "basicInfo": {"name": "Legacy", "gender": "male", "age": 40, "drive": "Revenge."},
        "fieldSkill": {"name": "Duelist", "description": "Deadly with a blade."},
    })
    read = char_files.read_character(ch["id"])
    assert read["basicInfo"]["sex"] == "male"
    assert read["basicInfo"]["apparentAge"] == "40"
    assert read["basicInfo"]["instinct"] == "Revenge."
    assert read["basicInfo"]["strengths"] == "Duelist — Deadly with a blade."
    assert "fieldSkill" not in read
    assert "gender" not in read["basicInfo"]
    char_files.delete_character(ch["id"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest server/tests/test_character_identity.py -v`
Expected: FAIL with `ImportError: cannot import name 'migrate_basic_info'`

- [ ] **Step 3: Rewrite the schema constants + add `migrate_basic_info` in `server/db/characters.py`**

Find (lines ~26-37):

```python
SCHEMA_VERSION = 1
_CROP_NAME = "crop.jpg"
_FULL_STEM = "full"
_VOICE_STEM = "voice"
_JSON_NAME = "character.json"

# Identity fields carried by a character.json's basicInfo (portrait is NOT one —
# the portrait is the sibling image files).
_BASIC_KEYS = (
    "name", "gender", "species", "age", "heightCm", "weightKg",
    "description", "likes", "dislikes", "personality", "drive", "other",
)
```

Replace with:

```python
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
```

- [ ] **Step 4: Rewrite `_clean_basic_info`, drop `_clean_field_skill`, and update the identity read/write helpers**

Find (lines ~117-160):

```python
def _clean_basic_info(basic_info: dict | None) -> dict:
    bi = dict(basic_info or {})
    out: dict = {}
    for k in _BASIC_KEYS:
        if k in ("age", "heightCm", "weightKg"):
            out[k] = int(bi.get(k) or 0)
        else:
            out[k] = bi.get(k) or ""
    return out


def _clean_field_skill(field_skill: dict | None) -> dict:
    fs = dict(field_skill or {})
    return {"name": fs.get("name") or "", "description": fs.get("description") or ""}


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
        _read_cache[cid] = (mtime, data)
        return dict(data)
    except (OSError, json.JSONDecodeError):
        _read_cache.pop(cid, None)
        return None
```

Replace with:

```python
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
```

- [ ] **Step 5: Drop `field_skill` from `create_character` / `update_identity`**

Find (lines ~162-196):

```python
def create_character(
    type: str = "character",
    basic_info: dict | None = None,
    field_skill: dict | None = None,
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
        "fieldSkill": _clean_field_skill(field_skill),
    }
    write_character(cid, data)
    return data


def update_identity(
    cid: str, basic_info: dict | None = None, field_skill: dict | None = None
) -> dict | None:
    """Patch a character's basicInfo/fieldSkill (whichever is given). Returns the
    updated identity, or None if the character doesn't exist."""
    data = read_character(cid)
    if data is None:
        return None
    if basic_info is not None:
        data["basicInfo"] = _clean_basic_info(basic_info)
    if field_skill is not None:
        data["fieldSkill"] = _clean_field_skill(field_skill)
    write_character(cid, data)
    return data
```

Replace with:

```python
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
```

- [ ] **Step 6: Drop `field_skill` from `duplicate_character` and `import_zip`**

Find in `duplicate_character` (lines ~232-236):

```python
    new = create_character(
        type=src.get("type", "character"),
        basic_info=src.get("basicInfo"),
        field_skill=src.get("fieldSkill"),
    )
```

Replace with:

```python
    new = create_character(
        type=src.get("type", "character"),
        basic_info=src.get("basicInfo"),
    )
```

Find in `import_zip` (lines ~319-323):

```python
    new = create_character(
        type=identity.get("type", "character"),
        basic_info=identity.get("basicInfo"),
        field_skill=identity.get("fieldSkill"),
    )
```

Replace with:

```python
    # A zip may carry a legacy-shaped card — migrate_basic_info (via
    # create_character's _clean_basic_info) folds fieldSkill into strengths.
    new = create_character(
        type=identity.get("type", "character"),
        basic_info=migrate_basic_info(identity.get("basicInfo"), identity.get("fieldSkill")),
    )
```

- [ ] **Step 7: Drop `field_skill` from `server/db/party.py`**

Find `RuntimeCharacter` (lines ~21-46):

```python
@dataclass
class RuntimeCharacter:
    id: str                 # character id (identity file) — the app-wide handle
    binding_id: str         # PartyBinding row id (internal)
    type: str               # persona | character
    role: str               # pc | member
    basic_info: dict
    field_skill: dict
    equipment: dict
    in_party: bool
    last_spoke_turn: int


def _compose(binding: PartyBinding, identity: dict | None) -> RuntimeCharacter:
    identity = identity or {}
    return RuntimeCharacter(
        id=binding.character_id,
        binding_id=binding.id,
        type=identity.get("type", "persona" if binding.role == "pc" else "character"),
        role=binding.role,
        basic_info=dict(identity.get("basicInfo") or {}),
        field_skill=dict(identity.get("fieldSkill") or {}),
        equipment=dict(binding.equipment or {}),
        in_party=bool(binding.in_party),
        last_spoke_turn=binding.last_spoke_turn or 0,
    )
```

Replace with:

```python
@dataclass
class RuntimeCharacter:
    id: str                 # character id (identity file) — the app-wide handle
    binding_id: str         # PartyBinding row id (internal)
    type: str               # persona | character
    role: str               # pc | member
    basic_info: dict        # unified schema incl. `strengths` (see characters.py)
    equipment: dict
    in_party: bool
    last_spoke_turn: int


def _compose(binding: PartyBinding, identity: dict | None) -> RuntimeCharacter:
    identity = identity or {}
    return RuntimeCharacter(
        id=binding.character_id,
        binding_id=binding.id,
        type=identity.get("type", "persona" if binding.role == "pc" else "character"),
        role=binding.role,
        basic_info=dict(identity.get("basicInfo") or {}),
        equipment=dict(binding.equipment or {}),
        in_party=bool(binding.in_party),
        last_spoke_turn=binding.last_spoke_turn or 0,
    )
```

Find `set_pc_identity` (lines ~143-157):

```python
async def set_pc_identity(
    session: AsyncSession, basic_info: dict | None, field_skill: dict | None = None
) -> RuntimeCharacter:
    """Upsert the player character: create the persona file + pc binding on first
    call; otherwise patch the identity file. Equipment is set separately."""
    b = await pc_binding(session)
    if b is None:
        identity = char_files.create_character("persona", basic_info, field_skill)
        b = PartyBinding(character_id=identity["id"], role="pc", in_party=True, sort_order=0)
        session.add(b)
        await session.flush()
    else:
        identity = char_files.update_identity(b.character_id, basic_info, field_skill) \
            or char_files.create_character("persona", basic_info, field_skill, cid=b.character_id)
    return _compose(b, identity)
```

Replace with:

```python
async def set_pc_identity(
    session: AsyncSession, basic_info: dict | None
) -> RuntimeCharacter:
    """Upsert the player character: create the persona file + pc binding on first
    call; otherwise patch the identity file. Equipment is set separately."""
    b = await pc_binding(session)
    if b is None:
        identity = char_files.create_character("persona", basic_info)
        b = PartyBinding(character_id=identity["id"], role="pc", in_party=True, sort_order=0)
        session.add(b)
        await session.flush()
    else:
        identity = char_files.update_identity(b.character_id, basic_info) \
            or char_files.create_character("persona", basic_info, cid=b.character_id)
    return _compose(b, identity)
```

Find `add_member` (lines ~168-183):

```python
async def add_member(
    session: AsyncSession,
    basic_info: dict | None = None,
    field_skill: dict | None = None,
    in_party: bool = True,
    character_id: str | None = None,
) -> RuntimeCharacter:
    """Create a new character file + a member binding for this adventure."""
    identity = char_files.create_character("character", basic_info, field_skill, cid=character_id)
```

Replace with:

```python
async def add_member(
    session: AsyncSession,
    basic_info: dict | None = None,
    in_party: bool = True,
    character_id: str | None = None,
) -> RuntimeCharacter:
    """Create a new character file + a member binding for this adventure."""
    identity = char_files.create_character("character", basic_info, cid=character_id)
```

Find `update_member_identity` (lines ~202-211):

```python
async def update_member_identity(
    session: AsyncSession, character_id: str, basic_info: dict | None, field_skill: dict | None
) -> RuntimeCharacter | None:
    b = await binding_for(session, character_id)
    if b is None or b.role != "member":
        return None
    identity = char_files.update_identity(character_id, basic_info, field_skill)
    if identity is None:
        return None
    return _compose(b, identity)
```

Replace with:

```python
async def update_member_identity(
    session: AsyncSession, character_id: str, basic_info: dict | None
) -> RuntimeCharacter | None:
    b = await binding_for(session, character_id)
    if b is None or b.role != "member":
        return None
    identity = char_files.update_identity(character_id, basic_info)
    if identity is None:
        return None
    return _compose(b, identity)
```

- [ ] **Step 8: Fold legacy `field_skill` into `basicInfo.strengths` in `migrate_characters_to_files`**

In `server/db/database.py`, find (lines ~491-510):

```python
        pc = (await s.execute(select(PlayerCharacter))).scalars().first() if pc_exists else None
        if pc is not None:
            # Don't clobber an existing character file (e.g. a bundled card the
            # row is linked to by id) — only mint identity when it's new.
            if not char_files.exists(pc.id):
                char_files.create_character("persona", pc.basic_info, None, cid=pc.id)
                _seed_portrait(pc.id, pc.basic_info)
            s.add(PartyBinding(character_id=pc.id, role="pc",
                               equipment=pc.equipment or {}, in_party=True, sort_order=0))
            await s.delete(pc)

        members = (await s.execute(select(PartyMember))).scalars().all() if pm_exists else []
        for i, m in enumerate(members):
            if not char_files.exists(m.id):
                char_files.create_character("character", m.basic_info, m.field_skill, cid=m.id)
                _seed_portrait(m.id, m.basic_info)
            s.add(PartyBinding(character_id=m.id, role="member", equipment=m.equipment or {},
                               in_party=bool(m.in_party), last_spoke_turn=m.last_spoke_turn or 0,
                               sort_order=i))
            await s.delete(m)
```

Replace with:

```python
        pc = (await s.execute(select(PlayerCharacter))).scalars().first() if pc_exists else None
        if pc is not None:
            # Don't clobber an existing character file (e.g. a bundled card the
            # row is linked to by id) — only mint identity when it's new.
            if not char_files.exists(pc.id):
                char_files.create_character(
                    "persona", char_files.migrate_basic_info(pc.basic_info), cid=pc.id)
                _seed_portrait(pc.id, pc.basic_info)
            s.add(PartyBinding(character_id=pc.id, role="pc",
                               equipment=pc.equipment or {}, in_party=True, sort_order=0))
            await s.delete(pc)

        members = (await s.execute(select(PartyMember))).scalars().all() if pm_exists else []
        for i, m in enumerate(members):
            if not char_files.exists(m.id):
                # Fold the legacy separate field_skill into basicInfo.strengths.
                char_files.create_character(
                    "character", char_files.migrate_basic_info(m.basic_info, m.field_skill), cid=m.id)
                _seed_portrait(m.id, m.basic_info)
            s.add(PartyBinding(character_id=m.id, role="member", equipment=m.equipment or {},
                               in_party=bool(m.in_party), last_spoke_turn=m.last_spoke_turn or 0,
                               sort_order=i))
            await s.delete(m)
```

Note: `_seed_portrait` reads `(basic_info or {}).get("portrait")` from the *legacy* row's `basic_info` (which still has the old `portrait` key) — pass the raw `m.basic_info`/`pc.basic_info` to it (as above), not the migrated dict, since `migrate_basic_info` drops `portrait`.

- [ ] **Step 9: Run the new test to verify it passes**

Run: `python -m pytest server/tests/test_character_identity.py -v`
Expected: PASS (7 tests)

- [ ] **Step 10: Commit**

```bash
git add server/db/characters.py server/db/party.py server/db/database.py server/tests/test_character_identity.py
git commit -m "feat: unified character identity schema + migrate_basic_info"
```

(The full suite is intentionally red on `test_prompt_builder`/`test_spotlight` here — restored in Task A2.)

---

### Task A2: AI consumers — prompt builder, spotlight, action suggester, agent tools

**Files:**
- Modify: `server/ai/prompt_builder.py` (PC summary + party roster)
- Modify: `server/ai/spotlight.py` (`strengths`-based relevance; `SpotlightSignal`; block text; default rule)
- Modify: `server/ai/action_suggester.py` (Personality & Instinct)
- Modify: `server/ai/narrator_actions.py` (`tool_get_character` payload)
- Modify: `server/ai/worldbuilder.py` (`create_member` tool schema + proposal + apply; guidance)
- Modify: `server/ai/planner.py` (`create_member`/`update_member`/`update_pc` tool schemas + apply)
- Modify: `server/tests/test_prompt_builder.py`, `server/tests/test_spotlight.py` (update field names)
- Test: `server/tests/test_character_identity.py` (append a Chronicler `create_member` case)

**Interfaces:**
- Consumes: `RuntimeCharacter.basic_info["strengths"]`/`["instinct"]`/`["sex"]`/`["apparentAge"]` from Task A1 (no more `field_skill`).
- Produces: restores the full suite to green.

- [ ] **Step 1: Update the failing legacy tests first (they define the new expectations)**

Open `server/tests/test_spotlight.py`. Every place that builds a member with `field_skill={"name": ..., "description": ...}` must instead put the skill text in `basic_info["strengths"]`, and any assertion referencing `field_skill_relevant` becomes `strengths_relevant`. Concretely, find each helper/fixture building a `RuntimeCharacter` (or the dict passed to `compute_spotlight_signals`) and change, e.g.:

```python
RuntimeCharacter(..., basic_info={"name": "Rosalina"}, field_skill={"name": "Lumas", "description": "commands star sprites"}, ...)
```

to:

```python
RuntimeCharacter(..., basic_info={"name": "Rosalina", "strengths": "Lumas — commands star sprites"}, ...)
```

and update the `RuntimeCharacter(...)` constructor call to drop the `field_skill=` keyword argument entirely (the dataclass no longer has that field). Rename any `signal.field_skill_relevant` assertions to `signal.strengths_relevant`.

Open `server/tests/test_prompt_builder.py`. Any fixture member built with `field_skill=` must move that text into `basic_info["strengths"]` and drop the `field_skill=` kwarg; any assertion checking the roster prints `"Field Skill:"` becomes `"Strengths:"`, and PC-summary assertions checking `"Drive"` become `"Instinct"`.

Run: `python -m pytest server/tests/test_spotlight.py server/tests/test_prompt_builder.py -v`
Expected: FAIL (the production code still emits `field_skill`/`Drive`) — these now encode the new contract.

- [ ] **Step 2: Update `server/ai/spotlight.py`**

Find (lines ~75-122):

```python
@dataclass
class SpotlightSignal:
    member_id: str
    member_name: str
    directly_addressed: bool
    field_skill_relevant: bool
    turns_since_last_spoke: int
```

Replace with:

```python
@dataclass
class SpotlightSignal:
    member_id: str
    member_name: str
    directly_addressed: bool
    strengths_relevant: bool
    turns_since_last_spoke: int
```

Find (inside `compute_spotlight_signals`, lines ~102-122):

```python
        # Field skill relevance: keyword overlap. Include the skill NAME's
        # distinctive tokens (e.g. 'Luma', 'Wrecking') — they recur in scenes
        # far more than the prose of the description.
        skill_name = pm.field_skill.get("name", "")
        skill_desc = pm.field_skill.get("description", "")
        skill_keywords = _extract_keywords(f"{skill_name} {skill_desc}")
        field_skill_relevant = any(
            re.search(rf"\b{re.escape(kw)}\b", context_lower) for kw in skill_keywords
        )

        # Turns since last spoke
        last_spoke = pm.last_spoke_turn or 0
        turns_since = current_turn - last_spoke

        signals.append(SpotlightSignal(
            member_id=pm.id,
            member_name=name,
            directly_addressed=directly_addressed,
            field_skill_relevant=field_skill_relevant,
            turns_since_last_spoke=turns_since,
        ))
```

Replace with:

```python
        # Strengths relevance: keyword overlap with the character's Strengths
        # text (the 1-3 GM-facing moves) — its distinctive tokens recur in scenes
        # that intersect what the character is good at.
        strengths = pm.basic_info.get("strengths", "")
        strengths_keywords = _extract_keywords(strengths)
        strengths_relevant = any(
            re.search(rf"\b{re.escape(kw)}\b", context_lower) for kw in strengths_keywords
        )

        # Turns since last spoke
        last_spoke = pm.last_spoke_turn or 0
        turns_since = current_turn - last_spoke

        signals.append(SpotlightSignal(
            member_id=pm.id,
            member_name=name,
            directly_addressed=directly_addressed,
            strengths_relevant=strengths_relevant,
            turns_since_last_spoke=turns_since,
        ))
```

Find in `format_spotlight_block` (lines ~154-157):

```python
        if s.field_skill_relevant:
            parts.append("scene may intersect their Field Skill")
        else:
            parts.append("no clear relevance to this beat")
```

Replace with:

```python
        if s.strengths_relevant:
            parts.append("scene may intersect their Strengths")
        else:
            parts.append("no clear relevance to this beat")
```

Find in `DEFAULT_SPOTLIGHT_RULE` (lines ~138-139):

```python
        "sentences, true to their established character and Field Skill."
```

Replace with:

```python
        "sentences, true to their established character and Strengths."
```

- [ ] **Step 3: Update `server/ai/prompt_builder.py`**

Find the PC summary (lines ~162-172):

```python
    pc_lines = [
        f"PLAYER CHARACTER: {pc_info.get('name', 'Unknown')}, "
        f"a {pc_info.get('species', 'unknown')} {pc_info.get('gender', '').lower()}. "
        f"{pc_info.get('description', '')}"
    ]
    if pc_info.get('personality'):
        pc_lines.append(f"Personality: {pc_info['personality']}")
    if pc_info.get('drive'):
        pc_lines.append(f"Drive (what pushes them forward): {pc_info['drive']}")
    pc_lines.append(f"Carrying: {equip_str}")
    messages.append({"role": "system", "content": "\n".join(pc_lines)})
```

Replace with:

```python
    pc_lines = [
        f"PLAYER CHARACTER: {pc_info.get('name', 'Unknown')}, "
        f"a {pc_info.get('species', 'unknown')} {pc_info.get('sex', '').lower()}. "
        f"{pc_info.get('description', '')}"
    ]
    if pc_info.get('personality'):
        pc_lines.append(f"Personality: {pc_info['personality']}")
    if pc_info.get('instinct'):
        pc_lines.append(f"Instinct (what they tend to do): {pc_info['instinct']}")
    if pc_info.get('strengths'):
        pc_lines.append(f"Strengths: {pc_info['strengths']}")
    pc_lines.append(f"Carrying: {equip_str}")
    messages.append({"role": "system", "content": "\n".join(pc_lines)})
```

Find the party roster (lines ~176-196):

```python
        roster_lines = ["PARTY ROSTER:"]
        for pm in party_members:
            info = pm.basic_info
            skill = pm.field_skill
            equip_pm_str = _format_equipment(pm.equipment, catalog_lookup)
            lines = [
                f"  {info.get('name', 'Unknown')} — {info.get('species', 'unknown')}. "
                f"{info.get('description', '')}",
            ]
            if info.get('personality'):
                lines.append(f"    Personality: {info['personality']}")
            if info.get('likes'):
                lines.append(f"    Likes: {info['likes']}")
            if info.get('dislikes'):
                lines.append(f"    Dislikes: {info['dislikes']}")
            if info.get('other'):
                lines.append(f"    Other: {info['other']}")
            lines.append(f"    Field Skill: {skill.get('name', 'None')} — {skill.get('description', '')}")
            lines.append(f"    Carrying: {equip_pm_str}")
            roster_lines.append("\n".join(lines))
        messages.append({"role": "system", "content": "\n".join(roster_lines)})
```

Replace with:

```python
        roster_lines = ["PARTY ROSTER:"]
        for pm in party_members:
            info = pm.basic_info
            equip_pm_str = _format_equipment(pm.equipment, catalog_lookup)
            lines = [
                f"  {info.get('name', 'Unknown')} — {info.get('species', 'unknown')}. "
                f"{info.get('description', '')}",
            ]
            if info.get('personality'):
                lines.append(f"    Personality: {info['personality']}")
            if info.get('instinct'):
                lines.append(f"    Instinct: {info['instinct']}")
            if info.get('other'):
                lines.append(f"    Other: {info['other']}")
            lines.append(f"    Strengths: {info.get('strengths') or 'None'}")
            lines.append(f"    Carrying: {equip_pm_str}")
            roster_lines.append("\n".join(lines))
        messages.append({"role": "system", "content": "\n".join(roster_lines)})
```

- [ ] **Step 4: Update `server/ai/action_suggester.py`**

Find (lines ~256-260):

```python
        pc_lines = [f"PLAYER CHARACTER: {info.get('name') or 'Unknown'}"]
        if info.get("personality"):
            pc_lines.append(f"  Personality: {info['personality']}")
        if info.get("drive"):
            pc_lines.append(f"  Drive (what pushes them forward): {info['drive']}")
```

Replace with:

```python
        pc_lines = [f"PLAYER CHARACTER: {info.get('name') or 'Unknown'}"]
        if info.get("personality"):
            pc_lines.append(f"  Personality: {info['personality']}")
        if info.get("instinct"):
            pc_lines.append(f"  Instinct (what they tend to do): {info['instinct']}")
```

Find (line ~51):

```python
- Sound like THIS player character: when a PLAYER CHARACTER personality and drive are given, the options are that person's impulses — phrase them in their voice, and when the scene allows, let one speak to their drive.
```

Replace with:

```python
- Sound like THIS player character: when a PLAYER CHARACTER personality and instinct are given, the options are that person's impulses — phrase them in their voice, and when the scene allows, let one speak to their instinct.
```

- [ ] **Step 5: Update `tool_get_character` in `server/ai/narrator_actions.py`**

Find (lines ~546-556):

```python
    info = character.basic_info or {}
    payload = {
        "name": info.get("name", "Unknown"),
        "species": info.get("species", ""),
        "description": info.get("description", ""),
        "equipped": equipped,
    }
    field_skill = getattr(character, "field_skill", None)
    if field_skill:
        payload["fieldSkill"] = field_skill
    return ToolEffect(result=json.dumps(payload, ensure_ascii=False))
```

Replace with:

```python
    info = character.basic_info or {}
    payload = {
        "name": info.get("name", "Unknown"),
        "species": info.get("species", ""),
        "description": info.get("description", ""),
        "equipped": equipped,
    }
    if info.get("strengths"):
        payload["strengths"] = info["strengths"]
    return ToolEffect(result=json.dumps(payload, ensure_ascii=False))
```

- [ ] **Step 6: Update the Chronicler's `create_member` in `server/ai/worldbuilder.py`**

Find the `create_member` tool schema (lines ~213-231):

```python
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
```

Replace with:

```python
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
                    "sex": {"type": "string"},
                    "apparentAge": {"type": "string", "description": "Freeform, e.g. 'looks mid-20s', 'ageless'."},
                    "description": {"type": "string", "description": "Physical description."},
                    "personality": {"type": "string"},
                    "instinct": {"type": "string", "description": "What they tend to do — their behavioural bent."},
                    "strengths": {"type": "string", "description": "1-3 short GM-facing moves/abilities, as text."},
                    "other": {"type": "string"},
                },
                "required": ["name", "species", "description"],
            },
        },
    },
```

Find the `create_member` proposal builder in `_proposal_from_call` (lines ~468-483):

```python
    if name == "create_member":
        mname = (args.get("name") or "").strip()
        if not mname or not _is_named_character(mname) or await _member_exists(session, mname):
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
```

Replace with:

```python
    if name == "create_member":
        mname = (args.get("name") or "").strip()
        if not mname or not _is_named_character(mname) or await _member_exists(session, mname):
            return None
        payload = {
            "name": mname,
            "species": args.get("species", ""),
            "sex": args.get("sex", ""),
            "apparentAge": args.get("apparentAge", ""),
            "description": args.get("description", ""),
            "personality": args.get("personality", ""),
            "instinct": args.get("instinct", ""),
            "strengths": args.get("strengths", ""),
            "other": args.get("other", ""),
        }
        return WorldbuildingProposal(
            turn_number=turn_number, kind="member", operation="create",
            payload=payload, summary=_summary("member", "create", payload),
        )
```

Find the `create_member` apply in `apply_proposal` (lines ~562-572; the `_absorb_lore_character` call + `add_member`):

```python
        absorbed = await _absorb_lore_character(session, p.get("name", ""))
        description = p.get("description", "") or (absorbed or "")
        await party_ops.add_member(
            session,
            basic_info={
                "name": p.get("name", ""), "species": p.get("species", ""),
                "description": description, "personality": p.get("personality", ""),
            },
            field_skill={"name": p.get("fieldSkillName", ""), "description": p.get("fieldSkillDescription", "")},
        )
        return True, None
```

Replace with:

```python
        absorbed = await _absorb_lore_character(session, p.get("name", ""))
        description = p.get("description", "") or (absorbed or "")
        await party_ops.add_member(
            session,
            basic_info={
                "name": p.get("name", ""), "species": p.get("species", ""),
                "sex": p.get("sex", ""), "apparentAge": p.get("apparentAge", ""),
                "description": description, "personality": p.get("personality", ""),
                "instinct": p.get("instinct", ""), "strengths": p.get("strengths", ""),
                "other": p.get("other", ""),
            },
        )
        return True, None
```

(`_absorb_lore_character` is retained in Phase A — it is only removed in Phase C when the pointer model replaces it.)

Find the Chronicler guidance's `create_member` lines (lines ~126 and ~134) and leave them as-is — they don't name the skill fields. No change needed there.

- [ ] **Step 7: Update the Editor's member/PC tools in `server/ai/planner.py`**

Find `create_member`/`update_member`/`update_pc` tool schemas (lines ~182-207):

```python
    _fn("create_member", "Add a party member.",
        {"name": {"type": "string"}, "species": {"type": "string"}, "gender": {"type": "string"},
         "age": {"type": "integer"}, "heightCm": {"type": "integer"}, "weightKg": {"type": "integer"},
         "description": {"type": "string"}, "personality": {"type": "string"},
         "likes": {"type": "string"}, "dislikes": {"type": "string"},
         "other": {"type": "string", "description": "Anything that doesn't fit the other fields — quirks, history, relationships."},
         "fieldSkillName": {"type": "string"}, "fieldSkillDescription": {"type": "string"}}, ["name"]),
    _fn("update_member", "Edit a party member's details/field skill, by name. Pass newName to rename.",
        {"name": {"type": "string", "description": "Which member to edit (their current name)."},
         "newName": {"type": "string", "description": "New name, to rename the member."},
         "species": {"type": "string"}, "gender": {"type": "string"},
         "age": {"type": "integer"}, "heightCm": {"type": "integer"}, "weightKg": {"type": "integer"},
         "description": {"type": "string"}, "personality": {"type": "string"},
         "likes": {"type": "string"}, "dislikes": {"type": "string"},
         "other": {"type": "string", "description": "Anything that doesn't fit the other fields — quirks, history, relationships."},
         "fieldSkillName": {"type": "string"}, "fieldSkillDescription": {"type": "string"}}, ["name"]),
    _fn("delete_member", "Remove a party member entirely (queued for confirmation), by name.",
        {"name": {"type": "string"}}, ["name"]),
    _fn("set_in_party", "Bench or re-add a member to the active party, by name.",
        {"name": {"type": "string"}, "inParty": {"type": "boolean"}}, ["name", "inParty"]),
    _fn("update_pc", "Edit the player character's details.",
        {"name": {"type": "string"}, "species": {"type": "string"}, "gender": {"type": "string"},
         "age": {"type": "integer"}, "heightCm": {"type": "integer"}, "weightKg": {"type": "integer"},
         "description": {"type": "string"}, "personality": {"type": "string"},
         "drive": {"type": "string", "description": "What pushes the character forward — their goal, want, or need. Shapes the generated action options."},
         "likes": {"type": "string"}, "dislikes": {"type": "string"}}, []),
```

Replace with:

```python
    _fn("create_member", "Add a party member.",
        {"name": {"type": "string"}, "species": {"type": "string"}, "sex": {"type": "string"},
         "apparentAge": {"type": "string", "description": "Freeform, e.g. 'looks mid-20s', 'ageless'."},
         "description": {"type": "string", "description": "Physical description."},
         "personality": {"type": "string"},
         "instinct": {"type": "string", "description": "What they tend to do — their behavioural bent."},
         "strengths": {"type": "string", "description": "1-3 short GM-facing moves/abilities, as text."},
         "other": {"type": "string", "description": "Anything that doesn't fit the other fields — quirks, history, relationships."}}, ["name"]),
    _fn("update_member", "Edit a party member's details, by name. Pass newName to rename.",
        {"name": {"type": "string", "description": "Which member to edit (their current name)."},
         "newName": {"type": "string", "description": "New name, to rename the member."},
         "species": {"type": "string"}, "sex": {"type": "string"}, "apparentAge": {"type": "string"},
         "description": {"type": "string"}, "personality": {"type": "string"},
         "instinct": {"type": "string"}, "strengths": {"type": "string"},
         "other": {"type": "string", "description": "Anything that doesn't fit the other fields — quirks, history, relationships."}}, ["name"]),
    _fn("delete_member", "Remove a party member entirely (queued for confirmation), by name.",
        {"name": {"type": "string"}}, ["name"]),
    _fn("set_in_party", "Bench or re-add a member to the active party, by name.",
        {"name": {"type": "string"}, "inParty": {"type": "boolean"}}, ["name", "inParty"]),
    _fn("update_pc", "Edit the player character's details.",
        {"name": {"type": "string"}, "species": {"type": "string"}, "sex": {"type": "string"},
         "apparentAge": {"type": "string"},
         "description": {"type": "string"}, "personality": {"type": "string"},
         "instinct": {"type": "string", "description": "What they tend to do — shapes the generated action options."},
         "strengths": {"type": "string", "description": "1-3 short GM-facing moves/abilities, as text."}}, []),
```

Find the `create_member` apply block (lines ~454-471):

```python
    if name == "create_member":
        mname = (args.get("name") or "").strip()
        ...
            return f"'{mname}' already exists — use update_member.", None
        await party_ops.add_member(
            session,
            basic_info={"name": mname, "species": args.get("species", ""),
                        "description": args.get("description", ""), "personality": args.get("personality", ""),
                        "gender": args.get("gender", ""), "age": args.get("age", 0) or 0,
                        "heightCm": args.get("heightCm", 0) or 0, "weightKg": args.get("weightKg", 0) or 0,
                        "likes": args.get("likes", ""), "dislikes": args.get("dislikes", ""),
                        "other": args.get("other", "")},
            field_skill={"name": args.get("fieldSkillName", ""), "description": args.get("fieldSkillDescription", "")},
        )
```

Read the exact current block first (`Read` the file around lines 454-472), then replace the `add_member(...)` call with:

```python
        await party_ops.add_member(
            session,
            basic_info={"name": mname, "species": args.get("species", ""),
                        "sex": args.get("sex", ""), "apparentAge": args.get("apparentAge", ""),
                        "description": args.get("description", ""), "personality": args.get("personality", ""),
                        "instinct": args.get("instinct", ""), "strengths": args.get("strengths", ""),
                        "other": args.get("other", "")},
        )
```

Find the `update_member` apply loop (lines ~477-490):

```python
        if name == "update_member":
            ...
            for k in ("species", "gender", "age", "heightCm", "weightKg",
                      "description", "personality", "likes", "dislikes", "other"):
                if args.get(k) is not None:
                    bi[k] = args[k]
            ...
            fs = dict(member.field_skill or {})
            if args.get("fieldSkillName") is not None:
                fs["name"] = args["fieldSkillName"]
            if args.get("fieldSkillDescription") is not None:
                fs["description"] = args["fieldSkillDescription"]
            await party_ops.update_member_identity(session, member.id, bi, fs)
```

Read the exact block first, then replace the field loop + field_skill handling with:

```python
        if name == "update_member":
            ...
            for k in ("species", "sex", "apparentAge",
                      "description", "personality", "instinct", "strengths", "other"):
                if args.get(k) is not None:
                    bi[k] = args[k]
            ...
            await party_ops.update_member_identity(session, member.id, bi)
```

(Drop the `fs = ...`/`fieldSkillName`/`fieldSkillDescription` lines and the `newName` handling that sets `bi["name"]` stays as-is — only the field loop and the `field_skill` argument change.)

Find the `update_pc` apply loop (lines ~504-505):

```python
        for k in ("name", "species", "gender", "age", "heightCm", "weightKg",
                  "description", "personality", "drive", "likes", "dislikes"):
```

Replace with:

```python
        for k in ("name", "species", "sex", "apparentAge",
                  "description", "personality", "instinct", "strengths"):
```

Find the `get_entry` character branch (line ~640):

```python
                "fieldSkill": getattr(character, "field_skill", {}),
```

Read the surrounding block, then remove that line (the character's `strengths` now lives in `basicInfo`, already included wherever `basicInfo` is emitted). If `basicInfo` isn't already in that payload, add `"basicInfo": character.basic_info,` in its place.

Also update the Editor guidance line ~66 ("Edit them with update_pc / update_member") — no field names there, leave it.

- [ ] **Step 8: Append a Chronicler `create_member` test**

Append to `server/tests/test_character_identity.py`:

```python
from server.tests.conftest import run


def test_chronicler_create_member_uses_strengths(client):
    from server.ai.worldbuilder import _proposal_from_call, apply_proposal
    from server.db.database import new_session
    from server.db import party as party_ops

    async def make_and_apply():
        async with new_session() as s:
            proposal = await _proposal_from_call(
                s, turn_number=1, name="create_member",
                args={
                    "name": "Kestrel", "species": "human", "sex": "female",
                    "apparentAge": "looks late-30s", "description": "Scarred ranger.",
                    "personality": "Terse.", "instinct": "Scout ahead alone.",
                    "strengths": "Trailcraft — reads any track; Longshot — deadly at range.",
                },
                member_names=set(), pc_name="", narration="Kestrel joins the party.",
            )
            assert proposal is not None
            ok, note = await apply_proposal(proposal, s)
            assert ok, note
            await s.commit()
            members = await party_ops.load_party(s)
            return next(m for m in members if m.basic_info.get("name") == "Kestrel")
    m = run(make_and_apply())
    assert m.basic_info["sex"] == "female"
    assert m.basic_info["apparentAge"] == "looks late-30s"
    assert m.basic_info["instinct"] == "Scout ahead alone."
    assert m.basic_info["strengths"].startswith("Trailcraft")
    assert not hasattr(m, "field_skill")
```

- [ ] **Step 9: Run the affected suites to verify green**

Run: `python -m pytest server/tests/test_spotlight.py server/tests/test_prompt_builder.py server/tests/test_character_identity.py -v`
Expected: PASS

- [ ] **Step 10: Run the full server suite**

Run: `python -m pytest server/tests -q`
Expected: PASS except the one pre-existing unrelated failure noted in Global Constraints.

- [ ] **Step 11: Commit**

```bash
git add server/ai/ server/tests/test_spotlight.py server/tests/test_prompt_builder.py server/tests/test_character_identity.py
git commit -m "feat: update AI consumers to the unified character schema"
```

---

### Task A3: API schemas + client (types, stores, sheets)

**Files:**
- Modify: `server/api/schemas.py` (`BasicInfoSchema`, remove `FieldSkillSchema`, PM create/update/response)
- Modify: `server/api/common.py` (`_pm_to_response` drop `fieldSkill`)
- Modify: `server/api/characters.py` (`add_party_member`, `update_party_member` drop `fieldSkill`)
- Modify: `shared/types/models.ts` (`BasicInfo`, remove `FieldSkill`, `PartyMember`, `CharacterCard`)
- Modify: `client/src/components/CharacterSheet/CharacterSheetEditor.tsx`
- Modify: `client/src/components/PartyMember/PartyMemberEditor.tsx`
- Modify: any client store/inspector referencing `fieldSkill`/removed fields (grep-driven)

**Interfaces:**
- Consumes: the server responses no longer carry `fieldSkill`; `basicInfo` carries `sex`/`apparentAge`/`instinct`/`strengths`/`other`.

- [ ] **Step 1: Update `server/api/schemas.py`**

Find (lines ~9-23):

```python
class BasicInfoSchema(BaseModel):
    name: str = ""
    gender: str = ""
    species: str = ""
    age: int = 0
    heightCm: int = 0
    weightKg: int = 0
    description: str = ""
    portrait: str = ""
    likes: str = ""
    dislikes: str = ""
    personality: str = ""
    # What pushes the character forward — their goal, want, or need. Shown on
    # the PC sheet and a major signal for the action suggester.
    drive: str = ""
```

Replace with:

```python
class BasicInfoSchema(BaseModel):
    name: str = ""
    species: str = ""
    sex: str = ""
    # Freeform descriptive age ("looks mid-20s", "ageless") — not a number.
    apparentAge: str = ""
    description: str = ""
    personality: str = ""
    # What the character tends to do — their behavioural bent. A major signal
    # for the action suggester.
    instinct: str = ""
    # 1-3 short GM-facing moves/abilities, as text (replaces the old Field Skill).
    strengths: str = ""
    other: str = ""
```

Find `FieldSkillSchema` (lines ~41-43):

```python
class FieldSkillSchema(BaseModel):
    name: str = ""
    description: str = ""
```

Delete it entirely.

Find PM schemas (lines ~66-87):

```python
class PartyMemberCreate(BaseModel):
    basicInfo: BasicInfoSchema = BasicInfoSchema()
    equipment: EquipmentSchema = EquipmentSchema()
    fieldSkill: FieldSkillSchema = FieldSkillSchema()


class PartyMemberUpdate(BaseModel):
    basicInfo: BasicInfoSchema
    equipment: EquipmentSchema
    fieldSkill: FieldSkillSchema


class PartyMemberResponse(BaseModel):
    id: str
    schemaVersion: int
    basicInfo: BasicInfoSchema
    equipment: EquipmentSchema
    fieldSkill: FieldSkillSchema
    lastSpokeTurn: int
    inParty: bool = True
    portraitFull: str | None = None
    portraitCrop: str | None = None
```

Replace with:

```python
class PartyMemberCreate(BaseModel):
    basicInfo: BasicInfoSchema = BasicInfoSchema()
    equipment: EquipmentSchema = EquipmentSchema()


class PartyMemberUpdate(BaseModel):
    basicInfo: BasicInfoSchema
    equipment: EquipmentSchema


class PartyMemberResponse(BaseModel):
    id: str
    schemaVersion: int
    basicInfo: BasicInfoSchema
    equipment: EquipmentSchema
    lastSpokeTurn: int
    inParty: bool = True
    portraitFull: str | None = None
    portraitCrop: str | None = None
```

- [ ] **Step 2: Update `server/api/common.py` `_pm_to_response`**

Find (lines ~60-72):

```python
def _pm_to_response(pm) -> PartyMemberResponse:
    return PartyMemberResponse(
        id=pm.id,
        schemaVersion=1,
        basicInfo=pm.basic_info,
        equipment=pm.equipment,
        fieldSkill=pm.field_skill,
        lastSpokeTurn=pm.last_spoke_turn,
        inParty=bool(pm.in_party),
        portraitFull=_portrait_full_url(pm.id),
        portraitCrop=_portrait_crop_url(pm.id),
        hasVoice=char_files.voice_path(pm.id) is not None,
    )
```

Replace with:

```python
def _pm_to_response(pm) -> PartyMemberResponse:
    return PartyMemberResponse(
        id=pm.id,
        schemaVersion=1,
        basicInfo=pm.basic_info,
        equipment=pm.equipment,
        lastSpokeTurn=pm.last_spoke_turn,
        inParty=bool(pm.in_party),
        portraitFull=_portrait_full_url(pm.id),
        portraitCrop=_portrait_crop_url(pm.id),
        hasVoice=char_files.voice_path(pm.id) is not None,
    )
```

- [ ] **Step 3: Update `server/api/characters.py` party-member routes**

Find `add_party_member` (lines ~87-91):

```python
    m = await party_ops.add_member(
        session,
        basic_info=data.basicInfo.model_dump(),
        field_skill=data.fieldSkill.model_dump(),
    )
```

Replace with:

```python
    m = await party_ops.add_member(
        session,
        basic_info=data.basicInfo.model_dump(),
    )
```

Find `update_party_member` (lines ~122-125):

```python
    await party_ops.update_member_identity(
        session, member_id, data.basicInfo.model_dump(), data.fieldSkill.model_dump()
    )
    await party_ops.set_equipment(session, member_id, data.equipment.model_dump())
```

Replace with:

```python
    await party_ops.update_member_identity(
        session, member_id, data.basicInfo.model_dump()
    )
    await party_ops.set_equipment(session, member_id, data.equipment.model_dump())
```

Also check `_character_meta` (lines ~144-157) — it emits `"fieldSkill": data.get("fieldSkill", {})`. `Read` that function and remove the `fieldSkill` line from the returned dict (the `/characters` library listing).

- [ ] **Step 4: Run the server suite again (schemas changed)**

Run: `python -m pytest server/tests -q`
Expected: PASS except the one pre-existing unrelated failure.

- [ ] **Step 5: Commit the server API layer**

```bash
git add server/api/
git commit -m "feat: drop fieldSkill + old basicInfo fields from the character API"
```

- [ ] **Step 6: Update `shared/types/models.ts`**

Find (lines ~47-92):

```typescript
export interface BasicInfo {
  name: string
  gender: string
  species: string
  age: number
  heightCm: number
  weightKg: number
  description: string
  portrait?: string
  likes?: string
  dislikes?: string
  personality?: string
  /** What pushes the character forward — goal, want, or need. */
  drive?: string
  /** Anything that doesn't fit the structured fields — quirks, history, relationships. */
  other?: string
}

export interface FieldSkill {
  name: string
  description: string
}

export interface PlayerCharacter {
  id: string
  schemaVersion: number
  basicInfo: BasicInfo
  equipment: Equipment
  // Character-file portrait URLs (full → Inspector, crop → chat/avatars).
  portraitFull?: string | null
  portraitCrop?: string | null
  hasVoice?: boolean  // TTS voice-cloning sample present in the character folder
}

export interface PartyMember {
  id: string
  schemaVersion: number
  basicInfo: BasicInfo
  equipment: Equipment
  fieldSkill: FieldSkill
  lastSpokeTurn: number
  inParty: boolean
  portraitFull?: string | null
  portraitCrop?: string | null
  hasVoice?: boolean
}
```

Replace with:

```typescript
export interface BasicInfo {
  name: string
  species: string
  sex: string
  /** Freeform descriptive age ("looks mid-20s", "ageless") — not a number. */
  apparentAge: string
  description: string
  personality?: string
  /** What the character tends to do — their behavioural bent. */
  instinct?: string
  /** 1-3 short GM-facing moves/abilities, as text (replaces the old Field Skill). */
  strengths?: string
  /** Anything that doesn't fit the structured fields — quirks, history, relationships. */
  other?: string
}

export interface PlayerCharacter {
  id: string
  schemaVersion: number
  basicInfo: BasicInfo
  equipment: Equipment
  // Character-file portrait URLs (full → Inspector, crop → chat/avatars).
  portraitFull?: string | null
  portraitCrop?: string | null
  hasVoice?: boolean  // TTS voice-cloning sample present in the character folder
}

export interface PartyMember {
  id: string
  schemaVersion: number
  basicInfo: BasicInfo
  equipment: Equipment
  lastSpokeTurn: number
  inParty: boolean
  portraitFull?: string | null
  portraitCrop?: string | null
  hasVoice?: boolean
}
```

Find `CharacterCard` (lines ~95-104) and remove its `fieldSkill: FieldSkill` line (read the full interface first, then delete just that property).

- [ ] **Step 7: Update the two sheet editors**

In `client/src/components/CharacterSheet/CharacterSheetEditor.tsx`, replace the view + edit field bindings so they use the new schema. Read the file, then:

- View mode (lines ~96-109): replace `Gender`→`Sex` (`d.basicInfo.sex`); replace `Age`/`Height`/`Weight` `ViewField`s with a single `apparentAge` field: `<ViewField label="Apparent Age" value={d.basicInfo.apparentAge} />`; replace the `Drive` `ViewField` (`d.basicInfo.drive`) with `<ViewField label="Instinct" value={d.basicInfo.instinct} />`; add `{d.basicInfo.strengths && <ViewField label="Strengths" value={d.basicInfo.strengths} />}`.
- Edit mode (lines ~142-164): replace the `Gender` `Field` with `Sex` (`updateBasic('sex', v)`); replace the three `NumField`s (`age`/`heightCm`/`weightKg`) with one text `Field` "Apparent Age" bound to `apparentAge`; replace the `drive` `TextArea` with an `instinct` one (label "Instinct"); add a `strengths` `TextArea` (label "Strengths", placeholder "1-3 short moves/abilities…").
- Remove any `NumField` import/usage that is now unused.

In `client/src/components/PartyMember/PartyMemberEditor.tsx`, apply the same field-binding changes (read the file first). Party members previously had a separate Field Skill section (`fieldSkill.name`/`fieldSkill.description`) — replace it with the single `strengths` text field on `basicInfo`. Remove `fieldSkill` from the update payload sent by the store (it no longer exists in the type).

- [ ] **Step 8: Grep for any remaining stale references and fix them**

Run: `grep -rn "fieldSkill\|\.gender\|\.drive\|heightCm\|weightKg\|basicInfo.age\|\.likes\|\.dislikes" client/src/ shared/`
Expected after fixes: no hits in client/shared except unrelated words. Fix every real reference (stores, inspectors, chat avatars, save/load cards) to the new field names. Common spots: `client/src/state/partyStore.ts` (update payload), `client/src/components/Inspector/PartyInspector.tsx` (any member/PC detail rendering), `client/src/state/charactersStore.ts`.

- [ ] **Step 9: Verify the client builds and tests pass**

Run: `cd client && npm run build && npm test`
Expected: PASS (tsc clean, vite build, 20 vitest green)

- [ ] **Step 10: Commit the client**

```bash
git add shared/types/models.ts client/src/
git commit -m "feat: unified character schema in the client types and sheets"
```

---

### Task A4: Phase A verification + docs

**Files:**
- Modify: `CLAUDE.md` (Data Models "Characters are portable files" bullet — new basicInfo field list, no fieldSkill)
- Modify: `TODO.md` (log Phase A)

- [ ] **Step 1: Full server suite**

Run: `python -m pytest server/tests -q`
Expected: PASS except the one pre-existing unrelated failure.

- [ ] **Step 2: Client build + tests**

Run: `cd client && npm run build && npm test`
Expected: PASS

- [ ] **Step 3: Grep the server for stale field names**

Run: `grep -rn "field_skill\|fieldSkill\|\.get(.gender.\|\.get(.drive.\|heightCm\|weightKg\|_clean_field_skill" server/ --include="*.py" | grep -v "test_"`
Expected: no hits except (a) `migrate_basic_info`'s own legacy-mapping logic in `characters.py`, (b) the legacy `PlayerCharacter`/`PartyMember` ORM models and `migrate_characters_to_files` reading `m.field_skill` (kept for the one-time back-fill). Everything else must be gone. Fix any straggler.

- [ ] **Step 4: Update `CLAUDE.md`**

In the Data Models section, find the "Characters are portable files" bullet and update the `basicInfo` field list from `(name/gender/species/age/height/weight/description/likes/dislikes/personality/drive — no portrait field) and fieldSkill` to `(name/species/sex/apparentAge/description/personality/instinct/strengths/other — no portrait field); the old separate fieldSkill is folded into basicInfo.strengths`. Note that `RuntimeCharacter` no longer carries `field_skill`, and that `migrate_basic_info` (`server/db/characters.py`) upgrades legacy files on read.

- [ ] **Step 5: Log in `TODO.md`**

Add a done entry describing Phase A (the unified identity schema), referencing this plan and the commits.

- [ ] **Step 6: Commit the docs**

```bash
git add CLAUDE.md TODO.md
git commit -m "docs: record the unified character identity schema (Phase A)"
```

---

# Phase B — Storage Relocation (roadmap)

**Write this as its own plan once Phase A merges.** Goal: move character folders from global `server/data/characters/<id>/` to campaign-scoped `server/data/campaigns/<cid>/characters/<id>/`, so a campaign's characters travel with it and there's no cross-campaign library.

Key tasks (to be fully specified in the Phase B plan):

1. **Active-scope path seam.** Change `char_files.characters_dir()` to resolve the *active* campaign's characters folder from `db._active_campaign_path.parent / "characters"` (a new accessor in `database.py`, e.g. `active_characters_dir()`), instead of the fixed `DATA_DIR / "characters"`. All runtime `char_dir`/`full_path`/etc. inherit this with zero signature changes. Add a `storage.campaign_characters_dir(cid)` helper for the non-active-campaign cases below.
2. **One-time migration** (`migrate_characters_to_campaign_scope` in `database.py`, wired into `_run_scope_migrations`): for the active campaign, move each global character folder referenced by a `PartyBinding`/PC pointer into the campaign folder; a character referenced by no campaign is attached to whichever campaign is active at migration time, with a logged note. Idempotent (skips folders already moved).
3. **Bundled starter cards per-campaign.** Remove the boot-time global `install_bundled_cards()` call (`database.py:138`). Instead have `apply_template` copy the bundled card folders (`server/templates/cards/`) into the new campaign's characters folder before `migrate_characters_to_files` runs, so template-pinned member ids resolve.
4. **Export/import rewiring.** `storage.build_campaign_zip(cid)` reads char folders from `campaign_characters_dir(cid)` (not the active-scope `char_dir`). Campaign import writes restored char folders into `campaign_characters_dir(new_cid)` (the new campaign isn't active at import time). `server/api/campaigns.py` import loop + `server/db/storage.py` export loop both change.
5. **`GET /characters` becomes campaign-scoped** implicitly (it already lists `characters_dir()`, which now resolves per-campaign) — verify the client "character library" browser reads it correctly, or remove that browser if it assumed cross-campaign scope.

Tests: a migration test moving a global folder into the active campaign; an export→import round-trip that round-trips a character folder through the campaign-scoped path; a template-application test asserting the bundled card lands in the new campaign's folder.

---

# Phase C — Lore Characters as Pointers + Promote/Demote + Bond (roadmap)

**Write this as its own plan once Phase B merges** (it depends on campaign-scoped character storage). Goal: a `cat=="characters"` lore entry becomes a thin pointer to a character file; promote/demote (party ↔ NPC) is non-destructive; add the per-adventure `Bond` and the non-PM `equipment` text field.

Key tasks (to be fully specified in the Phase C plan):

1. **`LorebookEntry.character_id` column** (additive migration, like `species_fields`), non-null only for `cat=="characters"` rows. A `compose_character_content(basic_info) -> str` helper (parallel to `compose_species_content`) projects the linked character's fields into the entry's read-only `content`; `title` mirrors the character's Name. Keywords/injection stay lore-only.
2. **`PartyBinding.bond`** integer column (additive, default 0) + the non-PM `equipment` **text** field on `basicInfo` (identity), surfaced in the schema/TS. Bond is manually edited, no automatic behavior (not wired into spotlight/tools this iteration).
3. **Promote/demote as bind/unbind.** Promote = create a `PartyBinding` for an existing character id (its lore pointer is untouched); demote = remove the binding (character file + lore pointer untouched). REST + client Promote/Demote action on the character sheet. "In the party" = an active binding exists.
4. **Chronicler rewiring.** Engagement gate for `characters` (only record when the player's turn shows real engagement); `create_lore`/`update_lore` for `cat=="characters"` carry the structured identity fields and create/update *both* the character record and its lore pointer atomically (recomposing `content`); `create_member` binds an existing lore-linked character instead of duplicating; **delete `_absorb_lore_character`** (no destructive lore deletion for characters remains).
5. **Editor rewiring.** The Editor's character-lore tools mirror the Chronicler's (structured fields → character record + pointer). The Lore panel's Characters tab becomes the same editing UI as the party-member sheet, parameterized by whether a binding exists, plus the Promote/Demote action.
6. **PC stays excluded** from the pointer mechanism (never filed as lore), as today.

Tests: promote (bind) doesn't modify the lore pointer; demote (unbind) leaves both the file and pointer intact; `create_member` reusing an existing lore-linked character binds without a duplicate record; `create_lore` for `cat=="characters"` produces an entry that creates both the character record and a correctly-composed pointer.

---

## Self-Review notes (Phase A)

- **Spec coverage (Phase A slice):** unified schema field rename ✅ (A1-A3); PC uses same schema ✅ (A2/A3 update_pc + PC summary + suggester); migration non-destructive/idempotent ✅ (A1 `migrate_basic_info` + on-read upgrade); downstream consumers ✅ (A2 covers prompt_builder/spotlight/action_suggester/narrator/worldbuilder/planner; A3 covers schemas/common/routes/client). Bond, non-PM equipment text, storage relocation, and lore pointers are deliberately deferred to Phases B/C per the spec's phasing guidance and are captured in the roadmaps.
- **Type consistency:** `migrate_basic_info(basic_info, field_skill=None)`, `create_character(type, basic_info, cid=None, created_at=None)`, `update_identity(cid, basic_info=None)`, `add_member(session, basic_info=None, in_party=True, character_id=None)`, `update_member_identity(session, character_id, basic_info)`, `set_pc_identity(session, basic_info)`, `SpotlightSignal.strengths_relevant` are used identically everywhere they appear.
- **New basicInfo keys** `name/species/sex/apparentAge/description/personality/instinct/strengths/other` are identical across `_BASIC_KEYS`, `BasicInfoSchema`, the TS `BasicInfo`, and every tool schema.
