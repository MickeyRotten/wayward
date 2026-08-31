# Wayward · Project Loom · Project Aimon — a comparison, and what Wayward should take

Written against: `wayward@80ea3c8`, `ProjectLoom@2af55e4`, Aimon design doc (design
locked, no code).

Goal this is measured against: **a smart, easy-to-use roleplay engine that runs on
PC and Android as a native APK.**

---

## 1. The three projects in one view

| | **Wayward** | **Project Loom** | **Project Aimon** |
|---|---|---|---|
| Status | Shipping, large | Shipping, MVP + long post-MVP tail | Design locked, no code |
| Runtime | Python FastAPI + SQLAlchemy + SQLite, React client over HTTP | Client-only React, IndexedDB | Client-only React, Dexie, static PWA |
| Android | Chaquopy embeds CPython 3.12 + FastAPI + uvicorn + SQLAlchemy + httpx; WebView polls `/health` | Capacitor wraps the built web app | PWABuilder |
| Model calls / turn | **2–8** (narration loop 1–6 rounds + Chronicler + suggester + occasional summariser/vision) | **1** (+ rare repair, occasional journal) | **0** on canonical actions; 1–2 otherwise |
| Who owns state | **The narrator writes it** (tool calls execute against the DB mid-turn) | The narrator *proposes* a delta block; the client folds, validates, then applies | **Code owns truth. The LLM owns prose.** Nothing is ever proposed |
| Dice | Model decides when to roll; `random.randint`; fixed DC map | Deterministic risk gate; roll seeded on `(turn, action)`; every number a setting | Seeded d100; engine-owned; solver proves a route exists without simulating dice |
| Scope posture | Accretive — everything built stays | Accretive but with named retirements (1-bit pass, quick actions, location art, image editing) | **Closed list for v1**, explicit "not in v1" list |

The three are one continuous argument, and Wayward is on the wrong end of it. Loom
was built as "Wayward without the machinery"; Aimon was written after Loom, and its
own justification for being a third repo (`Port manifest → Why not edit Loom`) is
the clearest statement of the problem:

> Loom's founding contract is that the narrator emits a block of deltas and the
> client applies them — *the narrator writes state*. … `reconcileBlock`,
> `goldIsNarrated`, no-op ops, restated ops, `simplifyLocation`, frozen character
> sheets, taking `day` away from the narrator entirely. … That is a long and
> genuinely clever sequence of defences against a decision made on day one — and
> every one of those bug classes simply does not exist when nothing is ever
> proposed.

Wayward sits **one step further out than Loom**, not one step in. Loom's narrator
proposes a block the client can inspect, fold and reject *before anything is
written*. Wayward's narrator calls tools that mutate SQLite **during** the
generation loop — so every defence Loom later had to build, Wayward cannot even
place, because by the time the prose exists the writes have already committed.

That single fact explains most of what follows.

---

## 2. Performance

### 2.1 The turn costs two to eight model calls; Loom's costs one

One player turn in Wayward, traced through `client/src/state/chatStore.ts:502-517`
and `server/api/chat.py`:

1. Narration — the agentic loop, **1 to `max_tool_rounds` (default 6)** full
   round-trips (`server/db/models.py:69`, `server/ai/narrator_agent.py:302`). Each
   round re-sends the *entire* prompt.
2. Chronicler — a second model pass over the new beat
   (`chatStore.ts:507` → `server/ai/worldbuilder.py:778`).
3. Action suggester — a third call, whenever `action_suggestions_mode` is
   `separate`, **which is the default** (`chatStore.ts:514`).
4. Occasionally the background summariser (`_summarize_in_background`).

Loom does all of this in **one streamed call**: prose, then a `<<<LOOM>>>` JSON
block carrying scene, party, inventory, quest and condition deltas *and the action
options*. Aimon goes further — 70% of turns (movement, take, examine) never touch
the network at all.

Wayward already owns most of the fix and does not use it. `action_suggestions_mode
= 'inline'` exists and works; it is not the default. The Chronicler has a cheap
deterministic pre-filter (`worldbuilder.py:757`), which is good, but when it passes
it is still a whole second generation.

**Actions**
- Default `action_suggestions_mode` to `inline`. Saves one call per turn outright.
  The separate call stays as the reroll/self-heal path, which is what it is good at.
- Fold scene state out of a tool round. `set_scene` costs an entire extra round-trip
  to write four strings; a trailing block carries them free. Wayward's own TODO
  already names this ("carry scene state in a trailing block instead of a tool
  round") — it is the highest-value item on that list.
- Consider running the Chronicler every *N* turns, or on a scene change, rather than
  on every beat that passes the pre-filter.

### 2.2 The tool loop is the wrong shape for the models that narrate best

`_resolve_narration_mode` (`chat.py:399`) already concedes this: the four-way `Tool
Mode` exists because "the best *narrative* models aren't necessarily the newest".
So Wayward maintains **two protocols** — a native tool loop and a hardened
`<<<ACTIONS>>>` text block — and both need feeding, testing and prompt text.

Loom collapsed the problem the other way: **one protocol, emitted canonically, read
leniently.** `loomBlock.ts` accepts marker variants, accepts a block with no marker
at all (last brace-balanced object whose keys intersect the contract), normalises
five different shapes of `options`, and buys **one** repair call only after every
salvage path has failed. Aimon promotes this to a rule for every structured call it
makes and adds the finding that fixed two whole classes of malformed output in Loom:

> **Ship a worked example, not just a schema.** A schema describes; an example
> demonstrates.

**Action:** make the text-block protocol the *primary* path and native tool calling
an accelerator for the *read* tools (`lookup_item`, `search_items`,
`list_inventory`, `get_character`), where a round-trip genuinely buys something.
State writes never need a round-trip. That collapses Tool Mode from a four-way
compatibility switch into a performance hint, deletes a protocol, and makes weak
narrative models first-class instead of a fallback.

### 2.3 Android carries a Python server it does not need

`android/app/build.gradle.kts:84-96` ships CPython 3.12 plus pydantic, FastAPI,
uvicorn, SQLAlchemy, greenlet, aiosqlite, httpx and python-multipart into the APK,
extracts them on first launch, boots uvicorn in a daemon thread and has the WebView
poll `/health` before it can render anything. Loom and Aimon ship a WebView and an
IndexedDB.

Everything that server does on-device is (a) assemble a prompt, (b) call OpenRouter
over HTTPS, (c) read and write SQLite. None of it needs a process boundary, and the
process boundary costs cold-start time, APK size, the pydantic-v1 pin (v2's Rust
core has no Android wheels), the greenlet-version-must-match-Chaquopy's-repo
constraint, and the exclusion of TTS.

I am **not** recommending a rewrite — that is just writing Loom again, and Aimon is
explicit that rewriting to escape an architecture destroys a working app people
play. But it is worth being honest that this is the single largest structural cost
in the project, and worth keeping the server thin enough that a future port is a
port and not an excavation. Concretely: keep prompt assembly, spotlight, delta
folding and the clock as **pure functions with no session argument**, the way
Loom's `src/lib/` is deliberately pure and tested.

### 2.4 Per-turn I/O

`_load_game_context` (`chat.py:349`) loads, every single turn: 500 chat messages
(`_HISTORY_WINDOW = 500`, `chat.py:346`), **the entire lorebook**
(`select(LorebookEntry)` unfiltered, for keyword matching), the full item catalog,
all tasks, objectives and wishes. Then the Chronicler and the suggester each open
their own session and re-query. Loom holds one in-memory `GameState`.

After an Editor turn, `refreshWorldPanels()` (`chatStore.ts:324`) fires **ten**
REST calls.

Neither is fatal on a desktop. Both are felt on a phone with a large campaign.

---

## 3. Intelligence

### 3.1 The prompt's tier order is inverted — this is the highest-value fix in the document

`build_prompt` (`server/ai/prompt_builder.py:88`) assembles, in this order:

```
core instructions · story style · world rules · PC sheet · party roster ·
objectives · tasks · wishlist · story summary · spotlight · lore(top)
→ HISTORY ←
lore(before_input) · post-history instructions · player message · lore(bottom)
```

Everything volatile is **before** the history. Loom's `prompt.ts` states the rule
Wayward is breaking, and Aimon repeats it as one of the two rules holding its
narration packet together:

> **Anything the history can contradict is stated after the history.**

The party roster, the inventory-bearing equipment lines, the task list — all of
these are things the last twenty beats actively misremember. A companion who left
is named in a block a whole history window before the beats describing their
departure, and the later text wins. This is why narrators keep voicing people who
are gone.

The second rule Wayward breaks:

> **Every fact is stated exactly once.**

Wayward states equipment in the PC block *and* the party roster *and* (via keyword
match) the item lore entries. Loom found the cost empirically: a fact shown twice
is a fact the narrator re-states, and a re-statement becomes a state op, a toast
chip and a line of transcript.

**Action:** restructure `build_prompt` into Loom's five tiers. This is a
self-contained change to one isolated function that Wayward's own architecture
notes already call out as deliberately inspectable, and it needs no schema change:

1. **Standing context** — instructions, style, scenario, PC sheet, party sheets.
2. **Turn context** — the keyword-gated blocks (lore, spotlight, relevant gear),
   one message, skipped whole on a quiet turn, all sharing **one** scan window.
   (Wayward currently has `LorebookConfig.scan_depth` for lore and a separate
   implicit window for the spotlight — Loom names that exact drift: three matchers
   sharing a keyword helper and then disagreeing about how much text to look at,
   so "mentioned" quietly meant three different things.)
3. **History.**
4. **State of play** — one authority line, then: current scene · **active-party
   roll call** · conditions · inventory · active tasks & objectives.
5. **This turn** — outcome band, regen note, output protocol, player message.

The **roll call** is the piece Wayward has no equivalent of at all and should add
first. Loom's `formatPartyComposition` re-reads the roster every turn and names
who is present (`n/PARTY_LIMIT`), who is benched and explicitly "NOT in this
scene", who has departed or fallen, and every known NPC — and it is emitted **even
when the party is empty** ("the player is ALONE"), because the empty case is
exactly where the history drifts.

### 3.2 Restated ops apply twice — Wayward has no `reconcileBlock`

`tool_grant_item` → `_change_inventory` (`narrator_actions.py:448`) grants
unconditionally. There is no check for whether the item is already held, no
duplicate-row fold within a turn, no "an op that changes nothing is not an op".

Loom hit this hard enough to name it: **one rusty key became Rusty Key ×7**,
because a narrator asked every turn what changed answers with the state instead of
the change. `deltas.ts → reconcileBlock` now drops a row whose requested state is
the state already there — a condition equal to the current mark, an update to the
count it already is, a quest add for a quest on the board, a remove for something
not held, an op naming something nothing resolves — plus exact-duplicate rows
inside one block, plus an inventory `add` with no quantity for an item already held
(dropped, or demoted to the `update` it meant).

And `goldIsNarrated`: gold drifted 15 → 25 → 45 across beats about mushrooms, so a
gold row that *moves* the total is now dropped unless the prose contains a money
word.

**Wayward cannot do this today**, and that is the architectural cost of tool
calling: the write commits inside the generation loop, so there is no moment where
a proposed set of changes exists next to the prose and can be folded against
current state. Fixing it properly means moving state writes out of the loop and
into a post-generation apply step — which is Loom's shape.

The cheap intermediate: make each tool handler a **no-op when the requested state is
the current state**, and return that fact as the tool result so the model sees
"already held" rather than silently succeeding. That is a contained change to
`narrator_actions.py` and kills most of the class.

### 3.3 The dice can be save-scummed and the narrator decides when to roll

`tool_skill_check` (`narrator_actions.py:394`) is `random.randint(1, 20)`. Three
problems, all of which Loom solved and Aimon re-states as a rule:

- **Unseeded.** Regenerate re-rolls. A regenerate button over an unseeded roll is an
  open save-scum hole, and no failure ever has to be lived with. Loom seeds on
  `(turn, action)` so a regenerate re-*tells* the same result and editing the action
  — genuinely choosing something else — earns a new roll.
- **The model decides when it's risky.** Wayward offers `skill_check` as a tool; a
  narrator that wants the player to succeed simply does not call it. Loom's risk
  gate is deterministic and on-device (`isRisky`, word-boundary matched, with the
  keyword list a setting), so the model is *handed* an outcome band it must honour
  and never gets to pick.
- **Nothing modifies it and nothing configures it.** The DC map is a hardcoded
  dict; there is no strengths/flaws input. Loom made every number a setting
  (`DiceRules`: dice count, sides, bonus, penalty, thresholds) sanitised at read,
  and wired `Character.strengths`/`flaws` in as ±1 — which was the first time those
  fields had a mechanical consumer at all.

If you port the seeding, port **the warning with it**. Both Loom and Aimon carry
it, because Loom shipped it broken twice: FNV-1a's low bit is the XOR of the input
bytes' low bits and `h % sides` shares its parity for even `sides`, so a d6 could
roll only 1, 3, 5; and hashing `turn|action|i` for extra dice locked them into
opposite parities, so **2d6 could never roll 7**. One hash, avalanched through a
murmur3 finalizer, extra dice counting off that base. Regression-test it.

Wayward's dice chip is already good — the visible arithmetic is a real UX win.
Loom's version adds the scale ("5+ strong · 3–4 mixed · 2− cost"), because a 3 that
needed a 4 is a different beat from a 3 that needed a 12.

### 3.4 The narrator owns the calendar and the place name

`tool_set_scene` (`narrator_actions.py:413-432`) takes whatever the model sends:
`day` is any positive integer (no monotonicity check — it can freeze, jump or run
backwards), `location` is a freeform string.

Loom took both away:

- **`clock.ts`** — `"day"` left the output protocol entirely. The narrator emits a
  *duration label* off a fixed ladder (`moment · brief · scene · hour · hours ·
  halfday · day · night`) and the client owns every number. An unrecognised label
  falls to the smallest, so a garbage value is unrepresentable rather than clamped;
  `night` anchors to the next 07:00 rather than adding a span; time reaches the
  player and the model as a **phase word** only, never a clock face. And crucially,
  a block with **no** duration still advances time, so an unparseable turn cannot
  freeze the world.
- **`simplifyLocation`** — a compound location joined by ` - `, ` — `, ` / ` or
  `: ` keeps only the last segment ("Boars Head Tavern - Damp Cellar" → "Damp
  Cellar"). Prompt wording alone was not enough, because the location is the label
  the reading area rules off, and the two forms read as two different rooms every
  time the model changes its mind about the prefix. Commas are deliberately not
  joiners; a hyphen without spaces is part of a name ("Half-Moon Inn").

Wayward feels this twice over, because `location` also drives the backdrop matcher
(`lib/backdrops.ts`) and the scene header — a drifting prefix changes the art.

### 3.5 Loom's `places.ts` — the missing layer between "location" and "lorebook"

Loom's best original idea and the one Wayward would benefit from most. `location`
is one name, the most specific one, so the narrator knows it is in the "Damp
Cellar" and re-improvises the tavern, the town and everyone in it every turn. A
`Place` is the **area** that room sits inside — three kinds (`steading` ·
`dungeon` · `wild`) differing only in which tag slots exist, plus rooms (common ⟂
unique), rumours (believed, not true) and keywords. It is authored once by a side
call the first time the player walks in, then read back as authority. Re-entry
costs nothing. The narrator **reads places and never writes them**.

Injection is two-sited and the split is the clever part: the area you are *standing
in* rides in the state tier in full; areas the turn merely *named* are keyword-gated
into the turn tier trimmed to name/kind/description — because "you have heard of
this" and "you are standing in it" are different amounts of context, and shipping a
room list for a town three days away is how a narrator ends up narrating it.

Wayward's lorebook could carry this as a new structured category with almost no new
machinery — it already has the pattern twice (Scenario's 6 fields, Species' 8
fields, both composed into `content` so the injection pipeline needs zero changes).

### 3.6 The journal beats the rolling summary

Wayward compresses old history into a single `StorySummary` that a model rewrites
in place — lossy, and each rewrite compounds the last one's drift.

Loom's `journal.ts` is append-only dated entries written at a **client-chosen**
boundary (a rested turn landing in a new day, a turn ceiling, a floor folding short
stretches). Each entry carries `system` lines derived from the turn's own applied
deltas — **exact, free, and the same records the toast chips read** — plus `model`
lines for what left no state change, with the facts scaffolding the call and
forbidden as output. Old entries decay to their facts before dropping out; the
player keeps every entry forever on the Journal screen while the model sees only
the tail.

The race handling is worth copying verbatim: the entry is opened **synchronously
before** the reversal snapshot and written **asynchronously after**, so undo wins
and a failed call still leaves a usable entry.

Wayward already has the Journal *panel* and derives a day timeline client-side. It
is the model-facing half that is the rolling summary.

### 3.7 Feature switches: four scattered booleans vs. one map

Wayward has `tool_mode`, `dice_enabled`, `worldbuilding_mode`,
`action_suggestions_enabled` — four switches across three config sections, covering
maybe a third of what the narrator actually does. A player who wants a pure prose
sandbox has no way to ask for one.

Loom's `features.ts` is one boolean per subsystem (world: location/places/weather/
clock · cast: characters/spotlight/gear/conditions · play: inventory/quests/stakes/
options · memory: notes/journal), all shipping on, folded in at read so a flag a
stored blob has never heard of reads as on.

The part to actually copy is the **three-things-must-agree rule**, because skipping
any one leaks:

1. `prompt.ts` does not build the block.
2. `prompt.ts` does not *document the channel* in the output protocol — a named
   field is an **invitation**. This is why Loom builds the worked example from the
   flags rather than writing it out: an example is the strongest instruction in the
   protocol, and one showing a field teaches it back after every rule above has
   dropped it.
3. `filterBlock` strips the channel from whatever came back anyway — because the
   history window is full of turns from before the switch was thrown, and a model
   reads its own past output as the example of what a turn looks like.

And: **off never deletes and never hides.** The screens stay reachable behind a
banner that links back to the switch.

### 3.8 Renames, frozen sheets, and the standing ladder

Three Loom findings Wayward's Chronicler is exposed to and has no answer for:

- **Renames.** A narrator introduces someone before the scene has a name for them,
  and its only way to say "that was this person" is a second `add` — so the party
  holds *Unnamed Goblin* **and** *Grik*. Renaming in place is worse: the id
  survives but the transcript, the journal and the model's next few ops keep saying
  the old name, and every name-keyed path (speaker detection, `directlyAddressed`,
  NPC gating) silently stops matching until the window rolls over. Loom's answer:
  **the name moves and the old one is kept** (`Character.aliases`, `nameForms` is
  what every matcher takes, `withRename` is the only writer, shared by the narrator
  op and the player's Name edit). A rename onto a name someone else holds is
  refused — that is a merge, and merging two sheets is the player's call.
- **Frozen sheets.** In Loom a sheet is authored **once**, on the op that creates
  the character; every later op moves standing and nothing else, enforced in code
  so no prompt wording can reopen it. Wayward's Chronicler proposes member updates
  freely.
- **The standing ladder.** `none | npc | active | benched | departed | fallen`
  replaced a boolean. Only `active` is capped; the bench is unlimited, so an
  over-cap add lands benched instead of nowhere. `npc` gives the cast a tier the
  narrator actually reads, keyword-gated so an adventure can know fifty people
  without any of them costing a turn they are absent from. Wayward has `in_party`
  and `max_party_size`, and an over-cap Chronicler proposal just fails.

### 3.9 What Aimon adds that neither has

Aimon is a different genre (map, combat, generated adventures) so most of it does
not transfer. Three things do, as *principles*:

- **Three-tier player input.** Tier 1 canonical actions resolve deterministically
  with **no API call, instant**. Tier 2 free actions get *classified* by the model
  into a closed enum (`{stat, band, target, effect}`) which the engine validates and
  resolves — **the model classifies; it never resolves.** Tier 3 is pure expression:
  no roll, no cost, just prose. Wayward's fixed actions (Look Around, Rest, Talk to
  Party) are all full narration turns; several of them could be cheaper.
- **Failure taxonomy — pass the reason, not just the failure.** When a tool call
  fails, hand the narrator *why* (`NOT_IN_SCOPE` — "the engine knows the lantern is
  in the cellar, so the narrator says something true instead of improvising").
  Wayward's tool results already do some of this (`"No item named X exists in the
  world"`); it is worth making systematic.
- **The world half of the turn.** Aimon runs an engine-owned world step every turn
  regardless of what the player did — clock, depletion, wanderers, event deck — and
  the narrator is *not told the deck exists*, because if it could request an event
  it would request one every beat. That is the same helpfulness reflex that makes
  Wayward's Chronicler rewrite the same lore entries every turn (already an open
  item in `TODO.md`).

---

## 4. Usability

| Gap | Wayward today | Loom's answer |
|---|---|---|
| **Android hardware Back** | No `popstate` handling anywhere in `client/src`. Back exits the app from a full-screen mobile Inspector. | One spare history entry; screens with internal depth register `setBackHandler`, so the Android button matches the UI's own depth (`SubMenuScreen.tsx`). |
| **Settings sprawl** | `SettingsPanel.tsx` is **1830 lines**, one screen, ~15 sections. | Two captioned groups split on the seam already in the data model — *This Adventure* (dies with the next adventure) vs *Settings* (outlives it) — then domain sub-menus, plus `MenuLink` turning copy that *names* a path into a button that goes there. |
| **First run** | No setup screen. A new user lands in the app and has to find Config → AI & Model. | `SetupScreen` gated on `setupDone` (**not** on "is there a key", which would eject the player mid-keystroke), a filterable `ModelPicker` with a free-models filter, and a Test button. |
| **Play vs Edit mode** | Inspector is read-only in Play; "+ New Entry" only in Edit; a whole second agent (`planner.py`, 822 lines) and a second chat thread. | Locked decision: *everything player-editable, inline, no edit mode.* |
| **Character art** | Upload + crop only. | Generated portraits — OpenRouter, or a self-hosted **ComfyUI** backend with the player's own workflow JSON; deterministic triggers; upload/download/remove all still work. |
| **PC ↔ phone transfer** | Manual zip export/import. | Cloud saves: sign in, snapshots sync. |
| **Composer** | Fixed footer under the log + a fixed-actions header. | Composer is the last thing *in* the scrolling log; Return sends; no GO button. |

Two caveats on that last column, both from the projects themselves:

- **Cloud sync: port the second design, not the first.** Loom shipped sync as a
  whole-device mirror — the live game pushed on a 5s debounce after every write,
  re-sending the entire transcript per beat with no delta protocol, plus a conflict
  prompt and two rescue snapshots purely to survive two devices playing one live
  game. The corrected shape: **the live game stays on the device playing it, and
  the cloud holds only what the player deliberately saved.** Per-turn network cost
  zero, and a snapshot is the legible act. Two traps come with it: a stamp with
  nothing local behind it reads as a **deletion** (retired keys must be *skipped*,
  never tombstoned), and **snapshots must freeze their own portraits** under
  slot-scoped keys, or replacing one portrait rewrites that face in every save the
  character appears in. That second one applies to Wayward *right now*, generation
  or no generation — its campaign zip export bundles portraits from a global
  folder.
- **Images: Aimon cut generation entirely.** Deliberately: "This removes two
  backends, a template system, a settings sub-tree and an entire class of failure."
  Worth weighing against the fact that generated portraits are, honestly, one of
  the most immediately felt features Loom has.

---

## 5. What Wayward should *not* take

Aimon's port manifest ends with two rules that exist because Loom nearly became
Wayward again, and they apply just as well in reverse:

> 1. Port a file only when it is needed that day. Never pre-emptively, never in
>    bulk.
> 2. Anything touching the delta system is forbidden, however useful it looks.

For Wayward specifically:

- **Do not port ComfyUI, image prompt templates, or the 1-bit pass.** Wayward's
  design system is warm gold, not 1-bit; the template system exists in Loom
  *because* SD-family checkpoints read Danbooru tags and one set of prose fields
  could not serve both backends. If Wayward wants portraits, it wants one backend.
- **Do not port Loom's retired designs.** Loom itself deleted the 1-bit
  post-process, image editing, location art, quick actions and the sync conflict
  prompt. The retirements are as informative as the features.
- **Resist the reflex to add a system per fix.** The single clearest signal across
  all three documents is that Wayward's problem is not missing features. Aimon
  names it as a hard constraint in its own table: *"Wayward got bloated and stopped
  being fun → scope discipline is a first-class requirement."* Every item in §3 of
  this document is a **deletion or a consolidation** — collapse two protocols into
  one, take `day` away from the narrator, state each fact once, one scan window,
  one features map replacing four scattered booleans.

---

## 6. Suggested order

Ordered by (value ÷ risk), and each item is self-contained.

**Tier A — a weekend each, large effect, no schema change**

1. **Reorder `build_prompt` into the five tiers**, and add the **active-party roll
   call** after the history. Wayward's single biggest intelligence win, in one
   already-isolated function. (§3.1)
2. **Default `action_suggestions_mode` to `inline`.** One fewer model call per
   turn, for a config default. (§2.1)
3. **One scan window.** Make lore matching, spotlight and gear relevance read the
   same `CONTEXT_TURNS`, scanned once. (§3.1)
4. **`simplifyLocation` + a monotonic day guard** in `tool_set_scene`. Twenty lines.
   (§3.4)
5. **No-op tool results.** Each handler returns "already held / already equipped /
   nothing changed" instead of writing again. (§3.2)

**Tier B — the structural ones**

6. **Seed the dice on `(turn, action)`**, add a deterministic risk gate, make the
   numbers settings, wire attributes or a strengths field into the modifier. Bring
   the parity regression tests with it. (§3.3)
7. **Collapse to one protocol**: hardened text block as primary, native tools as an
   accelerator for reads only. Carry scene state and options in the block. Ship a
   worked example; read leniently; buy one repair call. This also lets state writes
   move *after* generation, which is what makes a `reconcileBlock` possible at all.
   (§2.2, §3.2)
8. **Feature flags** — one map, three-things-must-agree, off never deletes. (§3.7)

**Tier C — user-facing**

9. **Android Back handling.** Small, and currently a daily annoyance on the APK.
10. **Split the settings panel** on the campaign ⟂ app-settings seam, and add a
    first-run setup screen.
11. **Places** as a structured lorebook category, two-sited injection. (§3.5)
12. **Journal** — append-only dated entries with delta-derived fact lines, replacing
    the rolling summary as the model-facing memory. (§3.6)

**Explicitly deferred**

Portrait generation, cloud saves, renames/aliases, the standing ladder. All are
good; none of them fixes anything that is currently wrong.

---

## 7. The one-line version

Loom is what Wayward looks like when the narrator only *proposes* state and one
model call does the whole turn. Aimon is what it looks like when the narrator never
touches state at all. Wayward does not need to become either — but almost every
problem it has left is a consequence of letting the narrator write directly to the
database mid-generation, and almost every fix listed here is a step back toward
**code owns truth, the LLM owns prose.**
