# Species & Creature Templates — Lorebook Design

## Motivation

The lorebook's "characters" category has always been flat freeform text
(title/content/keywords). The same is true of "monsters" — describing a
creature type today means writing one undifferentiated paragraph, with no
structure to separate "what it looks like" from "how dangerous it is" from
"what it's called." There's no way to build a reusable species/creature
*template* the way a bestiary entry works: consistent sections an author (or
the Chronicler) can fill in piecemeal, that read back as one coherent
description.

This mirrors a pattern the codebase already has proven out: the **Scenario**
tab stores 6 structured fields on a `LorebookEntry` and composes them into
the entry's freeform `content` at save time (`compose_scenario_content` in
`server/ai/scenario.py`), so the lore-injection pipeline
(`lore_injector.py`/`prompt_builder.py`) needs zero changes — it just reads
`content` like always. Species entries reuse that exact shape, per-row
instead of on a singleton.

## Scope decision: one category, not two

A Species entry covers **both** sapient peoples (Elves, a player-facing
culture) and monsters/creature types (a Dire Wolf, a dragon). The existing
`cat == "monsters"` lorebook category is **retired and merged** into a new
`cat == "species"` category. Fields that don't apply to a given entry (e.g.
Name Examples for a non-naming predator) are simply left blank — this is the
same "skip empty fields" behavior Scenario already uses.

## Fields

Composed into `content` in this order, each as a labeled section, empty
fields skipped:

1. **Overview** — a one/two-sentence hook: what they are, where typically
   found, general impression.
2. **Physical Appearance** — build, distinguishing features, size range,
   variation.
3. **Biology & Reproduction** — physiology, lifespan, diet, how they grow or
   reproduce.
4. **Culture & Behavior** — society/customs for sapient peoples, or
   pack/territorial/instinctual behavior for creatures. One flexible field
   either way.
5. **Danger & Combat Notes** — threat level, tactics, notable
   abilities/weaknesses. Carries forward what the old Monsters category
   tracked. Purely descriptive/narrative flavor for now — there is no combat
   system yet (same treatment as Attributes elsewhere in the app) — do not
   design this field around future mechanics.
6. **Typical Gear** — what they carry, use, build, or lair in.
7. **Archetypes & Variants** — common roles/builds/subtypes seen within the
   species (e.g. "raider," "shaman" for a people; "alpha," "scout" for a
   creature).
8. **Name Examples** — naming conventions + sample names. Naturally blank for
   non-naming creatures.

## Data model

`LorebookEntry` gains a `species_fields: JSON` column — a dict keyed
`overview` / `physicalAppearance` / `biologyReproduction` /
`cultureBehavior` / `dangerCombat` / `typicalGear` / `archetypesVariants` /
`nameExamples`, all strings, only meaningful when `cat == "species"`. This is
an additive migration, same shape as `scenario_fields`.

`compose_species_content(fields: dict) -> str` lives in a new
`server/ai/species.py` (parallel to `scenario.py`), skipping empty fields
and rendering each present field as a labeled paragraph. Called wherever a
species entry's fields are written (API PUT, Editor tool, Chronicler
`apply_proposal`) so `content` stays in sync — the lore-injection pipeline
never needs to know structured fields exist.

## Category migration (monsters → species)

Existing `cat == "monsters"` rows are recategorized to `cat == "species"` in
a one-time migration (same place other additive back-fills run, per
`_run_scope_migrations` in `database.py`). Their existing freeform `content`
is **not discarded** — the first time such an entry is read or saved with an
empty `species_fields`, the old content is carried into the **Overview**
field as a starting point, exactly the same idempotent, non-destructive
carry-over Scenario already does for pre-feature campaigns
(`GET /scenario`'s legacy migration).

`LorebookConfig.injection_order` / `injection_position` (both JSON dicts
keyed by category) drop the `"monsters"` key and gain `"species"` — additive
migration, existing per-campaign customizations for other categories are
untouched, campaigns that never customized injection order get the new
default key for free.

## API & Editor tool changes

- Lore entry CRUD (`GET`/`POST`/`PUT /lore`) already handles arbitrary
  categories generically. The create/update payload gains an optional
  `speciesFields` object (mirrored in `schemas.py`), used only when
  `cat == "species"` — same pattern as the existing `itemType`/`slot`/
  `rarity` fields that only apply when `cat == "items"`.
- The Editor's `create_lore`/`update_lore` tools (`planner.py`) gain the same
  optional `speciesFields` parameter for `cat == "species"`, letting the
  Editor author a species entry field-by-field in conversation, the same way
  `set_scenario` does partial per-field updates for the Scenario singleton.

## Chronicler changes (`worldbuilder.py`)

- `LORE_CATS` / `LORE_CAT_ORDER`: `"monsters"` → `"species"`.
- `create_lore`'s tool schema gains the `speciesFields` object (all optional
  strings) alongside `cat == "species"`.
- `CHRONICLER_GUIDANCE`'s species paragraph replaces the old monsters
  paragraph: record only fields the fiction has actually established (leave
  the rest blank — don't invent, matching the existing "do not invent" rule
  for every other category).
- **Gating**: a species entry is recorded on **first real appearance** in
  the fiction — encountering, fighting, or learning about a species is
  itself the fact worth recording, unlike Characters (see the companion
  Character/Party-Member spec) which require actual player engagement. This
  keeps the existing "be conservative" LLM-judgment gate that Monsters
  already used; no new deterministic backstop is needed.
- `apply_proposal`'s `lore`/`create` and `lore`/`update` handlers read/write
  `species_fields` on the entry and recompute `content` via
  `compose_species_content` after every write.

## Testing

- Pure-function tests for `compose_species_content` (empty-field skipping,
  field ordering, labeled-section rendering) — mirrors the existing
  `scenario.py` test coverage.
- Migration test: a legacy `cat == "monsters"` entry is recategorized to
  `"species"` and its freeform content is carried into `overview` on first
  read, idempotently (a second read doesn't re-carry or duplicate).
- Chronicler proposal test: a `create_lore` call with `cat == "species"` and
  a partial `speciesFields` payload produces a proposal whose applied entry
  has correctly composed `content`.
- No new client-side pure-lib logic is introduced (composition is
  server-side only, same as Scenario) — the Species tab's structured form is
  a new component, covered by manual QA rather than a vitest unit, consistent
  with how `ScenarioEditor.tsx` is untested today.

## Out of scope

- No changes to combat, attributes, or any mechanical resolution — Danger &
  Combat Notes is flavor text only.
- No cross-campaign species template library/sharing — species entries stay
  campaign-scoped lore, same as every other lorebook category today.
