# Species Lorebook Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge the lorebook's "monsters" category into a new "species" category with 8 structured fields (Overview, Physical Appearance, Biology & Reproduction, Culture & Behavior, Danger & Combat Notes, Typical Gear, Archetypes & Variants, Name Examples), composed into the entry's freeform `content` at save time — exactly the pattern the Scenario tab already proved out.

**Architecture:** A new `server/ai/species.py` module owns field composition/merging (pure functions, mirroring `server/ai/scenario.py`). `LorebookEntry` gains a `species_fields` JSON column (mirroring `scenario_fields`). Every write path that can touch a species entry — the generic `/lore` API, the Chronicler (`worldbuilder.py`), and the Editor (`planner.py`) — calls the same composer so `content` never drifts from the structured fields. A one-time migration recategorizes existing `cat == "monsters"` rows and carries their old freeform content into the new `overview` field.

**Tech Stack:** FastAPI + SQLAlchemy (async, aiosqlite) on the server; React + TypeScript + Zustand on the client. No new dependencies.

## Global Constraints

- Additive-only DB migrations — add the `species_fields` column via the existing `_run_scope_migrations` tuple list; never alter/drop existing columns.
- The lore-injection pipeline (`lore_injector.py`, `prompt_builder.py`) must need **zero changes** — it only ever reads `LorebookEntry.content`.
- `cat == "species"` replaces `cat == "monsters"` everywhere; do not keep both as live options.
- Danger & Combat Notes is narrative flavor only — no combat mechanics exist yet; do not design around future systems.
- Every server-side write path (API, Chronicler, Editor) must produce an entry whose `content` is always `compose_species_content(entry.species_fields)` when `species_fields` was provided — never let the two drift.
- Follow existing code conventions exactly: file locations, naming, docstring style, and test patterns already established in `server/ai/scenario.py`, `server/tests/test_story_style.py`, and `server/tests/test_continue_backups_backdrops.py`.

---

### Task 1: `server/ai/species.py` — field composition, merging, legacy migration

**Files:**
- Create: `server/ai/species.py`
- Test: `server/tests/test_species.py`

**Interfaces:**
- Produces: `SPECIES_FIELDS: list[tuple[str, str]]` (key, label pairs, in order), `compose_species_content(fields: dict) -> str`, `merge_species_fields(existing: dict | None, partial: dict | None) -> dict`, `migrate_legacy_species_fields(species_fields: dict | None, content: str) -> dict`. All later tasks (DB migration, `/lore` API, Chronicler, Editor) import from this module.

- [ ] **Step 1: Write the failing tests**

Create `server/tests/test_species.py`:

```python
"""Species/Creature-template field composition — see CLAUDE.md >
Species & Creature Templates."""

from server.ai.species import (
    SPECIES_FIELDS,
    compose_species_content,
    merge_species_fields,
    migrate_legacy_species_fields,
)


# ── Pure: composer ──────────────────────────────────────────────────

def test_compose_empty_is_blank():
    assert compose_species_content({}) == ""
    assert compose_species_content({"overview": "", "typicalGear": "   "}) == ""


def test_compose_skips_empty_fields_and_orders_by_field_list():
    block = compose_species_content({
        "nameExamples": "Grak, Thok",
        "overview": "A hulking forest guardian.",
    })
    assert block == "Overview: A hulking forest guardian.\n\nName Examples: Grak, Thok"


def test_compose_all_fields_labeled():
    fields = {key: f"[{key}]" for key, _label in SPECIES_FIELDS}
    block = compose_species_content(fields)
    for key, label in SPECIES_FIELDS:
        assert f"{label}: [{key}]" in block


# ── Pure: partial merge ─────────────────────────────────────────────

def test_merge_keeps_untouched_fields_and_drops_unknown_keys():
    existing = {"overview": "Old overview.", "typicalGear": "Claws."}
    merged = merge_species_fields(existing, {"overview": "New overview.", "bogus": "x"})
    assert merged == {"overview": "New overview.", "typicalGear": "Claws."}
    assert "bogus" not in merged


def test_merge_none_partial_is_a_noop():
    existing = {"overview": "Old overview."}
    assert merge_species_fields(existing, None) == existing


def test_merge_none_existing_starts_fresh():
    assert merge_species_fields(None, {"overview": "Fresh."}) == {"overview": "Fresh."}


# ── Pure: legacy content → overview migration ───────────────────────

def test_migrate_legacy_seeds_overview_once_then_idempotent():
    assert migrate_legacy_species_fields(None, "A shadow that hunts by scent.") == {
        "overview": "A shadow that hunts by scent."
    }
    assert migrate_legacy_species_fields(None, "") == {}  # nothing to migrate
    assert migrate_legacy_species_fields({"overview": "Set already"}, "Old text") == {
        "overview": "Set already"
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest server/tests/test_species.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'server.ai.species'`

- [ ] **Step 3: Write the implementation**

Create `server/ai/species.py`:

```python
"""Species/Creature-template field composition — shared by the /lore API
routes (server/api/lore.py) and the Chronicler/Editor's create_lore/update_lore
tools (server/ai/worldbuilder.py, server/ai/planner.py). Single source of
truth for how the 8 structured Species fields fold into the underlying
LorebookEntry.content, so the existing prompt-injection pipeline
(lore_injector.py, prompt_builder.py) keeps reading an ordinary freeform
content string with zero changes. Mirrors server/ai/scenario.py's pattern —
one Species entry covers both sapient peoples and monsters/creatures; the
old 'monsters' lorebook category is retired (see migrate_legacy_species_fields
and server/db/database.py's migrate_species_lore).
"""

# (field key, display label) pairs, in display/compose order.
SPECIES_FIELDS: list[tuple[str, str]] = [
    ("overview", "Overview"),
    ("physicalAppearance", "Physical Appearance"),
    ("biologyReproduction", "Biology & Reproduction"),
    ("cultureBehavior", "Culture & Behavior"),
    ("dangerCombat", "Danger & Combat Notes"),
    ("typicalGear", "Typical Gear"),
    ("archetypesVariants", "Archetypes & Variants"),
    ("nameExamples", "Name Examples"),
]


def compose_species_content(fields: dict) -> str:
    """Compose the 8 structured Species fields into LorebookEntry.content.

    Empty/whitespace-only fields are skipped entirely (no dangling "Label: "
    line). Non-empty sections are joined as "Label: value" blocks separated by
    a blank line.
    """
    parts = []
    for key, label in SPECIES_FIELDS:
        value = (fields.get(key) or "").strip()
        if value:
            parts.append(f"{label}: {value}")
    return "\n\n".join(parts)


def merge_species_fields(existing: dict | None, partial: dict | None) -> dict:
    """Partial per-field merge: only keys present in `partial` overwrite
    `existing`; every other existing field is left untouched. Unknown keys
    are dropped, matching how the Editor's set_scenario tool does partial
    per-field updates."""
    merged = dict(existing or {})
    for key, _label in SPECIES_FIELDS:
        if partial and key in partial:
            merged[key] = partial[key] or ""
    return merged


def migrate_legacy_species_fields(species_fields: dict | None, content: str) -> dict:
    """One-time, non-destructive legacy migration: if `species_fields` is
    empty/missing (all falsy) but `content` is non-empty (a monsters-category
    entry recategorized from before this feature existed), seed the
    `overview` field from the old freeform content as a starting point.
    Otherwise return species_fields unchanged (normalized to a dict).

    Pure function — callers persist the result themselves if it changed.
    """
    fields = dict(species_fields or {})
    if not any(fields.values()) and (content or "").strip():
        fields["overview"] = content.strip()
    return fields
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest server/tests/test_species.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add server/ai/species.py server/tests/test_species.py
git commit -m "feat: add species field composition module"
```

---

### Task 2: `LorebookEntry.species_fields` column + `monsters` → `species` DB migration

**Files:**
- Modify: `server/db/models.py:180-189` (LorebookEntry, after `scenario_fields`)
- Modify: `server/db/database.py:238-257` (`_run_scope_migrations`'s additive migration tuples), `server/db/database.py:308-310` (call site), and add a new `migrate_species_lore()` function near `migrate_characters_to_files`
- Test: `server/tests/test_species.py` (append)

**Interfaces:**
- Consumes: `migrate_legacy_species_fields` from Task 1 (`server.ai.species`).
- Produces: `LorebookEntry.species_fields` column; `async def migrate_species_lore() -> None` in `server.db.database`, callable directly in tests via `run(migrate_species_lore())`.

- [ ] **Step 1: Write the failing test**

Append to `server/tests/test_species.py`:

```python
from sqlalchemy import select

from server.tests.conftest import run


# ── Integration: DB migration (monsters → species) ──────────────────

def test_migrate_species_lore_recategorizes_and_renames_config_key(client):
    from server.db.database import migrate_species_lore, new_session
    from server.db.models import LorebookConfig, LorebookEntry

    async def seed_legacy():
        async with new_session() as s:
            s.add(LorebookEntry(title="Dire Wolf", content="A large wolf.", cat="monsters"))
            cfg = (await s.execute(select(LorebookConfig))).scalars().first()
            order = dict(cfg.injection_order or {})
            order["monsters"] = order.pop("species", 40)
            cfg.injection_order = order
            position = dict(cfg.injection_position or {})
            position["monsters"] = position.pop("species", "top")
            cfg.injection_position = position
            await s.commit()
    run(seed_legacy())

    run(migrate_species_lore())

    async def check():
        async with new_session() as s:
            entry = (await s.execute(
                select(LorebookEntry).where(LorebookEntry.title == "Dire Wolf")
            )).scalars().first()
            cfg = (await s.execute(select(LorebookConfig))).scalars().first()
            return entry, cfg
    entry, cfg = run(check())
    assert entry.cat == "species"
    assert entry.species_fields == {"overview": "A large wolf."}
    assert "species" in cfg.injection_order and "monsters" not in cfg.injection_order
    assert "species" in cfg.injection_position and "monsters" not in cfg.injection_position

    # Idempotent: running again changes nothing further and doesn't error.
    run(migrate_species_lore())
    entry2, cfg2 = run(check())
    assert entry2.cat == "species"
    assert entry2.species_fields == {"overview": "A large wolf."}
    assert "monsters" not in cfg2.injection_order
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest server/tests/test_species.py::test_migrate_species_lore_recategorizes_and_renames_config_key -v`
Expected: FAIL with `ImportError: cannot import name 'migrate_species_lore'` (or `AttributeError: 'LorebookEntry' object has no attribute 'species_fields'`)

- [ ] **Step 3: Add the column**

In `server/db/models.py`, find this block (right after `scenario_fields`, before the "Item fields" comment, around line 180-182):

```python
    scenario_fields: Mapped[dict] = mapped_column(JSON, default=dict)

    # Item fields — only meaningful when cat == "items" (the unified item
```

Replace with:

```python
    scenario_fields: Mapped[dict] = mapped_column(JSON, default=dict)

    # Structured Species fields — only meaningful when cat == "species" (the
    # merged Species/Monsters lorebook category). Holds a dict with keys
    # overview/physicalAppearance/biologyReproduction/cultureBehavior/
    # dangerCombat/typicalGear/archetypesVariants/nameExamples (all strings).
    # `content` is derived from it via compose_species_content()
    # (server/ai/species.py), same pattern as scenario_fields above. May be
    # `{}` or `None` for rows that predate this column — always read via
    # `entry.species_fields or {}`.
    species_fields: Mapped[dict] = mapped_column(JSON, default=dict)

    # Item fields — only meaningful when cat == "items" (the unified item
```

- [ ] **Step 4: Register the additive column migration**

In `server/db/database.py`, find the last entry in the `migrations` list inside `_run_scope_migrations` (around line 256):

```python
        ("campaign.narrator_configs", "style_fields", "ALTER TABLE campaign.narrator_configs ADD COLUMN style_fields JSON"),
    ]
```

Replace with:

```python
        ("campaign.narrator_configs", "style_fields", "ALTER TABLE campaign.narrator_configs ADD COLUMN style_fields JSON"),
        ("campaign.lorebook_entries", "species_fields", "ALTER TABLE campaign.lorebook_entries ADD COLUMN species_fields JSON"),
    ]
```

- [ ] **Step 5: Write `migrate_species_lore()` and wire it into the migration run**

In `server/db/database.py`, find the end of `_run_scope_migrations` (around line 308-310):

```python
    await migrate_to_item_instances()
    await migrate_quests_to_tasks()
    await migrate_characters_to_files()
```

Replace with:

```python
    await migrate_to_item_instances()
    await migrate_quests_to_tasks()
    await migrate_characters_to_files()
    await migrate_species_lore()
```

Then add the new function directly after `migrate_characters_to_files` (find where that function ends — search for the next top-level `async def` after it, or simply append this function at the end of the file if `migrate_characters_to_files` is the last one):

```python
async def migrate_species_lore() -> None:
    """One-time, idempotent recategorization of the legacy 'monsters' lorebook
    category into 'species' (Species & Creature Templates). Carries each
    recategorized entry's freeform content into its new species_fields.overview
    as a starting point (non-destructive — see migrate_legacy_species_fields),
    and renames the 'monsters' key to 'species' in the campaign's
    LorebookConfig injection settings. Re-running is a no-op once no
    'monsters' rows or config keys remain."""
    if async_session is None or _active_campaign_path is None:
        return

    from server.ai.species import migrate_legacy_species_fields
    from server.db.models import LorebookConfig, LorebookEntry

    async with async_session() as s:
        legacy = (await s.execute(
            select(LorebookEntry).where(LorebookEntry.cat == "monsters")
        )).scalars().all()
        for entry in legacy:
            entry.species_fields = migrate_legacy_species_fields(entry.species_fields, entry.content)
            entry.cat = "species"

        cfg = (await s.execute(select(LorebookConfig))).scalars().first()
        if cfg is not None:
            order = dict(cfg.injection_order or {})
            if "monsters" in order and "species" not in order:
                order["species"] = order.pop("monsters")
                cfg.injection_order = order
            position = dict(cfg.injection_position or {})
            if "monsters" in position and "species" not in position:
                position["species"] = position.pop("monsters")
                cfg.injection_position = position

        await s.commit()
```

- [ ] **Step 6: Run test to verify it passes**

Run: `python -m pytest server/tests/test_species.py -v`
Expected: PASS (all tests, including the new migration test)

- [ ] **Step 7: Commit**

```bash
git add server/db/models.py server/db/database.py server/tests/test_species.py
git commit -m "feat: add species_fields column and monsters->species DB migration"
```

---

### Task 3: `server/api/schemas.py` + `server/api/lore.py` — `/lore` API wiring

**Files:**
- Modify: `server/api/schemas.py:479-524` (LorebookEntrySchema, LorebookEntryCreate, LorebookEntryUpdate, LorebookConfigSchema)
- Modify: `server/api/lore.py` (imports, `_lore_to_schema`, `create_lore_entry`, `update_lore_entry`)
- Test: `server/tests/test_species.py` (append)

**Interfaces:**
- Consumes: `compose_species_content`, `merge_species_fields` from Task 1.
- Produces: `POST/PUT /lore` accept an optional `speciesFields: dict | None`; every `LorebookEntrySchema` response includes `speciesFields` (non-`None` only when `cat == "species"`).

- [ ] **Step 1: Write the failing test**

Append to `server/tests/test_species.py`:

```python
# ── Integration: /lore API composes + merges species fields ────────

def test_lore_species_create_composes_content(client):
    res = client.post("/api/lore", json={
        "title": "Dire Wolf",
        "content": "",
        "cat": "species",
        "keywords": ["wolf"],
        "speciesFields": {
            "overview": "A larger, more cunning cousin of the common wolf.",
            "dangerCombat": "Hunts in coordinated packs; flees if its alpha falls.",
        },
    })
    assert res.status_code == 201, res.text
    body = res.json()
    entry_id = body["id"]
    assert body["speciesFields"]["overview"].startswith("A larger")
    assert body["content"] == (
        "Overview: A larger, more cunning cousin of the common wolf.\n\n"
        "Danger & Combat Notes: Hunts in coordinated packs; flees if its alpha falls."
    )

    # Partial PUT merges into existing fields rather than replacing them.
    put = client.put(f"/api/lore/{entry_id}", json={
        "speciesFields": {"typicalGear": "None — relies on claw and fang."},
    }).json()
    assert put["speciesFields"]["overview"].startswith("A larger")  # untouched
    assert put["speciesFields"]["typicalGear"] == "None — relies on claw and fang."
    assert "Typical Gear: None" in put["content"]

    # Non-species entries never carry speciesFields.
    other = client.post("/api/lore", json={"title": "A Cave", "content": "Dark.", "cat": "world"}).json()
    assert other["speciesFields"] is None
    client.delete(f"/api/lore/{other['id']}")
    client.delete(f"/api/lore/{entry_id}")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest server/tests/test_species.py::test_lore_species_create_composes_content -v`
Expected: FAIL — `body["speciesFields"]` raises `KeyError` (schema doesn't have the field yet) or the composed-content assertion fails (nothing composes `content` yet)

- [ ] **Step 3: Update the Pydantic schemas**

In `server/api/schemas.py`, find (around line 479-524):

```python
class LorebookEntrySchema(BaseModel):
    id: str
    title: str
    content: str
    keywords: list[str] = []
    enabled: bool = True
    permanent: bool = False
    locked: bool = False
    cat: str = "world"


class LorebookEntryCreate(BaseModel):
    title: str
    content: str = ""
    keywords: list[str] = []
    enabled: bool = True
    permanent: bool = False
    cat: str = "world"


class LorebookEntryUpdate(BaseModel):
    title: str | None = None
    content: str | None = None
    keywords: list[str] | None = None
    enabled: bool | None = None
    permanent: bool | None = None
    cat: str | None = None


class LorebookConfigSchema(BaseModel):
    injectionOrder: dict[str, int] = {
        "pillars": 0, "world": 10, "characters": 20, "items": 30,
        "monsters": 40, "spells": 50,
    }
    injectionPosition: dict[str, str] = {
        "pillars": "top", "world": "top", "characters": "top", "items": "top",
        "monsters": "top", "spells": "top",
    }
    scanDepth: int = 3
```

Replace with:

```python
class LorebookEntrySchema(BaseModel):
    id: str
    title: str
    content: str
    keywords: list[str] = []
    enabled: bool = True
    permanent: bool = False
    locked: bool = False
    cat: str = "world"
    speciesFields: dict | None = None


class LorebookEntryCreate(BaseModel):
    title: str
    content: str = ""
    keywords: list[str] = []
    enabled: bool = True
    permanent: bool = False
    cat: str = "world"
    speciesFields: dict | None = None


class LorebookEntryUpdate(BaseModel):
    title: str | None = None
    content: str | None = None
    keywords: list[str] | None = None
    enabled: bool | None = None
    permanent: bool | None = None
    cat: str | None = None
    speciesFields: dict | None = None


class LorebookConfigSchema(BaseModel):
    injectionOrder: dict[str, int] = {
        "pillars": 0, "world": 10, "characters": 20, "items": 30,
        "species": 40, "spells": 50,
    }
    injectionPosition: dict[str, str] = {
        "pillars": "top", "world": "top", "characters": "top", "items": "top",
        "species": "top", "spells": "top",
    }
    scanDepth: int = 3
```

- [ ] **Step 4: Wire composition into the `/lore` routes**

In `server/api/lore.py`, add the import (near the top, alongside the existing `server.ai.scenario` import):

```python
from server.ai.scenario import compose_scenario_content, migrate_legacy_fields
```

Replace with:

```python
from server.ai.scenario import compose_scenario_content, migrate_legacy_fields
from server.ai.species import compose_species_content, merge_species_fields
```

Find `_lore_to_schema` (around line 97-107):

```python
def _lore_to_schema(entry: LorebookEntry) -> LorebookEntrySchema:
    return LorebookEntrySchema(
        id=entry.id,
        title=entry.title,
        content=entry.content,
        keywords=entry.keywords or [],
        enabled=bool(entry.enabled),
        permanent=bool(entry.permanent),
        locked=bool(entry.locked),
        cat=entry.cat,
    )
```

Replace with:

```python
def _lore_to_schema(entry: LorebookEntry) -> LorebookEntrySchema:
    return LorebookEntrySchema(
        id=entry.id,
        title=entry.title,
        content=entry.content,
        keywords=entry.keywords or [],
        enabled=bool(entry.enabled),
        permanent=bool(entry.permanent),
        locked=bool(entry.locked),
        cat=entry.cat,
        speciesFields=(entry.species_fields or {}) if entry.cat == "species" else None,
    )
```

Find `create_lore_entry` (around line 161-177):

```python
@router.post("/lore", response_model=LorebookEntrySchema, status_code=201)
async def create_lore_entry(
    data: LorebookEntryCreate,
    session: AsyncSession = Depends(get_session),
):
    entry = LorebookEntry(
        title=data.title,
        content=data.content,
        keywords=data.keywords,
        enabled=data.enabled,
        permanent=data.permanent,
        cat=data.cat,
    )
    session.add(entry)
    await session.commit()
    await session.refresh(entry)
    return _lore_to_schema(entry)
```

Replace with:

```python
@router.post("/lore", response_model=LorebookEntrySchema, status_code=201)
async def create_lore_entry(
    data: LorebookEntryCreate,
    session: AsyncSession = Depends(get_session),
):
    entry = LorebookEntry(
        title=data.title,
        content=data.content,
        keywords=data.keywords,
        enabled=data.enabled,
        permanent=data.permanent,
        cat=data.cat,
    )
    if data.cat == "species" and data.speciesFields is not None:
        entry.species_fields = merge_species_fields(None, data.speciesFields)
        entry.content = compose_species_content(entry.species_fields)
    session.add(entry)
    await session.commit()
    await session.refresh(entry)
    return _lore_to_schema(entry)
```

Find `update_lore_entry` (around line 191-214):

```python
@router.put("/lore/{entry_id}", response_model=LorebookEntrySchema)
async def update_lore_entry(
    entry_id: str,
    data: LorebookEntryUpdate,
    session: AsyncSession = Depends(get_session),
):
    entry = await session.get(LorebookEntry, entry_id)
    if not entry:
        raise HTTPException(404, "Lorebook entry not found")
    if data.title is not None:
        entry.title = data.title
    if data.content is not None:
        entry.content = data.content
    if data.keywords is not None:
        entry.keywords = data.keywords
    if data.enabled is not None:
        entry.enabled = data.enabled
    if data.permanent is not None:
        entry.permanent = data.permanent
    if data.cat is not None:
        entry.cat = data.cat
    await session.commit()
    await session.refresh(entry)
    return _lore_to_schema(entry)
```

Replace with:

```python
@router.put("/lore/{entry_id}", response_model=LorebookEntrySchema)
async def update_lore_entry(
    entry_id: str,
    data: LorebookEntryUpdate,
    session: AsyncSession = Depends(get_session),
):
    entry = await session.get(LorebookEntry, entry_id)
    if not entry:
        raise HTTPException(404, "Lorebook entry not found")
    if data.title is not None:
        entry.title = data.title
    if data.content is not None:
        entry.content = data.content
    if data.keywords is not None:
        entry.keywords = data.keywords
    if data.enabled is not None:
        entry.enabled = data.enabled
    if data.permanent is not None:
        entry.permanent = data.permanent
    if data.cat is not None:
        entry.cat = data.cat
    if entry.cat == "species" and data.speciesFields is not None:
        entry.species_fields = merge_species_fields(entry.species_fields, data.speciesFields)
        entry.content = compose_species_content(entry.species_fields)
    await session.commit()
    await session.refresh(entry)
    return _lore_to_schema(entry)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest server/tests/test_species.py -v`
Expected: PASS (all tests)

- [ ] **Step 6: Commit**

```bash
git add server/api/schemas.py server/api/lore.py server/tests/test_species.py
git commit -m "feat: wire species field composition into the /lore API"
```

---

### Task 4: Seed content, templates, and campaign-export defaults

**Files:**
- Modify: `server/db/seed.py:110-128` (SEED_LOREBOOK monster entries), `server/db/seed.py:492-500` (LorebookConfig defaults)
- Modify: `server/db/templates.py:59-65` (`_DEFAULT_INJECTION_ORDER`/`_DEFAULT_INJECTION_POSITION`)
- Modify: `server/templates/fantasy.json` (the one `"cat": "monsters"` entry)
- Modify: `server/api/campaigns.py:600-601` (two default dict literals in the story-export route)
- Test: `server/tests/test_species.py` (append)

**Interfaces:**
- Consumes: `compose_species_content` from Task 1.
- No new interfaces produced — this task only changes default data.

- [ ] **Step 1: Write the failing test**

Append to `server/tests/test_species.py`:

```python
# ── Integration: seeded demo campaign has species content ──────────

def test_boot_seed_has_species_not_monsters(client):
    entries = client.get("/api/lore").json()
    cats = {e["cat"] for e in entries}
    assert "monsters" not in cats
    assert "species" in cats

    shadow_wraith = next(e for e in entries if e["title"] == "Shadow Wraith")
    assert shadow_wraith["cat"] == "species"
    assert shadow_wraith["speciesFields"]["overview"]
    assert shadow_wraith["speciesFields"]["dangerCombat"]
    assert shadow_wraith["content"] == (
        f"Overview: {shadow_wraith['speciesFields']['overview']}\n\n"
        + "\n\n".join(
            f"{label}: {shadow_wraith['speciesFields'][key]}"
            for key, label in [
                ("physicalAppearance", "Physical Appearance"),
                ("biologyReproduction", "Biology & Reproduction"),
                ("cultureBehavior", "Culture & Behavior"),
                ("dangerCombat", "Danger & Combat Notes"),
                ("typicalGear", "Typical Gear"),
                ("archetypesVariants", "Archetypes & Variants"),
                ("nameExamples", "Name Examples"),
            ]
            if shadow_wraith["speciesFields"].get(key)
        )
    )

    cfg = client.get("/api/lore/config").json()
    assert "species" in cfg["injectionOrder"] and "monsters" not in cfg["injectionOrder"]
    assert "species" in cfg["injectionPosition"] and "monsters" not in cfg["injectionPosition"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest server/tests/test_species.py::test_boot_seed_has_species_not_monsters -v`
Expected: FAIL — `cats` still contains `"monsters"`, or `shadow_wraith["speciesFields"]["overview"]` is falsy

- [ ] **Step 3: Update `server/db/seed.py`**

Add the import at the top of the file, alongside the other imports:

```python
from server.ai.narrator_actions import ACTION_INSTRUCTION
```

Replace with:

```python
from server.ai.narrator_actions import ACTION_INSTRUCTION
from server.ai.species import compose_species_content
```

Find the two Monsters entries (around line 110-128):

```python
    # --- Monsters (2 entries) ---
    {
        "id": LORE_IDS["shadow_wraith"],
        "title": "Shadow Wraith",
        "content": "A formless, dark entity that drifts through places where old magic has soured. Shadow wraiths are drawn to fear and confusion. They cannot be struck by ordinary weapons — only light, fire, or magic disperses them. They do not kill outright but drain warmth and will from the living, leaving victims hollow and lost.",
        "keywords": ["shadow", "wraith", "dark", "darkness", "shade"],
        "enabled": True,
        "permanent": False,
        "cat": "monsters",
    },
    {
        "id": LORE_IDS["moss_golem"],
        "title": "Moss Golem",
        "content": "A hulking figure of packed earth, stone, and living moss that guards ancient places in the Whispering Woods. Moss golems are slow but enormously strong. They do not attack unprovoked — they respond to intrusion, particularly near the stone pillars and old ward-lines. Destroying one is difficult; they reassemble unless the core stone at their center is removed.",
        "keywords": ["golem", "moss", "stone guardian", "earth"],
        "enabled": True,
        "permanent": False,
        "cat": "monsters",
    },
```

Replace with:

```python
    # --- Species (2 entries) ---
    {
        "id": LORE_IDS["shadow_wraith"],
        "title": "Shadow Wraith",
        "content": compose_species_content({
            "overview": "A formless, dark entity that drifts through places where old magic has soured.",
            "cultureBehavior": "Shadow wraiths are drawn to fear and confusion.",
            "dangerCombat": "Cannot be struck by ordinary weapons — only light, fire, or magic disperses them. They do not kill outright but drain warmth and will from the living, leaving victims hollow and lost.",
        }),
        "species_fields": {
            "overview": "A formless, dark entity that drifts through places where old magic has soured.",
            "cultureBehavior": "Shadow wraiths are drawn to fear and confusion.",
            "dangerCombat": "Cannot be struck by ordinary weapons — only light, fire, or magic disperses them. They do not kill outright but drain warmth and will from the living, leaving victims hollow and lost.",
        },
        "keywords": ["shadow", "wraith", "dark", "darkness", "shade"],
        "enabled": True,
        "permanent": False,
        "cat": "species",
    },
    {
        "id": LORE_IDS["moss_golem"],
        "title": "Moss Golem",
        "content": compose_species_content({
            "overview": "A hulking figure of packed earth, stone, and living moss that guards ancient places in the Whispering Woods.",
            "physicalAppearance": "Moss golems are slow but enormously strong.",
            "cultureBehavior": "They do not attack unprovoked — they respond to intrusion, particularly near the stone pillars and old ward-lines.",
            "dangerCombat": "Destroying one is difficult; they reassemble unless the core stone at their center is removed.",
        }),
        "species_fields": {
            "overview": "A hulking figure of packed earth, stone, and living moss that guards ancient places in the Whispering Woods.",
            "physicalAppearance": "Moss golems are slow but enormously strong.",
            "cultureBehavior": "They do not attack unprovoked — they respond to intrusion, particularly near the stone pillars and old ward-lines.",
            "dangerCombat": "Destroying one is difficult; they reassemble unless the core stone at their center is removed.",
        },
        "keywords": ["golem", "moss", "stone guardian", "earth"],
        "enabled": True,
        "permanent": False,
        "cat": "species",
    },
```

Find the `LorebookConfig` defaults (around line 492-500):

```python
        lore_config = LorebookConfig(
            injection_order={
                "pillars": 0, "world": 10, "characters": 20, "items": 30,
                "monsters": 40, "spells": 50,
            },
            injection_position={
                "pillars": "top", "world": "top", "characters": "top", "items": "top",
                "monsters": "top", "spells": "top",
            },
        )
```

Replace with:

```python
        lore_config = LorebookConfig(
            injection_order={
                "pillars": 0, "world": 10, "characters": 20, "items": 30,
                "species": 40, "spells": 50,
            },
            injection_position={
                "pillars": "top", "world": "top", "characters": "top", "items": "top",
                "species": "top", "spells": "top",
            },
        )
```

- [ ] **Step 4: Update `server/db/templates.py`**

Find (around line 59-65):

```python
_DEFAULT_INJECTION_ORDER = {
    "pillars": 0, "world": 10, "characters": 20, "items": 30, "monsters": 40, "spells": 50,
}
_DEFAULT_INJECTION_POSITION = {
    "pillars": "top", "world": "top", "characters": "top", "items": "top",
    "monsters": "top", "spells": "top",
}
```

Replace with:

```python
_DEFAULT_INJECTION_ORDER = {
    "pillars": 0, "world": 10, "characters": 20, "items": 30, "species": 40, "spells": 50,
}
_DEFAULT_INJECTION_POSITION = {
    "pillars": "top", "world": "top", "characters": "top", "items": "top",
    "species": "top", "spells": "top",
}
```

- [ ] **Step 5: Update `server/templates/fantasy.json`**

Find (around line 166-175):

```json
    {
      "cat": "monsters",
      "title": "Goblin",
```

Replace with:

```json
    {
      "cat": "species",
      "title": "Goblin",
```

(The Fantasy demo template's "Freeform lore" loader in `templates.py` only reads `cat`/`title`/`content`/`keywords`/`permanent` — it does not compose structured fields for any category. This entry keeps its existing plain-content shape, same as every other Fantasy-template lore entry; only the category id changes.)

- [ ] **Step 6: Update `server/api/campaigns.py`**

Find (around line 600-601):

```python
            "injectionOrder": lore_config.injection_order if lore_config else {"pillars": 0, "world": 10, "characters": 20, "items": 30, "monsters": 40, "spells": 50},
            "injectionPosition": lore_config.injection_position if lore_config else {"pillars": "top", "world": "top", "characters": "top", "items": "top", "monsters": "top", "spells": "top"},
```

Replace with:

```python
            "injectionOrder": lore_config.injection_order if lore_config else {"pillars": 0, "world": 10, "characters": 20, "items": 30, "species": 40, "spells": 50},
            "injectionPosition": lore_config.injection_position if lore_config else {"pillars": "top", "world": "top", "characters": "top", "items": "top", "species": "top", "spells": "top"},
```

Then find the same pattern again around line 762-763:

```python
        injection_order=lc_data.get("injectionOrder", {"pillars": 0, "world": 10, "characters": 20, "items": 30, "monsters": 40, "spells": 50}),
        injection_position=lc_data.get("injectionPosition", {"pillars": "top", "world": "top", "characters": "top", "items": "top", "monsters": "top", "spells": "top"}),
```

Replace with:

```python
        injection_order=lc_data.get("injectionOrder", {"pillars": 0, "world": 10, "characters": 20, "items": 30, "species": 40, "spells": 50}),
        injection_position=lc_data.get("injectionPosition", {"pillars": "top", "world": "top", "characters": "top", "items": "top", "species": "top", "spells": "top"}),
```

- [ ] **Step 7: Run test to verify it passes**

Run: `python -m pytest server/tests/test_species.py -v`
Expected: PASS (all tests)

- [ ] **Step 8: Run the full server test suite to check for regressions**

Run: `python -m pytest server/tests -v`
Expected: PASS (no test anywhere still asserts `cat == "monsters"` or a `"monsters"` config key)

- [ ] **Step 9: Commit**

```bash
git add server/db/seed.py server/db/templates.py server/templates/fantasy.json server/api/campaigns.py server/tests/test_species.py
git commit -m "feat: recategorize seed/template monster content as species"
```

---

### Task 5: Chronicler wiring (`server/ai/worldbuilder.py`)

**Files:**
- Modify: `server/ai/worldbuilder.py` — imports, `LORE_CATS`/`LORE_CAT_ORDER`, `CHRONICLER_GUIDANCE`, `TOOL_SCHEMAS`'s `create_lore` entry, `_proposal_from_call`'s `create_lore`/`update_lore` handling, `apply_proposal`'s `lore`/`create` and `lore`/`update` handling, `_reverse_accepted_proposal`'s `lore`/`update` handling
- Test: `server/tests/test_species.py` (append)

**Interfaces:**
- Consumes: `compose_species_content`, `merge_species_fields` from Task 1.
- Produces: the Chronicler can propose `cat == "species"` lore creates/updates carrying a `speciesFields` payload key; applying such a proposal composes `content` the same way the API does; reversing an update restores the pre-update `species_fields`.

- [ ] **Step 1: Write the failing test**

Append to `server/tests/test_species.py`:

```python
# ── Integration: Chronicler create_lore/update_lore for species ────

def test_chronicler_species_proposal_composes_and_reverses(client):
    from server.ai.worldbuilder import _proposal_from_call, apply_proposal, _reverse_accepted_proposal
    from server.db.database import new_session
    from server.db.models import LorebookEntry

    async def create_and_apply():
        async with new_session() as s:
            proposal = await _proposal_from_call(
                s, turn_number=1, name="create_lore",
                args={
                    "cat": "species", "title": "Cave Newt", "content": "unused-placeholder",
                    "keywords": ["newt"],
                    "speciesFields": {"overview": "A blind, pale newt found in deep caverns."},
                },
                member_names=set(), pc_name="", narration="A **Cave Newt** slithers past.",
            )
            assert proposal is not None
            ok, note = await apply_proposal(proposal, s)
            assert ok, note
            await s.commit()
            return proposal.target_id
    entry_id = run(create_and_apply())

    async def check_created():
        async with new_session() as s:
            entry = await s.get(LorebookEntry, entry_id)
            return entry.cat, entry.species_fields, entry.content
    cat, fields, content = run(check_created())
    assert cat == "species"
    assert fields["overview"] == "A blind, pale newt found in deep caverns."
    assert content == "Overview: A blind, pale newt found in deep caverns."

    async def update_and_apply():
        async with new_session() as s:
            proposal = await _proposal_from_call(
                s, turn_number=2, name="update_lore",
                args={"title": "Cave Newt", "speciesFields": {"typicalGear": "None."}},
                member_names=set(), pc_name="", narration="",
            )
            assert proposal is not None
            ok, note = await apply_proposal(proposal, s)
            assert ok, note
            await s.commit()
            return proposal
    updated_proposal = run(update_and_apply())

    async def check_updated():
        async with new_session() as s:
            entry = await s.get(LorebookEntry, entry_id)
            return entry.species_fields, entry.content
    fields2, content2 = run(check_updated())
    assert fields2["overview"] == "A blind, pale newt found in deep caverns."  # untouched
    assert fields2["typicalGear"] == "None."
    assert "Typical Gear: None." in content2

    # Reversing the update restores the pre-update species_fields + content.
    async def reverse():
        async with new_session() as s:
            proposal = await s.merge(updated_proposal)
            changed = await _reverse_accepted_proposal(proposal, s)
            await s.commit()
            return changed
    assert run(reverse()) is True

    async def check_reversed():
        async with new_session() as s:
            entry = await s.get(LorebookEntry, entry_id)
            return entry.species_fields, entry.content
    fields3, content3 = run(check_reversed())
    assert "typicalGear" not in fields3
    assert content3 == "Overview: A blind, pale newt found in deep caverns."

    run_cleanup(entry_id)


def run_cleanup(entry_id: str) -> None:
    from server.db.database import new_session
    from server.db.models import LorebookEntry

    async def cleanup():
        async with new_session() as s:
            entry = await s.get(LorebookEntry, entry_id)
            if entry:
                await s.delete(entry)
                await s.commit()
    run(cleanup())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest server/tests/test_species.py::test_chronicler_species_proposal_composes_and_reverses -v`
Expected: FAIL — `content` is `"unused-placeholder"` instead of the composed string (speciesFields is silently dropped by `_proposal_from_call`/`apply_proposal` today)

- [ ] **Step 3: Update `LORE_CATS`/`LORE_CAT_ORDER` and imports**

In `server/ai/worldbuilder.py`, find (around line 24-41):

```python
from server.ai.openrouter import chat_completion_agent_turn, provider_endpoint
from server.db import events as event_ops
from server.db import party as party_ops
from server.db.database import new_session
from server.db.models import (
    CampaignRules,
    ChatMessage,
    LorebookEntry,
    OpenRouterSettings,
    Task,
    WorldbuildingProposal,
)

log = logging.getLogger("wayward.worldbuilder")

LORE_CATS = {"pillars", "world", "characters", "items", "monsters", "spells"}
# Display order for world-state listings (Pillars first, then Locations, ...).
LORE_CAT_ORDER = ("pillars", "world", "characters", "items", "monsters", "spells")
```

Replace with:

```python
from server.ai.openrouter import chat_completion_agent_turn, provider_endpoint
from server.ai.species import compose_species_content, merge_species_fields
from server.db import events as event_ops
from server.db import party as party_ops
from server.db.database import new_session
from server.db.models import (
    CampaignRules,
    ChatMessage,
    LorebookEntry,
    OpenRouterSettings,
    Task,
    WorldbuildingProposal,
)

log = logging.getLogger("wayward.worldbuilder")

LORE_CATS = {"pillars", "world", "characters", "items", "species", "spells"}
# Display order for world-state listings (Pillars first, then Locations, ...).
LORE_CAT_ORDER = ("pillars", "world", "characters", "items", "species", "spells")
```

- [ ] **Step 4: Update `CHRONICLER_GUIDANCE`**

Find (around line 121-144):

```python
CHRONICLER_GUIDANCE = """You are the Chronicler: a quiet archivist who keeps the world's records as an adventure unfolds. You do NOT narrate. After each turn you review what just happened and record only what genuinely changed.

Use your tools to:
- create_lore / update_lore — record new world rules (pillars), places (world/locations), characters (NPCs), items, monsters, or spells that the fiction has established, or update an existing entry with new facts. Pick the right category.
```

Replace with:

```python
CHRONICLER_GUIDANCE = """You are the Chronicler: a quiet archivist who keeps the world's records as an adventure unfolds. You do NOT narrate. After each turn you review what just happened and record only what genuinely changed.

Use your tools to:
- create_lore / update_lore — record new world rules (pillars), places (world/locations), characters (NPCs), items, species (sapient peoples AND monsters/creatures), or spells that the fiction has established, or update an existing entry with new facts. Pick the right category.
```

Then find the per-category rules list ending (around line 138-144):

```python
Per-category rules (write the entry as a timeless world fact, NOT a diary of this turn):
- items — Describe the item ITSELF, generically: what it is, looks like, does. Do NOT mention who currently holds or wears it, or the scene it appeared in. ALWAYS set its "itemType" (Equipment, Tool, Consumable, Key Item, Artifact, or Other); for Equipment also set a body "slot" (Head, Neck, Torso, Hands, Waist, Legs, Feet, or Accessory); set "rarity" if the fiction implies one (c=common, u=uncommon, r=rare, e=epic, l=legendary; default common).
- pillars — A foundational RULE of the world/universe (how magic works, a law of nature, a societal absolute), not a place or thing. Only file one when the fiction firmly establishes such a rule. These are always in context, so keep them few and load-bearing.
- world (places / locations) — Describe the place generically and permanently. Nothing about the party, what they did there this turn, or transient events.
- monsters — Describe the creature/type in general (appearance, behaviour, danger), not this one encounter's outcome.
- spells — Describe the spell's effect and limits in general, not who cast it just now.
- characters (NPCs) — Describe the person: who they are, appearance, role. Not the party's momentary interaction with them."""
```

Replace with:

```python
Per-category rules (write the entry as a timeless world fact, NOT a diary of this turn):
- items — Describe the item ITSELF, generically: what it is, looks like, does. Do NOT mention who currently holds or wears it, or the scene it appeared in. ALWAYS set its "itemType" (Equipment, Tool, Consumable, Key Item, Artifact, or Other); for Equipment also set a body "slot" (Head, Neck, Torso, Hands, Waist, Legs, Feet, or Accessory); set "rarity" if the fiction implies one (c=common, u=uncommon, r=rare, e=epic, l=legendary; default common).
- pillars — A foundational RULE of the world/universe (how magic works, a law of nature, a societal absolute), not a place or thing. Only file one when the fiction firmly establishes such a rule. These are always in context, so keep them few and load-bearing.
- world (places / locations) — Describe the place generically and permanently. Nothing about the party, what they did there this turn, or transient events.
- species — Covers BOTH sapient peoples and monsters/creatures — one category. Record on first real appearance (encountering, fighting, or learning about them is itself worth recording; unlike characters, this doesn't require the player to interact with them). Use the "speciesFields" object instead of writing one blob into "content": overview, physicalAppearance, biologyReproduction, cultureBehavior, dangerCombat, typicalGear, archetypesVariants, nameExamples. Set ONLY the fields the fiction has actually established — leave the rest out rather than inventing detail. dangerCombat is narrative flavor only; there is no combat system yet.
- spells — Describe the spell's effect and limits in general, not who cast it just now.
- characters (NPCs) — Describe the person: who they are, appearance, role. Not the party's momentary interaction with them."""
```

- [ ] **Step 5: Add `speciesFields` to the `create_lore`/`update_lore` tool schemas**

Find (around line 147-183):

```python
TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "create_lore",
            "description": "Record a new lorebook entry for something the fiction has established. For cat='items', ALSO set itemType (and slot for Equipment).",
            "parameters": {
                "type": "object",
                "properties": {
                    "cat": {"type": "string", "enum": sorted(LORE_CATS)},
                    "title": {"type": "string", "description": "Short name, e.g. 'Sunken Chapel'."},
                    "content": {"type": "string", "description": "A concise descriptive paragraph. For items, describe the item itself — not who holds it."},
                    "keywords": {"type": "array", "items": {"type": "string"}},
                    "itemType": {"type": "string", "enum": ["Equipment", "Tool", "Consumable", "Key Item", "Artifact", "Currency", "Other"], "description": "Items only. The kind of item."},
                    "slot": {"type": "string", "enum": ["Head", "Neck", "Torso", "Hands", "Waist", "Legs", "Feet", "Accessory"], "description": "Equipment items only. The body slot it's worn in."},
                    "rarity": {"type": "string", "enum": ["c", "u", "r", "e", "l"], "description": "Items only. c=common u=uncommon r=rare e=epic l=legendary."},
                },
                "required": ["cat", "title", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_lore",
            "description": "Add new facts to an existing lorebook entry, by its exact title.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "content": {"type": "string", "description": "The full updated description."},
                    "keywords": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["title", "content"],
            },
        },
    },
```

Replace with:

```python
_SPECIES_FIELDS_SCHEMA = {
    "type": "object",
    "description": "For cat='species' only. Structured fields — set only what the fiction has established; leave the rest out. content is ignored/overwritten when this is provided.",
    "properties": {
        "overview": {"type": "string"},
        "physicalAppearance": {"type": "string"},
        "biologyReproduction": {"type": "string"},
        "cultureBehavior": {"type": "string"},
        "dangerCombat": {"type": "string"},
        "typicalGear": {"type": "string"},
        "archetypesVariants": {"type": "string"},
        "nameExamples": {"type": "string"},
    },
}

TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "create_lore",
            "description": "Record a new lorebook entry for something the fiction has established. For cat='items', ALSO set itemType (and slot for Equipment). For cat='species', set speciesFields instead of writing one blob into content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cat": {"type": "string", "enum": sorted(LORE_CATS)},
                    "title": {"type": "string", "description": "Short name, e.g. 'Sunken Chapel'."},
                    "content": {"type": "string", "description": "A concise descriptive paragraph. For items, describe the item itself — not who holds it."},
                    "keywords": {"type": "array", "items": {"type": "string"}},
                    "itemType": {"type": "string", "enum": ["Equipment", "Tool", "Consumable", "Key Item", "Artifact", "Currency", "Other"], "description": "Items only. The kind of item."},
                    "slot": {"type": "string", "enum": ["Head", "Neck", "Torso", "Hands", "Waist", "Legs", "Feet", "Accessory"], "description": "Equipment items only. The body slot it's worn in."},
                    "rarity": {"type": "string", "enum": ["c", "u", "r", "e", "l"], "description": "Items only. c=common u=uncommon r=rare e=epic l=legendary."},
                    "speciesFields": _SPECIES_FIELDS_SCHEMA,
                },
                "required": ["cat", "title", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_lore",
            "description": "Add new facts to an existing lorebook entry, by its exact title.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "content": {"type": "string", "description": "The full updated description."},
                    "keywords": {"type": "array", "items": {"type": "string"}},
                    "speciesFields": _SPECIES_FIELDS_SCHEMA,
                },
                "required": ["title", "content"],
            },
        },
    },
```

- [ ] **Step 6: Thread `speciesFields` through `_proposal_from_call`**

Find (around line 397-430, the `create_lore` branch):

```python
        payload = {"cat": cat, "title": title, "content": args.get("content", ""), "keywords": args.get("keywords", [])}
        if cat == "items":
            payload["itemType"] = (args.get("itemType") or "Other")
            payload["rarity"] = (args.get("rarity") or "c")
            if args.get("slot"):
                payload["slot"] = args.get("slot")
        return WorldbuildingProposal(
            turn_number=turn_number, kind="lore", operation="create",
            payload=payload, summary=_summary("lore", "create", payload),
        )
```

Replace with:

```python
        payload = {"cat": cat, "title": title, "content": args.get("content", ""), "keywords": args.get("keywords", [])}
        if cat == "items":
            payload["itemType"] = (args.get("itemType") or "Other")
            payload["rarity"] = (args.get("rarity") or "c")
            if args.get("slot"):
                payload["slot"] = args.get("slot")
        if cat == "species" and args.get("speciesFields"):
            payload["speciesFields"] = args["speciesFields"]
        return WorldbuildingProposal(
            turn_number=turn_number, kind="lore", operation="create",
            payload=payload, summary=_summary("lore", "create", payload),
        )
```

Find the `update_lore` branch right after it (around line 432-444):

```python
    if name == "update_lore":
        title = (args.get("title") or "").strip()
        if title.lower() in member_names or (pc_name and title.lower() == pc_name):
            return None
        existing = await _resolve_lore(session, title)
        if not existing or existing.locked:
            return None
        payload = {"content": args.get("content", ""), "keywords": args.get("keywords")}
        return WorldbuildingProposal(
            turn_number=turn_number, kind="lore", operation="update",
            target_id=existing.id, payload=payload,
            summary=_summary("lore", "update", payload, existing.title),
        )
```

Replace with:

```python
    if name == "update_lore":
        title = (args.get("title") or "").strip()
        if title.lower() in member_names or (pc_name and title.lower() == pc_name):
            return None
        existing = await _resolve_lore(session, title)
        if not existing or existing.locked:
            return None
        payload = {"content": args.get("content", ""), "keywords": args.get("keywords")}
        if existing.cat == "species" and args.get("speciesFields"):
            payload["speciesFields"] = args["speciesFields"]
        return WorldbuildingProposal(
            turn_number=turn_number, kind="lore", operation="update",
            target_id=existing.id, payload=payload,
            summary=_summary("lore", "update", payload, existing.title),
        )
```

- [ ] **Step 7: Compose content in `apply_proposal`, and restore `species_fields` on reversal**

Find (around line 501-529):

```python
    if kind == "lore" and op == "create":
        cat = p.get("cat", "world")
        entry = LorebookEntry(
            title=p.get("title", ""), content=p.get("content", ""),
            keywords=p.get("keywords") or [], cat=cat,
        )
        if cat == "items":
            entry.item_type = p.get("itemType") or "Other"
            entry.rarity = p.get("rarity") or "c"
            entry.slot = p.get("slot")
            entry.max_stack = 1
        session.add(entry)
        await session.flush()
        proposal.target_id = entry.id  # tie the created entry to this proposal/turn
        return True, None

    if kind == "lore" and op == "update":
        entry = await session.get(LorebookEntry, proposal.target_id)
        if not entry:
            return False, "Lore entry no longer exists."
        if entry.locked:
            return False, "Entry is locked."
        # Snapshot prior state so a regenerate/delete of this turn can restore it.
        _snapshot_prev(proposal, {"content": entry.content, "keywords": list(entry.keywords or [])})
        if p.get("content") is not None:
            entry.content = p["content"]
        if p.get("keywords") is not None:
            entry.keywords = p["keywords"]
        return True, None
```

Replace with:

```python
    if kind == "lore" and op == "create":
        cat = p.get("cat", "world")
        entry = LorebookEntry(
            title=p.get("title", ""), content=p.get("content", ""),
            keywords=p.get("keywords") or [], cat=cat,
        )
        if cat == "items":
            entry.item_type = p.get("itemType") or "Other"
            entry.rarity = p.get("rarity") or "c"
            entry.slot = p.get("slot")
            entry.max_stack = 1
        if cat == "species" and p.get("speciesFields"):
            entry.species_fields = merge_species_fields(None, p["speciesFields"])
            entry.content = compose_species_content(entry.species_fields)
        session.add(entry)
        await session.flush()
        proposal.target_id = entry.id  # tie the created entry to this proposal/turn
        return True, None

    if kind == "lore" and op == "update":
        entry = await session.get(LorebookEntry, proposal.target_id)
        if not entry:
            return False, "Lore entry no longer exists."
        if entry.locked:
            return False, "Entry is locked."
        # Snapshot prior state so a regenerate/delete of this turn can restore it.
        _snapshot_prev(proposal, {
            "content": entry.content, "keywords": list(entry.keywords or []),
            "speciesFields": dict(entry.species_fields or {}),
        })
        if entry.cat == "species" and p.get("speciesFields"):
            entry.species_fields = merge_species_fields(entry.species_fields, p["speciesFields"])
            entry.content = compose_species_content(entry.species_fields)
        elif p.get("content") is not None:
            entry.content = p["content"]
        if p.get("keywords") is not None:
            entry.keywords = p["keywords"]
        return True, None
```

Find `_reverse_accepted_proposal`'s `lore`/`update` branch (around line 593-601):

```python
    if kind == "lore" and op == "update":
        entry = await session.get(LorebookEntry, p.target_id) if p.target_id else None
        if entry is not None and not entry.locked and prev:
            if "content" in prev:
                entry.content = prev["content"]
            if "keywords" in prev:
                entry.keywords = prev["keywords"]
            return True
        return False
```

Replace with:

```python
    if kind == "lore" and op == "update":
        entry = await session.get(LorebookEntry, p.target_id) if p.target_id else None
        if entry is not None and not entry.locked and prev:
            if "content" in prev:
                entry.content = prev["content"]
            if "keywords" in prev:
                entry.keywords = prev["keywords"]
            if "speciesFields" in prev:
                entry.species_fields = prev["speciesFields"]
            return True
        return False
```

- [ ] **Step 8: Run test to verify it passes**

Run: `python -m pytest server/tests/test_species.py -v`
Expected: PASS (all tests)

- [ ] **Step 9: Commit**

```bash
git add server/ai/worldbuilder.py server/tests/test_species.py
git commit -m "feat: wire species fields into the Chronicler's lore proposals"
```

---

### Task 6: Editor wiring (`server/ai/planner.py`)

**Files:**
- Modify: `server/ai/planner.py` — imports, `PLANNER_GUIDANCE`, `TOOL_SCHEMAS`'s `create_lore`/`update_lore` entries, `_exec_tool`'s `create_lore`/`update_lore` handling
- Test: `server/tests/test_species.py` (append)

**Interfaces:**
- Consumes: `compose_species_content`, `merge_species_fields`, `SPECIES_FIELDS` from Task 1.
- Produces: the Editor's `create_lore`/`update_lore` tools accept `speciesFields` and compose `content` the same way the Chronicler and API do.

- [ ] **Step 1: Write the failing test**

Append to `server/tests/test_species.py`:

```python
# ── Integration: Editor create_lore/update_lore for species ────────

def test_editor_species_create_and_update_composes(client):
    from server.ai.planner import _exec_tool
    from server.db.database import new_session
    from server.db.models import LorebookEntry

    async def create():
        async with new_session() as s:
            result, pending = await _exec_tool("create_lore", {
                "cat": "species", "title": "Bog Sprite", "content": "unused-placeholder",
                "speciesFields": {"overview": "A small, luminous marsh spirit."},
            }, s)
            assert pending is None
            assert "Bog Sprite" in result
            entry = (await s.execute(
                select(LorebookEntry).where(LorebookEntry.title == "Bog Sprite")
            )).scalars().first()
            await s.commit()
            return entry.id
    entry_id = run(create())

    async def check_created():
        async with new_session() as s:
            entry = await s.get(LorebookEntry, entry_id)
            return entry.species_fields, entry.content
    fields, content = run(check_created())
    assert fields == {"overview": "A small, luminous marsh spirit."}
    assert content == "Overview: A small, luminous marsh spirit."

    async def update():
        async with new_session() as s:
            result, pending = await _exec_tool("update_lore", {
                "title": "Bog Sprite",
                "speciesFields": {"typicalGear": "None."},
            }, s)
            assert pending is None
            assert "Bog Sprite" in result
            await s.commit()
    run(update())

    async def check_updated():
        async with new_session() as s:
            entry = await s.get(LorebookEntry, entry_id)
            return entry.species_fields, entry.content
    fields2, content2 = run(check_updated())
    assert fields2["overview"] == "A small, luminous marsh spirit."  # untouched
    assert fields2["typicalGear"] == "None."
    assert "Typical Gear: None." in content2

    run_cleanup(entry_id)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest server/tests/test_species.py::test_editor_species_create_and_update_composes -v`
Expected: FAIL — `content` is `"unused-placeholder"` instead of the composed string

- [ ] **Step 3: Update imports and `PLANNER_GUIDANCE`**

Find (around line 35):

```python
from server.ai.worldbuilder import LORE_CAT_ORDER, LORE_CATS, TASK_STATUSES, _resolve_lore, _resolve_task
```

Replace with:

```python
from server.ai.species import compose_species_content, merge_species_fields
from server.ai.worldbuilder import LORE_CAT_ORDER, LORE_CATS, TASK_STATUSES, _resolve_lore, _resolve_task
```

Find (line 58):

```python
PLANNER_GUIDANCE = """You are the Editor: a collaborative world-building assistant. You are NOT the narrator — you do not narrate scenes or play the adventure. Your job is to help the player build and shape their adventure: places, characters, items, monsters, spells, tasks, the party, the player character, the Scenario, and even the Narrator's instructions.
```

Replace with:

```python
PLANNER_GUIDANCE = """You are the Editor: a collaborative world-building assistant. You are NOT the narrator — you do not narrate scenes or play the adventure. Your job is to help the player build and shape their adventure: places, characters, items, species, spells, tasks, the party, the player character, the Scenario, and even the Narrator's instructions.
```

Find (line 63):

```python
- Pick the right lore category for lore (pillars, world, characters, monsters, spells). For NPCs use 'characters'. Use 'world' for places/locations. Use 'pillars' for foundational RULES of the world/universe (how magic works, laws of nature, societal absolutes) — these are always kept in the narrator's context, so reserve them for load-bearing rules, not ordinary facts.
```

Replace with:

```python
- Pick the right lore category for lore (pillars, world, characters, species, spells). For NPCs use 'characters'. Use 'world' for places/locations. Use 'pillars' for foundational RULES of the world/universe (how magic works, laws of nature, societal absolutes) — these are always kept in the narrator's context, so reserve them for load-bearing rules, not ordinary facts. Use 'species' for creature/people templates — it covers BOTH sapient peoples and monsters/creatures — and set the structured speciesFields (overview, physical appearance, biology & reproduction, culture & behavior, danger & combat notes, typical gear, archetypes & variants, name examples) rather than writing one blob into content.
```

Find (line 70):

```python
- TIMELESS ENTRIES: write every lore/item entry as a permanent world fact, not a note about the current scene or party. Items — describe the item itself, generically (what it is/does), never who currently holds or wears it, and always give it a proper type (and slot for Equipment). World/places — describe the place generically; nothing about the party or what they're doing there. Monsters — the creature in general. Spells — the effect and its limits. Characters (NPCs) — who they are, not the party's momentary interaction with them.
```

Replace with:

```python
- TIMELESS ENTRIES: write every lore/item entry as a permanent world fact, not a note about the current scene or party. Items — describe the item itself, generically (what it is/does), never who currently holds or wears it, and always give it a proper type (and slot for Equipment). World/places — describe the place generically; nothing about the party or what they're doing there. Species — the creature or people in general, using the structured speciesFields rather than one blob of content. Spells — the effect and its limits. Characters (NPCs) — who they are, not the party's momentary interaction with them.
```

- [ ] **Step 4: Add `speciesFields` to the tool schemas**

Find (around line 91):

```python
_LORE_CAT_ENUM = sorted(LORE_CATS)
```

Replace with:

```python
_LORE_CAT_ENUM = sorted(LORE_CATS)

_SPECIES_FIELDS_SCHEMA = {
    "type": "object",
    "description": "For cat='species' only — structured fields, partial (set only what you're changing). content is ignored/overwritten when this is provided.",
    "properties": {
        "overview": {"type": "string"},
        "physicalAppearance": {"type": "string"},
        "biologyReproduction": {"type": "string"},
        "cultureBehavior": {"type": "string"},
        "dangerCombat": {"type": "string"},
        "typicalGear": {"type": "string"},
        "archetypesVariants": {"type": "string"},
        "nameExamples": {"type": "string"},
    },
}
```

Find (around line 125-134):

```python
TOOL_SCHEMAS: list[dict] = [
    _fn("create_lore", "Create a lorebook entry (place, character/NPC, item, monster, or spell).",
        {"cat": {"type": "string", "enum": _LORE_CAT_ENUM}, "title": {"type": "string"},
         "content": {"type": "string"}, "keywords": {"type": "array", "items": {"type": "string"}}},
        ["cat", "title", "content"]),
    _fn("update_lore", "Edit an existing lorebook entry, by its exact title.",
        {"title": {"type": "string"}, "content": {"type": "string"},
         "keywords": {"type": "array", "items": {"type": "string"}},
         "cat": {"type": "string", "enum": _LORE_CAT_ENUM}},
        ["title"]),
```

Replace with:

```python
TOOL_SCHEMAS: list[dict] = [
    _fn("create_lore", "Create a lorebook entry (place, character/NPC, item, species, or spell).",
        {"cat": {"type": "string", "enum": _LORE_CAT_ENUM}, "title": {"type": "string"},
         "content": {"type": "string"}, "keywords": {"type": "array", "items": {"type": "string"}},
         "speciesFields": _SPECIES_FIELDS_SCHEMA},
        ["cat", "title", "content"]),
    _fn("update_lore", "Edit an existing lorebook entry, by its exact title.",
        {"title": {"type": "string"}, "content": {"type": "string"},
         "keywords": {"type": "array", "items": {"type": "string"}},
         "cat": {"type": "string", "enum": _LORE_CAT_ENUM},
         "speciesFields": _SPECIES_FIELDS_SCHEMA},
        ["title"]),
```

- [ ] **Step 5: Wire composition into `_exec_tool`**

Find (around line 303-328):

```python
    # ---- Lore ----
    if name == "create_lore":
        cat = args.get("cat")
        title = (args.get("title") or "").strip()
        if cat not in LORE_CATS or not title:
            return "create_lore needs a valid cat and title.", None
        if cat == "items":
            return "Use create_item for items so type/slot/rarity are set correctly.", None
        if await _resolve_lore(session, title):
            return f"'{title}' already exists — use update_lore instead.", None
        session.add(LorebookEntry(title=title, content=args.get("content", ""),
                                  keywords=args.get("keywords") or [], cat=cat))
        return f"Created {cat} lore: {title}.", None

    if name == "update_lore":
        entry = await _resolve_lore(session, (args.get("title") or "").strip())
        if not entry:
            return f"No lore entry named '{args.get('title', '')}'.", None
        if entry.locked and args.get("cat"):
            return f"'{entry.title}' is locked; its category can't change.", None
        if args.get("content") is not None:
            entry.content = args["content"]
        if args.get("keywords") is not None:
            entry.keywords = args["keywords"]
        if args.get("cat") in LORE_CATS and not entry.locked:
            entry.cat = args["cat"]
        return f"Updated lore: {entry.title}.", None
```

Replace with:

```python
    # ---- Lore ----
    if name == "create_lore":
        cat = args.get("cat")
        title = (args.get("title") or "").strip()
        if cat not in LORE_CATS or not title:
            return "create_lore needs a valid cat and title.", None
        if cat == "items":
            return "Use create_item for items so type/slot/rarity are set correctly.", None
        if await _resolve_lore(session, title):
            return f"'{title}' already exists — use update_lore instead.", None
        entry = LorebookEntry(title=title, content=args.get("content", ""),
                              keywords=args.get("keywords") or [], cat=cat)
        if cat == "species" and args.get("speciesFields"):
            entry.species_fields = merge_species_fields(None, args["speciesFields"])
            entry.content = compose_species_content(entry.species_fields)
        session.add(entry)
        return f"Created {cat} lore: {title}.", None

    if name == "update_lore":
        entry = await _resolve_lore(session, (args.get("title") or "").strip())
        if not entry:
            return f"No lore entry named '{args.get('title', '')}'.", None
        if entry.locked and args.get("cat"):
            return f"'{entry.title}' is locked; its category can't change.", None
        if entry.cat == "species" and args.get("speciesFields"):
            entry.species_fields = merge_species_fields(entry.species_fields, args["speciesFields"])
            entry.content = compose_species_content(entry.species_fields)
        elif args.get("content") is not None:
            entry.content = args["content"]
        if args.get("keywords") is not None:
            entry.keywords = args["keywords"]
        if args.get("cat") in LORE_CATS and not entry.locked:
            entry.cat = args["cat"]
        return f"Updated lore: {entry.title}.", None
```

- [ ] **Step 6: Run test to verify it passes**

Run: `python -m pytest server/tests/test_species.py -v`
Expected: PASS (all tests)

- [ ] **Step 7: Run the full server test suite**

Run: `python -m pytest server/tests -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add server/ai/planner.py server/tests/test_species.py
git commit -m "feat: wire species fields into the Editor's lore tools"
```

---

### Task 7: Shared TS types + `speciesFields.ts` client lib

**Files:**
- Modify: `shared/types/models.ts:287-298` (LoreCategory, LorebookEntry), and add a `SpeciesFields` interface after `ScenarioFields`
- Create: `client/src/lib/speciesFields.ts`

**Interfaces:**
- Produces: `LoreCategory` includes `'species'` (not `'monsters'`); `LorebookEntry.speciesFields?: SpeciesFields`; `SPECIES_FIELD_DEFS` array for the Inspector form (Task 9).

- [ ] **Step 1: Update `shared/types/models.ts`**

Find (around line 285-298):

```typescript
// Note: 'world' is the internal id for the "Locations" tab (kept for data
// stability — existing entries and the locked Scenario are cat='world').
export type LoreCategory = 'pillars' | 'world' | 'characters' | 'items' | 'monsters' | 'spells'

export interface LorebookEntry {
  id: string
  title: string
  content: string
  keywords: string[]
  enabled: boolean
  permanent: boolean
  locked?: boolean
  cat: LoreCategory
}
```

Replace with:

```typescript
// Note: 'world' is the internal id for the "Locations" tab (kept for data
// stability — existing entries and the locked Scenario are cat='world').
export type LoreCategory = 'pillars' | 'world' | 'characters' | 'items' | 'species' | 'spells'

export interface LorebookEntry {
  id: string
  title: string
  content: string
  keywords: string[]
  enabled: boolean
  permanent: boolean
  locked?: boolean
  cat: LoreCategory
  /** Only meaningful when cat === 'species'; null/undefined otherwise. */
  speciesFields?: SpeciesFields | null
}
```

Find `ScenarioFields` (around line 307-314):

```typescript
export interface ScenarioFields {
  setting: string
  historyBrief: string
  species: string
  geography: string
  techAndMagic: string
  other: string
}
```

Replace with:

```typescript
export interface ScenarioFields {
  setting: string
  historyBrief: string
  species: string
  geography: string
  techAndMagic: string
  other: string
}

/** The 8 structured Species/Creature-template fields (see "Species &
 *  Creature Templates" — merges the old Monsters category). */
export interface SpeciesFields {
  overview: string
  physicalAppearance: string
  biologyReproduction: string
  cultureBehavior: string
  dangerCombat: string
  typicalGear: string
  archetypesVariants: string
  nameExamples: string
}
```

- [ ] **Step 2: Create `client/src/lib/speciesFields.ts`**

```typescript
import type { SpeciesFields } from '@shared/types/models'

export type SpeciesFieldKey = keyof SpeciesFields

/** The 8 structured Species fields, in display/compose order (see "Species
 *  & Creature Templates"). Mirrors scenarioFields.ts's SCENARIO_FIELD_DEFS
 *  for the Scenario tab — same pattern, per-entry instead of a singleton. */
export const SPECIES_FIELD_DEFS: { key: SpeciesFieldKey; label: string; placeholder: string }[] = [
  { key: 'overview', label: 'Overview', placeholder: 'What are they, at a glance? Where are they typically found?' },
  { key: 'physicalAppearance', label: 'Physical Appearance', placeholder: 'Build, distinguishing features, size range, variation...' },
  { key: 'biologyReproduction', label: 'Biology & Reproduction', placeholder: 'Physiology, lifespan, diet, how they grow or reproduce...' },
  { key: 'cultureBehavior', label: 'Culture & Behavior', placeholder: 'Society and customs, or pack/territorial/instinctual behavior...' },
  { key: 'dangerCombat', label: 'Danger & Combat Notes', placeholder: 'Threat level, tactics, notable abilities or weaknesses...' },
  { key: 'typicalGear', label: 'Typical Gear', placeholder: 'What they carry, use, build, or lair in...' },
  { key: 'archetypesVariants', label: 'Archetypes & Variants', placeholder: 'Common roles/builds/subtypes seen within the species...' },
  { key: 'nameExamples', label: 'Name Examples', placeholder: 'Naming conventions and sample names...' },
]
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd client && npm run build`
Expected: FAILS — the 4 files with `'monsters'` literals (Task 8) don't satisfy the narrowed `LoreCategory` type yet. This is expected at this point in the plan; Task 8 fixes it. Confirm the *only* errors are `'monsters'` not assignable to `LoreCategory` in `LorePanel.tsx`, `CategoryIcon.tsx`, `SettingsPanel.tsx`, and `PartyInspector.tsx`.

- [ ] **Step 4: Commit**

```bash
git add shared/types/models.ts client/src/lib/speciesFields.ts
git commit -m "feat: add SpeciesFields type and client field defs"
```

---

### Task 8: Client category rename (`monsters` → `species` across the UI)

**Files:**
- Modify: `client/src/components/LorePanel/LorePanel.tsx:22`
- Modify: `client/src/components/CategoryIcon.tsx:14`
- Modify: `client/src/components/Settings/SettingsPanel.tsx:26`
- Modify: `client/src/components/Inspector/PartyInspector.tsx:1024,1033`

**Interfaces:**
- Consumes: the narrowed `LoreCategory` type from Task 7.
- No new interfaces — purely renames the category id/label everywhere it's hardcoded.

- [ ] **Step 1: `LorePanel.tsx`**

Find (line 22):

```typescript
  { id: 'monsters', label: 'Monsters' },
```

Replace with:

```typescript
  { id: 'species', label: 'Species' },
```

- [ ] **Step 2: `CategoryIcon.tsx`**

Find (line 14):

```typescript
    case 'monsters': // fanged maw
```

Replace with:

```typescript
    case 'species': // fanged maw
```

- [ ] **Step 3: `SettingsPanel.tsx`**

Find (line 26):

```typescript
  { id: 'monsters', label: 'Monsters' },
```

Replace with:

```typescript
  { id: 'species', label: 'Species' },
```

- [ ] **Step 4: `PartyInspector.tsx`**

Find (line 1024):

```typescript
  { value: 'monsters', label: 'Monsters' },
```

Replace with:

```typescript
  { value: 'species', label: 'Species' },
```

Find (line 1033):

```typescript
  monsters: 'text-[#cf7a7a]',
```

Replace with:

```typescript
  species: 'text-[#cf7a7a]',
```

- [ ] **Step 5: Verify TypeScript compiles**

Run: `cd client && npm run build`
Expected: PASS — no `LoreCategory` errors remain.

- [ ] **Step 6: Commit**

```bash
git add client/src/components/LorePanel/LorePanel.tsx client/src/components/CategoryIcon.tsx client/src/components/Settings/SettingsPanel.tsx client/src/components/Inspector/PartyInspector.tsx
git commit -m "feat: rename Monsters tab to Species across the client UI"
```

---

### Task 9: Client structured Species form in the Lore Inspector

**Files:**
- Modify: `client/src/components/Inspector/PartyInspector.tsx` (imports, `LoreInspector`'s edit-mode branch)

**Interfaces:**
- Consumes: `SPECIES_FIELD_DEFS` from Task 7 (`client/src/lib/speciesFields.ts`).
- Produces: editing a `cat === 'species'` lore entry in Edit Mode shows 8 labeled fields instead of one plain content textarea; every other category is unchanged.

- [ ] **Step 1: Add the import**

Find, near the top of `PartyInspector.tsx` where other lib imports live (alongside the existing `useLoreStore`/`useUiStore` imports):

```typescript
import { useLoreStore } from '../../state/loreStore'
```

Replace with:

```typescript
import { useLoreStore } from '../../state/loreStore'
import { SPECIES_FIELD_DEFS } from '../../lib/speciesFields'
```

(If `useLoreStore`'s import line looks different by the time this task runs, add `import { SPECIES_FIELD_DEFS } from '../../lib/speciesFields'` as its own new line anywhere in the top import block instead.)

- [ ] **Step 2: Replace the plain Content section with a conditional structured form**

Find, inside `LoreInspector`'s edit-mode branch (around line 1225-1233):

```tsx
      {/* Content */}
      <LoreSection title="Content">
        <LoreTextArea
          value={d.content ?? ''}
          onChange={(v) => update('content', v)}
          onBlur={(v) => update('content', v, true)}
          placeholder="Entry content..."
        />
      </LoreSection>
```

Replace with:

```tsx
      {/* Content — structured fields for Species, plain text otherwise */}
      {d.cat === 'species' ? (
        <LoreSection title="Species Fields">
          <div className="space-y-4">
            {SPECIES_FIELD_DEFS.map(({ key, label, placeholder }) => (
              <label key={key} className="block">
                <span className="text-[11px] text-textdim font-body block mb-0.5">{label}</span>
                <LoreTextArea
                  value={d.speciesFields?.[key] ?? ''}
                  onChange={(v) => update('speciesFields', { ...(d.speciesFields ?? {}), [key]: v })}
                  onBlur={(v) => update('speciesFields', { ...(d.speciesFields ?? {}), [key]: v }, true)}
                  placeholder={placeholder}
                />
              </label>
            ))}
          </div>
        </LoreSection>
      ) : (
        <LoreSection title="Content">
          <LoreTextArea
            value={d.content ?? ''}
            onChange={(v) => update('content', v)}
            onBlur={(v) => update('content', v, true)}
            placeholder="Entry content..."
          />
        </LoreSection>
      )}
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd client && npm run build`
Expected: PASS

- [ ] **Step 4: Manual smoke test**

Run: `cd client && npm run dev` (and in another terminal, the server via `Run.bat`/`Run.ps1` if not already running)
In the browser: open Edit Mode → Lore panel → Species tab → "+ NEW ENTRY" → confirm 8 labeled fields appear (not a single Content box) → fill in Overview and Danger & Combat Notes → switch to Play mode view → confirm the entry's displayed Content shows both as labeled paragraphs, in field order. Stop the dev server when done.

- [ ] **Step 5: Commit**

```bash
git add client/src/components/Inspector/PartyInspector.tsx
git commit -m "feat: add structured Species field form to the Lore Inspector"
```

---

### Task 10: Full-suite verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full server test suite**

Run: `python -m pytest server/tests -v`
Expected: PASS, no failures, no test referencing `"monsters"` anywhere

- [ ] **Step 2: Run the full client test suite**

Run: `cd client && npm test`
Expected: PASS

- [ ] **Step 3: Run the client build (type-check + bundle)**

Run: `cd client && npm run build`
Expected: PASS, no TypeScript errors

- [ ] **Step 4: Grep for any remaining "monsters" reference outside migration/legacy-comment context**

Run: `grep -rn "monsters" server/ client/src/ shared/ --include="*.py" --include="*.ts" --include="*.tsx" --include="*.json"`
Expected: only remaining hits are inside `migrate_species_lore`'s docstring/logic (the `cat == "monsters"` lookup and the `"monsters"` key checks in `server/db/database.py`, which must stay — they're what makes the migration work) and any purely-prose mentions of "monsters" as a plain English word (e.g. `fantasy.json`'s historyBrief text "...the monsters that crept in..." — leave that alone, it's flavor text, not a category key).

- [ ] **Step 5: Commit (if the grep step required any cleanup)**

```bash
git add -A
git commit -m "chore: verify species lorebook migration is complete"
```

(Skip this commit if Step 4 found nothing to fix — an empty diff means no commit is needed.)
