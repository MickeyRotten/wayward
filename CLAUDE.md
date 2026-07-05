# Wayward — Architecture & Working Notes

> This file started as the alpha build plan; it now documents the **current
> system**. The original alpha (a polished LLM narrative scene with a PC + party)
> is built and has grown well past it — see the feature sections below. Combat,
> grid/world navigation, and the Bond/Stunt system remain future vision, not yet
> built. `feedback.md` (gitignored locally, but tracked) is the running log of
> requests and what was done.

## What This Is

Wayward is an AI-driven RPG suite — a more intelligent, purpose-built alternative to SillyTavern. The full vision includes grid-based world navigation, JRPG-style turn-based combat, a Bond/Stunt system for party members, and user-generated content tools.

The heart of the app is a **polished, agentic LLM narrative scene** — chat-based roleplay with a player character and a party — wrapped in tooling to build and manage worlds.

## What's built

- **Narrator** — an agentic, multi-step tool-calling chat agent (see "The Narrator Agent Loop").
- **Party spotlight** — deterministic signals decide when party members speak (see "Party Member Spotlight Logic").
- **Chronicler** — a passive post-turn world-builder that proposes lore/task/member additions.
- **Edit Mode (the Editor)** — a foreground, conversational world-builder; full CRUD over the world.
- **Lorebook** (world/characters/items/monsters/spells, with keyword injection), **tasks** (a flat to-do list; the successor to quests+objectives), **inventory + a unified item system** (items are lore entries; owned copies are non-stacking `ItemInstance`s — see "Data Models"), **equip/unequip + Drop** from the item Inspector, a **crop/zoom portrait editor**, a structured **Scenario** tab (Setting/History/Species/Geography/Technology & Magic/Other — see "The Scenario"), an in-game **day** counter.
- **Action Suggestions** — optional, AI-generated contextual choice buttons rendered in-chat (visual-novel style) under the latest beat, alongside fixed canned actions above the input (see "Action Suggestions").
- **OpenRouter integration** — model list (filtered to tool-capable), sampling params, tool settings.
- **Campaigns & Adventures** — separate worlds (campaigns) and save files (adventures), each its own SQLite file; Save/Load, campaign switching, and zip import/export for sharing (see "Campaigns & Adventures").
- Three-pane UI (left management / middle chat / right inspector) with a **Play vs Edit** mode toggle and an Edit-Mode theme.

## Not yet built (future vision — don't scaffold for it)
- Grid/world navigation, towns, dungeons, the tile system.
- JRPG battle screen, AP economy, Bond Gauge, Combat Stunts, enemy AI.
- The player's combat-facing Skills/Stunts/Spells progression.
- Any dice/formal skill-check resolution — **Attributes (STR/CON/…) are narrative flavor only**; the Narrator uses them as characterization context, not a mechanic.

---

## Tech Stack

| Layer | Choice |
|---|---|
| Frontend | React + TypeScript |
| Styling | Tailwind v4 (`@theme inline` mapped to CSS vars) |
| State | Zustand |
| Backend | Python + FastAPI + SQLAlchemy (async, aiosqlite) |
| AI | OpenRouter API (OpenAI-compatible) |
| Database | SQLite — **multiple files**, one per campaign + per adventure, ATTACHed at runtime (see "Campaigns & Adventures") |

Client owns game/UI logic; server owns AI calls, persistence, and prompt assembly. Shared TS types live in `shared/types/models.ts`.

---

## Design System

Dark, warm, gold-accented — **not** monochrome. Tokens are the single source of truth in [`client/src/theme.css`](client/src/theme.css) (the `:root` block) and are mapped onto Tailwind utilities (`bg-bg0`, `text-gold`, `border-line`, `font-disp`, …) in [`client/src/index.css`](client/src/index.css) via `@theme inline`. Edit a token in `theme.css` and it propagates everywhere — so prefer the utilities over literal colors.

Key tokens (see theme.css for the full set):
- Surfaces (dark, faintly warm): `--bg0 #100e0a` … `--bg3 #262016`.
- Gold accents: `--gold #c9a558`, `--gold2 #e8cf8c`, `--golddeep`. Blue (`--blue`) marks the player character.
- Borders are translucent gold: `--line` / `--line2`.
- Three fonts: **Cinzel** (`--fdisp`, display/headers/names), **Quicksand** (`--fbody`, body prose), **Hanken Grotesk** (`--fui`, UI chrome/labels). Cinzel sits high in the line box → add a small `pt-[2-3px]` to Cinzel headings (see `.font-disp-corrected`).
- Item rarity colors `--rarity-c…l` and danger tokens `--danger*`.

**Edit Mode re-skins the app** to a cool indigo/violet palette: when Edit Mode is active, `<body>` gets the `edit-mode` class and [`client/src/edit-theme.css`](client/src/edit-theme.css) overrides the same tokens at runtime. Warm/gold = Play (Narration); indigo/violet = Edit.

---

## Data Models

**Source of truth: [`server/db/models.py`](server/db/models.py)** (SQLAlchemy) and [`shared/types/models.ts`](shared/types/models.ts) (the mirrored TS). Models are **schema-tagged by scope** (see "Campaigns & Adventures"): `app` (settings), `campaign` (the world), `adventure` (a save). Every entity keeps a stable UUID + `schema_version`.

Highlights / things that have changed from the original alpha plan:
- **Items are lorebook entries** (`LorebookEntry`, `cat == "items"`, carrying type/slot/rarity/maxStack/uses) — the shared *catalog* (campaign-scoped). No separate item table. The lorebook also holds world/characters/monsters/spells, with keyword-based injection (`LorebookConfig`).
- **Item instances** (`ItemInstance`, adventure-scoped) are the party's owned physical copies — one row per copy (`id` UUID, `item_id` → catalog, `count`). **Equipment never stacks** (`count==1`, one row per copy, duplicates are distinct instances); stackables (consumables…) keep one row with a count. The legacy `InventoryStack` remains only for the one-time back-fill (`migrate_to_item_instances` in [`database.py`](server/db/database.py)). Instance helpers live in [`server/db/inventory.py`](server/db/inventory.py) (`equipped_map`, `find_stowed_instance`, `grant_items`/`remove_items`, `equip_instance`).
- **Equipment** is 12 fixed slots; each value is an **instance id** (references an `ItemInstance`, not the catalog). "Equipped" is **derived** — an instance is *equipped* iff some character's `equipment[slot]` references its id, else it's *stowed* in the pack (single source of truth; no `equipped_by` column). `/inventory` returns every instance with server-derived `equippedBy`/`slot` (inventory is unbounded — no carry-slot limit).
- **Characters are portable files, not DB rows.** Identity lives in per-character folders `server/data/characters/<id>/{character.json, full.<ext>, crop.jpg}` — `character.json` holds `type` (`persona`|`character`), `basicInfo` (name/gender/species/age/height/weight/description/likes/dislikes/personality — **no** portrait field) and `fieldSkill`; the two images are the portraits (**full** → Inspector, **crop** → chat + avatars; only ever one of each, replaced on re-upload). These are the reusable/shareable "character cards" (see [`server/db/characters.py`](server/db/characters.py)). Per-adventure state — worn **equipment**, `in_party`, `last_spoke_turn`, and `role` (`pc`|`member`) — lives in an adventure-scoped **`PartyBinding`** row referencing the character id. [`server/db/party.py`](server/db/party.py) joins the two into `RuntimeCharacter` composites (`load_pc`/`load_party`) with binding writers (`set_equipment`/`set_in_party`/`set_last_spoke`); the app still reads `.basic_info`/`.equipment`/`.field_skill`/`.in_party`/`.last_spoke_turn`/`.id` (id == character id). A `/characters` REST API lists/imports/duplicates/deletes cards, serves/uploads portraits, and zips a card for sharing. `migrate_characters_to_files` (in [`database.py`](server/db/database.py)) converts legacy `PlayerCharacter`/`PartyMember` rows (kept only for that back-fill) into files+bindings on load. Campaign zip export/import bundles the referenced character folders. (SillyTavern-compatible `.png` card import/export is a planned later parser.)
- **Scenario** is edited as 6 structured fields, composed into a permanent, **locked** World lore entry's `content` (not its own table) — see "The Scenario". It still reaches the narrator via ordinary lore injection.
- **NarratorConfig** (campaign-scoped) holds `instructions`, `action_instruction`, `spotlight_rule`, `post_history_instructions`, `first_message`, `planner_instructions`, `action_suggestions_enabled` (each text field falls back to a built-in default when blank).
- **OpenRouterSettings** (app-scoped) holds the api key (never returned to client), model/sampling params, `max_tokens_response`, `max_context_tokens`, `max_party_size`, plus agent settings `use_tools`, `max_tool_rounds`, `worldbuilding_mode`, `worldbuilding_model_id`, `action_suggestions_model_id`. (The old carry-slot limit was removed — inventory is unbounded.)
- **ChatMessage** (adventure-scoped) carries `role`, `content`, `turn_number`, `variant`, `speaker`, `mode` (`narrator`|`planner`), narrator-declared scene state (`location`, `time_of_day`, `weather`, `day`), `spotlight_reason`, and `applied_inventory_deltas`/`applied_equipment_changes` (for swipe/regenerate/delete reversal).
- Also: `PartyBinding` (adventure-scoped character↔adventure state; identity is files — see above), `Task` (flat to-do list — replaced `Quest`+`QuestObjective`; legacy tables kept only for the one-time `migrate_quests_to_tasks` back-fill), `ItemInstance` (+ legacy `InventoryStack`), `StorySummary`, `WorldbuildingProposal` (Chronicler), `AppState` (active campaign/adventure pointer). Legacy `PlayerCharacter`/`PartyMember` tables remain only for `migrate_characters_to_files`.

Attributes (STR/CON/…) are narrative flavor only — not currently surfaced as a hard mechanic.

---

## OpenRouter Integration

Confirmed against current OpenRouter docs — these are the real endpoints and shapes, not assumptions:

**Fetching the model list:**
```
GET https://openrouter.ai/api/v1/models
Authorization: Bearer <OPENROUTER_API_KEY>
```
Returns `{ data: [ { id, name, context_length, pricing: {...}, ... } ] }`. Use this to populate the model dropdown.

**Important correction to the original ask:** max context does not need to be "inferred" — `context_length` is returned directly per model in this response. Just store it alongside the selected `modelId` when the user picks a model; no inference logic needed.

**Sending a chat turn:**
```
POST https://openrouter.ai/api/v1/chat/completions
Authorization: Bearer <OPENROUTER_API_KEY>
Content-Type: application/json

{
  "model": "<modelId>",
  "messages": [...],
  "max_tokens": 1000,
  "temperature": <setting>
}
```
Standard OpenAI-compatible shape. `max_tokens` must be ≤ `context_length` minus prompt length — clamp it client or server-side rather than trusting raw user input, since OpenRouter will reject or truncate otherwise.

---

## The Core Problem: Party Member Spotlight Logic

This is the hardest part of the alpha and worth building carefully. The goal: party members feel present and alive, without the DM voicing someone every single turn (which gets noisy fast) or never voicing anyone unprompted (which makes the party feel like furniture).

**Spotlight stays deterministic and single-call.** Do not add a separate classifier call per party member to decide "should X speak" — that's slow and costly. Instead, compute cheap deterministic signals locally and feed them into the narration prompt as context, letting the Narrator make the judgment call within its generation. (Note: as of the agentic refactor the *narrator* may take several tool round-trips per turn — see "The Narrator Agent Loop" below — but the spotlight signals themselves remain purely local computation, injected once into the prompt, with no extra LLM calls.)

**Signals computed every turn, before the LLM call:**

```typescript
interface SpotlightSignal {
  memberId: string;
  directlyAddressed: boolean;  // player's message contains the
                                // member's name, or addresses the
                                // group ("we", "you guys", "everyone")
  fieldSkillRelevant: boolean; // simple keyword/condition match
                                // between the message + recent scene
                                // context and the member's Field
                                // Skill description
  turnsSinceLastSpoke: number; // from lastSpokeTurn, current turn
}
```

`directlyAddressed` is a hard override — if true, that party member's response is **not optional**. Build this as an explicit instruction, not a soft hint, or players will learn talking to their party is unreliable and stop doing it.

`fieldSkillRelevant` and `turnsSinceLastSpoke` are soft biases, not triggers. A long silence nudges the Narrator toward giving someone a small beat; it doesn't force one.

**Inject into the prompt as a labeled block, every call**, something like:

```
PARTY SPOTLIGHT — THIS TURN
  Tifa     — not addressed · no clear relevance to this beat ·
             last spoke 4 turns ago
  Rosalina — not addressed · scene involves something starlit/
             cosmic, intersects her Field Skill · last spoke 1
             turn ago

RULE: Voice a party member only when directly addressed, clearly
relevant to what's happening, or significantly overdue for a beat.
Default to silence — most turns, no party member needs to speak.
If a party member IS directly addressed, you MUST have them
respond. Never have more than one react to the same beat unless
the player addressed the whole group. When voiced, keep it to one
or two sentences, true to their established character and Field
Skill.
```

Update `lastSpokeTurn` after the call resolves, based on whether the response actually included that member's voice (simple presence check on their name/dialogue tag in the output is fine for alpha — no need for anything fancier).

---

## The Narrator Agent Loop

The narrator runs as a **multi-step agent** (in [`server/ai/narrator_agent.py`](server/ai/narrator_agent.py)), not a single text-completion. Within one player turn it may take several model round-trips: it can call tools, see the results, and continue before writing the final prose. This replaces the older "append a `<<<ACTIONS>>>` JSON block, parse it with a regex" approach, which couldn't validate against real game state.

**The loop** (`run_narrator_agent`):
1. Build the prompt (`build_prompt(..., include_action_protocol=False)`) — the spotlight block is still injected, deterministically, exactly as above. `TOOL_GUIDANCE` and a `FORMATTING_GUIDE` (the chat-formatting conventions — see "Chat Rendering & Narration Formatting") are prepended as system messages so they hold even if the user cleared their editable narrator instructions.
2. Call the model with `tools` (streaming). If it returns tool calls, execute each against the DB, append the results as `role:"tool"` messages, and loop. If it returns prose with no tool calls, that's the narration → stream it and stop.
3. `max_tool_rounds` (default 6, configurable) caps the loop; the final round drops `tools` to force narration.

**Tools** (handlers in [`server/ai/narrator_actions.py`](server/ai/narrator_actions.py)):
- *Write:* `set_scene` (location/timeOfDay/weather), `grant_item`, `remove_item`, `consume_item` (replaces the old deterministic item-use keyword scan), `equip`, `unequip`, `update_summary` (replaces threshold summarization — the model compresses history when nudged by a context hint).
- *Read:* `lookup_item`, `search_items`, `list_inventory`, `get_character` — let the model validate before acting (e.g. confirm an item exists and its slot before `equip`).

The item tools operate on **instances**: `grant`/`equip` reuse a stowed instance or mint one; `unequip` just clears the slot (the instance becomes stowed — no inventory delta); `remove`/`consume` delete a stowed instance or decrement a stackable. Equipment inventory deltas and equipment changes carry **instance ids** so reversal restores the exact copy.

**Persistence/reversal is unchanged in shape.** Tools mutate the DB during the loop; the accumulated inventory deltas, equipment changes, and scene state are recorded on the `ChatMessage`, so swipe/regenerate/delete reversal (`_reverse_message_effects`) works identically — now threading instance ids.

**Model support & fallback.** Tool calling needs a tool-capable model. The model picker (`supportsTools` from OpenRouter's `supported_parameters`) defaults to tool-capable models. When `use_tools` is off **or** the selected model lacks tool support, the narrator falls back to the legacy `<<<ACTIONS>>>` text-block path — `parse_action_block`/`execute_actions`/`ACTION_INSTRUCTION` are retained for exactly this reason. Both `use_tools` and `max_tool_rounds` live on `OpenRouterSettings`, editable in Config → Agents & Tools.

---

## Chat Rendering & Narration Formatting

The chat is styled like a **classical JRPG dialogue scene**. The narration stays a single freeform-prose `ChatMessage` (`speaker="narrator"`) — there is **no** backend message-splitting — and the client segments it for display, so streaming, swipe/regenerate/delete reversal, variants, and the Chronicler are all untouched.

- **Client segmenter** ([`client/src/lib/narration.ts`](client/src/lib/narration.ts)): `parseSegments(content, resolver)` turns the prose into ordered blocks — `narration` / `dialogue` / `blockquote` / `divider` — line-by-line (robust to single- or double-newline paragraphs). `buildMemberResolver` keys **in-party** members by full and first name.
  - **Party dialogue**: a line `Name: "…"` whose name resolves to an in-party member becomes a **JRPG dialogue block** (rectangular portrait + Cinzel name plate over a tinted, left-accented box). `splitSpokenLine` keeps only the quoted span in the box and pushes any trailing prose ("…", she said) to its own narration beat. Unresolved `Name:` lines (NPCs) stay plain prose — graceful fallback.
  - The **PC** message uses the same block, blue-accented with a `YOU` badge, padded/sized to align with the narrator + party portraits ([`ChatScene.tsx`](client/src/components/Scene/ChatScene.tsx), shared `CHAT_PORTRAIT_SIZE`).
- **Inline markup** (`formatNarration`): `**bold**` and `*italics*`. Entity names (items/members) get a non-interactive gold highlight (`applyEntityChips`). The configured First Message keeps the gold **drop-cap**.
- **Block markup**: `> …` → an inset **inscription/letter** box; a line of only `* * *` / `---` → an ornamental **scene divider**. A cinematic **`LOCATION · TIME`** header is shown above a narrator message when its declared scene state changes (derived from `message.location`/`timeOfDay` — no new narrator output).
- **Convention enforcement**: the always-injected `FORMATTING_GUIDE` (in [`narrator_agent.py`](server/ai/narrator_agent.py)) documents these conventions to the model; the client parser is the deterministic backstop when the model drifts. The `Name: "…"` dialogue convention is the same one `_member_spoke` (`spotlight.py`) already detects, so `last_spoke_turn`/spotlight tracking needs no extra wiring.

---

## The Chronicler (World-Building Agent)

A **separate** agent ([`server/ai/worldbuilder.py`](server/ai/worldbuilder.py)) that runs as a **second LLM pass after each narration turn** — the world fills itself in as you play. It reviews the new narration + a compact snapshot of current world state and proposes create/update operations for **lorebook entries** (any category, including items), **tasks**, and **party members**.

Its tool calls are **not executed directly** — each becomes a `WorldbuildingProposal` row (`pending`/`accepted`/`rejected`/`failed`), so behavior is gated by `worldbuilding_mode` on `OpenRouterSettings`:
- **disabled** — never runs (no LLM call).
- **confirmation** (default) — all proposals saved `pending` for the player to approve in the **Suggestions** rail panel (badge = pending count).
- **auto** — lore/task proposals applied immediately; **party-member proposals always stay `pending`** (recruiting needs approval).

Key points: the Chronicler reuses [`chat_completion_agent_turn`](server/ai/openrouter.py) for one tool pass; name resolution prefers **update over duplicate** and never touches `locked` entries; applying a proposal ([`apply_proposal`](server/ai/worldbuilder.py)) mirrors the manual CRUD writes (and enforces `max_party_size`). It uses an optional separate model (`worldbuilding_model_id`, blank → main model). Client flow: after a turn completes, `chatStore` calls `worldbuildStore.runForTurn`; `POST /worldbuild/run` clears stale pending proposals for that turn and regenerates. Accepted world facts are **sticky** — not reverted on swipe/regenerate.

---

## Action Suggestions

Two surfaces in Play mode: always-available fixed buttons in a row above the chat input, and short AI-generated contextual suggestions rendered **inside the chat** (visual-novel style) under the latest narration beat.

- **Fixed buttons** (no LLM cost, always shown, above the input): Look Around, Talk to Party, Rest, and Use an Item (opens an inline popover listing current inventory via `ItemCard`; picking an item sends `"I use the <item>."` and relies on the narrator's existing `consume_item`/`equip` tools to apply the effect).
- **AI-contextual suggestions**: 3-4 short, scene-specific phrases (e.g. "Ask Tifa about the ruins") from a lightweight one-shot agent ([`server/ai/action_suggester.py`](server/ai/action_suggester.py)) modeled on the Chronicler but much smaller — one tool call (`suggest_actions`), no DB persistence, no accept/reject; a transient list regenerated every turn and lost on refresh. Rendered as elegant choice buttons at the bottom of the chat (only when idle), not above the input.
- Gated by `NarratorConfig.action_suggestions_enabled` (**per-campaign**, default off — an extra LLM call per turn when on) with an optional model override `OpenRouterSettings.action_suggestions_model_id` (blank → main model), both editable in Config → Agents & Tools.
- Fire-and-forget from `chatStore` after each narrator turn completes (`POST /action-suggestions/run`) — the same pattern as the Chronicler's `worldbuildStore.runForTurn`, so it never blocks the chat UI. Fixed buttons and AI suggestions alike just call the existing `sendTurn` with canned text — no special submission path.

---

## The Scenario

The framing premise for the whole world, edited as **6 structured fields** in a dedicated **Scenario tab** in the Lore panel (shown first, before World/Characters/Items/Monsters/Spells): **Setting**, **History (Brief)**, **Species**, **Geography**, **Technology & Magic**, **Other**.

- The fields are the source of truth. Saving (`GET`/`PUT /scenario`, a singleton resource mirroring `/narrator`) composes them into a single freeform string via `compose_scenario_content` ([`server/ai/scenario.py`](server/ai/scenario.py)) — skipping empty fields — and writes it as the `content` of the same permanent, **locked** World `LorebookEntry` the Scenario has always been. This means the existing lore-injection pipeline (`lore_injector.py`/`prompt_builder.py`) needed **zero changes** — it still just reads an ordinary freeform `content` string.
- **Storage**: a `scenario_fields` JSON column directly on `LorebookEntry` (only ever populated on the single Scenario row), alongside the existing `content`.
- **Legacy migration**: campaigns from before this feature have real freeform `content` but empty `scenario_fields`. The first time either is read (`GET /scenario`, or the Editor's `get_scenario` tool), the old text is carried into `setting` as a starting point — one-time, non-destructive, idempotent.
- **Editor tool**: `set_scenario` is a **partial, per-field update** (pass only the field(s) changing; others untouched) rather than whole-text replacement; `get_scenario` reads back all 6 labeled fields.
- The Scenario is excluded from the World tab's entry list (it has its own tab now) and is editable only in Edit Mode — Play mode shows the 6 fields as read-only text.

---

## Edit Mode (the Editor)

A **foreground** world-builder. Engine-style framing: **Play mode = Narration** (runtime), **Edit Mode = building the game**. Toggle it with the Unity-style **Play button on the left of the chat location banner** (lit gold while playing). When on, the chat's primary agent becomes the **Editor** ([`server/ai/planner.py`](server/ai/planner.py) — internal names still say "planner"/`planner_instructions`/`/planner/...`) with full CRUD over lore (all categories incl. dedicated `create_item`/`update_item` with type/slot/rarity + `equip`/`unequip`), tasks, party members, the PC, the **Scenario**, and the **Narrator's instructions**. You converse with it and it creates/edits many things per turn, then replies conversationally.

- **Separate thread.** Editor messages are tagged `ChatMessage.mode = 'planner'` and live in their own conversation (the toggle swaps the chat view). They **never enter narration context** — the narrator path filters `mode != 'planner'` in [`_load_game_context`](server/api/routes.py). Each thread numbers its own turns.
- **Create/edit apply immediately** (committed each round, via `run_planner_agent` — same loop shape as the narrator; multi-round prose is accumulated, not discarded). **Deletes are queued**: the turn's `done` event carries `pendingDeletes`; the client shows a ConfirmDialog → `POST /planner/deletes/apply`. Locked entries (the Scenario) can be edited via `set_scenario` — a structured, per-field partial update (see "The Scenario") — but never deleted.
- **Edit Mode drives the rest of the UI:** the right-hand Inspector is editable in Edit Mode and read-only (view) in Play; "+ New Entry" (Lore) and "+ Add Member" appear only in Edit Mode; the whole app re-skins to the indigo theme. (Exception: **equipment** on the PC/party sheets is editable in Play mode too — managing gear is a play action.)
- After an Editor turn the client refreshes lore/tasks/party/items/narrator panels; the Chronicler does **not** run for Editor turns.
- A future guided FTUE (Editor dialogue → Narrator) is intended; a structured starter message already opens in Edit Mode for a freshly created campaign.

---

## Campaigns & Adventures

Storage is **modular, per-world, shareable**. A **Campaign** is a world; an **Adventure** is a save file within it.

- **On disk** (`server/data/`, gitignored): `app.db` (settings + active-scope pointer), then `campaigns/<id>/{campaign.json, campaign.db, portraits/, adventures/<id>/{adventure.json, adventure.db, portraits/}}`. Campaign DB = lore + items + narrator config; adventure DB = PC, party, tasks, inventory, chat, summary, proposals. JSON sidecars are the cheap index for Save/Load cards.
- **At runtime** ([`server/db/database.py`](server/db/database.py)): one engine on `app.db` **ATTACHes** the active `campaign.db` (AS `campaign`) and `adventure.db` (AS `adventure`) on every connection. Because models are schema-tagged, one session reads/writes all three transparently (`select(LorebookEntry)` → `campaign.lorebook_entries`). `switch_active()` swaps the attached paths and disposes pooled connections so they re-attach. Use `new_session()` (not a top-level import of the sessionmaker) so callers get the live engine. Cross-scope references (equipment slot → instance id → catalog item id) are resolved **in Python**, never via cross-file SQL joins.
- **Storage helpers + migration** in [`server/db/storage.py`](server/db/storage.py): folder/json layout, list/create campaign+adventure, and a one-time migration that splits a legacy single `wayward.db` into the default scope (kept as a backup).
- **Management:** Save/Load adventures in the **Saves** rail tab (new adventure = blank slate, sharing the campaign's world). Config → **Campaign** switches/creates/deletes campaigns (new campaign opens in Edit Mode). **Export/Import** a campaign as a self-contained `.zip` (DB files + referenced portraits); import always creates a new, name-deduped campaign.
- **Templates:** creating a campaign runs through a **New Campaign modal** (name + template dropdown). Templates are plain JSON files in [`server/templates/`](server/templates/) (`empty.json`, `fantasy.json`); [`server/db/templates.py`](server/db/templates.py) (`list_templates`, `apply_template`) reads one and populates the fresh campaign/adventure DBs — narrator config, scenario, lore, keyed catalog items, PC, party, and inventory (written as catalog-id equipment + `InventoryStack`, then converted via `migrate_to_item_instances`). **Universal defaults:** the applier always stores non-empty Narrator Instructions / Spotlight Rule / Editor Instructions (built-in defaults unless the template overrides), so a new campaign is never blank on those.

---

## Prompt Assembly

One isolated function — [`build_prompt`](server/ai/prompt_builder.py) — assembles every narration call, roughly in order:

```
1. Narrator Instructions (campaign NarratorConfig.instructions)
2. (legacy action protocol — skipped in the agentic loop; tool guidance is
   prepended by run_narrator_agent instead)
3. Player Character summary (name, species, description, equipped items w/ descriptions)
4. Party roster (each in-party member: description, personality/likes/dislikes,
   Field Skill, equipped items)
5. Active tasks
6. Story summary (auto-compressed older history)
7. PARTY SPOTLIGHT block (computed signals — see below)
8. Lorebook entries matched by keyword (injected at top / before-input / bottom
   positions per LorebookConfig)
9. Recent chat history (trimmed to the context budget; the editable First Message
   is prepended as the opening assistant turn). Planner-thread messages are
   excluded.
10. Post-History Instructions (always last, right before the user message)
11. The player's new message
```

Keep prompt assembly in `build_prompt` so it stays inspectable independently of the chat UI. The full assembled prompt + model settings + response are logged to the terminal (the `wayward` logger) and the last one is saved for the Tools → View Prompt Log modal.

---

## UI Layout

A narrow **icon rail** + left panel, a middle chat, and a right **Inspector** — full-bleed, no outer scroll ([`AppShell`](client/src/components/Layout/AppShell.tsx), [`App.tsx`](client/src/App.tsx) switches the left panel on the active rail tab):

```
┌──┬─────────────┬────────────────────────┬──────────────┐
│██│ LEFT PANEL   │ MIDDLE                 │ RIGHT         │
│  │ (per tab)    │ Chat / scene view       │ Inspector     │
│Ho│ Home: PC +   │ banner (Play/Edit       │ selected      │
│It│  party       │ toggle, location, day,  │ entity:       │
│Qu│ Items / Lore │ time/weather)           │ PC / member / │
│Lo│ / Tasks /    │ message history + input │ item / task /│
│Id│ Ideas (Chron)│                         │ lore — view   │
│Sa│ / Saves /    │                         │ or edit (by   │
│Cf│  Config      │                         │ mode)         │
└──┴─────────────┴────────────────────────┴──────────────┘
```

Rail tabs: **Home** (PC + party), **Items**, **Tasks**, **Lore**, **Ideas** (Chronicler suggestions, with a pending badge), **Saves** (adventures), **Config**. The right Inspector shows whatever is selected; its view/edit state follows the chat's Edit Mode (see "Edit Mode"). No HP/MP/AP/Bond display — there's no combat yet; don't add it preemptively.

---

## Field Skill Writing Guidance

Since the alpha includes an editable Field Skill field, it's worth the editor UI nudging good input. The established format: one to three sentences, a vivid concrete comparison that implies its own ceiling, and an explicit limitation only if it's genuinely non-obvious. Plain enough that a kid playing with action figures would describe it the same way.

```
Tifa     Punches as hard as a wrecking ball — able to break
         stone and put a big dent in metal with her bare fist.
         Still just a punch — things too big, too tough, or not
         physical at all are out of her reach.

Rosalina Commands a small swarm of Lumas — star sprites the
         size of a fist. They scout, fetch, distract, and watch
         passages. Fast and clever, but fragile and not fighters.
```

A placeholder/example shown in the empty Field Skill text field in the UI is worth doing — it teaches the format without needing separate documentation.

---

## Project Structure (current)

```
wayward/
├── client/src/
│   ├── components/
│   │   ├── Scene/ChatScene.tsx     Chat + banner; JRPG dialogue blocks, formatting
│   │   ├── Home/                   PC + party (HomeView)
│   │   ├── CharacterSheet/, PartyMember/   PC / member editors (view+edit)
│   │   ├── PortraitBlock.tsx, PortraitEditor.tsx   portrait display + crop/zoom modal
│   │   ├── Inspector/PartyInspector.tsx    Right pane — selected entity (+ item equip/drop)
│   │   ├── ItemsPanel/, LorePanel/, TasksPanel/   left panels
│   │   ├── LorePanel/ScenarioEditor.tsx    the Scenario tab's 6-field form
│   │   ├── Suggestions/SuggestionsPanel.tsx  Chronicler proposals ("Ideas")
│   │   ├── SaveLoad/SaveLoadView.tsx       adventures Save/Load
│   │   ├── Settings/SettingsPanel.tsx      Config (campaign, API/model, narration…)
│   │   ├── IconRail/, Layout/, common/ExpandableTextarea.tsx, ConfirmDialog.tsx
│   ├── state/   chatStore, partyStore, narratorStore, settingsStore, itemsStore,
│   │            tasksStore, loreStore, scenarioStore, worldbuildStore,
│   │            actionSuggestionsStore, adventuresStore, campaignsStore, uiStore   (Zustand)
│   ├── lib/     api.ts, location.ts (scene-banner derivation), narration.ts
│   │            (JRPG chat segmenter), equipSlots.ts (item↔slot fit)
│   ├── theme.css / edit-theme.css / index.css   design tokens + Tailwind mapping
│
├── server/
│   ├── ai/
│   │   ├── openrouter.py    model list (+ supportsTools) + chat_completion_stream
│   │   │                    + chat_completion_agent_turn (streaming tool calls)
│   │   ├── prompt_builder.py   build_prompt (see Prompt Assembly)
│   │   ├── spotlight.py        deterministic spotlight signals
│   │   ├── summarizer.py       threshold history compression (legacy path)
│   │   ├── narrator_agent.py   run_narrator_agent (the agentic loop) + tool schemas
│   │   ├── narrator_actions.py tool handlers + legacy <<<ACTIONS>>> parser/executor
│   │   ├── worldbuilder.py     the Chronicler (post-turn world-building)
│   │   ├── action_suggester.py lightweight one-shot contextual quick-action suggestions
│   │   ├── scenario.py         Scenario field composition (structured fields → derived content)
│   │   ├── planner.py          the Editor (Edit Mode agent)
│   │   └── item_detection.py   legacy deterministic item-use (non-tool path)
│   ├── db/
│   │   ├── models.py    SQLAlchemy (schema-tagged: app / campaign / adventure)
│   │   ├── inventory.py item-instance helpers (equip/grant/remove, equipped map, capacity)
│   │   ├── database.py  multi-DB ATTACH engine, init_db, switch_active, new_session,
│   │   │                migrate_to_item_instances (idempotent back-fill)
│   │   ├── storage.py   campaign/adventure folders + json + legacy migration
│   │   └── seed.py      default demo content (Seraphine + Tifa + Rosalina + world)
│   ├── api/routes.py    all REST + /chat/turn (+ swipe/regenerate) + agents + zip I/O
│   ├── main.py          FastAPI app, lifespan → init_db, wayward stdout logger
│   └── data/            (gitignored) per-campaign/per-adventure SQLite + json
│
└── shared/types/models.ts   TS types mirroring the server models
```

---

## Status & conventions

The original alpha is **done** (editable narrator/PC/party, persistent SQLite, OpenRouter picker, end-to-end chat, working spotlight, the design system, the Seraphine+Tifa+Rosalina seed). Everything in "What's built" above is live and verified. Notes for future work:

- **Persistence** is per-campaign/per-adventure SQLite under `server/data/` (survives restart). The legacy single `wayward.db` is migrated once and kept as a backup.
- **Multiple campaigns + adventures** exist (Save/Load, switching, zip share). `lastSpokeTurn` and scene state (`location`/`time_of_day`/`weather`/`day`) are system-tracked on rows, not user-edited.
- **Reversal:** narration effects (inventory deltas, equipment changes, scene state) are recorded on the `ChatMessage` so swipe/regenerate/delete unwind cleanly (`_reverse_message_effects`).
- **Agent reliability:** tool calling needs a tool-capable model; weaker models may narrate success without calling tools. The model picker defaults to tool-capable models; legacy fallbacks remain for non-tool models.
- **Deferred refinements:** choosing which adventures to include on export (endpoint supports it, no UI yet); per-scope portrait folders (portraits are bundled from the global `server/portraits/` on export).
