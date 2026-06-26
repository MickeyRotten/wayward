# Wayward feedback list

---
[x] In config, load models by default. When I open Config, I should already be able to pick from a dropdown list of models.

Done (commit e294a91): Config now fetches the OpenRouter model list automatically when the panel opens (if an API key is set), so the model dropdown is populated without clicking LOAD MODELS.

---
[x] Pressing "New adventure" should not wipe the API and Model settings.

Done (commit e294a91): /adventure/reset no longer clears OpenRouterSettings. API key, model, sampling params, context and carry-slot config are treated as user configuration (not adventure progress) and survive New Adventure.

---
[x] Scenario should be a special, permanent item in Lore > World that cannot be deleted - and not accessible from the chat's top bar.

Done (commit 40fc3f4): Scenario is now a permanent, locked entry in Lorebook → World (seeded permanent=True, locked=True). Delete is blocked server-side (403); the UI shows a LOCKED badge + lock glyph and hides the delete button. Removed the Scenario table/routes/schema, the Config → Narration scenario textarea, and the chat top-bar Scenario tab. Scenario context still reaches the narrator via the permanent World lore injection.

---
[x] At default the location in chat top bar says: "The party stands at the edge of a moonlit clearing deep in t…", this is not good. By default it could read "The Void" or something vague, and the location should be explicitly stated by the narrator as a parsed state, which is then shown as the location.

Done (commit 40fc3f4): The chat header shows the current location under a "LOCATION" label, defaulting to "The Void". The narrator declares the location via a "location" field in its action block; it is parsed, stripped from prose, and stored per message. The client shows the most recently declared location (and reverts naturally on swipe/delete).

---
[x] All the various different instructions given to the Narrator should be shown and editable in the Config

Done: NarratorConfig now stores three editable instruction blocks — Narrator Instructions, Action Protocol (item/equipment/location action format, previously hardcoded), and Spotlight Rule (when party members speak, previously hardcoded) — all shown and editable in Config → Narration. The prompt builder and spotlight formatter use the stored values, falling back to the built-in defaults when blank, and the GET /narrator response surfaces the effective default text so the fields are never empty. Export/import carry the new fields.

---
[x] The chat should have a First Message already shown by default (and this should be modifiable in Config too). The first message will have the drop cap. The first message is included in history and context when user prompts the first time.

Done: NarratorConfig gains a `first_message` field (seeded with an opening for the Moonlit Clearing, editable in Config → Narration → First Message). The chat renders it as the drop-capped opening narrator block; the per-message drop-cap is suppressed when a First Message is present so only the opening is decorated. The prompt builder prepends it as the first assistant turn so it is always in history/context — verified live (roles: …system, assistant[first message], user). It persists across New Adventure (it's narrator config).

---
[x] PC / Party Member equipment list in View: Should be a single-column grid, not a two column one.

Done: The equipment list in View mode for both the Player Character sheet and Party Member sheets is now a single-column layout (was grid-cols-2), with the slot label and item on one row each.

---
[x] Pressing Esc should clear the Inspector and show the default one

Done: A global Escape handler (App.tsx) clears the inspector selection (select(null)) → the default "select something to inspect" view. It's suppressed while focus is in an input/textarea/select/contenteditable so Esc still cancels inline edits and field entry.

---
[x] Party Members have equipment that aren't in the Item Catalog -> add them to catalog

Verified done: every item the PC and party members have equipped already resolves to an Item Catalog entry (the catalog migration made equipment reference catalog IDs). Checked live against a fresh seed — all 7 equipped items (Worn Lute, Traveler's Cloak, Premium Leather Gloves, Steel-Toed Boots, Celestial Gown, Star Wand) are present in the 20-item catalog, so nothing was missing to add. (If a stale pre-migration wayward.db shows raw strings, a New Adventure / fresh seed resolves it.)

---
[x] Tapping on an equipped item should open that item's Inspector view, same as clicking on it in Inventory etc.

Done: equipped items in the PC/Party View are now buttons; tapping one selects it as an item (select({kind:'item', id})), so the right-hand Inspector switches to that item's detail view — identical to clicking it in the Inventory list. Hover highlights the item in gold; empty slots remain plain.

---
[x] Chat text input should be just one row by default. Expand as text wraps.

Done: the chat input is now a single row by default and auto-grows as text wraps (up to ~160px, then scrolls). Height resets after sending.

---
[x] On the left-hand side of the chat input field, have a button for Tools (show a fitting icon). Tapping it opens a dropdown menu (above the button) with the following options: Regenerate, Clear Chat. More options will come later. Make them functional.

Done: added a Tools button (wrench icon) on the left of the input. Tapping it opens a dropdown above the button with Regenerate, Clear Chat, and View Prompt Log — all functional (Regenerate disabled until there's a last response to regenerate; Clear Chat / View Prompt Log disabled when history is empty; Clear Chat goes through the confirm dialog). Clicking outside closes the menu. The old inline regenerate/LOG/CLEAR buttons were removed in favor of this menu.

---
[x] The terminal should show the logs of all activity for easy trouble-shooting, at least all LLM related ones, e.g. the full prompt sent to the LLM + all the model settings, etc, and the full output message from LLM.

Done: the server now logs LLM activity to the terminal. Before each call it logs an LLM REQUEST line (model + temperature/top_p/min_p/top_k/penalties + max tokens + max context + estimated prompt tokens) and the full assembled LLM PROMPT (every message, labelled by role). After the call it logs the full LLM RESPONSE (raw output) and, if present, the parsed LLM ACTIONS. A dedicated "wayward" stdout logger is configured in main.py (UTF-8-forced so em-dashes/non-ASCII in prompts don't break logging on Windows). Verified live: clean output, no encode errors.

---
[x] When I remove a party member from Party, add them to a new list in the Party view, called "Not in party". Removing doesn't require confirmation, and a character who's not in party can be easily added back in.

Done: party members now have an `in_party` flag. Removing from the party benches them (no confirmation) instead of deleting. The Party view shows two sections — the active "PARTY" list and a "NOT IN PARTY" list — each row has a one-tap −/+ control to bench / re-add. Only in-party members participate in narration and the spotlight. (Permanent character deletion still lives in the member editor.)

---
[x] Add a party size limit (default 3 + PC), visible in the party menu, and configurable in Config (combine Inventory and Party into Adventure Settings).

Done: added Max Party Size (default 3, excluding the PC), shown as "N / max" in the Party header and configurable in Config. The Config "Inventory" section is now "Adventure Settings" containing Max Party Size + Max Carry Slots. The limit is enforced server-side on creating a new member and on re-adding a benched one (400 when full); the ADD MEMBER button and the re-add control disable when the party is full. Verified live: bench → active list updates; create/​re-add blocked at the limit.

---
[x] When a party member's name is mentioned by Narrator, it should be highlighted, similar to items.

Done: party-member names mentioned in chat are now highlighted as inline chips (blue tint) alongside item chips (gold), via a generalized entity-chip pass over the rendered narration.

---
[x] Nice to have: Highlighted items and party members in chat should be links that open the relevant Inspector view

Done: item and member chips are clickable. Each chip carries data-entity/data-id; a delegated click handler opens the relevant Inspector (item → item detail, member → member sheet) and stops the click from also triggering message edit. Hover highlights the chip.

---
[x] When I click something in Inspector view that opens another Inspector view, include a small back link next to the sub-header (above the big header), e.g. "◀ Back | Sub-header". For example, clicking an Equipment Item in the Party Member view.

Done: drilling into a sub-inspector now records a breadcrumb. uiStore gains selectInto() (remembers the current selection as `back`) and goBack(); normal navigation via select() clears it. The inspector header renders "◀ BACK | <sub-header>" above the big name when a back target exists. Wired drill-downs: clicking an equipped item in the PC/Party view, clicking an item/member chip in chat, and jumping to a quest's related-lore chip — each shows a Back link to the entity you came from.

---
[x] The Party Members' equipment still aren't in Lore > Items. They should be there. A Party Member cannot have an item equipped that's not in the Lorebook.

Done (unified item system, per your choice): the separate Item Catalog table is gone — items are now lorebook entries (cat='items') carrying the item fields (type/slot/maxStack/uses/rarity), so every item (including all equipment) appears in Lore → Items. Equipment, inventory, narrator item-grants/equips, and prompt name-resolution all read from the lorebook, so a member can only equip an item that exists in the Lorebook. The /items API surface is unchanged (now lorebook-backed) and item mutations keep the Lore list in sync. The Lore → Items list opens items in the richer Item inspector. Seed converts the 20 catalog items into Lore → Items (same stable IDs, so existing equipment still resolves) and drops the 2 duplicate narrative item entries. Verified live on a fresh DB: /items=20, Lore→Items=20, inventory/equipment resolve, stacking + capacity enforced, and a narrator action granted "Starlight Vial" + swapped Tifa's equipment successfully.

---
[x] Descriptions of equipment items worn by party members aren't included in the prompt -> should be.

Done: the prompt builder now renders each equipped item as "slot: Name — description" for both the player character and party members (resolved from the lorebook item entries). Verified live — e.g. "rightHand: Worn Lute — A well-traveled lute…".

---
[x] In Config, also add a field for Post-History Instructions, which will be added to the prompt always after everything else, right before the user's prompt. This is empty by default.

Done: NarratorConfig gains `post_history_instructions` (empty by default), editable in Config → Narration → Post-History Instructions. The prompt builder injects it as the final system message immediately before the user's message. Verified live (prompt tail: …, system[post-history], user). Carried in export/import.

---
[x] In Config > Model, can the model list be already populated even without an API key? Right now I have to put in API key -> click Save -> and then the dropdown model list appears. Unintuitive. One option is to also have an "Apply" button next to the API field, and clicking it will then show the model dropdown list (which is entirely hidden before this) - in this example the API and Model categories could then be combined.

Done: OpenRouter's model list is public, so the server /models endpoint no longer requires a key, and Config auto-loads the list when the panel opens — the dropdown is populated immediately, before any key is entered (no Save dance, no Apply button needed). Verified live: /models returns 339 models with no API key set. (Went with auto-populate rather than the Apply-button/combine-categories option since it removes the extra click entirely; happy to combine the API + Model sections too if you'd prefer.)

---
[x] Chat Location Banner should also show Time of Day (Morning, Day, Afternoon, Evening, Night) and Weather. These should be added into the action protocol and parsed as information in the location banner, on the right-hand side, aligned vertically with the location label. The time of day should also have an icon next to it.

Done: the action protocol now also accepts "timeOfDay" (Morning/Day/Afternoon/Evening/Night) and "weather" (short descriptor), parsed and stored per message exactly like "location". ChatMessage gains time_of_day + weather columns (round-tripped through schema/get/export/import). The chat banner now has the location on the left and, on the right (top-aligned with the LOCATION label), the time of day with a matching icon (sunrise/sun/partly-cloudy/sunset/moon for the five values) above the weather text. The client derives the most-recently-declared time/weather from history (reverts on swipe/delete), and the right block is hidden until the narrator establishes them. Verified deterministically (parse extracts timeOfDay/weather; DB column round-trips) — live emission is model-dependent, same as the other action-block fields.

---
[x] Layout: Let's combine Scene and Party tabs into one. PC will be at the top, then a section for Party, and then a section for Scene, with the scene items. We'll call this combined menu tab "Home" or "Main".

Done: the Scene and Party tabs are merged into a single "Home" tab (house icon) — the icon rail is now Home / Items / Quests / Lore / Config, and Home is the default tab. The new HomeView shows the PC at the top, then a "Party" section (active list + "Not in Party" + size counter + Add Member), then a "Scene" section (current location + the POI items). Removed the old PartyView and ScenePOIList components.

[x] Layout #2: Let's make the Party Member (and PC) portraits in the left-hand menu larger. We don't have to show the Field Skill tag there to save some space.

Done: portraits in the Home menu are now 48px (was 36px), and the Field Skill tag was removed from member rows to save space.

[x] Layout #3: The PC and Party Members should be clearer cards / elements with a border rather than floating list items.

Done: the PC and party members are now bordered cards (1.5px border-line on bg-bg2, brightening to border-line2 on hover; selected card uses border-line2 on bg-bg0) instead of borderless floating rows. The bench/re-add control sits in its own bordered cell on the right of each card.

---
[x] Combine API and Model config containers

Done (commit 8a0eb6d): the API and Model sections are merged into one "API & Model" container — API key + Load Models at the top, then the model picker and sampling params.

---
[x] PC and Party Member cards: Let's have the Portrait Image fit the card vertically (edge to edge), and set to the left edge of the card. It'll be a part of the card and bigger this way.

Done (commit cbb5e5d): portraits now fill the card's full height, flush to the left edge (56px wide with a right divider), instead of a small inset avatar — part of the card and larger. Cards use items-stretch + overflow-hidden so the image clips to the rounded card; empty portraits show a Cinzel initial.

---
[x] Let's make Items into Cards, with an icon denoting the type instead of a portrait, and the rarity shown as a thicker border on the left edge of the card, but so that the Selection Border doesn't overlap it.

Done (commit 0379440): inventory rows are cards with a type icon (shield/wrench/flask/key/gem/box per item type) replacing the rarity dot, and rarity shown as a thick 3px bar on the left edge. The gold selection accent bar is offset to the right of the rarity bar so they never overlap.

---
[x] Having three command prompts open when I run Run.bat is a bit much. Can some / all be combined?

Done (commit de53744): both servers now run in the single launcher window (Start-Process -NoNewWindow) instead of two extra cmd windows — logs interleave there and closing the one window stops both. The launcher also waits for backend /health before opening the browser.

---
[x] Same as the Item card, but let's apply it to all Lorebook items. Lorebook > Item should be the same as Inventory. Characters should be similar to PC cards. Everything else is the Item card without Rarity border.

Done (commit 17dff20): the inventory item card was extracted into a shared <ItemCard> and reused for Lore > Items (sourced from the full item catalog), so it matches the Inventory exactly. Lore > Characters now render as PC-style cards with an edge-to-edge initial avatar. World/Monsters/Spells use the same item-card layout with a per-category icon and no rarity bar. Disabled entries are dimmed; the lock glyph is kept.

--- 
[x] Let's remove the Scene category and items from the Home menu. Instead, let's be simple and just have the Narrator highlight important items and character names. They don't need to be clickable or anythng such. Simplify.

Done (commit 064cf47): the Scene section and its POI list are removed from the Home menu. Item and character names are now highlighted inline in the narration with a subtle gold emphasis (and the PC's name too), but are no longer clickable chips — the click-to-inspect wiring was removed. Highlighting is automatic from the catalog/roster names; no manual setup needed.

---
[x] Move Spotlight Rule and Post-History Instructions into a new category in Config: Advanced.

Done: Config now has a dedicated "Advanced" section (after "Narration") containing Spotlight Rule and Post-History Instructions, which were moved out of the Narration section. Narration now holds just Narrator Instructions and First Message.

---
[x] For Narrator Instructions and First Message, add a small button to the right side of the header row that shows a larger text editor field, e.g. overlayed over the UI with a semi-opaque black background, for easier writing of longer texts.

Done: each of those two fields has a small expand button that opens a modal editor overlaid on the UI (semi-opaque black backdrop) with a large ~80vh textarea bound to the same value, plus a DONE button; clicking the backdrop or pressing Escape closes it. Edits persist into the field and are saved by the normal SAVE button. (Superseded by the next item: the trigger is now a shared corner button on every textarea rather than a header-row button, for consistency across all boxes.)

---
[x] Add the same modal text editor to every editable text box (not single-row text fields)

Done: extracted a shared <ExpandableTextarea> (client/src/components/common/ExpandableTextarea.tsx) — a textarea with a small corner "expand" button that opens the same modal editor — and used it for every multi-line text box: Config (Narrator Instructions, First Message, Spotlight Rule, Post-History Instructions), the Player Character and Party Member sheet descriptions/field-skill, the Inspector item/quest/lore editors, and the in-chat message editor. The component supports both the controlled (Config) and uncontrolled save-on-blur (sheet/inspector) textarea patterns used across the app. Single-row inputs (the chat input, name/number fields) are intentionally left alone.

---
[x] Don't let me send a message until Chronicler and other agents are done. Show an indicator for what's happening so the player doesn't think it's bugged.

Done: the chat input + SEND (and Regenerate/Swipe/Delete) are now blocked on a combined `busy` = narrator streaming OR the post-turn Chronicler running — not just the narration. While the Chronicler runs after a turn, a labelled indicator shows in the chat ("THE CHRONICLER IS RECORDING ···", book glyph), matching the narrator's "THINKING" indicator, so it's clearly working rather than frozen. The indicator/blocking only applies when world-building actually runs (skipped in Disabled mode).

---
[x] Let's rename Planning Mode to Edit Mode, and the Planner into Editor.

Done: all user-facing copy renamed — the Tools toggle now reads "Edit Mode", the chat header banner shows "EDIT MODE", the working indicator says "THE EDITOR IS WORKING", message tags show "⚙ EDITOR", the empty-thread hint and Config field ("Editor Instructions") follow suit, and the Editor's default core instructions open with "You are the Editor". (Internal code identifiers/the wire token still say "planner" to avoid a churny rename + DB migration; not user-visible.)

---
[x] If the Editor has a response with multiple turns, the previous turn gets replaced in the chat log, rather than showing each response.

Done: run_planner_agent now accumulates the Editor's prose across every tool round (joined with blank lines) instead of discarding all but the final round, so a multi-step reply ("let me check… [acts] …done") is preserved as one growing message rather than each round replacing the last. Removed the per-round `discard` for the Editor; rounds are separated with a blank line as they stream.

---
[x] Let's separate Edit view of Inspector and make it the domain of the Edit mode. To edit anything, I need to toggle on the Edit mode. When I do, Inspector will always be in the Edit mode. When I return to Narration mode, Inspector will always be in the View mode. Toggling the Mode will therefore remember which Inspector view I have open. Adding lore entries and party members will also be the domain of the Edit Mode. Basically, if you think of this like a Game Engine, Narrator mode is the "Runtime / Play Mode", and Edit mode allows me to work on the game.

Done: the Inspector's view/edit state is now driven entirely by the chat's Edit Mode — Edit Mode on → the Inspector edits; Narration → it views. The per-entity EDIT/VIEW toggle button is replaced by a read-only EDITING/VIEW badge. Your current selection is preserved when you flip modes (selection lives in uiStore, the mode flag in chatStore), so toggling remembers what you have open and just swaps view↔edit. Adding is now Edit-Mode-only: the "+ NEW ENTRY" (Lore) and "+ ADD MEMBER" (Home) buttons only appear in Edit Mode. (Play vs Edit, engine-style.)

---
[x] When Edit Mode is active, switch over to an alternative color scheme (can be its own .css), to visually communicate which mode is currently active. This could be purple / blue in colour.

Done: added client/src/edit-theme.css — while Edit Mode is on, <body> gets an `edit-mode` class (toggled in App.tsx) that overrides the design tokens to a cool indigo/violet palette (surfaces, borders, the gold accent → periwinkle/violet, scrollbars). Because index.css maps every Tailwind utility to var(--…) via @theme inline, this re-skins the entire app at runtime with no component changes. Default warm/gold = Play; indigo/violet = Edit.

---
[x] Edit Mode - Deleting Lore entries manually: Let's add a "Remove entries" button above New Entry. Clicking Remove Entries will show a tick box next to the items in that current page. Remove Entries button changes to "Remove selected entries". New entry button is replaced with Cancel button. The operation is also canceled if I switch the view.

Done: in Edit Mode the Lorebook footer has a "Remove Entries" button above "+ New Entry". Clicking it enters remove-mode: a checkbox appears next to each card in the current category, the button becomes "Remove Selected Entries (N)", and "+ New Entry" is replaced by "Cancel". Clicking a card toggles its checkbox; locked entries (e.g. Scenario) are disabled/un-checkable. Removing asks for a confirm, then deletes the selected lore/items. Switching category — or leaving Edit Mode / the panel — cancels the operation.

---
[x] Both Modes - Entry sorting. Below the search entry field, add a label: "Sorting:" and then a dropdown with By newest, Alphabetically, By type, By rarity, and then a button to switch Descending / Ascending next to that (just an arrow up or arrow down).

Done: a "Sorting:" row sits below the search field (in both modes) with a dropdown (By newest, Alphabetically, By type, By rarity) and an asc/desc arrow toggle. Newest uses insertion order; type sorts by item type (and is a no-op within a single lore category); rarity orders c→u→r→e→l (items). Applies to both the items catalog and lore-entry lists.

---
[x] Move the Mode toggle into the location banner, e.g. on the left side of the location headers (a Play button, like in Unity editor?)

Done: the Edit-Mode toggle moved out of the chat Tools menu and into the location banner as a Unity-style Play button on the left of the location/mode header. It's lit gold while playing (Narration) and a dim "edit" glyph in Edit Mode; clicking toggles between Play and Edit. The banner title still reads "Edit Mode" when active.

---
[x] Switching Equipment for characters should be availabe in View / Play Mode.

Done: the Equipment section of the PC and Party Member sheets is now editable in View/Play mode too (it uses the same equip slot field as Edit Mode), since managing gear is a play action rather than world-editing. The rest of the sheet stays read-only in View mode. Changes save immediately via the existing flush/PUT path. (Removed the now-unused read-only EquipViewField.)

---
[ ] Campaigns and Adventures, a huge, foundational, multi-step change. Give this a good think before you start implementing it. 

  [ ] Differentiate between Campaign (lore entries, narrator instructions, first message, spotlight rule, post-history), and Adventure (PC, party members, quests, inventory, adventure settings, chat). A Campaign (Game) is the world and specific narrator settings. Adventure (Save File) is the journey of a specific PC and their party in it. This categorization should be reflected in the Config too.

  [ ] Portraits should also be included. This could call for a restructuring of the project structure: Campaigns could be folders, and Adventures folders within those, and Characters folders within those. Separate databases / jsons, which are compiled at runtime? Just a thought, you're the expert, but it should be logical and modular, something that's easy to share and import.

  [ ] Allow for multiple Adventures (Saves, Save Files, etc.) within a Campaign. This could be its own Save / Load view. Each Save Game shows the portraits of the PC and Party, their current location, and the day (how many in-game days since start), etc. I can Load an existing Adventure, start a new Adventure, or delete an Adventure.

  [ ] Allow for multiple Campaigns (Games). Each Campaign has its own Adventures linked to it. Adventures do not carry over to another Campaign. This could be accessible through Config, e.g. Active Campaign category with a dropdown of the Campaigns, and a button for + New Campaign, and a Delete Campaign button. When I select a new Campaign, there could also be a confirmation button before the Campaign is switched. You can show a loading screen at this point.

  [ ] When I create a new Campaign, switch over to it. The default view of a new Campaign is the Edit Mode, with a default message shown that gives a structured start to creating the Campaign.

  [ ] When I export a Campaign, I can choose which Adventures (if any) are included in that export. The export (if using the new project structure), can be just a zip file.

  [ ] When I import a Campaign, always create a new Campaign. If it has the same name as another Campaign, you can add e.g. "(2)" after the second one, etc. If using the zip file, then I should be able to import the zip file.

  ---