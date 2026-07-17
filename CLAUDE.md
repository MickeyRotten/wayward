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
- **The action panel** — the primary text-adventure interaction: numbered AI-generated choice options (one per editable moral rule; scripted options on the opening beat) plus the fixed actions, rendered in-chat under the latest beat, with the freeform input demoted below an "Or do something else:" header (see "Action Suggestions").
- **OpenRouter integration** — model list (filtered to tool-capable), sampling params, tool settings.
- **Campaigns & Adventures** — separate worlds (campaigns) and save files (adventures), each its own SQLite file; Save/Load, campaign switching, and zip import/export for sharing (see "Campaigns & Adventures").
- **Voice / TTS** — optional per-speaker text-to-speech with zero-shot voice cloning from ~10s samples (see "Voice / TTS").
- **Journal** — a rail tab surfacing the auto-maintained Story So Far as a recap card + a clickable day-by-day timeline, plus a dismissible "Previously on…" chat banner on adventure load (see "Journal").
- **Skill checks (dice)** — a server-rolled d20 `skill_check` narrator tool for uncertain, consequential actions, rendered as dice chips in chat (see "The Narrator Agent Loop"). Per-campaign toggle (`NarratorConfig.dice_enabled`, default on).
- **Chat backdrops + weather effects** — scene art behind the messages (deterministically matched to the declared location/time) with the narrator-declared weather animated over it: rain, storms with lightning, snow, drifting fog (see "Chat Rendering & Narration Formatting" → Backdrop art & weather effects).
- Three-pane UI (left management / middle chat / right inspector) with a **Play vs Edit** mode toggle and an Edit-Mode theme. Below 1024px the app swaps to a single-pane **mobile layout** (`useIsMobile` → [`MobileShell`](client/src/components/Layout/MobileShell.tsx) + `MobileNav`).
- **Android app (APK)** — a self-contained Chaquopy build under `android/` that embeds the backend on the phone (see "Android App (APK)").

## Not yet built (future vision — don't scaffold for it)
- Grid/world navigation, towns, dungeons, the tile system.
- JRPG battle screen, AP economy, Bond Gauge, Combat Stunts, enemy AI.
- The player's combat-facing Skills/Stunts/Spells progression.
- **Attributes (STR/CON/…) remain narrative flavor only** — the narrative d20 `skill_check` tool (see above) is the only dice mechanic; there is no attribute-modifier math, HP, or combat resolution.

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
- **Characters are portable files, not DB rows.** Identity lives in per-character folders `server/data/characters/<id>/{character.json, full.<ext>, crop.jpg}` — `character.json` holds `type` (`persona`|`character`), `basicInfo` (name/gender/species/age/height/weight/description/likes/dislikes/personality/drive — **no** portrait field) and `fieldSkill`; the two images are the portraits (**full** → Inspector, **crop** → chat + avatars; only ever one of each, replaced on re-upload). These are the reusable/shareable "character cards" (see [`server/db/characters.py`](server/db/characters.py)). Per-adventure state — worn **equipment**, `in_party`, `last_spoke_turn`, and `role` (`pc`|`member`) — lives in an adventure-scoped **`PartyBinding`** row referencing the character id. [`server/db/party.py`](server/db/party.py) joins the two into `RuntimeCharacter` composites (`load_pc`/`load_party`) with binding writers (`set_equipment`/`set_in_party`/`set_last_spoke`); the app still reads `.basic_info`/`.equipment`/`.field_skill`/`.in_party`/`.last_spoke_turn`/`.id` (id == character id). A `/characters` REST API lists/imports/duplicates/deletes cards, serves/uploads portraits, and zips a card for sharing. `migrate_characters_to_files` (in [`database.py`](server/db/database.py)) converts legacy `PlayerCharacter`/`PartyMember` rows (kept only for that back-fill) into files+bindings on load. Campaign zip export/import bundles the referenced character folders. (SillyTavern-compatible `.png` card import/export is a planned later parser.)
- **Scenario** is edited as 6 structured fields, composed into a permanent, **locked** World lore entry's `content` (not its own table) — see "The Scenario". It still reaches the narrator via ordinary lore injection.
- **NarratorConfig** (campaign-scoped) holds `instructions`, `action_instruction`, `spotlight_rule`, `post_history_instructions`, `first_message`, `first_message_options` (scripted opening choices for the primary opening, JSON), `first_message_alternates` (JSON list of `{message, options}` — alternate openings, each with its OWN scripted options; at turn 0 the chat swipe arrows cycle `[first_message, *alternates]` showing each opening's own options, and the chosen one is anchored per-adventure to `StorySummary.opening_message`, which then overrides the primary message in display + prompt; authored as per-opening cards under the Scenario tab's "Opening Messages" section — `normalize_openings` in ai/scenario.py coerces the legacy bare-string shape), `planner_instructions`, `action_suggestions_enabled` (default on), `action_suggestions_instructions`, `action_suggestions_mode` (`separate`|`inline` — see "Action Suggestions"), `action_option_rules` (JSON; one generated option per rule — null → good/neutral/dark/wildcard defaults) (each text field falls back to a built-in default when blank), and `dice_enabled` (offers the narrator the `skill_check` d20 tool; default on).
- **OpenRouterSettings** (app-scoped) holds the api key (never returned to client), model/sampling params, `max_tokens_response`, `max_context_tokens`, `max_party_size`, plus agent settings `use_tools`, `max_tool_rounds`, `auto_retry_count` (auto-regenerate on an error/safety block; default 2, 0-5 — see "The Narrator Agent Loop"), `reasoning_effort` (''=provider default | low/medium/high — sent as OpenRouter's `reasoning.effort` on narrator calls only, never to strict providers; reasoning deltas render live as "REASONING · ~N WORDS", and an all-reasoning empty reply surfaces a clear error), `worldbuilding_mode`, `worldbuilding_model_id`, `action_suggestions_model_id`, and TTS settings `tts_enabled`/`tts_autoplay`. Real **usage accounting** is requested on every OpenRouter stream and stored per assistant message (`ChatMessage.prompt_tokens`/`completion_tokens`/`gen_cost`, summed across tool rounds; shown as a dim per-message meta label, and the context meter prefers it over the chars/4 estimate). It also carries the **provider selector** `llm_provider` (`openrouter`|`nvidia_nim`|`custom`, default `openrouter`) with per-provider write-only creds+model — `nim_api_key`/`nim_model_id`, `custom_base_url`/`custom_api_key`/`custom_model_id` (`api_key`/`model_id` are OpenRouter's) — resolved via `provider_endpoint` (see "OpenRouter Integration (+ multi-provider)"). (The old carry-slot limit was removed — inventory is unbounded.)
- **ChatMessage** (adventure-scoped) carries `role`, `content`, `turn_number`, `variant`, `speaker`, `mode` (`narrator`|`planner`), narrator-declared scene state (`location`, `time_of_day`, `weather`, `day`), `spotlight_reason`, `applied_inventory_deltas`/`applied_equipment_changes` (for swipe/regenerate/delete reversal), and `editor_actions` (planner messages: the `{name, result}` tool actions the Editor took — see "Edit Mode").
- **CampaignRules** (campaign-scoped singleton — the world's "World Rules") holds `party_size` (moved off the app-global `OpenRouterSettings.max_party_size`, which is now only a back-fill seed — `_max_party_size`/the Chronicler read `CampaignRules`), `currency_{name,abbrev,symbol}`, `attributes` (JSON `[{name,description}]` — declared stat vocabulary, narrative only), and `tone`. Injected into the narrator prompt as a compact `WORLD RULES` block (`ai/rules.py` `compose_rules_block` → `build_prompt(campaign_rules=…)`), edited in Config → **World Rules** (`campaignRulesStore`, auto-save) and via the Editor's `get_world_rules`/`set_world_rules` tools; `GET`/`PUT /campaign-rules` (singleton, like `/scenario`). Additive migration creates the table + back-fills `party_size` for pre-existing campaigns.
- Also: `PartyBinding` (adventure-scoped character↔adventure state; identity is files — see above), `Task` (flat to-do list — replaced `Quest`+`QuestObjective`; legacy tables kept only for the one-time `migrate_quests_to_tasks` back-fill), `ItemInstance` (+ legacy `InventoryStack`), `StorySummary` (auto-maintained; surfaced read-only via `GET /journal` — see "Journal"), `WorldbuildingProposal` (Chronicler), `ChatEvent` (adventure-scoped persistent in-chat toasts: Chronicler notices + dice rolls tethered to their turn, untethered player item actions — kinds `chronicler`|`item`|`dice`; see "Chat Rendering & Narration Formatting"), `AppState` (active campaign/adventure pointer). Legacy `PlayerCharacter`/`PartyMember` tables remain only for `migrate_characters_to_files`.
- **SQLite conventions:** every attached DB runs `journal_mode=WAL` + `synchronous=NORMAL` + `busy_timeout` (set in `_attach`, [`database.py`](server/db/database.py)) so the narrator's writes and the concurrent post-turn Chronicler/suggester reads never contend. Hot filter columns carry `index=True` (new files) plus `CREATE INDEX IF NOT EXISTS` back-fills in `_run_scope_migrations`. Per-turn history loads are **bounded**: the chat turn reads a `_HISTORY_WINDOW` (500) newest-message window; the Chronicler/suggester make targeted per-turn queries — never load a whole adventure.

Attributes (STR/CON/…) are narrative flavor only — not currently surfaced as a hard mechanic.

---

## OpenRouter Integration (+ multi-provider)

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

**Multiple providers (OpenRouter / NVIDIA NIM / custom OpenAI-compatible).** The whole LLM surface lives in one module ([`server/ai/openrouter.py`](server/ai/openrouter.py)); every provider is OpenAI-compatible, so only **base URL + key + model + sampling strictness + model-list mapping** differ. The seam is **`provider_endpoint(settings) -> (base_url, api_key, main_model)`**, resolved once at each call site (narrator/planner/Chronicler/suggester/summarizer/vision/legacy path + `/models`); `base_url` is threaded through `chat_completion_stream`/`chat_completion_agent_turn`/`chat_completion_text`/`fetch_models` (default `OPENROUTER_BASE`, so nothing else changed). Providers: **openrouter** (`api_key`/`model_id`, the original), **nvidia_nim** (`https://integrate.api.nvidia.com/v1`, `nvapi-…` key, default model `deepseek-ai/deepseek-v4-pro`), **custom** (`custom_base_url` + key + model — any OpenAI-compatible endpoint). Two gotchas the seam handles: (1) **`openai_strict` sampling** — `min_p`/`top_k`/`repetition_penalty` are OpenRouter-superset params NIM rejects, so `_apply_sampling(openai_strict=not is_openrouter(base_url))` sends only the OpenAI-standard `top_p`/`frequency_penalty`/`presence_penalty` off-OpenRouter; (2) **model-list mapping** — OpenRouter's `/models` is rich (`supported_parameters`/`architecture`), NIM/custom return plain `{data:[{id}]}` → marked tool-capable, no context length. Per-agent model overrides (`worldbuilding_model_id`, …) stay model ids on the active provider. Keys are **per-provider, write-only** (`nimApiKeySet`/`customApiKeySet` mirror `apiKeySet`). Config → AI & Model has the **Provider dropdown**; switching persists + refetches the model list. **LiteLLM was deliberately NOT used** — it needs pydantic v2 + heavy native deps (Rust tokenizers, tiktoken, grpcio) with no Android wheels, which would break the pydantic-v1-pinned APK; the direct httpx path adds zero deps.

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
- *Write:* `set_scene` (location/timeOfDay/weather), `grant_item`, `remove_item`, `consume_item` (replaces the old deterministic item-use keyword scan), `equip`, `unequip`. (History summarisation is deterministic and server-side: when the prompt crosses the threshold, compression runs as a **post-turn background pass** — `_summarize_in_background` in server/api/chat.py — never blocking the player's turn.)
- *Read:* `lookup_item`, `search_items`, `list_inventory`, `get_character` — let the model validate before acting (e.g. confirm an item exists and its slot before `equip`).
- *Dice:* `skill_check(characterName, skill, difficulty)` — offered only when `NarratorConfig.dice_enabled` (schema + `DICE_GUIDANCE` appended conditionally in `run_narrator_agent`). **The server rolls the d20** (DC map easy 8 / normal 12 / hard 16 / heroic 19, nat 1/20 = crits) and returns roll/DC/outcome, so the model narrates a result it was *given* and can't fudge. Each roll writes a **tethered `ChatEvent` (`kind='dice'`)** rendered as a gold/red dice chip in chat; being tethered, it vanishes with the turn on swipe/regenerate/delete and the retelling re-rolls fresh. Agentic path only (no legacy `<<<ACTIONS>>>` equivalent).

The item tools operate on **instances**: `grant`/`equip` reuse a stowed instance or mint one; `unequip` just clears the slot (the instance becomes stowed — no inventory delta); `remove`/`consume` delete a stowed instance or decrement a stackable. Equipment inventory deltas and equipment changes carry **instance ids** so reversal restores the exact copy.

**Persistence/reversal is unchanged in shape.** Tools mutate the DB during the loop; the accumulated inventory deltas, equipment changes, and scene state are recorded on the `ChatMessage`, so swipe/regenerate/delete reversal (`_reverse_message_effects`) works identically — now threading instance ids.

**Model support & fallback.** Tool calling needs a tool-capable model. The model picker (`supportsTools` from OpenRouter's `supported_parameters`) defaults to tool-capable models. When `use_tools` is off **or** the selected model lacks tool support, the narrator falls back to the legacy `<<<ACTIONS>>>` text-block path — `parse_action_block`/`execute_actions`/`ACTION_INSTRUCTION` are retained for exactly this reason. Both `use_tools` and `max_tool_rounds` live on `OpenRouterSettings`, editable in Config → Agents & Tools.

**Auto-retry on error / safety block.** OpenRouter errors and safety-filter blocks both surface as `RuntimeError` from the model call. `OpenRouterSettings.auto_retry_count` (default 2, 0-5; Config → Agents & Tools) silently regenerates that many extra times before the error reaches the player. Retries happen **per model call** — [`agent_turn_with_retry`](server/ai/openrouter.py) (agentic narrator + Editor) and [`stream_with_retry`](server/ai/openrouter.py) (legacy text path) re-invoke a fresh stream on failure; because the transcript is only appended after a *successful* result, a retry never re-runs tools that already committed. A partial attempt emits `discard` (client clears it) then a `retry` event → the UI shows "Retrying (n/N)". Applies to the Narrator (both paths) and the Editor.

---

## Chat Rendering & Narration Formatting

The chat is styled like a **classical JRPG dialogue scene**. The narration stays a single freeform-prose `ChatMessage` (`speaker="narrator"`) — there is **no** backend message-splitting — and the client segments it for display, so streaming, swipe/regenerate/delete reversal, variants, and the Chronicler are all untouched.

- **Client segmenter** ([`client/src/lib/narration.ts`](client/src/lib/narration.ts)): `parseSegments(content, resolver)` turns the prose into ordered blocks — `narration` / `dialogue` / `blockquote` / `divider` — line-by-line (robust to single- or double-newline paragraphs). `buildMemberResolver` keys **in-party** members by full and first name.
  - **Party dialogue**: a line `Name: "…"` whose name resolves to an in-party member becomes a **JRPG dialogue block** (rectangular portrait + Cinzel name plate over a tinted, left-accented box). `splitSpokenLine` keeps only the quoted span in the box and pushes any trailing prose ("…", she said) to its own narration beat. Unresolved `Name:` lines (NPCs) stay plain prose — graceful fallback.
  - The **PC** message uses the same block, blue-accented with a `YOU` badge, padded/sized to align with the narrator + party portraits ([`ChatScene.tsx`](client/src/components/Scene/ChatScene.tsx), shared `CHAT_PORTRAIT_SIZE`).
- **Inline markup** (`formatNarration`): `**bold**` and `*italics*`. Entity names (items/members) get a non-interactive gold highlight (`applyEntityChips`). The configured First Message keeps the gold **drop-cap**.
- **Block markup**: `> …` → an inset **inscription/letter** box; a line of only `* * *` / `---` → an ornamental **scene divider**. A cinematic **`LOCATION · TIME`** header is shown above a narrator message when its declared scene state changes (derived from `message.location`/`timeOfDay` — no new narrator output).
- **Convention enforcement**: the always-injected `FORMATTING_GUIDE` (in [`narrator_agent.py`](server/ai/narrator_agent.py)) documents these conventions to the model; the client parser is the deterministic backstop when the model drifts. The `Name: "…"` dialogue convention is the same one `_member_spoke` (`spotlight.py`) already detects, so `last_spoke_turn`/spotlight tracking needs no extra wiring.

**Backdrop art & weather effects** (Play mode only; Edit Mode stays solid indigo):
- The chat's message area layers **backdrop art** behind the messages with a semi-transparent dark wash over it. `GET /api/backdrops` lists images in `server/backdrops/` (png/jpg/webp); [`lib/backdrops.ts`](client/src/lib/backdrops.ts) deterministically picks the best match by scoring filename tokens ("city_day" → city + day) against the narrator-declared location + time of day, falling back to `forest_day.png` — scenes match automatically from the filename. Backdrops are **managed in Config → Appearance** (thumbnail grid + upload/delete via `POST /backdrops/upload` / `DELETE /backdrops/{file}` — the only way to add art on the APK). **Note: `server/backdrops/` is not committed** (the art lives only on the user's machine), so fresh clones/the APK render the plain dark chat until backdrops are added.
- **Weather effects** animate the narrator-declared weather over the backdrop: [`lib/weather.ts`](client/src/lib/weather.ts) maps the freeform declaration onto rain / storm (wind-blown rain + lightning pulses) / snow / drifting fog-haze ("snowstorm" reads as snow; sand/dust as haze), rendered by [`Scene/WeatherEffects.tsx`](client/src/components/Scene/WeatherEffects.tsx) — one canvas between the wash and the messages, area-scaled particle counts, delta-timed, DPR-capped, idle while the tab is hidden, disabled under `prefers-reduced-motion`. Effects show even when no backdrop art matches. `wayward.weatherOverride` in localStorage forces a kind (debug).
- **Config → Appearance** ([`appearanceStore`](client/src/state/appearanceStore.ts), device-local via localStorage): chat font size, background-wash opacity (`--chat-overlay-opacity`), and the Weather Effects toggle (default on).

---

## The Chronicler (World-Building Agent)

A **separate** agent ([`server/ai/worldbuilder.py`](server/ai/worldbuilder.py)) that runs as a **second LLM pass after each narration turn** — the world fills itself in as you play. It reviews the new narration + a compact snapshot of current world state and proposes create/update operations for **lorebook entries** (any category, including items), **tasks**, and **party members**.

Its tool calls are **not executed directly** — each becomes a `WorldbuildingProposal` row (`pending`/`accepted`/`rejected`/`failed`), so behavior is gated by `worldbuilding_mode` on `OpenRouterSettings`:
- **disabled** — never runs (no LLM call).
- **confirmation** (default) — all proposals saved `pending` for the player to approve in the **Suggestions** rail panel (badge = pending count).
- **auto** — lore/task proposals applied immediately; **party-member proposals always stay `pending`** (recruiting needs approval).

Key points: the Chronicler reuses [`chat_completion_agent_turn`](server/ai/openrouter.py) for one tool pass; name resolution prefers **update over duplicate** and never touches `locked` entries; applying a proposal ([`apply_proposal`](server/ai/worldbuilder.py)) mirrors the manual CRUD writes (and enforces `max_party_size`). It uses an optional separate model (`worldbuilding_model_id`, blank → main model). Client flow: after a turn completes, `chatStore` calls `worldbuildStore.runForTurn`; `POST /worldbuild/run` clears stale pending proposals for that turn and regenerates. Accepted world facts are **sticky** — not reverted on swipe/regenerate.

---

## Action Suggestions (the action panel)

Play mode is **choices-first, text-adventure style**: a unified **action panel** renders in-chat under the latest narration beat (when idle), and the freeform composer sits below it under a small "OR DO SOMETHING ELSE:" header (placeholder "Type your own action…") — still fully functional, deliberately secondary.

The panel, top to bottom:
- **Numbered choice options** (1.-6., clickable; number keys submit too) under the latest beat. After each narrator beat these are AI-generated by the one-shot agent in [`server/ai/action_suggester.py`](server/ai/action_suggester.py) — **one option per Option Rule**, in order, phrased as the PC's impulses: the PC's **Personality & Drive** (basicInfo fields, edited on the PC sheet) lead the suggester's context and both mode guidances. Rules live in `NarratorConfig.action_option_rules` (JSON, per-campaign; null/empty → `DEFAULT_OPTION_RULES`: good / neutral / dark / wildcard) and are edited per-slot (add/remove 1-6, reset) in Config → Agents & Tools; the rule shows as the option's tooltip. On the **opening beat** (no player turns yet) the options are the **scripted** `NarratorConfig.first_message_options`, authored next to the First Message in its Scenario-tab Inspector (templates may supply them — fantasy.json does); the suggester never runs at turn 0. A **↻ REROLL** button sits with the options (re-POSTs `/action-suggestions/run`; the route accepts `turn: null` → latest turn, so reroll works even after a refresh; hidden on the opening beat).
- **Options always show up**: a self-healing ChatScene effect fetches whenever the panel is visible mid-adventure with no attempt for the current chat state (`lastTurn === null` — reset by `clear()`; covers boot/refresh/save/campaign switches, aborts, and failed turns), the suggester retries once server-side at lower temperature on a flaky response, and a genuinely empty roll renders a visible "NO OPTIONS CAME THROUGH — ↻ REROLL" hint instead of nothing.
- **Fixed actions** (always shown) sit **above the composer**, under the "OR DO SOMETHING ELSE:" header (not in the in-chat panel): **Continue** (a true continuation — `POST /chat/continue` EXTENDS the latest narration message in place, no new turn, prose-only with no tools/options; also the rescue for a beat clipped by max tokens; falls back to sending "I wait and let the scene unfold." when there's no narration yet), Look Around, Talk to Party, Rest, and Use an Item (inline inventory popover via `ItemCard`; picking sends `"I use the <item>."`).

Mechanics: **two generation modes** (`NarratorConfig.action_suggestions_mode`, Config → Agents & Tools): `separate` (default) runs the Chronicler-style one-shot tool call (`suggest_actions`, `minItems == maxItems == len(rules)`) after the turn — its own small LLM call, optionally on a cheaper model; `inline` makes the narrator end its reply with a machine-read `<<<OPTIONS>>>` JSON line (guidance injected by the stream drivers via `build_inline_options_guidance`, parsed + stripped by `parse_inline_options` before persisting, options ride the `done` SSE event; `StreamingWindow` truncates the display at `<<<` so the block never flashes mid-stream) — no extra call, tied to the main model. When an inline block fails to parse, the client falls back to the separate call automatically; **reroll and the self-healing fetch always use the separate call**. No DB persistence either way, transient per turn; custom `action_suggestions_instructions` replace the preamble but the OPTION RULES block is always appended. Gated by `NarratorConfig.action_suggestions_enabled` (**per-campaign**, default **on** for new campaigns — an extra small LLM call per turn; existing campaigns keep their stored setting) with an optional model override `OpenRouterSettings.action_suggestions_model_id` (blank → main model). Fire-and-forget from `chatStore` after each narrator turn (`POST /action-suggestions/run`); every option/fixed action just calls the existing `sendTurn` with its text — no special submission path. When suggestions are disabled or empty the panel still shows the fixed actions.

---

## Voice / TTS

Optional per-speaker text-to-speech via **Chatterbox** (MIT; zero-shot voice cloning from ~10s samples), wrapped in [`server/ai/tts.py`](server/ai/tts.py). The heavy stack (torch/chatterbox) is an **optional install** (`server/requirements-tts.txt`, one-click via `Install-TTS.bat` → `Install-TTS.ps1`, which reuses Run.bat's `server\.venv`, auto-detects an NVIDIA GPU for the CUDA torch build, and pre-warms the model with `tts.preload()`); **nothing heavy is imported unless installed** — keep it that way (lazy imports inside `_load_model`/`_synthesize_sync` only).

- **Voices**: the Narrator (narration + NPC lines) clones from a per-campaign `narrator-voice.<ext>` in the campaign folder; each character clones from a `voice.<ext>` sibling in their character folder (managed via a VoiceBlock on the PC/member sheets; narrator sample in Config → Voice & Audio). Samples ride along with character/campaign zips + duplicates automatically. No sample → Chatterbox default voice, never an error.
- **Engine**: device auto-pick (cuda→mps→cpu); sentence-batched synthesis (≤300 chars/generation) in a lock-serialized worker thread (`asyncio.to_thread` — the event loop/SSE never blocks); content-addressed wav cache under `server/data/tts-cache/` (key = model + voice-sample hash + text) so replays/swiped variants are free.
- **REST**: `GET /tts/status` (installed/loaded/device/error), `POST /tts/speak {text, voice: 'narrator'|characterId}` → `{url, cached}` (JSON-with-URL so the client can prefetch), `GET /tts/audio/<sha256>.wav` (immutable-cached), plus `POST/GET/DELETE /characters/{id}/voice` and `/narrator/voice`; `hasVoice` on PC/member/character/narrator responses.
- **Client** ([`ttsStore`](client/src/state/ttsStore.ts)): after a narration turn, the segmenter output plays in order — narrator voice for narration/blockquotes (NPC lines stay narration), member voices for dialogue blocks — with next-segment prefetch; ♪ SPEAK/■ STOP per message, a gold wash on the segment being read, `tts_enabled`/`tts_autoplay` toggles. Playback stops on new turn/swipe/delete. Player messages are never voiced.

---

## Journal ("The Story So Far")

The auto-maintained `StorySummary` is surfaced to the player. `GET /journal` returns `{summary, upToTurn}` (read-only — the summarizer/`update_summary` tool still own the row). The **Journal rail tab** ([`JournalPanel`](client/src/components/Journal/JournalPanel.tsx), [`journalStore`](client/src/state/journalStore.ts)) shows a recap card plus a **day-by-day timeline** derived client-side from narrator-declared scene changes + `ChatEvent`s (latest-wins day/location carry-forward, same rule as `lib/location.ts`); clicking an entry scrolls the chat to that message. A dismissible **"Previously on your adventure"** banner appears above the chat when an adventure with a recap loads — re-armed only by `journalStore.fetch(true)` (boot + adventure switch), not by the quiet post-turn refresh.

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

- **Separate thread.** Editor messages are tagged `ChatMessage.mode = 'planner'` and live in their own conversation (the toggle swaps the chat view). They **never enter narration context** — the narrator path filters `mode != 'planner'` in [`_load_game_context`](server/api/chat.py). Each thread numbers its own turns.
- **Create/edit apply immediately** (committed each round, via `run_planner_agent` — same loop shape as the narrator; multi-round prose is accumulated, not discarded). **Deletes are queued**: the turn's `done` event carries `pendingDeletes`; the client shows a ConfirmDialog → `POST /planner/deletes/apply`. Locked entries (the Scenario) can be edited via `set_scenario` — a structured, per-field partial update (see "The Scenario") — but never deleted.
- **Live action feed:** each Editor tool call streams a `{name, result}` `tool` SSE event; the client prints these under the ⚙ EDITOR heading **in real time** as the turn runs (`chatStore.editorActions`, rendered by `EditorActionsFeed` with a friendly label from the shared `editorActionLabel` map). The ordered list is also persisted on the finished planner `ChatMessage` (`editor_actions` JSON column, additive migration; surfaced as `editorActions`) so the record of what was built/edited stays on the message — the same component renders the live feed and the persisted one.
- **Edit Mode drives the rest of the UI:** the right-hand Inspector is editable in Edit Mode and read-only (view) in Play; "+ New Entry" (Lore) and "+ Add Member" appear only in Edit Mode; the whole app re-skins to the indigo theme. (Exception: **equipment** on the PC/party sheets is editable in Play mode too — managing gear is a play action.)
- After an Editor turn the client refreshes lore/tasks/party/items/narrator panels; the Chronicler does **not** run for Editor turns.
- A future guided FTUE (Editor dialogue → Narrator) is intended; a structured starter message already opens in Edit Mode for a freshly created campaign.

---

## Campaigns & Adventures

Storage is **modular, per-world, shareable**. A **Campaign** is a world; an **Adventure** is a save file within it.

- **On disk** (`server/data/`, gitignored): `app.db` (settings + active-scope pointer), then `campaigns/<id>/{campaign.json, campaign.db, portraits/, adventures/<id>/{adventure.json, adventure.db, portraits/}}`. Campaign DB = lore + items + narrator config; adventure DB = PC, party, tasks, inventory, chat, summary, proposals. JSON sidecars are the cheap index for Save/Load cards.
- **At runtime** ([`server/db/database.py`](server/db/database.py)): one engine on `app.db` **ATTACHes** the active `campaign.db` (AS `campaign`) and `adventure.db` (AS `adventure`) on every connection. Because models are schema-tagged, one session reads/writes all three transparently (`select(LorebookEntry)` → `campaign.lorebook_entries`). `switch_active()` swaps the attached paths and disposes pooled connections so they re-attach. Use `new_session()` (not a top-level import of the sessionmaker) so callers get the live engine. Cross-scope references (equipment slot → instance id → catalog item id) are resolved **in Python**, never via cross-file SQL joins.
- **Storage helpers + migration** in [`server/db/storage.py`](server/db/storage.py): folder/json layout, list/create campaign+adventure, and a one-time migration that splits a legacy single `wayward.db` into the default scope (kept as a backup).
- **Management:** Save/Load adventures in the **Saves** rail tab (new adventure = blank slate, sharing the campaign's world). Config → **Campaign** switches/creates/deletes campaigns (new campaign opens in Edit Mode). **Export/Import** a campaign as a self-contained `.zip` (DB files + referenced portraits); import always creates a new, name-deduped campaign. The active save also has **Export Story** (`GET /adventure/story-export`) — the narrator thread as a readable Markdown download (active variants only, day/location headers, no planner noise). **Automatic backups:** `storage.snapshot_campaign` writes a rotating campaign zip (same format as EXPORT) into `DATA_DIR/backups/` at boot and on campaign switch — throttled per campaign (6h), newest 10 kept, never raises; the Saves tab lists them (`GET /backups`) and **restore imports the snapshot as a NEW campaign** (`POST /backups/{file}/restore` → the shared import path), never overwriting live data.
- **Templates:** creating a campaign runs through a **New Campaign modal** (name + template dropdown). Templates are plain JSON files in [`server/templates/`](server/templates/) (`empty.json`, `fantasy.json`); [`server/db/templates.py`](server/db/templates.py) (`list_templates`, `apply_template`) reads one and populates the fresh campaign/adventure DBs — narrator config, scenario, lore, keyed catalog items, PC, party, and inventory (written as catalog-id equipment + `InventoryStack`, then converted via `migrate_to_item_instances`). **Universal defaults:** the applier always stores non-empty Narrator Instructions / Spotlight Rule / Editor Instructions (built-in defaults unless the template overrides), so a new campaign is never blank on those.

---

## Android App (APK)

Wayward ships as a self-contained Android app: [`android/`](android/) is a Chaquopy 17 project (Python 3.12) embedding the whole backend. The `server/` package plus the production-built client (`client/dist`) are bundled into the APK as `assets/wayward.zip` (the `bundleWaywardAssets` Gradle task) and extracted to app storage on first launch by `WaywardApp.kt` — **`server/data` and `server/portraits` are preserved across app updates; only code is refreshed**. `serverhost.py` boots uvicorn on `127.0.0.1:8000` in a daemon thread; `MainActivity` is a WebView that polls `/health`, then loads the app (file chooser wired up for portrait uploads).

Constraints to keep in mind:
- **pydantic is v1 on Android** — v2's Rust core has no Android wheels. The pins live in [`android/app/build.gradle.kts`](android/app/build.gradle.kts); [`server/api/schemas.py`](server/api/schemas.py) carries the v1 shim (aliases `model_dump` onto v1's `dict`). **Don't introduce pydantic v2-only APIs in server code.**
- `greenlet` (required by async SQLAlchemy) comes from Chaquopy's own wheel repo — the pin must match what `chaquo.com/pypi-13.1` actually publishes for the chosen Python version (3.0.1 currently).
- TTS is excluded on Android (torch doesn't run on-device); it's optional anyway, so nothing breaks.
- [`server/main.py`](server/main.py) serves `client/dist` statically when it exists (`WAYWARD_CLIENT_DIST` env overrides the path) — this is also how single-process self-hosted deploys work. Dev setups without a `dist/` are untouched (Vite keeps serving the client).
- CI: [`.github/workflows/android.yml`](.github/workflows/android.yml) builds the client + a **signed release APK** on pushes touching `android/`/`server/`/`client/`/`shared/`, uploads it as the `wayward-apk` artifact, and on **master** pushes also publishes it as a GitHub Release (`v0.1.<run_number>`) so phones can self-update via Obtainium.
- **Signing:** every build (debug and release) is signed with the committed keystore `android/signing/wayward-release.keystore` (env-overridable — see `signingConfigs` in `build.gradle.kts`), so any build installs over any other without uninstalling and user data survives updates. `versionCode` = 1 + the Actions run number. Don't regenerate the keystore — a new key breaks in-place updates for existing installs.

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
8. Lorebook entries matched by keyword — matching scans the new player message
   plus the last `LorebookConfig.scan_depth` turns of history (default 3), and
   entry titles count as implicit keywords (injected at top / before-input /
   bottom positions per LorebookConfig)
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

Rail tabs: **Home** (PC + party), **Items**, **Tasks**, **Lore**, **Journal** (Story So Far recap + day timeline), **Ideas** (Chronicler suggestions, with a pending badge), **Saves** (adventures), **Config**. The right Inspector shows whatever is selected; its view/edit state follows the chat's Edit Mode (see "Edit Mode"). No HP/MP/AP/Bond display — there's no combat yet; don't add it preemptively.

**Mobile layout (<1024px):** `useIsMobile` ([`client/src/lib/useIsMobile.ts`](client/src/lib/useIsMobile.ts)) swaps `AppShell` for [`MobileShell`](client/src/components/Layout/MobileShell.tsx) — one full-screen view at a time over a bottom tab bar ([`MobileNav`](client/src/components/Layout/MobileNav.tsx); primary tabs + a "More" sheet), with the Inspector as a full-screen slide-over that opens on selection and closes via its Back header. Same stores/components either way — only the shell differs.

**Turn-loop responsiveness:** typing/sending is gated only on `isLoading` (the narration itself); the post-turn Chronicler runs in the background with a live elapsed timer and does **not** lock input (`inputLocked` vs `busy` in [`ChatScene.tsx`](client/src/components/Scene/ChatScene.tsx) — destructive turn edits like swipe/regenerate/delete still wait for both). A failed send restores the typed text via `chatStore.failedInput`; plain sends **append** the persisted turn from the stream's `done` event (which carries the saved message + user-message id) instead of refetching the whole history.

**Client render conventions (keep these invariants):** per-chunk streaming state (`streamingContent`/`toolStatus`/thinking) is subscribed **only** inside `StreamingWindow` — never in `ChatScene` proper; `MessageBubble` is `React.memo`'d with a callback-tolerant comparator, so every derived prop passed to it (`memberResolver`, `chipEntities`, `catalogMap`, `sceneHeaders`, `visibleMessages`, …) must stay `useMemo`'d; `applyEntityChips` caches its compiled regex by `chipEntities` identity.

**Scope switches & crash safety:** while a campaign/adventure switch reloads every store, `App.tsx` **unmounts the panes** behind a themed loading screen (`uiStore.scopeLoading`, set by campaignsStore/adventuresStore around load/create/delete; `reloadAll` in [`adventuresStore`](client/src/state/adventuresStore.ts) refetches everything) — rendering against half-swapped stores is what used to blank the app. An app-wide [`ErrorBoundary`](client/src/components/common/ErrorBoundary.tsx) (wrapped in `main.tsx`) backstops any render crash with a "Something went astray — RELOAD" recovery screen instead of a blank page.

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
│   │   ├── Scene/ChatScene.tsx     Chat orchestrator (message list, backdrop, modals, shortcuts)
│   │   ├── Scene/                  its subcomponents: SceneBanner, ActionPanel, Composer,
│   │   │                           MessageBubble, StreamingWindow, Narration (JRPG segments +
│   │   │                           entity chips), EditorActionsFeed, EventToast, SearchBar,
│   │   │                           PromptLogModal, Indicators, chatDerived.ts
│   │   ├── Scene/WeatherEffects.tsx  canvas weather over the backdrop (rain/storm/snow/fog)
│   │   ├── Home/                   PC + party (HomeView)
│   │   ├── CharacterSheet/, PartyMember/   PC / member editors (view+edit)
│   │   ├── PortraitBlock.tsx, PortraitEditor.tsx   portrait display + crop/zoom modal
│   │   ├── Inspector/PartyInspector.tsx    Right pane — selected entity (+ item equip/drop)
│   │   ├── ItemsPanel/, LorePanel/, TasksPanel/   left panels
│   │   ├── LorePanel/ScenarioEditor.tsx    the Scenario tab's 6-field form
│   │   ├── Suggestions/SuggestionsPanel.tsx  Chronicler proposals ("Ideas")
│   │   ├── Journal/JournalPanel.tsx        Story So Far recap + day timeline
│   │   ├── SaveLoad/SaveLoadView.tsx       adventures Save/Load
│   │   ├── Settings/SettingsPanel.tsx      Config (campaign, API/model, narration, voice…)
│   │   ├── VoiceBlock.tsx                  voice-sample upload/play/remove (PC/member sheets)
│   │   ├── IconRail/, Layout/ (AppShell + MobileShell/MobileNav), common/ExpandableTextarea.tsx, ConfirmDialog.tsx
│   ├── state/   chatStore, partyStore, narratorStore, settingsStore, itemsStore,
│   │            tasksStore, loreStore, scenarioStore, worldbuildStore,
│   │            actionSuggestionsStore, adventuresStore, campaignsStore, uiStore,
│   │            ttsStore (playback queue), journalStore, appearanceStore
│   │            (device-local prefs: font size, wash opacity, weather fx)   (Zustand)
│   ├── lib/     api.ts, location.ts (scene-banner derivation), narration.ts
│   │            (JRPG chat segmenter), equipSlots.ts (item↔slot fit),
│   │            voice.ts (voice-sample upload helpers), useIsMobile.ts
│   │            (mobile/desktop shell switch), backdrops.ts (scene→art
│   │            matcher), weather.ts (declared weather → effect kind)
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
│   │   ├── tts.py              optional Chatterbox TTS (lazy load, synth cache, preload)
│   │   └── item_detection.py   legacy deterministic item-use (non-tool path)
│   ├── db/
│   │   ├── models.py    SQLAlchemy (schema-tagged: app / campaign / adventure)
│   │   ├── inventory.py item-instance helpers (equip/grant/remove, equipped map, capacity)
│   │   ├── database.py  multi-DB ATTACH engine, init_db, switch_active, new_session,
│   │   │                migrate_to_item_instances (idempotent back-fill)
│   │   ├── storage.py   campaign/adventure folders + json + legacy migration
│   │   └── seed.py      default demo content (Seraphine + Tifa + Rosalina + world)
│   ├── api/routes.py    thin /api aggregator over the domain routers below
│   ├── api/             domain routers: chat.py (turn/swipe/regenerate/continue +
│   │                    streaming drivers + background summary), campaigns.py
│   │                    (adventures/backups/zip I/O), characters.py, items.py,
│   │                    lore.py, narrator.py, settings.py, tasks.py, tts.py,
│   │                    backdrops.py, worldbuild.py, planner.py; shared helpers
│   │                    in common.py; pydantic schemas in schemas.py
│   ├── main.py          FastAPI app, lifespan → init_db, wayward stdout logger
│   ├── requirements-tts.txt   optional voice deps (chatterbox-tts + torch)
│   └── data/            (gitignored) per-campaign/per-adventure SQLite + json + tts-cache
│
├── android/                 self-contained APK: Chaquopy embeds server + built client
│                            (see "Android App (APK)")
├── .github/workflows/android.yml   CI — builds + uploads the wayward-debug-apk artifact
│
├── Run.bat / Run.ps1 (+ -Remote / -Tailscale variants)   one-click setup & launch
├── Install-TTS.bat / Install-TTS.ps1   one-click optional voice install (GPU auto-detect + model pre-warm)
│
└── shared/types/models.ts   TS types mirroring the server models
```

---

## Testing

- **Server:** `python -m pytest server/tests` (deps: `pip install -r server/requirements-dev.txt`). Pure-function tests for the deterministic seams (lore injector, prompt builder, spotlight, action options, provider resolution, summariser helpers) plus TestClient integration tests (story export, narrator item tools + reversal, Chronicler `_prev` restore, background summary with a stubbed LLM). **`WAYWARD_DATA_DIR`** overrides the data root (`server/db/database.py`); conftest sets it to a temp dir before any server import so tests never touch a real `server/data` — keep it that way when adding tests.
- **Client:** `npm test` in `client/` (vitest; dedicated `vitest.config.ts`, node env) — unit tests for the pure libs (`narration.ts`, `weather.ts`, `backdrops.ts`, `sortEntries.ts`) as `src/**/*.test.ts` siblings.
- **CI:** [`.github/workflows/test.yml`](.github/workflows/test.yml) runs both suites (+ client `tsc`) on every push/PR touching `server/`/`client/`/`shared/`; the Android workflow builds the APK separately.

## Status & conventions

The original alpha is **done** (editable narrator/PC/party, persistent SQLite, OpenRouter picker, end-to-end chat, working spotlight, the design system, the Seraphine+Tifa+Rosalina seed). Everything in "What's built" above is live and verified. Notes for future work:

- **Persistence** is per-campaign/per-adventure SQLite under `server/data/` (survives restart). The legacy single `wayward.db` is migrated once and kept as a backup.
- **Multiple campaigns + adventures** exist (Save/Load, switching, zip share). `lastSpokeTurn` and scene state (`location`/`time_of_day`/`weather`/`day`) are system-tracked on rows, not user-edited.
- **Reversal:** narration effects (inventory deltas, equipment changes, scene state) are recorded on the `ChatMessage` so swipe/regenerate/delete unwind cleanly (`_reverse_message_effects`).
- **Agent reliability:** tool calling needs a tool-capable model; weaker models may narrate success without calling tools. The model picker defaults to tool-capable models; legacy fallbacks remain for non-tool models.
- **Deferred refinements:** choosing which adventures to include on export (endpoint supports it, no UI yet); per-scope portrait folders (portraits are bundled from the global `server/portraits/` on export).
