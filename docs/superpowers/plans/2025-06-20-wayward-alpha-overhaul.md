# Wayward Alpha Overhaul — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the existing Wayward prototype into the alpha described in the updated CLAUDE.md — new visual system, four-pane icon-rail layout, full Item/Quest/Lorebook subsystems, Narrator action parsing, and complete chat message rendering.

**Architecture:** The existing React+Zustand frontend / Python+FastAPI backend / SQLite stack is kept. The overhaul adds three new subsystems (Items, Quests, Lorebook) as new DB models + API routes + Zustand stores + UI panels, replaces the current 3-pane layout with a 4-pane icon-rail layout, overhauls the visual token system (dark/gold manuscript aesthetic), and upgrades chat rendering with speaker differentiation, spotlight badges, and inventory notices.

**Tech Stack:** React 19, TypeScript, Tailwind v4 (inline theme), Zustand 5, Vite 8, Python FastAPI, SQLAlchemy (async SQLite), OpenRouter API

## Global Constraints

- SQLite only, single campaign, single player character — no multi-save.
- One LLM call per turn — spotlight signals are computed locally, injected into the single narration call.
- No dice, no numeric stats, no mechanical resolution. The `attributes` field (`AttributeBlock`) is being removed — character sheets are BasicInfo + Equipment (+ FieldSkill for party members) only.
- Equipment slots reference `ItemCatalogEntry.id` (or null), not free-text strings.
- Item catalog is closed — Narrator can only grant pre-authored items.
- Fonts: Cinzel (display/headers), Quicksand (body prose), Hanken Grotesk (UI chrome).
- Color tokens from CLAUDE.md: `--bg0: #100e0a` through `--golddeep: #8a6f3a`, `--blue: #7aa6cf`, `--text: #ece4d3` family.
- Grid: `66px 288px minmax(0,1fr) 344px` (icon rail, left panel, chat, inspector).
- All existing portrait uploads, seed data for Seraphine/Tifa/Rosalina, adventure export/import/reset, story summarization — preserved.

---

## Phase 1: Visual System & Layout Overhaul

Replaces the current light-mode 3-pane layout with the dark/gold 4-pane icon-rail layout from the spec. No new features — same Party/Chat/Inspector content, just reframed into the new shell. This phase produces a visually correct but feature-incomplete app.

### Task 1.1: CSS Token & Font Overhaul

**Files:**
- Modify: `client/src/index.css`
- Modify: `client/index.html` (add Google Fonts links)

**Interfaces:**
- Produces: CSS custom properties available globally via `var(--bg0)`, `var(--gold)`, `var(--fdisp)`, etc.
- Produces: Tailwind v4 inline theme tokens mapped to these values.

- [ ] **Step 1: Update `client/index.html` to load the three Google Fonts**

Add to `<head>`:
```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Cinzel:wght@400;600;700&family=Quicksand:wght@400;500;600&family=Hanken+Grotesk:wght@400;500;600;700&display=swap" rel="stylesheet">
```

- [ ] **Step 2: Replace the Tailwind inline theme in `client/src/index.css`**

Replace the entire `@theme inline { ... }` block and global styles with:

```css
@import "tailwindcss";

@theme inline {
  --color-bg0: #100e0a;
  --color-bg1: #17140e;
  --color-bg2: #1e1a12;
  --color-bg3: #262016;
  --color-line: rgba(201,165,88,.18);
  --color-line2: rgba(201,165,88,.42);
  --color-gold: #c9a558;
  --color-gold2: #e8cf8c;
  --color-golddeep: #8a6f3a;
  --color-blue: #7aa6cf;
  --color-text: #ece4d3;
  --color-text2: #cfc6b0;
  --color-textsec: #9b927a;
  --color-textdim: #6c654f;

  --font-disp: 'Cinzel', serif;
  --font-body: 'Quicksand', sans-serif;
  --font-ui: 'Hanken Grotesk', sans-serif;
}

html, body, #root {
  height: 100%;
  overflow: hidden;
  background-color: var(--color-bg0);
  color: var(--color-text);
  font-family: var(--font-body);
}
```

Keep the existing scrollbar styles, updating colors to use the new tokens (`var(--color-bg2)` for track, `var(--color-golddeep)` for thumb).

- [ ] **Step 3: Verify fonts render correctly**

Run `npm run dev` in `client/`. Confirm Cinzel, Quicksand, and Hanken Grotesk load in the browser's Network tab. Visually confirm text renders in the correct fonts.

- [ ] **Step 4: Commit**

```bash
git add client/index.html client/src/index.css
git commit -m "feat: replace visual token system with dark/gold manuscript aesthetic"
```

---

### Task 1.2: Four-Pane AppShell with Icon Rail

**Files:**
- Modify: `client/src/components/Layout/AppShell.tsx`
- Create: `client/src/components/IconRail/IconRail.tsx`
- Create: `client/src/state/uiStore.ts` (replace existing minimal version)
- Modify: `client/src/App.tsx`

**Interfaces:**
- Consumes: CSS tokens from Task 1.1
- Produces: `useUiStore` with `activeTab: TabId`, `selection`, `everSelected`, `mode`, `modeMemory`, `editDirty`
- Produces: `TabId = 'scene' | 'party' | 'items' | 'quests' | 'lore' | 'config'`
- Produces: `<IconRail activeTab={TabId} onTabChange={fn} />`
- Produces: `<AppShell />` rendering 4-column grid: icon rail, left panel (contextual), chat, inspector

- [ ] **Step 1: Rewrite `uiStore.ts` with the full inspector state model**

```typescript
import { create } from 'zustand'

export type TabId = 'scene' | 'party' | 'items' | 'quests' | 'lore' | 'config'

export type SelectionKind =
  | { kind: 'player' }
  | { kind: 'member'; id: string }
  | { kind: 'item'; id: string }
  | { kind: 'quest'; id: string }
  | { kind: 'lore'; id: string }
  | null

interface UiState {
  activeTab: TabId
  setActiveTab: (tab: TabId) => void

  selection: SelectionKind
  everSelected: boolean
  mode: 'view' | 'edit'
  modeMemory: Record<string, 'view' | 'edit'>
  editDirty: boolean

  select: (sel: SelectionKind) => void
  setMode: (mode: 'view' | 'edit') => void
  setEditDirty: (dirty: boolean) => void
}

export const useUiStore = create<UiState>((set, get) => ({
  activeTab: 'party',
  setActiveTab: (tab) => set({ activeTab: tab }),

  selection: null,
  everSelected: false,
  mode: 'view',
  modeMemory: {},
  editDirty: false,

  select: (sel) => {
    const prev = get().selection
    const prevKey = prev ? (prev.kind === 'player' ? 'player' : `${prev.kind}:${'id' in prev ? prev.id : ''}`) : null
    const currentMode = get().mode

    if (prevKey) {
      set((s) => ({ modeMemory: { ...s.modeMemory, [prevKey]: currentMode } }))
    }

    const newKey = sel ? (sel.kind === 'player' ? 'player' : `${sel.kind}:${'id' in sel ? sel.id : ''}`) : null
    const remembered = newKey ? get().modeMemory[newKey] : undefined

    set({
      selection: sel,
      everSelected: true,
      mode: remembered ?? 'view',
      editDirty: false,
    })
  },

  setMode: (mode) => set({ mode }),
  setEditDirty: (dirty) => set({ editDirty: dirty }),
}))
```

- [ ] **Step 2: Create `IconRail.tsx`**

Six vertically stacked icon buttons. Use simple SVG icons or Unicode glyphs with Cinzel font for the decorative ones. Active tab gets a gold left-border accent and brighter icon color.

```
Scene (image icon), Party (diamond), Items (grid), Quests (star),
Lore (book), Config (gear)
```

Each button: `w-[66px] h-[52px]`, centered icon, `bg-bg1` background, `text-textdim` default, `text-gold` + `border-l-2 border-gold` when active.

- [ ] **Step 3: Rewrite `AppShell.tsx` to 4-column grid**

```tsx
export function AppShell({ iconRail, left, middle, right }: {
  iconRail: ReactNode
  left: ReactNode
  middle: ReactNode
  right: ReactNode
}) {
  return (
    <div className="grid h-full grid-cols-[66px_288px_minmax(0,1fr)_344px]">
      <nav className="flex flex-col overflow-hidden bg-bg1 border-r border-line">
        {iconRail}
      </nav>
      <aside className="flex flex-col overflow-y-auto bg-bg1 border-r border-line">
        {left}
      </aside>
      <main className="flex flex-col overflow-hidden bg-bg0">
        {middle}
      </main>
      <aside className="flex flex-col overflow-y-auto bg-bg1 border-l border-line">
        {right}
      </aside>
    </div>
  )
}
```

- [ ] **Step 4: Update `App.tsx` to wire the icon rail and tab-switched left panel**

For now, only `party` tab renders the existing `<PartyView />`. All other tabs render a placeholder `<div>` with the tab name. The Config tab triggers `setShowSettings(true)` and switches back to the previous tab.

- [ ] **Step 5: Update all existing components to use new color tokens**

Do a sweep of `PartyView.tsx`, `ChatScene.tsx`, `PartyInspector.tsx`, `PartyMemberEditor.tsx`, `CharacterSheetEditor.tsx`, `SettingsPanel.tsx`, `ConfirmDialog.tsx` — replace old token references (`bg-off`, `text-text`, `border-border`, `bg-white`, `text-text-sec`, `text-text-dim`, `font-h`, etc.) with the new tokens (`bg-bg1`, `text-text`, `border-line`, `bg-bg0`, `text-textsec`, `text-textdim`, `font-disp`, `font-ui`, etc.).

This is a mechanical find-and-replace. Each component file needs its own pass.

- [ ] **Step 6: Verify in browser**

Run dev server. Confirm: 4-column layout renders correctly, icon rail shows 6 tabs with correct active state, clicking tabs switches left panel, Party tab still shows the roster, clicking a character still loads inspector, chat still works, dark/gold aesthetic throughout.

- [ ] **Step 7: Commit**

```bash
git add client/src/components/Layout/AppShell.tsx client/src/components/IconRail/IconRail.tsx client/src/state/uiStore.ts client/src/App.tsx
git add client/src/components/PartyView/PartyView.tsx client/src/components/Scene/ChatScene.tsx client/src/components/Inspector/PartyInspector.tsx client/src/components/PartyMember/PartyMemberEditor.tsx client/src/components/CharacterSheet/CharacterSheetEditor.tsx client/src/components/Settings/SettingsPanel.tsx client/src/components/ConfirmDialog.tsx
git commit -m "feat: four-pane icon-rail layout with dark/gold visual system"
```

---

### Task 1.3: Inspector View/Edit Pattern

**Files:**
- Modify: `client/src/components/Inspector/PartyInspector.tsx`
- Modify: `client/src/components/CharacterSheet/CharacterSheetEditor.tsx`
- Modify: `client/src/components/PartyMember/PartyMemberEditor.tsx`

**Interfaces:**
- Consumes: `useUiStore` (mode, modeMemory, editDirty, everSelected, selection)
- Produces: Inspector header with View/Edit toggle button and unsaved-changes dot
- Produces: Character sheet components that accept `mode: 'view' | 'edit'` and render read-only or editable accordingly

- [ ] **Step 1: Add View/Edit toggle to inspector header**

In `PartyInspector.tsx`, add a header bar with:
- Entity name (from selected character's basicInfo.name)
- A toggle button: "VIEW" / "EDIT" — calls `useUiStore.setMode()`
- A small gold dot indicator when `editDirty` is true
- Gate all content on `everSelected` — show an empty state ("Select something to inspect") when false

- [ ] **Step 2: Update CharacterSheetEditor to support view mode**

When `mode === 'view'`: render all fields as read-only styled text (name as Cinzel header, description as body paragraph, equipment as a slot grid with item names or "Empty"). When `mode === 'edit'`: render as form inputs (current behavior). Remove the `attributes` section entirely — the spec removes numeric stats for alpha.

- [ ] **Step 3: Update PartyMemberEditor to support view mode**

Same pattern as CharacterSheetEditor, plus Field Skill section (view: styled name + description text; edit: inputs). Remove attributes section.

- [ ] **Step 4: Wire dirty tracking**

When in edit mode, any field change calls `setEditDirty(true)`. On successful save, call `setEditDirty(false)`.

- [ ] **Step 5: Verify**

Click a character → inspector shows View mode. Toggle to Edit → fields become inputs. Change something → gold dot appears. Save → dot disappears. Switch to another character and back → mode is remembered.

- [ ] **Step 6: Commit**

```bash
git add client/src/components/Inspector/PartyInspector.tsx client/src/components/CharacterSheet/CharacterSheetEditor.tsx client/src/components/PartyMember/PartyMemberEditor.tsx
git commit -m "feat: inspector View/Edit toggle with mode persistence and dirty indicator"
```

---

### Task 1.4: Remove Attributes from Data Model

**Files:**
- Modify: `shared/types/models.ts` — remove `AttributeBlock`, remove `attributes` from `PlayerCharacter` and `PartyMember`
- Modify: `server/db/models.py` — remove `attributes` column from both models
- Modify: `server/db/seed.py` — remove attributes from seed data
- Modify: `server/api/schemas.py` — remove `AttributeBlockSchema` and `attributes` from PC/PM schemas
- Modify: `server/api/routes.py` — remove any attribute handling
- Modify: `server/ai/prompt_builder.py` — remove attributes from PC/party summaries

**Interfaces:**
- Produces: Cleaned data model matching CLAUDE.md spec (BasicInfo + Equipment + FieldSkill only)

- [ ] **Step 1: Remove `AttributeBlock` from `shared/types/models.ts`**

Delete the `AttributeBlock` interface. Remove `attributes: AttributeBlock` from both `PlayerCharacter` and `PartyMember`.

- [ ] **Step 2: Remove `attributes` column from `server/db/models.py`**

Delete the `attributes: Mapped[dict]` line from both `PlayerCharacter` and `PartyMember` classes.

- [ ] **Step 3: Update `server/db/seed.py`**

Remove all `attributes={...}` arguments from the `PlayerCharacter()` and `PartyMember()` constructors. Remove the `DEFAULT_ATTRIBUTES` constant.

- [ ] **Step 4: Update `server/api/schemas.py`**

Remove `AttributeBlockSchema`. Remove `attributes` field from `PlayerCharacterUpdate`, `PlayerCharacterResponse`, `PartyMemberCreate`, `PartyMemberUpdate`, `PartyMemberResponse`.

- [ ] **Step 5: Update `server/ai/prompt_builder.py`**

Remove the attributes line from the PC summary (the `f"Attributes: STR {pc_attrs.get(...)}..."` line). Remove `pc_attrs = player_character.attributes`.

- [ ] **Step 6: Delete and recreate database**

Delete `wayward.db` so it re-seeds without the attributes column on next server start.

- [ ] **Step 7: Verify**

Start server — tables create, seed runs. Start client — characters load without attributes. Edit a character — saves correctly.

- [ ] **Step 8: Commit**

```bash
git add shared/types/models.ts server/db/models.py server/db/seed.py server/api/schemas.py server/api/routes.py server/ai/prompt_builder.py
git commit -m "refactor: remove numeric attributes from character data model per alpha spec"
```

---

## Phase 2: Item Catalog & Inventory System

The foundation for everything else — quests reference items, lorebook has an Items category, equipment slots reference catalog entries, Narrator actions grant catalog items. This must land before Quests, Lorebook, or Narrator Actions.

### Task 2.1: Item & Inventory Data Models (Server)

**Files:**
- Modify: `shared/types/models.ts` — add `ItemType`, `Rarity`, `ItemCatalogEntry`, `InventoryStack`
- Modify: `server/db/models.py` — add `ItemCatalogEntry`, `InventoryStack` tables
- Modify: `server/api/schemas.py` — add Pydantic schemas
- Modify: `server/db/seed.py` — add seed item catalog

**Interfaces:**
- Produces: `ItemCatalogEntry` model (id, name, type, slot, maxStack, uses, rarity, desc)
- Produces: `InventoryStack` model (id, item_id FK, count)
- Produces: Pydantic schemas for API serialization
- Produces: Seed catalog with ~15–20 items covering all types and the items already referenced in equipment/scenario

- [ ] **Step 1: Add TypeScript types to `shared/types/models.ts`**

```typescript
export type ItemType = 'Equipment' | 'Tool' | 'Consumable' | 'Key Item' | 'Artifact' | 'Other'
export type Rarity = 'c' | 'u' | 'r' | 'e' | 'l'

export interface ItemCatalogEntry {
  id: string
  kind: 'item'
  name: string
  type: ItemType
  slot?: string
  maxStack?: number
  uses?: number
  rarity: Rarity
  desc: string
}

export interface InventoryStack {
  itemId: string
  count: number
}
```

Also update `Equipment` interface — all slot fields become `string | null` instead of `string`:

```typescript
export interface Equipment {
  head: string | null
  neck: string | null
  torsoOver: string | null
  // ... all 12 slots, all `string | null`
}
```

- [ ] **Step 2: Add SQLAlchemy models to `server/db/models.py`**

```python
class ItemCatalogEntry(Base):
    __tablename__ = "item_catalog"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)  # Equipment|Tool|Consumable|Key Item|Artifact|Other
    slot: Mapped[str | None] = mapped_column(String, nullable=True)
    max_stack: Mapped[int] = mapped_column(Integer, default=1)
    uses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rarity: Mapped[str] = mapped_column(String, default="c")  # c|u|r|e|l
    desc: Mapped[str] = mapped_column(Text, default="")


class InventoryStack(Base):
    __tablename__ = "inventory_stacks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_id: Mapped[str] = mapped_column(String, nullable=False)  # ItemCatalogEntry.id
    count: Mapped[int] = mapped_column(Integer, default=1)
```

- [ ] **Step 3: Add Pydantic schemas to `server/api/schemas.py`**

```python
class ItemCatalogEntrySchema(BaseModel):
    id: str
    kind: str = "item"
    name: str
    type: str
    slot: str | None = None
    maxStack: int = 1
    uses: int | None = None
    rarity: str = "c"
    desc: str = ""

class ItemCatalogCreate(BaseModel):
    name: str
    type: str
    slot: str | None = None
    maxStack: int = 1
    uses: int | None = None
    rarity: str = "c"
    desc: str = ""

class ItemCatalogUpdate(BaseModel):
    name: str | None = None
    type: str | None = None
    slot: str | None = None
    maxStack: int | None = None
    uses: int | None = None
    rarity: str | None = None
    desc: str | None = None

class InventoryStackSchema(BaseModel):
    itemId: str
    count: int

class InventoryAddRequest(BaseModel):
    itemId: str
    count: int = 1

class InventoryRemoveRequest(BaseModel):
    itemId: str
    count: int = 1
```

- [ ] **Step 4: Add seed item catalog to `server/db/seed.py`**

Seed items that already appear in the prototype equipment + a handful more for gameplay variety. Must include at minimum:

- **Equipment items** matching what Seraphine/Tifa/Rosalina have equipped: Worn Lute (rightHand), Traveler's Cloak (torsoOver), Premium Leather Gloves (leftHand/rightHand), Steel-Toed Boots (feet), Celestial Gown (torsoOver), Star Wand (rightHand)
- **Consumable/Tool items** for gameplay: Tide-Salt Draught (consumable, stack 5), Moonstone Lantern (tool), Healer's Pouch (tool), Starlight Vial (consumable, stack 3)
- **Key Items**: Observatory Key, Ancient Sigil Fragment
- **A few more Equipment items**: Iron Helm (head), Leather Belt (waist), Silver Pendant (neck), Wool Leggings (legsOver), Travel Boots (feet)

After seeding catalog items, update seed characters' equipment to reference `ItemCatalogEntry.id` instead of free-text strings. This requires seeding catalog items first, then using their IDs in equipment dicts.

Also seed a few initial inventory stacks (e.g., 2x Tide-Salt Draught, 1x Moonstone Lantern).

- [ ] **Step 5: Update seed equipment to use item IDs**

Change `EMPTY_EQUIPMENT` values from `""` to `None`. Update Seraphine/Tifa/Rosalina's equipment dicts to use the IDs of the catalog items seeded in step 4.

- [ ] **Step 6: Delete `wayward.db`, restart server, verify tables create and seed**

- [ ] **Step 7: Commit**

```bash
git add shared/types/models.ts server/db/models.py server/api/schemas.py server/db/seed.py
git commit -m "feat: item catalog and inventory data models with seed catalog"
```

---

### Task 2.2: Item & Inventory API Routes

**Files:**
- Modify: `server/api/routes.py` — add item catalog CRUD + inventory management endpoints

**Interfaces:**
- Consumes: `ItemCatalogEntry`, `InventoryStack` models; Pydantic schemas from Task 2.1
- Produces: REST endpoints:
  - `GET /items` — list all catalog items (with optional `?type=` filter)
  - `GET /items/{id}` — single item
  - `POST /items` — create catalog entry
  - `PUT /items/{id}` — update catalog entry
  - `DELETE /items/{id}` — delete catalog entry
  - `GET /items/search?q=` — search by name (>=3 chars)
  - `GET /inventory` — list party inventory stacks (joined with item details)
  - `POST /inventory/add` — add item to inventory (stacking + capacity check)
  - `POST /inventory/remove` — remove item from inventory (decrement or delete stack)
  - `GET /inventory/capacity` — returns `{ used: N, max: M }`

- [ ] **Step 1: Add catalog CRUD routes**

```python
@router.get("/items")
async def list_items(type: str | None = None, session = Depends(get_session)):
    query = select(ItemCatalogEntry)
    if type:
        query = query.where(ItemCatalogEntry.type == type)
    items = (await session.execute(query)).scalars().all()
    return [_item_to_dict(i) for i in items]

@router.get("/items/search")
async def search_items(q: str, session = Depends(get_session)):
    if len(q) < 3:
        return []
    items = (await session.execute(
        select(ItemCatalogEntry).where(ItemCatalogEntry.name.ilike(f"%{q}%"))
    )).scalars().all()
    return [_item_to_dict(i) for i in items]

@router.get("/items/{item_id}")
async def get_item(item_id: str, session = Depends(get_session)): ...

@router.post("/items")
async def create_item(data: ItemCatalogCreate, session = Depends(get_session)): ...

@router.put("/items/{item_id}")
async def update_item(item_id: str, data: ItemCatalogUpdate, session = Depends(get_session)): ...

@router.delete("/items/{item_id}")
async def delete_item(item_id: str, session = Depends(get_session)): ...
```

- [ ] **Step 2: Add inventory management routes**

```python
MAX_CARRY_SLOTS_DEFAULT = 12

@router.get("/inventory")
async def list_inventory(session = Depends(get_session)):
    stacks = (await session.execute(select(InventoryStack))).scalars().all()
    result = []
    for s in stacks:
        item = await session.get(ItemCatalogEntry, s.item_id)
        result.append({"itemId": s.item_id, "count": s.count, "item": _item_to_dict(item) if item else None})
    return result

@router.post("/inventory/add")
async def add_to_inventory(data: InventoryAddRequest, session = Depends(get_session)):
    item = await session.get(ItemCatalogEntry, data.itemId)
    if not item:
        raise HTTPException(404, "Item not in catalog")

    existing = (await session.execute(
        select(InventoryStack).where(InventoryStack.item_id == data.itemId)
    )).scalars().first()

    if existing:
        new_count = existing.count + data.count
        if item.max_stack > 1 and new_count > item.max_stack:
            raise HTTPException(400, f"Exceeds max stack of {item.max_stack}")
        existing.count = new_count
    else:
        # Check carry capacity
        total_stacks = (await session.execute(select(func.count()).select_from(InventoryStack))).scalar()
        settings = await session.get(OpenRouterSettings, 1)
        max_slots = getattr(settings, 'max_carry_slots', MAX_CARRY_SLOTS_DEFAULT)
        if total_stacks >= max_slots:
            raise HTTPException(400, "Inventory full — no carry slots remaining")
        session.add(InventoryStack(item_id=data.itemId, count=data.count))

    await session.commit()
    return {"ok": True}

@router.post("/inventory/remove")
async def remove_from_inventory(data: InventoryRemoveRequest, session = Depends(get_session)):
    existing = (await session.execute(
        select(InventoryStack).where(InventoryStack.item_id == data.itemId)
    )).scalars().first()
    if not existing:
        raise HTTPException(404, "Item not in inventory")
    existing.count -= data.count
    if existing.count <= 0:
        await session.delete(existing)
    await session.commit()
    return {"ok": True}
```

- [ ] **Step 3: Add `max_carry_slots` to `OpenRouterSettings` model**

Add `max_carry_slots: Mapped[int] = mapped_column(Integer, default=12)` to the `OpenRouterSettings` model in `models.py`. Add the field to the settings schemas and the settings GET/PUT routes.

- [ ] **Step 4: Add helper function for item serialization**

```python
def _item_to_dict(item: ItemCatalogEntry) -> dict:
    return {
        "id": item.id, "kind": "item", "name": item.name,
        "type": item.type, "slot": item.slot, "maxStack": item.max_stack,
        "uses": item.uses, "rarity": item.rarity, "desc": item.desc,
    }
```

- [ ] **Step 5: Update adventure export/import to include items and inventory**

In the `/adventure/export` route, add `items` (full catalog) and `inventory` (all stacks) to the export JSON. In `/adventure/import`, restore them. In `/adventure/reset`, clear both tables and re-seed.

- [ ] **Step 6: Verify with curl/httpie**

Test: create an item, search, add to inventory, check capacity, remove, export includes items.

- [ ] **Step 7: Commit**

```bash
git add server/api/routes.py server/db/models.py server/api/schemas.py
git commit -m "feat: item catalog CRUD and inventory management API routes"
```

---

### Task 2.3: Items Zustand Store & Left Panel UI

**Files:**
- Create: `client/src/state/itemsStore.ts`
- Create: `client/src/components/ItemsPanel/ItemsPanel.tsx`
- Modify: `client/src/App.tsx` — wire Items tab to `<ItemsPanel />`
- Modify: `client/src/components/Inspector/PartyInspector.tsx` — add item inspection branch

**Interfaces:**
- Consumes: Item/Inventory API routes from Task 2.2
- Consumes: `useUiStore` selection/tab state from Task 1.2
- Produces: `useItemsStore` with catalog, inventory, add/remove/search methods
- Produces: `<ItemsPanel />` — left panel Items tab with inventory list, search-to-add flow, carry capacity bar
- Produces: Item detail view in Inspector (View/Edit modes)

- [ ] **Step 1: Create `itemsStore.ts`**

```typescript
import { create } from 'zustand'
import { api } from '../lib/api'
import type { ItemCatalogEntry, InventoryStack } from '@shared/types/models'

interface InventoryStackWithItem extends InventoryStack {
  item?: ItemCatalogEntry
}

interface ItemsState {
  catalog: ItemCatalogEntry[]
  inventory: InventoryStackWithItem[]
  maxCarrySlots: number
  searchResults: ItemCatalogEntry[]

  fetchCatalog: () => Promise<void>
  fetchInventory: () => Promise<void>
  searchItems: (q: string) => Promise<void>
  clearSearch: () => void
  addToInventory: (itemId: string, count?: number) => Promise<void>
  removeFromInventory: (itemId: string, count?: number) => Promise<void>
  createItem: (data: Omit<ItemCatalogEntry, 'id' | 'kind'>) => Promise<void>
  updateItem: (id: string, data: Partial<ItemCatalogEntry>) => Promise<void>
  deleteItem: (id: string) => Promise<void>
}
```

Implement each method calling the corresponding API route from Task 2.2.

- [ ] **Step 2: Create `ItemsPanel.tsx`**

Layout:
- Header: "INVENTORY" label + carry capacity counter (`3 / 12`)
- Inventory list: each stack shows item name, count (if >1), rarity dot, type badge
- Clicking a stack selects it in the inspector via `useUiStore.select({ kind: 'item', id })`
- Divider
- "ADD ITEM" section: search input (shows "Type to search..." until >=3 chars), results dropdown, quantity picker (only if maxStack > 1), confirm button
- Search calls `useItemsStore.searchItems(q)`, results come from `searchResults`

Style with new tokens: `bg-bg1`, `text-text`, gold accents on interactive elements, `font-ui` for labels.

- [ ] **Step 3: Add item detail branch in Inspector**

When `selection.kind === 'item'`, render an item detail view showing: name, type badge, rarity badge, slot (if equipment), maxStack, uses, description. In Edit mode: all fields editable, Save/Delete buttons.

- [ ] **Step 4: Wire Items tab in `App.tsx`**

In the tab-switch logic, render `<ItemsPanel />` when `activeTab === 'items'`. Add `fetchCatalog()` and `fetchInventory()` to the initial data fetch in `useEffect`.

- [ ] **Step 5: Verify**

Open Items tab → inventory displays with correct counts. Search for an item → results appear after 3 chars. Add an item → inventory updates, capacity counter changes. Click an inventory item → inspector shows detail. Edit and save → persists.

- [ ] **Step 6: Commit**

```bash
git add client/src/state/itemsStore.ts client/src/components/ItemsPanel/ItemsPanel.tsx client/src/App.tsx client/src/components/Inspector/PartyInspector.tsx
git commit -m "feat: items panel with inventory management and catalog search"
```

---

### Task 2.4: Equipment Slots Reference Catalog Items

**Files:**
- Modify: `client/src/components/CharacterSheet/CharacterSheetEditor.tsx`
- Modify: `client/src/components/PartyMember/PartyMemberEditor.tsx`
- Modify: `server/ai/prompt_builder.py` — resolve item IDs to names in equipment summary

**Interfaces:**
- Consumes: `useItemsStore.catalog` for item name lookups
- Produces: Equipment section shows item names resolved from catalog IDs
- Produces: Equipment edit mode uses a search-to-equip flow (search catalog filtered to Equipment type with matching slot)

- [ ] **Step 1: Update equipment display in View mode**

For each slot, look up `catalog.find(i => i.id === slotValue)` to get the item name. Show name + rarity dot. Show "Empty" for null slots.

- [ ] **Step 2: Update equipment editing in Edit mode**

Each slot gets a search input. Typing searches catalog items filtered to `type === 'Equipment'` with compatible `slot`. Selecting an item sets that slot to the item's ID. A clear button sets it to null.

- [ ] **Step 3: Update `prompt_builder.py` to resolve equipment IDs**

The prompt builder currently reads equipment values as strings. Add a parameter `item_catalog: list[ItemCatalogEntry]` to `build_prompt()`. When building the "Carrying: ..." line, resolve each equipment slot value from an ID to the item's name via the catalog. Non-null values that don't resolve should fall back to displaying the raw value (backwards compat during transition).

- [ ] **Step 4: Update the route that calls `build_prompt` to pass the catalog**

In `routes.py`, load all `ItemCatalogEntry` rows alongside other game context and pass them to `build_prompt()`.

- [ ] **Step 5: Verify**

Characters show item names in equipment slots. Editing a slot searches the catalog. Prompt log shows resolved item names.

- [ ] **Step 6: Commit**

```bash
git add client/src/components/CharacterSheet/CharacterSheetEditor.tsx client/src/components/PartyMember/PartyMemberEditor.tsx server/ai/prompt_builder.py server/api/routes.py
git commit -m "feat: equipment slots reference catalog items with search-to-equip flow"
```

---

## Phase 3: Quest System

### Task 3.1: Quest Data Model & API

**Files:**
- Modify: `shared/types/models.ts` — add `QuestObjective`, `Quest`
- Modify: `server/db/models.py` — add `Quest`, `QuestObjective` tables
- Modify: `server/api/schemas.py` — add quest Pydantic schemas
- Modify: `server/api/routes.py` — add quest CRUD routes
- Modify: `server/db/seed.py` — add seed quests

**Interfaces:**
- Produces: `Quest` model (id, title, status, desc, notes, relatedLore[])
- Produces: `QuestObjective` model (id, quest_id, text, done)
- Produces: REST endpoints: `GET/POST /quests`, `GET/PUT/DELETE /quests/{id}`, `POST /quests/{id}/objectives`, `PUT /quests/{id}/objectives/{oid}`, `DELETE /quests/{id}/objectives/{oid}`

- [ ] **Step 1: Add TypeScript types**

```typescript
export interface QuestObjective {
  id: string
  text: string
  done: boolean
}

export interface Quest {
  id: string
  title: string
  status: 'active' | 'completed' | 'failed'
  desc: string
  objectives: QuestObjective[]
  notes: string
  relatedLore: string[]
}
```

- [ ] **Step 2: Add SQLAlchemy models**

```python
class Quest(Base):
    __tablename__ = "quests"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default="active")
    desc: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    related_lore: Mapped[list] = mapped_column(JSON, default=list)

class QuestObjective(Base):
    __tablename__ = "quest_objectives"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    quest_id: Mapped[str] = mapped_column(String, nullable=False)
    text: Mapped[str] = mapped_column(String, default="")
    done: Mapped[bool] = mapped_column(Integer, default=False)  # SQLite uses int for bool
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
```

- [ ] **Step 3: Add Pydantic schemas and API routes**

Full CRUD for quests and objectives. Quest GET returns objectives nested. Seed 2–3 quests with objectives.

- [ ] **Step 4: Add quest summaries to prompt builder**

Add `quests: list[Quest]` parameter to `build_prompt()`. Insert active quest summary (title + open objectives) as a system message after the party inventory summary (prompt assembly step 6). Load quests in the route's `_load_game_context()`.

- [ ] **Step 5: Update adventure export/import/reset for quests**

- [ ] **Step 6: Verify**

curl CRUD operations work. Prompt log includes active quest summaries.

- [ ] **Step 7: Commit**

```bash
git add shared/types/models.ts server/db/models.py server/api/schemas.py server/api/routes.py server/db/seed.py server/ai/prompt_builder.py
git commit -m "feat: quest system data model and API with prompt integration"
```

---

### Task 3.2: Quests Zustand Store & UI Panel

**Files:**
- Create: `client/src/state/questsStore.ts`
- Create: `client/src/components/QuestsPanel/QuestsPanel.tsx`
- Modify: `client/src/App.tsx` — wire Quests tab
- Modify: `client/src/components/Inspector/PartyInspector.tsx` — add quest inspection branch

**Interfaces:**
- Consumes: Quest API from Task 3.1; `useUiStore` from Task 1.2
- Produces: `useQuestsStore` — quests CRUD, objective toggling
- Produces: `<QuestsPanel />` — left panel with active/completed quest list, inline new-quest input
- Produces: Quest detail in Inspector — objectives, notes, related lore, status toggle

- [ ] **Step 1: Create `questsStore.ts`**

Methods: fetchQuests, createQuest, updateQuest, deleteQuest, addObjective, updateObjective, deleteObjective.

- [ ] **Step 2: Create `QuestsPanel.tsx`**

- Header: "QUESTS" label
- "Active" section: list of active quests, each clickable to inspect
- "Completed / Failed" section (collapsible): list of non-active quests
- Inline "New Quest" input at bottom — type title, press Enter to create
- Each quest shows title + objective completion count (e.g., "2/4")

- [ ] **Step 3: Add quest inspection branch in Inspector**

View mode: title (Cinzel), status badge (gold = active, dim = completed/failed), description, objectives as a checklist (checkboxes toggle `done`), notes text, related lore as clickable chips.

Edit mode: all fields editable, add/remove objectives, status dropdown, notes textarea, related lore toggle list.

- [ ] **Step 4: Wire in App.tsx, fetch on mount**

- [ ] **Step 5: Verify**

Create a quest, add objectives, toggle them, link lore (will show IDs for now — lore entries added in Phase 4). Inspector shows detail, persists edits.

- [ ] **Step 6: Commit**

```bash
git add client/src/state/questsStore.ts client/src/components/QuestsPanel/QuestsPanel.tsx client/src/App.tsx client/src/components/Inspector/PartyInspector.tsx
git commit -m "feat: quests panel with objectives, status, and inspector detail"
```

---

## Phase 4: Lorebook System

### Task 4.1: Lorebook Data Model, API & Injection Logic

**Files:**
- Modify: `shared/types/models.ts` — add `LoreCategory`, `LorebookEntry`, `LorebookConfig`
- Modify: `server/db/models.py` — add `LorebookEntry`, `LorebookConfig` tables
- Modify: `server/api/schemas.py` — add lorebook Pydantic schemas
- Modify: `server/api/routes.py` — add lorebook CRUD + config routes
- Create: `server/ai/lore_injector.py` — keyword matching + injection logic
- Modify: `server/ai/prompt_builder.py` — integrate lore injection at three positions
- Modify: `server/db/seed.py` — seed lorebook entries across categories

**Interfaces:**
- Produces: `LorebookEntry` model (id, title, content, keywords[], enabled, permanent, cat)
- Produces: `LorebookConfig` model (injection_order per category, injection_position per category)
- Produces: `lore_injector.match_entries(message, entries) -> list[LorebookEntry]`
- Produces: `lore_injector.group_by_position(matched, config) -> dict[position, list[LorebookEntry]]`
- Produces: REST endpoints: `GET/POST /lore`, `GET/PUT/DELETE /lore/{id}`, `GET/PUT /lore/config`, `GET /lore?cat=world`
- Produces: Prompt builder inserts matched lore at top/before_input/bottom positions

- [ ] **Step 1: Add TypeScript types**

```typescript
export type LoreCategory = 'world' | 'characters' | 'items' | 'monsters' | 'spells'

export interface LorebookEntry {
  id: string
  title: string
  content: string
  keywords: string[]
  enabled: boolean
  permanent: boolean
  cat: LoreCategory
}

export interface LorebookConfig {
  injectionOrder: Record<LoreCategory, number>
  injectionPosition: Record<LoreCategory, 'top' | 'bottom' | 'before_input'>
}
```

- [ ] **Step 2: Add SQLAlchemy models**

```python
class LorebookEntry(Base):
    __tablename__ = "lorebook_entries"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String, default="")
    content: Mapped[str] = mapped_column(Text, default="")
    keywords: Mapped[list] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(Integer, default=True)
    permanent: Mapped[bool] = mapped_column(Integer, default=False)
    cat: Mapped[str] = mapped_column(String, default="world")

class LorebookConfig(Base):
    __tablename__ = "lorebook_config"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    injection_order: Mapped[dict] = mapped_column(JSON, default=lambda: {"world": 0, "characters": 10, "items": 20, "monsters": 30, "spells": 40})
    injection_position: Mapped[dict] = mapped_column(JSON, default=lambda: {"world": "top", "characters": "top", "items": "top", "monsters": "top", "spells": "top"})
```

- [ ] **Step 3: Create `lore_injector.py`**

```python
def match_entries(player_message: str, entries: list[LorebookEntry]) -> list[LorebookEntry]:
    """Return all entries that match: permanent=True OR any keyword appears in message (case-insensitive)."""
    matched = []
    msg_lower = player_message.lower()
    for entry in entries:
        if not entry.enabled:
            continue
        if entry.permanent:
            matched.append(entry)
            continue
        for kw in entry.keywords:
            if kw.lower() in msg_lower:
                matched.append(entry)
                break
    return matched

def group_by_position(matched: list[LorebookEntry], config: LorebookConfig) -> dict[str, list[LorebookEntry]]:
    """Group matched entries by their category's injection position, sorted by injection order."""
    groups: dict[str, list[LorebookEntry]] = {"top": [], "before_input": [], "bottom": []}
    order = config.injection_order
    position = config.injection_position
    for entry in matched:
        pos = position.get(entry.cat, "top")
        groups[pos].append(entry)
    for pos in groups:
        groups[pos].sort(key=lambda e: order.get(e.cat, 50))
    return groups

def format_lore_block(entries: list[LorebookEntry]) -> str:
    """Format matched entries into a single text block for prompt injection."""
    lines = ["LOREBOOK ENTRIES:"]
    for e in entries:
        lines.append(f"[{e.cat.upper()}] {e.title}: {e.content}")
    return "\n".join(lines)
```

- [ ] **Step 4: Integrate into `prompt_builder.py`**

Add parameters: `lore_entries: list[LorebookEntry]`, `lore_config: LorebookConfig`. Call `match_entries` and `group_by_position`. Insert `top` entries after step 7 (spotlight), `before_input` entries before the player message, `bottom` entries after the player message.

- [ ] **Step 5: Add API routes and Pydantic schemas**

Full CRUD for lorebook entries. GET supports `?cat=world` filter. GET/PUT for lorebook config. Seed ~8–10 entries across all five categories.

- [ ] **Step 6: Update `_load_game_context()` in routes.py to load lore entries and config, pass to prompt builder**

- [ ] **Step 7: Update adventure export/import/reset**

- [ ] **Step 8: Verify**

Create entries with keywords. Send a chat message containing a keyword. Check prompt log — matched entry appears at configured position.

- [ ] **Step 9: Commit**

```bash
git add shared/types/models.ts server/db/models.py server/api/schemas.py server/api/routes.py server/ai/lore_injector.py server/ai/prompt_builder.py server/db/seed.py
git commit -m "feat: lorebook system with keyword matching and prompt injection"
```

---

### Task 4.2: Lorebook Zustand Store & UI Panel

**Files:**
- Create: `client/src/state/loreStore.ts`
- Create: `client/src/components/LorePanel/LorePanel.tsx`
- Modify: `client/src/App.tsx` — wire Lore tab
- Modify: `client/src/components/Inspector/PartyInspector.tsx` — add lore inspection branch

**Interfaces:**
- Consumes: Lore API from Task 4.1; `useUiStore` from Task 1.2
- Produces: `useLoreStore` — entries CRUD, config, per-category fetch/search
- Produces: `<LorePanel />` — 5 sub-tabs (World/Characters/Items/Monsters/Spells), search per category, entry list
- Produces: Lore detail in Inspector — title, content, keywords as tag pills, enabled/permanent toggles

- [ ] **Step 1: Create `loreStore.ts`**

State: entries (all), activeCategory, searchQuery, config. Methods: fetchEntries, fetchConfig, createEntry, updateEntry, deleteEntry, saveConfig, setCategory, search.

- [ ] **Step 2: Create `LorePanel.tsx`**

- Header: "LOREBOOK" label
- 5 sub-tab buttons: World / Characters / Items / Monsters / Spells — styled as small horizontal pills, active one highlighted gold
- Search input below sub-tabs (filters entries in active category by title/keywords)
- Entry list: each shows title + keyword count + enabled dot. Clicking selects for inspector.
- "+ NEW ENTRY" button at bottom — creates entry in active category with blank fields

- [ ] **Step 3: Add lore inspection in Inspector**

View mode: title (Cinzel), category badge, content text, keywords as small gold pills, enabled/permanent status indicators.

Edit mode: title input, content textarea, keywords as editable tag input (type + Enter to add, click X to remove), enabled checkbox, permanent checkbox, category dropdown.

- [ ] **Step 4: Wire quest related-lore linking**

Now that lore entries exist, update the quest inspector's related-lore section: in View mode show lore entry titles as clickable chips (clicking jumps to that lore entry in the inspector). In Edit mode show a toggle list of all lore entries.

- [ ] **Step 5: Wire in App.tsx, fetch on mount**

- [ ] **Step 6: Verify**

Create lore entries across categories, search, edit keywords, toggle enabled/permanent. Link a lore entry to a quest. Send a chat message with a keyword — check prompt log for injection.

- [ ] **Step 7: Commit**

```bash
git add client/src/state/loreStore.ts client/src/components/LorePanel/LorePanel.tsx client/src/App.tsx client/src/components/Inspector/PartyInspector.tsx
git commit -m "feat: lorebook panel with five category sub-tabs, search, and inspector detail"
```

---

## Phase 5: Chat Rendering & Message Interactions

### Task 5.1: Speaker-Differentiated Message Rendering

**Files:**
- Modify: `client/src/components/Scene/ChatScene.tsx`
- Modify: `server/api/routes.py` — return `speaker` info with messages
- Modify: `server/db/models.py` — add `speaker` field to ChatMessage
- Modify: `shared/types/models.ts` — update ChatMessage type

**Interfaces:**
- Consumes: Party store (character names, portraits), chat store (messages)
- Produces: Messages render differently by speaker type (Narrator, PC, Party Member) per CLAUDE.md spec
- Produces: Portrait avatars, name headers, prose color differentiation, drop-cap on first narrator message

- [ ] **Step 1: Add `speaker` field to ChatMessage model**

Add `speaker: Mapped[str] = mapped_column(String, default="narrator")` to the `ChatMessage` model. Values: `'narrator'`, player character ID, or party member ID. Update the chat turn route to set `speaker` on saved messages — user messages get the PC's ID, assistant messages get `'narrator'` initially, then update based on `detect_speakers()` output.

Update TypeScript `ChatMessage` type to include `speaker: string`.

- [ ] **Step 2: Implement speaker-differentiated rendering**

In `ChatScene.tsx`, replace the current flat message rendering with a `<ChatBubble>` component that renders differently based on speaker:

| Speaker | Avatar | Name header | Prose color |
|---|---|---|---|
| Narrator | None (except generating indicator) | None | `text-text2` |
| Player Character | Portrait box, `border-blue` | `"{Name} · You"`, `text-blue` | `text-text` |
| Party Member | Portrait box, `border-line2` | First name, `text-gold` | `text-text2` |

Portrait: 40×40px rounded box with the character's portrait image (or initials fallback). Use the existing portrait URL pattern (`/portraits/{filename}`).

- [ ] **Step 3: Add drop-cap on first Narrator message**

The very first `narrator` message in the history gets a large decorative first letter: Cinzel font, `text-gold`, `float-left`, `text-4xl`, `leading-none`, `mr-1`, `pt-1`. Apply via a CSS class on the first `<p>` of the first narrator message only.

- [ ] **Step 4: Add "What do you do?" divider**

After the most recent narrator message, when no user message follows, render a thin divider: `border-t border-line` with centered text "What do you do?" in `text-golddeep font-disp text-sm`. Hide it once the user starts typing.

- [ ] **Step 5: Add generating indicator**

While `isLoading`, show a placeholder narrator-style avatar ("N" in a gold circle) with animated dots. This replaces any current loading indicator.

- [ ] **Step 6: Verify**

Send a message. Narrator response renders without avatar, dimmer text. Player messages show portrait + blue name. Party member responses (when spotlight triggers) show portrait + gold name. First narrator message has drop-cap. Divider appears after narrator response.

- [ ] **Step 7: Commit**

```bash
git add client/src/components/Scene/ChatScene.tsx server/db/models.py server/api/routes.py shared/types/models.ts
git commit -m "feat: speaker-differentiated chat rendering with avatars, drop-cap, and divider"
```

---

### Task 5.2: Spotlight Badges & Inline Item Chips

**Files:**
- Modify: `client/src/components/Scene/ChatScene.tsx`
- Modify: `server/api/routes.py` — return spotlight reason with party member messages

**Interfaces:**
- Consumes: Spotlight signals (from server), item catalog (from itemsStore)
- Produces: Small outlined badge next to party member name showing why they spoke
- Produces: Inline gold-tinted pill for item names mentioned in messages

- [ ] **Step 1: Return spotlight reason with messages**

When saving a party member's message, store the primary spotlight reason (directlyAddressed > fieldSkillRelevant > overdue) alongside the message. Add `spotlight_reason: Mapped[str | None]` to `ChatMessage` model. Set it in the chat turn route based on the computed signals.

Update TypeScript type: `spotlightReason?: string`.

- [ ] **Step 2: Render spotlight badge**

Next to a party member's name header, if `spotlightReason` is set, render a small outlined chip:
- "Directly addressed" — `border-gold text-gold`
- "Field skill · relevant" — `border-gold text-gold`
- "Hasn't spoken in a while" — `border-golddeep text-golddeep`

Style: `text-[10px] font-ui px-1.5 py-0.5 border rounded-full`

- [ ] **Step 3: Render inline item-reference chips**

After rendering message content, post-process the HTML: for each item in the catalog, case-insensitive string match against the message text. Wrap matches in a `<span className="text-gold2 bg-gold/10 px-1 rounded text-sm font-ui">` pill.

Use `useItemsStore.catalog` for the item name list. Apply to all message types (narrator and player).

- [ ] **Step 4: Verify**

Send a message addressing a party member by name → their response shows "Directly addressed" badge. Send a message mentioning a catalog item name → item chip renders inline.

- [ ] **Step 5: Commit**

```bash
git add client/src/components/Scene/ChatScene.tsx server/db/models.py server/api/routes.py shared/types/models.ts
git commit -m "feat: spotlight badges on party member messages and inline item-reference chips"
```

---

### Task 5.3: Complete Message Interactions (Edit, Delete, Swipe, Regenerate)

**Files:**
- Modify: `client/src/components/Scene/ChatScene.tsx`
- Modify: `client/src/state/chatStore.ts`

**Interfaces:**
- Consumes: Existing chat API routes (edit, delete-and-after, regenerate)
- Produces: Inline edit textarea (replaces message content, no variant)
- Produces: Delete-and-truncate confirmation (removes message + everything after)
- Produces: Per-message swipe controls (prev/next + "i/n" counter, generates new variant)
- Produces: Global regenerate button in input area (replaces last narrator response entirely)

- [ ] **Step 1: Wire inline message editing**

On hover over a message, show a small edit icon. Clicking it replaces the message text with a textarea pre-filled with current content. Enter submits (calls `chatStore.editMessage`), Escape cancels.

- [ ] **Step 2: Wire delete-and-truncate**

On hover, show a delete icon. Clicking opens the existing `ConfirmDialog` with "Delete this message and everything after it?". On confirm, call `chatStore.deleteMessageAndAfter`.

- [ ] **Step 3: Wire per-message swipe**

On hover over an assistant message, show swipe controls: left/right arrows + variant counter ("2 / 3"). Left/right call `chatStore.setActiveVariant`. A regenerate-on-this-message icon generates a new variant for this specific message (POST to a new `/chat/messages/{turn}/swipe` endpoint that creates a new variant). The new variant is appended; the counter updates.

Add the swipe endpoint server-side: takes the turn number, generates against the same context as that turn, saves as a new variant, streams response.

- [ ] **Step 4: Wire global regenerate**

In the input area (below the message list), add a regenerate button (refresh icon). Clicking calls `chatStore.regenerate()` — this replaces the last narrator response entirely (wipes variant history for that turn).

The regenerate button should be visible whenever the last message is from the narrator, or when the user has sent a message but no narrator response exists yet.

- [ ] **Step 5: Verify**

Edit a message → content updates, no new variant. Delete → message and all after removed. Swipe on narrator message → new variant generated, can browse between variants. Regenerate → last narrator response replaced.

- [ ] **Step 6: Commit**

```bash
git add client/src/components/Scene/ChatScene.tsx client/src/state/chatStore.ts server/api/routes.py
git commit -m "feat: complete message interactions — edit, delete-truncate, swipe, regenerate"
```

---

## Phase 6: Narrator Actions & Inventory Tracking

### Task 6.1: Narrator Action Block Parsing & Execution

**Files:**
- Create: `server/ai/narrator_actions.py`
- Modify: `server/api/routes.py` — parse action block from response, execute actions
- Modify: `server/ai/prompt_builder.py` — append action instruction block to prompt
- Modify: `server/db/models.py` — add `applied_inventory_deltas` and `applied_equipment_changes` to ChatMessage

**Interfaces:**
- Produces: `parse_action_block(raw_response) -> (clean_text, actions_dict | None)` — strips `<<<ACTIONS>>>...<<<END ACTIONS>>>`, returns clean prose + parsed JSON
- Produces: `execute_actions(actions, catalog, inventory, party_members) -> (inv_deltas, equip_changes)` — validates and applies actions, returns what changed
- Produces: Action instruction block appended to every prompt (after narrator instructions, not user-editable)

- [ ] **Step 1: Create `narrator_actions.py`**

```python
import json
import re

ACTION_BLOCK_RE = re.compile(r'<<<ACTIONS>>>\s*(.*?)\s*<<<END ACTIONS>>>', re.DOTALL)

def parse_action_block(raw_response: str) -> tuple[str, dict | None]:
    match = ACTION_BLOCK_RE.search(raw_response)
    if not match:
        return raw_response, None
    clean = raw_response[:match.start()].rstrip() + raw_response[match.end():]
    try:
        actions = json.loads(match.group(1))
    except json.JSONDecodeError:
        return clean, None
    return clean.strip(), actions

ACTION_INSTRUCTION = """
When your narration results in the party gaining or losing items, or a character equipping/unequipping something, append this block at the very end of your response:

<<<ACTIONS>>>
{
  "addItems": [{ "itemName": "Item Name", "count": 1 }],
  "equip": [{ "characterName": "Tifa", "slot": "rightHand", "itemName": "Comet Wand" }],
  "unequip": [{ "characterName": "Seraphine", "slot": "head" }]
}
<<<END ACTIONS>>>

Only include keys that apply. If nothing changes, do not include the block at all.
""".strip()
```

```python
async def execute_actions(
    actions: dict,
    session,  # async SQLAlchemy session
) -> tuple[list[dict], list[dict]]:
    """Execute parsed narrator actions. Returns (inventory_deltas, equipment_changes)."""
    inv_deltas = []
    equip_changes = []

    # addItems
    for add in actions.get("addItems", []):
        item_name = add.get("itemName", "")
        count = add.get("count", 1)
        # Resolve name -> catalog entry (case-insensitive exact match)
        item = (await session.execute(
            select(ItemCatalogEntry).where(func.lower(ItemCatalogEntry.name) == item_name.lower())
        )).scalars().first()
        if not item:
            continue  # silently drop unresolved names

        # Try add to inventory (same logic as POST /inventory/add)
        existing = (await session.execute(
            select(InventoryStack).where(InventoryStack.item_id == item.id)
        )).scalars().first()

        if existing:
            existing.count += count
        else:
            total = (await session.execute(select(func.count()).select_from(InventoryStack))).scalar()
            settings = await session.get(OpenRouterSettings, 1)
            max_slots = getattr(settings, 'max_carry_slots', 12)
            if total >= max_slots:
                continue  # inventory full, drop silently
            session.add(InventoryStack(item_id=item.id, count=count))

        inv_deltas.append({"itemId": item.id, "delta": count, "source": "narrator_grant"})

    # equip / unequip — similar pattern, resolve character by name, validate slot, swap
    # ... (full implementation follows same resolve-by-name, validate, apply pattern)

    return inv_deltas, equip_changes
```

- [ ] **Step 2: Integrate into chat turn route**

After receiving the full streamed response:
1. Call `parse_action_block(full_response)` → get clean text + actions
2. Save the clean text as the message content (not the raw response with the action block)
3. If actions exist, call `execute_actions(actions, session)`
4. Store `inv_deltas` and `equip_changes` on the ChatMessage (new JSON columns)
5. Commit

- [ ] **Step 3: Add `applied_inventory_deltas` and `applied_equipment_changes` columns to ChatMessage**

```python
applied_inventory_deltas: Mapped[list | None] = mapped_column(JSON, nullable=True)
applied_equipment_changes: Mapped[list | None] = mapped_column(JSON, nullable=True)
```

Update the ChatMessage TypeScript type to include these optional fields.

- [ ] **Step 4: Append action instruction to prompt**

In `build_prompt()`, after the narrator instructions system message, append `ACTION_INSTRUCTION` as a separate system message. This is not part of the user-editable narrator instructions.

- [ ] **Step 5: Verify**

Send a message that might trigger a narrator item grant (e.g., "I search the chest"). If the narrator includes an `<<<ACTIONS>>>` block: action block is stripped from displayed text, item appears in inventory, delta is recorded on the message.

- [ ] **Step 6: Commit**

```bash
git add server/ai/narrator_actions.py server/api/routes.py server/ai/prompt_builder.py server/db/models.py shared/types/models.ts
git commit -m "feat: narrator action block parsing and execution for item grants and equipment changes"
```

---

### Task 6.2: Deterministic Item-Use Detection & Inventory Notices

**Files:**
- Create: `server/ai/item_detection.py`
- Modify: `server/api/routes.py` — run detection on player messages
- Modify: `client/src/components/Scene/ChatScene.tsx` — render inventory-change and equipment-change notices

**Interfaces:**
- Consumes: Player message text, current inventory (from itemsStore/server)
- Produces: `detect_item_use(message, inventory_with_items) -> list[dict]` — deterministic scan
- Produces: Inventory delta applied before narrator response generation
- Produces: UI notice pills below narrator messages showing item changes

- [ ] **Step 1: Create `item_detection.py`**

```python
def detect_item_use(message: str, inventory: list[dict]) -> list[dict]:
    """Scan player message for item-use phrasing. Returns list of {itemId, delta, source}."""
    deltas = []
    msg_lower = message.lower()
    use_verbs = ["use", "drink", "eat", "consume", "apply", "throw", "pull out", "take out"]

    for stack in inventory:
        item_name = stack["item"]["name"].lower()
        if item_name not in msg_lower:
            continue
        for verb in use_verbs:
            if verb in msg_lower:
                deltas.append({
                    "itemId": stack["itemId"],
                    "delta": -1,
                    "source": "player_action",
                })
                break
    return deltas
```

- [ ] **Step 2: Integrate into chat turn route**

Before generating the narrator response:
1. Call `detect_item_use(player_message, inventory_stacks)`
2. Apply deltas to inventory
3. After narrator response, merge player deltas with any narrator-granted deltas
4. Store combined deltas on the narrator's ChatMessage

- [ ] **Step 3: Implement reversal on swipe/regenerate/delete**

Before swiping or regenerating a narrator message that has `applied_inventory_deltas`:
1. Reverse those deltas (negate each `delta`, apply)
2. Re-run detection against the same player message
3. Apply fresh deltas (idempotency guard)

On delete-and-truncate: reverse the most recent message's deltas, don't walk back older ones.

- [ ] **Step 4: Render inventory-change notice in ChatScene**

Below a narrator message that has `appliedInventoryDeltas`, render a pill row:
- "Inventory" label in `text-textsec font-ui text-xs`
- For each delta: item chip (gold pill with name) + signed count (`−1` in red-ish, `+1` in green-ish) + remaining count

- [ ] **Step 5: Render equipment-change notice**

Below a narrator message that has `appliedEquipmentChanges`, render a similar pill row:
- Character name + slot label + "before → after" item names

- [ ] **Step 6: Verify**

Send "I drink a Tide-Salt Draught" → inventory decrements, notice appears below narrator response. Swipe → reverses and re-applies. Delete → reverses.

- [ ] **Step 7: Commit**

```bash
git add server/ai/item_detection.py server/api/routes.py client/src/components/Scene/ChatScene.tsx
git commit -m "feat: deterministic item-use detection with inventory notices and reversal"
```

---

## Phase 7: Config Panel & Scene Tab

### Task 7.1: Full Settings Panel

**Files:**
- Modify: `client/src/components/Settings/SettingsPanel.tsx`
- Modify: `client/src/state/settingsStore.ts`

**Interfaces:**
- Consumes: Settings API, lore config API
- Produces: Complete Config tab with all fields from spec: API key, model, temperature, max tokens, max context, narrator instructions, scenario, max carry slots, lorebook injection config

- [ ] **Step 1: Add max carry slots to settings**

Add a number input for max carry slots (default 12). Wire to settings store and API.

- [ ] **Step 2: Add lorebook injection config section**

For each of the 5 lore categories, show:
- Category name
- Injection order number input
- Injection position dropdown (top / bottom / before_input)

Wire to the lorebook config API from Task 4.1.

- [ ] **Step 3: Restructure the settings panel as a tab-panel within the Config tab**

Rather than a modal, the Config tab renders its content directly in the left panel. Sections: "API", "Model", "Narration", "Inventory", "Lorebook Injection". Each section is collapsible.

Move Narrator Instructions and Scenario textareas into the "Narration" section.

- [ ] **Step 4: Verify**

All settings save and persist. Lorebook injection config changes take effect on next chat turn.

- [ ] **Step 5: Commit**

```bash
git add client/src/components/Settings/SettingsPanel.tsx client/src/state/settingsStore.ts
git commit -m "feat: complete config panel with carry slots and lorebook injection settings"
```

---

### Task 7.2: Scene Tab (Stub)

**Files:**
- Create: `client/src/components/ScenePOIList/ScenePOIList.tsx`
- Modify: `client/src/App.tsx`

**Interfaces:**
- Produces: Scene tab left panel showing a placeholder list of POIs (points of interest) in the current location
- Produces: Clicking a POI selects it for inspection (stub inspector view)

This is a minimal stub — the Scene tab is in scope but points of interest are hand-authored content, not a system that needs full CRUD for alpha. The structural slot exists so the tab isn't empty.

- [ ] **Step 1: Create `ScenePOIList.tsx`**

Simple component: header "SCENE", location name from scenario (first sentence or a truncation), a static list of 2–3 placeholder POIs derived from the seed scenario (e.g., "Stone Pillars", "Silver Pool", "Misty Trail"). Clicking a POI could select it in the inspector with a minimal read-only view.

For alpha, this is static content — not persisted or editable.

- [ ] **Step 2: Wire Scene tab in App.tsx**

- [ ] **Step 3: Commit**

```bash
git add client/src/components/ScenePOIList/ScenePOIList.tsx client/src/App.tsx
git commit -m "feat: scene tab stub with placeholder points of interest"
```

---

## Phase 8: Visual Polish & Chat Header

### Task 8.1: Chat Header with Location Banner & Dot-Grain Texture

**Files:**
- Modify: `client/src/components/Scene/ChatScene.tsx`

**Interfaces:**
- Produces: Chat area header with placeholder banner image area, dot-grain texture overlay, "Scenario" / "History" toggle labels

- [ ] **Step 1: Add chat header component**

Above the message list, render a header area:
- Background: `bg-bg2` with a subtle dot-grain radial-gradient overlay:
  ```css
  background-image: radial-gradient(circle, rgba(201,165,88,0.08) 1px, transparent 1px);
  background-size: 4px 4px;
  ```
- Location name from scenario (first line/sentence), in Cinzel, `text-gold`
- "Scenario" / "History" toggle tabs below (switching between showing scenario description and jumping to history) — can be visual-only for alpha

- [ ] **Step 2: Verify**

Chat header shows with grain texture, location name, toggle tabs.

- [ ] **Step 3: Commit**

```bash
git add client/src/components/Scene/ChatScene.tsx
git commit -m "feat: chat header with location banner and dot-grain texture"
```

---

### Task 8.2: Cinzel Baseline Corrections & Final Visual Sweep

**Files:**
- Modify: `client/src/index.css` — add baseline correction utility classes
- Sweep: all components using `font-disp` (Cinzel)

**Interfaces:**
- Produces: Cinzel headers sit correctly on their baselines at all sizes used

- [ ] **Step 1: Add baseline correction utility class**

```css
.font-disp-corrected {
  font-family: var(--font-disp);
  padding-top: 3px;
}
```

- [ ] **Step 2: Audit all Cinzel usage**

Find every element using `font-disp` / Cinzel. Check at each rendered size (headers ~23-24px, smaller labels). Apply `padding-top: 3px` correction where glyphs sit visibly high.

- [ ] **Step 3: Final color/spacing sweep**

Walk through each panel and verify: gold accents consistent, border colors use `border-line` or `border-line2`, text hierarchy (`text-text` > `text-text2` > `text-textsec` > `text-textdim`) applied consistently, all interactive elements have hover states using gold.

- [ ] **Step 4: Commit**

```bash
git add client/src/index.css
git commit -m "fix: Cinzel baseline corrections and final visual consistency sweep"
```

---

## Phase 9: Integration Testing & Seed Content

### Task 9.1: End-to-End Verification & Seed Content Completion

**Files:**
- Modify: `server/db/seed.py` — ensure all seed content matches CLAUDE.md spec
- Possibly modify: various files for bugs found during testing

**Interfaces:**
- Produces: Complete seed data set matching "Definition of Alpha Done"
- Produces: All alpha checklist items verified working

- [ ] **Step 1: Verify seed content**

Confirm seed data includes:
- Seraphine (PC) + Tifa + Rosalina (party) with correct BasicInfo, Equipment (catalog IDs), FieldSkills
- Item catalog with ≥15 items covering all types
- 2–3 seed quests with objectives
- 8–10 lorebook entries across all 5 categories
- Default narrator instructions and scenario

- [ ] **Step 2: Walk through the Definition of Alpha Done checklist**

Go through each item in CLAUDE.md's "Definition of Alpha Done" section. For each:
1. Test the feature manually
2. Note any failures
3. Fix immediately or log for a follow-up

Checklist:
- [ ] Narrator instructions, Scenario, PC sheet, Party members editable and persist
- [ ] Party members can be added and removed
- [ ] OpenRouter model list loads; temperature, max tokens, max context configurable and respected
- [ ] Chat works end to end: message → prompt → OpenRouter → rendered response
- [ ] Spotlight logic: direct address gets response, silence default, max one unprompted reaction
- [ ] Item catalog defined; inventory add/remove/stack; carry capacity enforced (stacks not units)
- [ ] Player item use detected and reverses on swipe/regenerate/delete
- [ ] Narrator grants items and equips/unequips via action block, with reversal
- [ ] Quests CRUD, objectives toggle, status, lore links, persist
- [ ] Lorebook CRUD across 5 categories, keyword matching runs each turn, configured order/position
- [ ] Message edit, delete-truncate, swipe, regenerate all work and persist
- [ ] Six-tab UI matches visual system
- [ ] Seed content: Seraphine + Tifa + Rosalina, catalog, quests, lore

- [ ] **Step 3: Fix any failures found**

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "feat: complete Wayward alpha — all Definition of Alpha Done items verified"
```

---

## Execution Order Summary

| Phase | Tasks | What it delivers |
|---|---|---|
| **1** | 1.1–1.4 | Dark/gold visual system, 4-pane icon-rail layout, inspector View/Edit, attributes removed |
| **2** | 2.1–2.4 | Item catalog, party inventory, equipment references catalog items |
| **3** | 3.1–3.2 | Quest system with objectives, status, lore links |
| **4** | 4.1–4.2 | Lorebook with keyword matching, prompt injection, 5-category UI |
| **5** | 5.1–5.3 | Speaker-differentiated chat, spotlight badges, item chips, full message interactions |
| **6** | 6.1–6.2 | Narrator action parsing, item-use detection, inventory notices, reversal |
| **7** | 7.1–7.2 | Complete config panel, scene tab stub |
| **8** | 8.1–8.2 | Chat header, dot-grain texture, Cinzel baseline fixes |
| **9** | 9.1 | Seed content completion, full alpha checklist verification |

Each phase produces a working, testable increment. Phases 1–4 are the foundation; phases 5–6 are the gameplay loop; phases 7–9 are completion and polish.
