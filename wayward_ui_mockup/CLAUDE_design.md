# Wayward — LLM Roleplay Web UI

## Project
`Wayward.dc.html` — a single Design Component mockup of a tabletop-style AI narrator interface. Dark fantasy aesthetic, gold accent palette.

## Stack
- Single DC file, no external libraries
- Fonts: Cinzel (display), Quicksand (body), Hanken Grotesk (UI)
- CSS vars on root div: `--bg0/1/2/3`, `--line/line2`, `--gold/gold2`, `--blue`, `--text/text2/textsec/textdim`, `--fdisp/fbody/fui`
- Grid layout: `66px 288px minmax(0,1fr) 344px` (icon rail | left panel | chat | inspector)

## Layout sections
1. **Icon Rail** (66px) — tab nav: Scene, Party, Items, Quests, Lore, Config
2. **Left Panel** (288px) — tab content, scrollable
3. **Chat / Middle** — scene banner, message stream, composer
4. **Inspector** (344px) — entity details, View/Edit tabs

## Key state
- `tab` — active left panel tab
- `selectedId` — currently inspected entity id
- `everSelected` — false until first entity click; gates inspector content
- `mode` — 'view' | 'edit'
- `modeMemory` — persists view/edit tab per entity
- `editDirty` — unsaved edit indicator dot

## Entity kinds
- `scene` — POIs in the current scene
- character (PC/member) — party characters
- `item` — lore catalog items (Lore > Items)
- `lore` — lorebook entries (world/characters/monsters/spells)
- `quest` — quest entries
All gated in Inspector by `selIs*` flags, each also `&& this.state.everSelected`

## Inspector pattern (IMPORTANT)
The inspector body div must be exactly ONE direct child of the flex column after the header. Any stray `</div>` or orphaned `</sc-if>` after the portrait sc-if will close the body early, putting all content outside the scroll container — causing no padding, no scroll, empty space. Always verify body closes at the very end of the inspector section.

## Lore tabs
World | Characters | Items | Monsters | Spells
Each has a search input (≥2 chars filters by title/keyword).
Lorebook entries: `{ id, title, content, keywords[], enabled, permanent, cat }`

## Inventory
Party inventory (`partyInv`) — items from the lore catalog.
Carry capacity shown as `n / max slots`.
Items can stack; stack size shown when >1.
Add flow: search (≥3 chars), select candidate, set amount, confirm.

## Equipment (P2)
Per-slot equipment for PC and party members, sourced from inventory items filtered by slot type.

## Quests
`{ id, title, status, desc, objectives[], notes, relatedLore[] }`
Related lore links to lorebook entry ids; shown in View (chips) and Edit (toggle list).
Quest add: inline name input → Enter confirms.

## Config
API key, model (display names shown), temperature, max tokens, narrator instructions, response style, lorebook injection orders, max carry slots.

## Chat
Messages: m1–m7 example conversation.
`chatRef` auto-scrolls to bottom on mount and after generating ends.
Composer: auto-resizing textarea, Enter to send, Shift+Enter for newline.
Typing indicator: animated gold dots when `isGenerating`.
"What do you do?" divider shown only after latest narrator reply (m7).
Inventory change notices shown inline after narrator response when item used.

## Things NOT yet built (future)
- Real API calls / streaming
- Persistent localStorage (removed for mockup simplicity)
- PC/party member equipment sheets fully fleshed out
- Prompt preview panel
- Session history / log
- Lore > Items tab search
