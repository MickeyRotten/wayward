# Wayward — Alpha Build Plan

## What This Is

Wayward is an AI-driven RPG suite — a more intelligent, purpose-built alternative to SillyTavern. The full vision includes grid-based world navigation, JRPG-style turn-based combat, a Bond/Stunt system for party members, and user-generated content tools. **None of that is in scope for this alpha.**

The alpha is a single, focused deliverable: **a polished LLM-driven narrative scene — chat-based roleplay with a player character and a party, done extremely well.** Everything else is designed and waiting, but deliberately not being built yet. Resist the urge to scaffold for future systems (combat, grid, lorebook automation) inside alpha code — build only what's listed below, cleanly.

If prior design docs (`wayward-tech-stack.md`, `wayward-party-combat.md`, `wayward-style.html`) are present in the repo under `/docs`, treat them as background reference for the long-term vision — but this file is the source of truth for what to actually build right now.

---

## Alpha Scope

### In scope
- Editable Narrator instructions (the system prompt governing the DM/narrator LLM)
- Editable Scenario (freeform context describing the current setting/situation)
- Editable Party — add and remove party members
- Editable Player Character Sheet (full spec below)
- Editable Party Member sheets, including a Field Skill (full spec below)
- Party member narration logic — the spotlight system that decides when a party member reacts (this is the central technical problem of the alpha — see below)
- OpenRouter integration — model list, model settings, max tokens, max context
- Three-pane UI: left (character/party management), middle (chat), right (inspector showing current party)

### Explicitly out of scope (do not build)
- Grid/world navigation, towns, dungeons, the tile system
- JRPG battle screen, AP economy, Bond Gauge, Combat Stunts, enemy AI
- The player's own Skills/Stunts/Spells progression system (combat-facing)
- Dice-based or any other formal mechanical resolution for skill checks — for this alpha, Attributes are **narrative flavor only**. The Narrator LLM should use them as characterization context, not run them through a formal mechanic. *(Flagging this as an assumption — see Open Questions at the end.)*
- Lorebook, automated entry detection, world Currents/quests
- General inventory/items beyond the fixed equipment slots on the character sheet
- UGC tooling beyond the character/party editors already listed above
- Supabase — alpha uses SQLite only, per the locked tech stack's "SQLite for prototyping" decision. Still follow the schema_version + stable ID conventions from the UGC strategy doc, even though no sharing exists yet.

---

## Tech Stack

Locked previously, repeated here for convenience:

| Layer | Choice |
|---|---|
| Frontend | React + TypeScript |
| Styling | CSS + Tailwind |
| State | Zustand |
| Backend | Python + FastAPI |
| AI | OpenRouter API (OpenAI-compatible) |
| Database | SQLite (alpha) → Supabase later |

Client owns game/UI logic; server owns AI calls, persistence, and prompt assembly.

---

## Design System

Monochrome only. No color anywhere. Backgrounds are always white or off-white — never a dark surface. Borders are 1.5px solid near-black. Three fonts, each with a distinct job:

```css
:root{
  --white:    #ffffff;
  --off:      #f5f4f1;
  --off2:     #eceae6;
  --border:   #1a1816;
  --text:     #1a1816;
  --text-sec: #666460;
  --text-dim: #999793;
  --mid:      #c0bebb;

  --font-h:  'Bokor', serif;          /* headers, names, world text */
  --font-b:  'Rethink Sans', sans-serif; /* body prose, descriptions */
  --font-ui: 'Silkscreen', sans-serif;   /* buttons, tags, UI chrome */
}
```

**Bokor rules — both matter, easy to miss:**
1. Never apply `font-weight: bold` to Bokor. It has no true bold and faux-bold renders badly. Always `font-weight: 400`.
2. Bokor's ascent metrics sit high in the line box — glyphs look vertically misaligned without correction. Add `padding-top` to any Bokor element, scaled roughly to font size (a 52px heading needs ~6px, a 14px label needs ~2-3px).

If `wayward-style.html` is available in the repo, treat it as the canonical visual reference and copy its component CSS (cards, tags, bars, buttons) directly rather than reinventing them.

---

## Data Models

```typescript
interface AttributeBlock {
  STR: number;
  CON: number;
  DEX: number;
  INT: number;
  WIS: number;
  CHA: number;
}

interface Equipment {
  head: string;
  neck: string;
  torsoOver: string;
  torsoUnder: string;
  leftHand: string;
  rightHand: string;
  waist: string;
  legsOver: string;
  legsUnder: string;
  feet: string;
  accessory1: string;
  accessory2: string;
}

interface BasicInfo {
  name: string;
  gender: string;
  species: string;
  age: number;
  heightCm: number;
  weightKg: number;
  description: string; // textarea
}

interface FieldSkill {
  name: string;
  description: string; // textarea — see writing guidance below
}

interface PlayerCharacter {
  id: string;            // stable UUID — UGC convention, even though
                          // nothing is shared yet
  schemaVersion: 1;
  basicInfo: BasicInfo;
  attributes: AttributeBlock;
  equipment: Equipment;
}

interface PartyMember {
  id: string;
  schemaVersion: 1;
  basicInfo: BasicInfo;
  attributes: AttributeBlock;
  fieldSkill: FieldSkill;
  equipment: Equipment;
  lastSpokeTurn: number; // system-tracked, not user-edited —
                          // used by the spotlight logic below
}

interface Scenario {
  description: string; // freeform context, injected into every
                        // narrator call
}

interface NarratorConfig {
  instructions: string; // the editable system prompt
}

interface OpenRouterSettings {
  apiKey: string;          // stored server-side only, never returned
                            // to the client after save
  modelId: string;         // e.g. "anthropic/claude-sonnet-4.6" —
                            // populated from the fetched model list
  temperature: number;     // 0–2, OpenRouter default range
  maxTokensResponse: number; // default 1000
  maxContextTokens: number;  // see note below — this is NOT inferred,
                              // it's a direct field from the API
}
```

**Equipment is exactly 12 fixed slots, all plain text fields for alpha** — no item objects, no effects grammar, no validation beyond basic text length. This is intentional simplification; the richer item system is designed but deferred.

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
1. Build the prompt (`build_prompt(..., include_action_protocol=False)`) — the spotlight block is still injected, deterministically, exactly as above. Tool-use guidance is prepended.
2. Call the model with `tools` (streaming). If it returns tool calls, execute each against the DB, append the results as `role:"tool"` messages, and loop. If it returns prose with no tool calls, that's the narration → stream it and stop.
3. `max_tool_rounds` (default 6, configurable) caps the loop; the final round drops `tools` to force narration.

**Tools** (handlers in [`server/ai/narrator_actions.py`](server/ai/narrator_actions.py)):
- *Write:* `set_scene` (location/timeOfDay/weather), `grant_item`, `remove_item`, `consume_item` (replaces the old deterministic item-use keyword scan), `equip`, `unequip`, `update_summary` (replaces threshold summarization — the model compresses history when nudged by a context hint).
- *Read:* `lookup_item`, `search_items`, `list_inventory`, `get_character` — let the model validate before acting (e.g. confirm an item exists and its slot before `equip`).

**Persistence/reversal is unchanged.** Tools mutate the DB during the loop; the accumulated inventory deltas, equipment changes, and scene state are recorded on the `ChatMessage` exactly as before, so swipe/regenerate/delete reversal (`_reverse_message_effects`) works identically.

**Model support & fallback.** Tool calling needs a tool-capable model. The model picker (`supportsTools` from OpenRouter's `supported_parameters`) defaults to tool-capable models. When `use_tools` is off **or** the selected model lacks tool support, the narrator falls back to the legacy `<<<ACTIONS>>>` text-block path — `parse_action_block`/`execute_actions`/`ACTION_INSTRUCTION` are retained for exactly this reason. Both `use_tools` and `max_tool_rounds` live on `OpenRouterSettings`, editable in Config → API & Model.

---

## The Chronicler (World-Building Agent)

A **separate** agent ([`server/ai/worldbuilder.py`](server/ai/worldbuilder.py)) that runs as a **second LLM pass after each narration turn** — the world fills itself in as you play. It reviews the new narration + a compact snapshot of current world state and proposes create/update operations for **lorebook entries** (any category, including items), **quests/objectives**, and **party members**.

Its tool calls are **not executed directly** — each becomes a `WorldbuildingProposal` row (`pending`/`accepted`/`rejected`/`failed`), so behavior is gated by `worldbuilding_mode` on `OpenRouterSettings`:
- **disabled** — never runs (no LLM call).
- **confirmation** (default) — all proposals saved `pending` for the player to approve in the **Suggestions** rail panel (badge = pending count).
- **auto** — lore/quest proposals applied immediately; **party-member proposals always stay `pending`** (recruiting needs approval).

Key points: the Chronicler reuses [`chat_completion_agent_turn`](server/ai/openrouter.py) for one tool pass; name resolution prefers **update over duplicate** and never touches `locked` entries; applying a proposal ([`apply_proposal`](server/ai/worldbuilder.py)) mirrors the manual CRUD writes (and enforces `max_party_size`). It uses an optional separate model (`worldbuilding_model_id`, blank → main model). Client flow: after a turn completes, `chatStore` calls `worldbuildStore.runForTurn`; `POST /worldbuild/run` clears stale pending proposals for that turn and regenerates. Accepted world facts are **sticky** — not reverted on swipe/regenerate.

---

## Planning Mode (the Planner)

A **foreground** world-builder, toggled from the chat Tools menu. When on, the chat's primary agent becomes the **Planner** ([`server/ai/planner.py`](server/ai/planner.py)) — its own editable core instructions (`NarratorConfig.planner_instructions`) and full CRUD over lore (all categories), quests/objectives, party members, the PC, the **Scenario**, and the **Narrator's instructions**. You converse with it directly and it creates/edits many things per turn, then replies conversationally.

- **Separate thread.** Planner messages are tagged `ChatMessage.mode = 'planner'` and live in their own conversation; toggling swaps the chat view. They **never enter narration context** — the narrator path filters `mode != 'planner'` in [`_load_game_context`](server/api/routes.py). Each thread numbers its own turns.
- **Create/edit apply immediately** (committed each round, via `run_planner_agent` — same loop shape as the narrator). **Deletes are queued**, not executed: the handler returns a pending-delete; the turn's `done` event carries `pendingDeletes`; the client shows a ConfirmDialog → `POST /planner/deletes/apply`. Locked entries (e.g. the Scenario) can be edited via `set_scenario` but never deleted.
- After a planner turn the client refreshes lore/quests/party/items/narrator panels; the Chronicler does **not** run for planner turns.
- A future guided FTUE (Planner dialogue → Narrator) is intended but not built.

---

## Prompt Assembly

Every narration call assembles, in order:

```
1. Narrator Instructions (user-editable system prompt)
2. Scenario (user-editable context)
3. Player Character summary (name, species, description, equipped items)
4. Party roster summary (each member: name, species, description,
   Field Skill name + description)
5. PARTY SPOTLIGHT block (computed signals, see above)
6. Recent chat history
7. The player's new message
```

Keep this assembly in one clearly isolated function (`promptBuilder`) so it's easy to inspect and tune independently of the chat UI.

---

## UI Layout

Three-pane, full-bleed, no scroll on the outer shell:

```
┌─────────────┬──────────────────────────┬──────────────┐
│ LEFT         │ MIDDLE                   │ RIGHT        │
│ Player char  │ Chat / scene view         │ Inspector    │
│ sheet, Party │ (the actual narrative,    │ — alpha:     │
│ roster list  │ message history, input)   │ current      │
│ (add/remove, │                           │ party only   │
│ click to     │                           │ (portraits,  │
│ edit)        │                           │ names, Field │
│              │                           │ Skill)       │
└─────────────┴──────────────────────────┴──────────────┘
```

The right sidebar is intentionally minimal for alpha — just the party roster. No HP/MP/AP/Bond display belongs here; none of that exists yet since there's no combat in this build. Resist adding it preemptively.

If a prior chat mockup (`wayward-mockup.html`) exists in the repo, use its structure and component styling as the starting point — it already implements this exact three-pane shell. It will need its example content swapped from the old Mira/Runt roster to **Tifa and Rosalina**, and any combat-flavored UI (status effects, roll cards, active modifiers tied to the old resolution system) stripped out, since this alpha has no formal skill-check mechanic.

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

## Suggested Project Structure

```
wayward/
├── client/
│   ├── components/
│   │   ├── Scene/           Chat/narrative interface — main deliverable
│   │   ├── CharacterSheet/  Player character sheet editor
│   │   ├── PartyMember/     Party member editor (sheet + Field Skill)
│   │   ├── Inspector/       Right sidebar — party roster display
│   │   ├── Settings/        Narrator instructions, scenario, OpenRouter config
│   │   └── Layout/          Three-pane shell
│   ├── state/
│   │   ├── narratorStore.ts   Instructions + scenario text
│   │   ├── partyStore.ts      Player character + party members (CRUD)
│   │   ├── chatStore.ts       Message history, scene state
│   │   └── settingsStore.ts   OpenRouter model + settings
│   └── hooks/
│       ├── useChat.ts         Sends a turn, receives narration
│       └── useSpotlight.ts    Computes the deterministic spotlight signals
│
├── server/
│   ├── ai/
│   │   ├── openrouter.py      Model list fetch, chat completion call
│   │   └── prompt_builder.py  Assembles the full prompt (see above)
│   ├── db/
│   │   └── models.py          SQLAlchemy: PlayerCharacter, PartyMember,
│   │                            Scenario, NarratorConfig, OpenRouterSettings,
│   │                            ChatMessage
│   └── api/
│       └── routes.py          CRUD for character/party/scenario/settings,
│                                POST /chat/turn
│
└── shared/
    └── types/                 TS interfaces mirroring the data models above
```

---

## Definition of Alpha Done

- [ ] Narrator instructions are editable and persist
- [ ] Scenario text is editable and persists
- [ ] Player character sheet (all fields above) is fully editable and persists
- [ ] Party members can be added, edited (all fields including Field Skill), and removed
- [ ] OpenRouter model list loads into a picker; temperature, max tokens, and max context are configurable and respected
- [ ] Chat scene works end to end: player message → assembled prompt → OpenRouter call → narrated response rendered
- [ ] Party spotlight logic demonstrably works: direct address always gets a response; silence is the default; no more than one unprompted party reaction per beat
- [ ] Three-pane UI matches the design system (monochrome, three-font rules, no combat-flavored UI elements)
- [ ] Default seed content uses Seraphine (player) + Tifa + Rosalina as the example roster

---

## Open Questions / Assumptions Made Here

These were inferred to keep this document buildable rather than left blank — flag if any are wrong before implementation goes far:

1. **Attributes (STR/CON/DEX/INT/WIS/CHA) are narrative flavor only in this alpha** — no dice mechanic, no formal skill check resolution. The Narrator LLM sees them as characterization context. If you actually want some resolution mechanic active even at this stage, that needs to be specified — it wasn't in the original feature list.
2. **Persistence is assumed** — character sheets, party, scenario, and narrator instructions should survive closing and reopening the app (stored in SQLite), not just live in memory for a session.
3. **Single player-character / single active campaign** for alpha — no multi-campaign or multi-save-slot management yet, since it wasn't requested.
4. **`lastSpokeTurn` tracking is system-internal**, not a user-facing field — it exists purely to drive the spotlight logic.
