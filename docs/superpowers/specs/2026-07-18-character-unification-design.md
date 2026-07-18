# Character & Party Member Unification — Design

## Motivation

Today there are two unrelated character systems:

- **Party members/PC** — portable identity files
  (`server/data/characters/<id>/{character.json, full.<ext>, crop.jpg,
  voice.<ext>}`), globally stored (not campaign-scoped), with a structured
  `basicInfo`/`fieldSkill` schema, portraits, and voice samples. Per-adventure
  state (equipment, in_party, role) lives separately on `PartyBinding`.
- **Lorebook "characters" (NPCs)** — plain `LorebookEntry` rows: title,
  freeform `content`, keywords. No portrait, no structured fields.

When the Chronicler recruits an NPC into the party, it has to **delete** the
lorebook entry and create a new party-member file
(`_absorb_lore_character` in `worldbuilder.py`), because the two schemas
don't overlap — nothing can be preserved except a raw content-copy. This is
destructive and one-directional: there's no way back if a member later
leaves and should return to being a lore-visible NPC. It also means NPCs are
permanently second-class — thinner, no portrait, no personality structure —
unless and until they're recruited.

The fix is to give every named character (PC, party member, or NPC) **one
identity schema**, and make "in the party" a state layered on top of that
identity rather than a different kind of record.

## Unified schema

Every character (PC, party member, or lore Character) shares:

| Field | Notes |
|---|---|
| Name | |
| Species | |
| Apparent Age | freeform text (e.g. "looks to be in her mid-20s", "ageless") — not a number |
| Sex | replaces the old `gender` field |
| Physical Description | replaces `description` |
| Personality | |
| Instinct | replaces `drive` — what they're likely to do, behaviorally |
| Strengths | replaces Field Skill — 1-3 short GM-facing moves/abilities (Perilous Wilds Follower-style) |
| Other | freeform catch-all, kept from the current schema |
| Portrait (full + crop) | unchanged |
| Voice sample | unchanged |

Removed entirely from the old `basicInfo` shape: `likes`, `dislikes`,
`heightCm`, `weightKg`. This is a **full replacement**, not additive — every
consumer of the old field names needs updating (see "Downstream consumers"
below).

The PC uses this exact same schema — including Instinct and Strengths. Even
though the player (not the Narrator) ultimately decides the PC's actions,
Instinct/Strengths still give the action suggester and the Narrator a sense
of who the PC is, replacing what "Personality & Drive" context did before.

### Party-Member-only fields (live on `PartyBinding`, per-adventure)

- **Bond** — integer, default 0, can go negative. Manually edited, pure
  narrative flavor for now — **no automatic behavior**. It is explicitly
  *not* wired into the Spotlight system or any tool call in this iteration;
  it exists to lay groundwork for the future Bond Gauge without building any
  of that system now.
- **Equipment** — the existing full 12-slot structured system
  (`ItemInstance` references), unchanged in shape or behavior.

### Non-PM Character-only field

- **Equipment** — a single freeform text area living directly on the
  character's identity record (not `PartyBinding`, since a non-PM character
  never has one). "What they typically carry" — narrative flavor, no
  structured slots. If a character is later promoted into the party, this
  text is *not* migrated into structured equipment — the two are unrelated
  representations, and the party sheet's structured Equipment section takes
  over once bound.

## Storage & scope

Character identity files move from the current **global**
`server/data/characters/<id>/` to **campaign-scoped**
`server/data/campaigns/<id>/characters/<cid>/`. Folder-per-character is kept
(no change in shape, just nesting) — a campaign realistically has a PC, a
handful of party members, and at most some dozens of recorded NPCs over a
long playthrough, which is a trivial number of folders; the sibling-file
image/voice storage this enables (no DB blobs) is worth keeping.

Consequences:

- No more cross-campaign "Character Library" browser (`GET /characters`
  becomes implicitly scoped to the active campaign, same as lore/items/
  tasks already are).
- Sharing a character between campaigns, or with another user, becomes
  **explicit export/import as a zip bundle** — reusing the existing
  character-zip mechanism (`/characters/{id}/export`,
  `/characters/import-file`), just pointed at the new path. This mirrors how
  campaign export/import already works.
- `install_bundled_cards()` (repo-shipped starter cards used by
  `templates.py`) no longer installs into a global pool. Instead,
  `apply_template` copies a bundled starter card's json + images directly
  into the new campaign's character folder at campaign-creation time.
- **Migration**: existing installs' global character folders must be moved
  into whichever campaign(s) reference them via `PartyBinding`/PC pointer
  (one-time migration, same pattern as `migrate_characters_to_files`/
  `migrate_to_item_instances` in `database.py`). A character referenced by no
  campaign (an unused library card) is attached to whichever campaign is
  active at migration time, with a logged note — deterministic, no data
  loss, and low-stakes given how few existing installs have orphaned cards.

## Lorebook Characters as pointers

A `cat == "characters"` `LorebookEntry` no longer duplicates identity
data — it becomes a **pointer**: it gains a non-nullable `character_id`
column referencing the campaign-scoped character file. Every Characters
lore entry is created together with its linked character record — there is
no lighter "stub" tier; per the field-scope decision above, every character
gets the full schema from the start.

- **`content`** is a read-only projection, composed from the linked
  character's fields (Physical Description, Personality, Instinct,
  Strengths, Species, etc.) the same way `compose_species_content`/
  `compose_scenario_content` work — a new `compose_character_content()`
  helper. The lore-injection pipeline keeps reading `content` unchanged.
- **`title`** mirrors the character's Name.
- **Keywords and injection order/position** stay lorebook-only concerns —
  they don't belong on the character identity record, since the same
  character could plausibly want different keyword matching per campaign in
  principle (in practice a character only ever belongs to one campaign under
  this design, but the concern is still separate from identity).

### Promote / demote

- **Promote** (NPC → active party member) = create a `PartyBinding` for the
  character's existing id. No file is created, copied, or deleted. If the
  Chronicler is recruiting a character that has no prior lore entry at all
  (an ad hoc companion invented mid-recruitment), it creates the character
  record **and** its lore pointer entry in the same operation, so the
  character is immediately knowable in lore too.
- **Demote** (party member → NPC) = remove the `PartyBinding`. The character
  file and its lore pointer entry are untouched — the former party member
  simply reverts to being a normal, fully-detailed lore Character. This
  replaces today's "leave party" behavior (which already preserves the
  character file, just not any lore visibility) and eliminates the
  destructive delete step entirely.
- "In the party" is purely: does an active `PartyBinding` exist for this
  character id in the current adventure. Bench/un-bench (the existing
  `in_party` toggle, distinct from full removal) is unaffected by this
  design — it already doesn't touch the character file.

The PC is excluded from this pointer mechanism, same as today's rule
("never file a party member or the player character as lore") — the PC
already appears in every prompt via the Player Character summary and never
needs keyword-triggered injection.

## Chronicler changes (`worldbuilder.py`)

- **Engagement gate for Characters** (new): a Characters lore entry is only
  created when the player's turn shows **actual engagement** with that
  character — spoken to, acted toward, or a decision involving them — not
  merely a narrator mention in passing. The Chronicler already receives both
  the player's message and the narration for the turn (`_turn_context`), so
  this is a `CHRONICLER_GUIDANCE` prompt change, not a new data dependency.
  Contrast with Species (companion spec), where first appearance alone is
  enough — encountering a species doesn't require "interacting" with it the
  way meeting a person does.
- `create_lore` (`cat == "characters"`) and `update_lore` tool schemas
  replace the single freeform `content` argument with the structured fields
  (physicalDescription, personality, instinct, strengths, species,
  apparentAge, sex, other) for this category — mirroring how `itemType`/
  `slot`/`rarity` already ride alongside `content` for `cat == "items"`.
  Applying either proposal creates/updates both the character record and its
  lore pointer atomically, recomposing `content` afterward.
- `create_member`: before creating a new character, check whether a lore
  Characters pointer already exists for that name (an already-encountered
  NPC being recruited) — if so, **bind its linked character** (promote, as
  above) instead of creating a new record. If no such entry exists, create
  the character record and its lore pointer in the same operation, then
  bind it.
- `_absorb_lore_character` is deleted — replaced by the bind-not-delete
  logic above (no function does destructive lore deletion for characters
  anymore).
- `CHRONICLER_GUIDANCE`'s characters paragraph is rewritten to describe the
  new fields and the engagement gate, replacing the old single-paragraph
  "describe the person" instruction.

## Downstream consumers to update

This is the section most relevant to scoping the implementation plan — code
that reads the old field names or the old storage path:

- `server/ai/prompt_builder.py` — Player Character summary + party roster
  composition reference `description`/`fieldSkill` by name.
- `server/ai/spotlight.py` — `fieldSkillRelevant` signal matches against
  Field Skill's description; needs to match against Strengths instead.
- `server/ai/action_suggester.py` — "the PC's Personality & Drive... lead the
  suggester's context" becomes Personality & Instinct.
- `server/ai/narrator_agent.py` / `narrator_actions.py` — the `get_character`
  tool's output shape.
- `server/ai/worldbuilder.py` — as detailed above.
- `server/ai/planner.py` (the Editor) — `create_lore`/equivalent member
  tools need the same field-name updates as the Chronicler's.
- `server/api/campaigns.py` — zip export/import: bundling character folders
  becomes simpler (they physically live under the campaign folder already),
  but template application needs to copy bundled starter cards per-campaign
  instead of relying on a global install.
- `server/db/characters.py` — path resolution (`characters_dir()` etc.)
  becomes a function of the active campaign, not a fixed `DATA_DIR`-relative
  path.
- `server/db/party.py` — `RuntimeCharacter` composite field names.
- Client: `charactersStore.ts`, `partyStore.ts`, `CharacterSheet/`,
  `PartyMember/`, the Lore panel's Characters tab (which becomes the same
  editing UI as the Party Member sheet, parameterized by whether a
  `PartyBinding` exists, plus a Promote/Demote action).

## Testing

- Server: `prompt_builder` and `spotlight` pure-function tests updated for
  the new field names/Strengths-based relevance.
- A new test verifying promote (bind) does not modify the lore pointer
  entry, and demote (unbind) leaves both the character file and lore
  pointer intact.
- A migration test moving a legacy global character folder into the correct
  campaign folder.
- Chronicler proposal tests: `create_member` reusing an existing
  lore-linked character (bind, no duplicate record created); `create_lore`
  for `cat == "characters"` producing a proposal whose applied entry creates
  both the character record and a correctly-composed lore pointer.
- Client: no changes expected to existing pure-lib tests
  (`narration.ts`/etc.); `CharacterSheet`/`PartyMember` component field
  bindings are manual-QA, consistent with how these components are tested
  today.

## Suggested phasing

This is substantially larger than the Species spec and touches core
storage. The implementation plan should likely split this into phases (e.g.
schema + storage relocation + migration first; lore-pointer unification +
Chronicler rewiring second; UI last) rather than one single change —
left to the implementation plan to sequence in detail.

## Out of scope

- No combat/mechanical use of Bond — narrative flavor only, per the
  motivation section above.
- No cross-campaign character reuse beyond explicit zip export/import.
- No change to the PC's exclusion from lorebook injection.
