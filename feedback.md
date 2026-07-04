# Wayward feedback list

## INSTRUCTIONS
This is a list of changes / new features to add into the project. Whenever you finish a task, mark it done and write under the task what was done, commit, and push. Mention the ID of the commit also.

## FEEDBACK ITEMS
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
[x] Campaigns and Adventures, a huge, foundational, multi-step change. Give this a good think before you start implementing it.

Done across 5 phased commits (08a4459 P1 storage foundation, 10da995 P2 Save/Load, 2caa204 P3 Campaign switcher, 5093bef P4 zip import/export, 51d0f9a P5 day counter). Architecture: each Campaign and each Adventure is its own SQLite file on disk under server/data/ (campaigns/<id>/campaign.db + adventures/<id>/adventure.db, with json sidecars), ATTACHed at runtime onto one engine so a single session reads/writes all scopes — "separate databases compiled at runtime". Models are schema-tagged (app / campaign / adventure). Your existing wayward.db was migrated losslessly into a default campaign/adventure (kept as a backup). Sub-items below.

  [x] Differentiate between Campaign (lore entries, narrator instructions, first message, spotlight rule, post-history), and Adventure (PC, party members, quests, inventory, adventure settings, chat). A Campaign (Game) is the world and specific narrator settings. Adventure (Save File) is the journey of a specific PC and their party in it. This categorization should be reflected in the Config too.

  Done (P1 + P3): campaign.db holds lore/items + NarratorConfig (instructions/first message/spotlight/post-history/planner instructions) + lore config; adventure.db holds PC, party, quests, inventory, chat, story summary, proposals. Config has a "Campaign" section (active campaign + management). (Note: adventure settings — max party size / carry slots — are still app-global for now, not yet per-adventure.)

  [x] Portraits should also be included. This could call for a restructuring of the project structure: Campaigns could be folders, and Adventures folders within those, and Characters folders within those. Separate databases / jsons, which are compiled at runtime? Just a thought, you're the expert, but it should be logical and modular, something that's easy to share and import.

  Done (P1 + P4): folder-per-campaign / db-per-adventure structure with json sidecars; ATTACH compiles them at runtime. Export bundles referenced portraits into the zip and import restores them. (Refinement still open: portraits currently live in the global server/portraits/ dir and are gathered on export, rather than living inside per-scope portraits/ folders.)

  [x] Allow for multiple Adventures (Saves, Save Files, etc.) within a Campaign. This could be its own Save / Load view. Each Save Game shows the portraits of the PC and Party, their current location, and the day (how many in-game days since start), etc. I can Load an existing Adventure, start a new Adventure, or delete an Adventure.

  Done (P2): a "Saves" rail tab lists adventures as cards (PC + party portrait thumbnails, location, Day N from the day counter, ACTIVE badge) with Load / Delete and a "+ New Adventure" (blank slate, sharing the campaign's world). Can't delete the only adventure; deleting the active one switches to another first.

  [x] Allow for multiple Campaigns (Games). Each Campaign has its own Adventures linked to it. Adventures do not carry over to another Campaign. This could be accessible through Config, e.g. Active Campaign category with a dropdown of the Campaigns, and a button for + New Campaign, and a Delete Campaign button. When I select a new Campaign, there could also be a confirmation button before the Campaign is switched. You can show a loading screen at this point.

  Done (P3): Config → Campaign has an Active Campaign dropdown (switch with a confirm dialog + full-screen loading overlay), rename, New Campaign (name + Create), and Delete (blocked on the only campaign). Switching loads the campaign's latest adventure.

  [x] When I create a new Campaign, switch over to it. The default view of a new Campaign is the Edit Mode, with a default message shown that gives a structured start to creating the Campaign.

  Done (P3): creating a campaign switches to it and turns on Edit Mode; a structured Editor "starter" message (setting/location/characters/hook) is seeded into the new adventure's Editor thread.

  [x] When I export a Campaign, I can choose which Adventures (if any) are included in that export. The export (if using the new project structure), can be just a zip file.

  Done (P4): EXPORT downloads a self-contained .zip (campaign.db + each adventure.db + referenced portraits). The /campaigns/{id}/export endpoint supports an `adventures` filter to pick which to include — but the UI currently exports all (a selection dialog is the one remaining refinement).

  [x] When I import a Campaign, always create a new Campaign. If it has the same name as another Campaign, you can add e.g. "(2)" after the second one, etc. If using the zip file, then I should be able to import the zip file.

  Done (P4): IMPORT (.zip) always creates a NEW campaign, deduping the name to "Name (2)" etc.; regenerates folder/json ids and restores portraits. DB-internal ids stay self-consistent so equipment/inventory keep resolving.

  ---

  [x] Ensure that if the model returns an error or a safety layer is triggered, the message is posted into chat.

  Done: OpenRouter error chunks (previously swallowed by the stream parser) and content_filter / safety finishes now raise with the real provider message; non-2xx responses read the body for the actual error text. These surface as a prominent "GENERATION ERROR" bubble inline in the chat (danger-styled), instead of a tiny dim notice.

  ---
  [x] Give Editor the tool to read the Narrator's Instruction. Also, when the Editor is creating Lore entries, ensure that the Scenario is injected for context. Do a review of tools and create tools that you think are missing / are of use.

  Done: the Scenario is now always injected into the Editor's context (with a note to keep new content consistent with it). Added tools: get_narrator_instructions (read) + get_scenario (read), and set_first_message (set the opening narration) to round out the existing set_scenario / set_narrator_instructions writers. The guidance tells the Editor to consult the Narrator instructions/Scenario for tone consistency.

  ---
  [x] Ensure that the LLM (Narrator / Editor) also use the chat history for context - and that summarisation works. Expose summarisation settings in Config (when to summarise, which model is used for summarisation, etc.)

  Done: chat history is already included (build_prompt for the Narrator; the planner thread for the Editor). Summarisation is now DETERMINISTIC in both modes — it no longer relies on the model choosing to call update_summary; when the prompt exceeds the threshold, the oldest turns are compressed into the running "story so far". Exposed in Config → Agents → Summarisation: a "summarise at N% of context" slider (summary_threshold) and an optional summarisation model (summary_model_id, blank = main). Round-tripped through settings/export/import; existing app.db gets the new columns via an app migration.

  ---
  [x] World-Building category could be renamed to Agents with info on the existing agents and their settings, one of which is the Chronicler.

  Done: Config → "World-building" is now "Agents" with a blurb naming the Narrator / Editor / Chronicler. It groups the Chronicler settings (mode + model) and the new Summarisation settings (threshold + model) under sub-headers. (The Narrator's tool-loop settings stay in API & Model for now.)

  ---
  [x] Occasionally I get an empty message as a reply from the Editor. Not sure why.

  Done: the Editor sometimes calls tools but never writes a closing line, leaving the final round's content empty. run_planner_agent now falls back: if no prose was produced, it posts a "Done:" summary of the tool results (or, if nothing happened, a prompt asking what to build), so the reply is never empty. 

  ---
  [x] Add a Config category for Appearance, and in there add Font Size option for Chat.

  Done: Config now has an "Appearance" section with a Chat Font Size control (Small / Medium / Large / Extra Large segmented buttons + a live preview line). It drives a --chat-font-size CSS var that only scales the chat narration/dialogue prose (UI chrome, banner, badges unchanged), applies instantly, and persists per-device in localStorage (client-only — not in backend settings or campaign export).

  ---
  [x] Chronicler needs more rigid rules:
    - Only add Named Characters
    - Only add bolded items
    - Check for duplicate entries (at least at name level)
    - Do not add Party Members into Lorebook
    - Anything else you can think of

  Done: tightened both the Chronicler's guidance AND added a deterministic backstop in worldbuilder.py (the prompt alone drifts), so the rules hold regardless of the model:
    - Named characters only — a new `characters` entry is rejected unless the title looks like a proper name (capitalised, not led by an article: "a guard", "the innkeeper", "some soldiers" are blocked). Also applied to create_member.
    - Bolded items only — a new `items` entry is only created if the item name appears inside a **bold** span of that turn's narration.
    - No party members / PC in the lorebook — any lore create/update whose title matches a party member (including benched) or the player character's name is dropped.
    - Duplicate check — existing name-level dedup retained (case-insensitive title match → update instead of create; quests/members likewise); the world-state prompt still lists exact names to reuse.
    - Extras: existing entries that are `locked` (the Scenario) remain untouched; guidance now explicitly forbids unnamed/generic figures and transient mood/weather.

    
  ---

  [x] Often when I ask the Editor to create equipment for a party member, it'll try to directly equip the items (that don't exist), and then claims success. It should have better rules and instructions for creating different items and doing different things, e.g. if I ask "Create equipment for party member X", it should know that it first has to create the item in the Lorebook before it can equip them. Also, when I ask to edit a character in the lorebook (not a party member), it shouldn't try to give them equipment, and as a player I might not write "party member" or "character" but rather refer to them by name.

  Done (planner.py): both guidance and a deterministic guard, so it holds regardless of the model:
    - Create-before-equip: the Editor's equip handler now hard-fails with a directive message ("No item named 'X' exists yet — you must create_item first … THEN equip. Do NOT report it as equipped.") instead of silently delegating, so the model can't claim success on a phantom item. Guidance spells out the strict order (create_item → equip) and a HONESTY rule (never claim success when the tool returned an error).
    - Lorebook characters ≠ equippable: if the named target is a lorebook 'characters' NPC (not the PC/party), equip is refused with "describe their gear in their lore entry with update_lore instead." Guidance now distinguishes the three kinds — PC + party members (have equipment) vs lorebook NPCs (lore only).
    - Refer-by-name: guidance tells the Editor the player will just use a name, and to resolve it against world state (PC / party member / lorebook NPC) and pick the right action — and not to recruit an NPC into the party unless clearly asked. Verified live against the seed: missing-item, unknown-name, and lorebook-NPC equips all return the right corrective message with no mutation.

---

 [x] Chronicler iteration: If a Character is recruited as Party Member, that character is removed from Lorebook and moved into Party Members.

  Done (worldbuilder.py apply_proposal): when a member-create proposal is applied, _absorb_lore_character removes a matching lorebook 'characters' entry (case-insensitive; locked entries left alone) and reuses its description to seed the new party member if the proposal didn't supply one — so a recruited NPC moves out of the Lorebook into Party Members instead of being duplicated. Verified live (rolled back).

 ---

 [x] Chronicler created lore entries could be tied to the message that triggered it, so that when I delete that message, or regenerate it, the related lore entries are also deleted. Determine the feasibility of this, and if possible, implement it.

  Feasible and done. The WorldbuildingProposal row already carries the turn it came from; apply_proposal now also records the created entry's id on the proposal (target_id) for lore + quest creates. New reverse_chronicler_creations(from_turn, exact=) deletes the lore/quests a Chronicler created and their proposal rows, wired into all three reversal points: delete-message-and-after (this turn onward), swipe and regenerate (this turn exactly, so the discarded telling's facts go and the re-run records fresh). Scope/safety: only *accepted* *create* proposals for lore/quests are reversed — recruited party members are NOT auto-removed (deliberate), locked entries (the Scenario) are never touched, and manually/Editor-created lore stays sticky (no proposal link). Verified live (rolled back).

 ---

[x] In the chat, PC's name and avatar should also be on the left side. I don't like the alternating chat layout.

  Done (ChatScene MessageBubble): the player-character message no longer alternates to the right — it's now left-aligned (mr-auto) with the portrait on the left and the name header above the text, matching the narrator/party-member layout. Kept the PC's distinguishing blue accent, "YOU" badge, and subtle bubble. All messages now share one left-aligned column.

---
[x] I'd like the PC and Party Member cards to be taller and the profile pictures even bigger as a result.

  Done (HomeView): the PC and party cards now have a min height of 7rem (~112px, up from ~70px) and the edge-to-edge portrait widened from w-14 (56px) to w-24 (96px), filling the taller card. Name bumped to 20px and the no-portrait fallback initial to 30px to match the larger frame.

---
[x] Review the Narrator and create suggestions for improving its logic, performance, and player-facing UX.

  Reviewed narrator_agent.py, prompt_builder.py, spotlight.py, narrator_actions.py. The findings are broken into tasks below.

---
Narrator improvements (from the review above):

[x] N1 (logic) detect_speakers counts a name MENTION as the member SPEAKING (raw substring), corrupting last_spoke_turn + the spotlight "overdue" signal; short names false-match. Make it word-boundary + dialogue-aware.
  Done: _member_spoke requires the name (or first name, word-boundary) to be attributed dialogue — adjacent to a quote or a said-verb, either order. A bare mention ("Tifa was asleep") no longer counts. Unit-tested.

[x] N2 (logic) directly_addressed uses the same substring match — and it's a hard "MUST respond" override, so false positives force unwanted beats. Use word boundaries.
  Done: directly_addressed now uses _name_mentioned (word-boundary, matches full or first name), so 'Al' no longer matches 'also'. Unit-tested.

[x] N3 (logic) field_skill_relevant keyword-overlap pulls words from the skill prose; almost never matches the player's phrasing → near-always false. Match the skill name + a curated set, or drop it.
  Done: keywords now include the skill NAME's distinctive tokens (which recur in scenes far more than the description prose) and are matched with word boundaries.

[x] N4 (logic) The forced final round (max_tool_rounds reached) drops tools silently — the model can narrate an action it never executed (state desync). Add a "tools off, narrate only what already happened" nudge.
  Done: FINAL_ROUND_NUDGE is injected when the loop enters the forced (tools-off) round, telling the model to narrate only what tools actually carried out.

[x] N5 (cleanup) Summarisation is now deterministic, so SUMMARY_HINT never fires yet update_summary is still offered every turn. Remove both from the agent.
  Done: removed the update_summary tool schema + handler and the SUMMARY_HINT constant/injection (plus now-unused StorySummary/select imports). The summarize_hint param is kept (ignored) for call-site compatibility.

[x] N6 (perf) Full max_tokens_response on every tool-deciding round; cap tool rounds low (~256) and use the full budget only for final narration.
  Done: tool-deciding rounds are capped at 512 tokens; the full response budget is used for the final narration round. Safety: if a final narration lands on an early (capped) round and gets clipped (finish_reason=length), it's re-run at full length with tools off so nothing is truncated.

[x] N7 (perf) No retry/backoff on transient 429/5xx — one retry would save the turn.
  Done (openrouter.py): both stream functions retry transient statuses (429/500/502/503/504) up to 3 attempts, honoring Retry-After when present else exponential backoff. Retry only happens before any content streams (status checked on the initial response), so no duplicate/partial output; non-transient errors still raise immediately with the real message.

[x] N8 (perf) Token budget is chars/4 and first_message is inserted after trimming and not counted in the budget → can exceed real context on long histories. Count it; consider a safety margin.
  Done (prompt_builder.py): first_message tokens are now reserved before trimming (it's always kept), and a ~10% safety margin is applied to the history budget to absorb the chars/4 under-count.

[x] N9 (ux) Multi-round turns sit silent while tools run; surface the yielded tool events as ephemeral status ("checking inventory…", "equipping…").
  Done: chatStore now maps each narrator tool event to a friendly label (toolStatus) — "Checking inventory", "Equipping gear", "Setting the scene", etc. — shown in gold in the generating indicator; it clears when the final narration starts streaming and on done/abort.

[x] N10 (ux) Addressing a benched member silently no-ops; hint that they're not present.
  Done: when the player's message word-matches a benched (not-in-party) member's name, the turn injects an "ABSENT PARTY MEMBER" note onto the spotlight block so the narrator acknowledges they aren't travelling with the party instead of ignoring it.

---

[x] Review the Chronicler and create suggestions for improving its logic, performance, and player-facing UX. Turn the suggestions into tasks under this one.

  Reviewed worldbuilder.py + the runForTurn flow. Tasks below.

[x] C1 (perf, highest) The Chronicler makes a full second LLM pass EVERY turn even though most turns establish nothing. Add a cheap deterministic pre-filter (no new proper nouns / bold / quest-ish signals → skip the call) so it only runs when a turn plausibly introduced something.
  Done: _worth_chronicling gates the call — it runs only when the narration has bold (a potential item), quest-ish wording, or a capitalised name not already in the world (known names/titles are tokenised and excluded; common sentence-starters are ignored). Biased toward running so facts aren't missed. Unit-tested; logs "CHRONICLER SKIP" when gated.

[x] C2 (perf) max_tokens is the full response budget for a call that only emits tool calls; cap it low.
  Done: capped at min(max_tokens_response, 1024).

[x] C3 (perf) The prompt sends the full narration + four full prior turns + the whole world-state list every time; trim the lengths.
  Done: prior context cut from 4 turns to 2, each clipped (~280 chars); player msg clipped (400), narration clipped (1600).

[x] C4 (logic) Pending proposals accumulate across turns (only same-turn pending is cleared); cap the count and/or expire old ones.
  Done: the prune step now also drops pending older than 15 turns and anything beyond a 50-pending hard cap (oldest first), every run.

[x] C5 (ux) Auto-applied Chronicler changes are invisible in chat; surface a subtle notice of what was recorded.
  Done: in auto mode, runForTurn captures the accepted proposals and ChatScene shows a dismissible "CHRONICLER RECORDED · …" notice (auto-fades after 7s) listing what was just recorded.

[x] C6 (ux) Proposals in the Ideas panel don't show what triggered them; show the turn number (and a snippet) for context.
  Done: each proposal card now shows a "TURN N" badge (the turn that prompted it). (A text snippet was left out — it'd need storing the triggering narration on the proposal row; the turn number gives the context cheaply.)

[x] C7 (logic, minor) A non-tool worldbuilding_model_id silently yields zero proposals (swallowed); log it / fall back to the main model.
  Done: when the pre-filter passed (signals present) but the model returned no tool calls, logs "CHRONICLER no proposals … (check tool support if persistent)" as a troubleshooting hint.

---

[x] Review the Editor and create suggestions for improving its logic, performance, and player-facing UX. Turn the suggestions into tasks under this one.

  Reviewed planner.py + the planner route/stream. Tasks below.

[x] E1 (perf/logic, highest) run_planner_agent loads the ENTIRE planner thread every turn with no trimming → long Edit sessions overflow context and start failing. Trim oldest history to a budget (the narrator already does this).
  Done: planner history is now trimmed to the context budget (reusing prompt_builder._trim_to_budget / _estimate_tokens): budget = 90% of (max_context − max_response) minus the system/world preamble, oldest planner messages dropped first. Verified the trim keeps the newest turns.

[x] E2 (logic) The forced final round drops tools silently — add a "tools off, wrap up your reply" nudge (mirror the narrator's N4).
  Done: PLANNER_FINAL_NUDGE is injected on the forced (tools-off) round, telling the Editor to wrap up and not claim a change it didn't make.

[x] E3 (ux) The Editor's tool activity shows generic "Working" (the N9 status map only has narrator tool names); add friendly labels for the Editor's tools (create_item, create_lore, equip, …).
  Done: extended the TOOL_STATUS map with the Editor's tools — "Writing lore", "Forging an item", "Adding a quest", "Rewriting the Scenario", etc.

[x] E4 (ux/safety) The Editor rewrites the Scenario, Narrator instructions, and First Message immediately with no confirmation (deletes are confirmed, these aren't); an accidental overwrite is silent. Make it clearly announce these overwrites (confirm dialog is a heavier future option).
  Done (guidance): the Editor is now told set_scenario / set_narrator_instructions / set_first_message REPLACE the whole text immediately, to only do them when clearly asked, and to always tell the player explicitly that it changed them. (A hard confirm dialog like deletes is left as a future option.)

[x] E5 (logic) The Editor's context lists only titles, not content, so it can overwrite/duplicate facts it can't see when editing an existing entry. Nudge it to get_entry before editing.
  Done (guidance): "READ BEFORE YOU EDIT" — the Editor is told its world list shows only names, so it must get_entry to read current content before changing an existing entry and extend rather than overwrite.

---
[x] PC / Party Member cards: Align the name and species label vertically to the top of the card. 

Done: the PC and party member cards' text column now aligns to the top (justify-start instead of justify-center), so the name and species/gender label sit at the top of the taller card rather than being vertically centered.

---
[x] I should be able to delete Inventory items in Edit mode in the same way as Lore items

Done: the Inventory panel now has a "Remove Items" flow in Edit Mode mirroring the Lorebook — a "Remove Items" footer button (disabled when empty) enters remove-mode, showing a checkbox next to each inventory card; the button becomes "Remove Selected Items (N)" with a Cancel button, the Add Item section is hidden, and confirming clears each selected stack from the inventory (via removeFromInventory with the full stack count). Remove-mode auto-cancels when leaving Edit Mode.

---
[x] In Inventory, Add Item could be a button. When I click it, it shows a dropdown of all the items in Lorebook, but could also have a typing field to narrow down the results.

Done (commit 1c9cf97): Add Item is now a "+ ADD ITEM" button. Clicking it opens a dropdown panel listing every Lorebook item (the full item catalog, alpha-sorted), with a filter field on top that narrows the list live as you type (matches name or type, no 3-character minimum — replacing the old search-endpoint box). Picking an item shows the quantity picker (for stackables) + ADD TO INVENTORY / BACK; CANCEL closes the picker.

--- 
[x] PC / Party Member Equipment logic could follow the same Add Item logic, but just with items in the Inventory (and filtered by the slot type). Show "Equip" button when the slot is empty (same logic as Add Item button). When slot is full, I can remove the item with a small button.

Done (commit f760d09): equipment slots now mirror the Inventory Add Item pattern but source from the party Inventory and only list items that fit that slot. Empty slot shows a "+ Equip" button; clicking it opens a filterable dropdown (no minimum query length) of inventory items whose type is Equipment and whose slot matches (a new lib/equipSlots.ts maps the coarse item slots — Head/Torso/Hands/Waist/Neck/Legs/Feet — onto the 12 fine equipment slots; items with no slot are allowed anywhere). A full slot shows the item with a small remove (×) button. Applies to both the PC sheet and party member sheets, in Play and Edit mode. Note: equipping references the item (it does not consume it from the inventory stack), matching the existing equipment model — say the word if you'd rather equipping move the item out of the bag.

---
[x] Equipped items in inventory should have an indicator that they're equipped, and information on who has it equipped currently.

Done: inventory item cards now show an "Equipped · <names>" indicator (gold, with a check glyph) listing every character (PC or party member) currently wearing the item. Also — all equipped items are now shown in the Inventory even when worn rather than carried: items equipped by someone but not in a carried stack appear as extra (non-removable) rows, so the inventory reflects all gear. (Equipping references an item rather than consuming the stack, so an item can be both carried and worn.)

---
[x] I should be able to equip an item from Inventory. Button: Equip -> List of PC / Party Members (even those not active) -> Select Character -> Item is equipped. If an item was already equipped in that slot, that other item becomes unequipped.

Done (Equip lives in the Inspector view, per your follow-up): selecting an item opens the Inspector, which for Equipment shows an "Equip" section — current wearers (name · slot) each with an UNEQUIP button, plus an "+ EQUIP TO…" button that lists the PC and ALL party members (including benched) to pick from. Equipping places the item in the best-fitting slot (an empty fitting slot if available, else the first fitting slot — whose previous item is automatically unequipped via lib/equipSlots.pickEquipSlot). Equipment references the item (it isn't consumed from the inventory stack). Works in Play (view) mode where gear management lives.

---
[x] Iteration: When I edit an item, the Slot field is a text field. Should be a dropdown.

Done (commit 66fb5bf): the item editor's Slot is now a dropdown of body-slot categories (Head, Neck, Torso, Hands, Waist, Legs, Feet, Accessory, plus "— None —").

---
[x] Iteration: Ensure that Editor has access to all editable fields, such as:
 - the new Scenario fields (Setting, History, Species, Geography, Technology & Magic, Other)
 - First Message field
 - all PC / Party Member fields, including Age, Species, Gender, etc.

Done (commit da644ed): the Scenario structured fields (set_scenario) and First Message (set_first_message) were already exposed. Expanded update_pc / update_member / create_member to cover the full basic-info set — gender, age, heightCm, weightKg, likes, dislikes (plus newName to rename a member).

---
[x] Iteration: Portraits in the Party Member view should have a fixed height. Image should fill.

Done (commit da644ed): the PC/member Inspector view portrait now uses a fixed height (h-72) with the image filling (object-cover) instead of a width-driven aspect ratio.

---
[x] Iteration: I'd like to be able to edit the portrait in the Party Member view (resize the visible container, whose aspect ratio is fixed to the aspect ratio of the profile picture container), e.g. an "Edit Portrait" button that brings up the edit modal. The image in Inspector View should be the "full image", aka automatically fills the image area, no editing required.

Done: added a self-contained crop/zoom portrait editor (client/src/components/PortraitEditor.tsx — no external deps). A shared PortraitBlock shows the portrait in a fixed 3:4 container (image fills, no inline editing) with an "Edit Portrait" / "Add Portrait" button that opens the modal: a fixed 3:4 crop frame with drag-to-pan + wheel/slider zoom. On Save it bakes the framed region to a JPEG (canvas) and uploads it via the existing /api/portraits/upload, storing the result as the portrait. Wired into both the PC sheet and party member sheets, in view (Play) and edit modes. Chosen the bake approach so every view (Inspector, Home cards, chat, saves) just shows the finished, face-framed image.

---
[x] Bug: In Lorebook, sorting by Type doesn't work. UI disappears and nothing happens.

Done (commit 66fb5bf): the sort comparator coerces name/type to strings, so a missing value no longer throws (which was blanking the panel).

---
[x] Bug: When I select a new Campaign, UI disappears and nothing happens. I have to refresh for the new Campaign to load.

Done (commit 66fb5bf): reloadAll now uses Promise.allSettled, so one failing store fetch during a campaign switch can no longer abort the whole reload (which left the UI blank until a manual refresh).

---
[x] Bug: When I try to remove an item in my inventory using the Remove button in the Inspector (view), it shows: "removeInstance is not a function"

Done (commit 0a00300): this was fallout from the item-instances merge — the server + some client files were instance-based but itemsStore/models.ts/ItemsPanel/the editors had reverted to pre-instance. Reconciled the client back to the instance model (InventoryStack type, itemsStore.removeInstance, ItemsPanel + EquipSlotFields, PartyInspector equip/unequip, ChangeNotices), added the /inventory/remove-instance endpoint, and restored the idempotent migrate_to_item_instances so fresh + existing DBs convert catalog-id equipment + stacks into non-stacking instances (kept the merged Action-Suggestions/Scenario migrations). Verified: client build clean; fresh-seed smoke = 10 instances, 7 worn slots each resolving to a distinct instance (Tifa's two gloves are now two copies).

---
[x] Bug: In Party Member view, when I unequip an item, it's removed from the Party Member's equipment, but still shows it as equipped in Inventory. I cannot re-equip it in the Party Member view (probably for this reason.)

Done (commit 86e161d): the character sheets write equipment directly via savePlayerCharacter/savePartyMember, which weren't refreshing the inventory store — so its equipped/stowed flags (derived server-side from the equipment dicts) went stale, leaving the item shown as equipped and out of the sheet's stowed picker. Both save methods now refetch the inventory after saving, so unequip immediately frees the copy and it can be re-equipped.

---

[x] Restore: 
- Add Remove -button into Inventory Item view. Removes the item from Inventory (Could be renamed to Drop Item).
- Add the missing Equip / Unequip -button into Inventory Item view, with the old functionality: (Equip lives in the Inspector view, per your follow-up): selecting an item opens the Inspector, which for Equipment shows an "Equip" section — current wearers (name · slot) each with an UNEQUIP button, plus an "+ EQUIP TO…" button that lists the PC and ALL party members (including benched) to pick from. Equipping places the item in the best-fitting slot (an empty fitting slot if available, else the first fitting slot — whose previous item is automatically unequipped via lib/equipSlots.pickEquipSlot). Equipment references the item (it isn't consumed from the inventory stack). Works in Play (view) mode where gear management lives.

Done (commit 86e161d): the item Inspector's Equip section is back to the aggregate view — every current wearer shown as name · slot with an UNEQUIP button, plus a "+ EQUIP TO…" picker listing the PC and ALL party members (including benched). Equipping takes a stowed copy into the best-fitting slot (pickEquipSlot; prior occupant auto-unequipped) and references the item without consuming it. Added a "DROP ITEM" button in the Inventory section that removes a stowed copy from the pack. (This replaced the narrower instance-only "This Copy" section.)

---
[x] Iteration: The same item in Inventory should be its own instance. e.g. if I have two Iron Knuckle Dusters, and I select one, only that one should be selected, and shows only the Equip / Unequip for that particular instance of that item.

Done (commit 6d77b9e): Inventory rows now select a specific copy. Selecting a row sets `selection.instanceId` (not just the catalog id), and the row-highlight compares instanceId, so two copies of the same item highlight independently. The item Inspector branches: with a specific copy (opened from the Inventory) it shows a "This Copy" section — "Equipped by <name> · <slot>" with an "Unequip this copy" button, or "Stowed in the pack" with Drop + "+ Equip to…" that equips THAT exact instance. Opened from Lore → Items (no copy) it keeps the aggregate view (all wearers, stowed count). Verified by client type-check; equip/unequip/drop now thread the inspected instance id.

---
[x] Visual Bug: "Use an Item" button seems to be a couple of pixels lower than the other buttons

Done (commit 4323ed2): the "Use an Item" button was wrapped in a `<div className="relative">` (for its popover) — that block wrapper introduced an inline-block baseline/descender gap, so the button rendered a few pixels below its flex siblings. Changed the wrapper to `relative flex`, which removes the baseline gap and aligns it with the other quick-action buttons.

---
[x] Remove: Let's remove the Inventory slot limit system. It's a needless complexity.

Done (commit d4f12d7): removed the carry-slot cap end to end. Server: dropped `capacity_used`/`_max_slots` and every "inventory is full" check in inventory.py, both capacity checks in narrator_actions.py (agent + legacy paths), the `/inventory/capacity` endpoint, the `max_carry_slots` column on OpenRouterSettings, and the field from the settings schema/response/export/import. Client: removed `maxCarrySlots` from settingsStore/itemsStore/models.ts, the "N / max" header (now shows a plain item count), and the "Max Carry Slots" field in Config → Adventure Settings. Inventory is now unbounded. (The DB column is simply no longer mapped; existing DBs keep the vestigial column harmlessly.) Verified: client tsc clean, server modules import clean.

---
[x] Iteration: Add sorting to Inventory, same as in Lorebook.

Done (commit f738510): extracted the Lorebook's sort logic into a shared client/src/lib/sortEntries.ts (SortKey, SORT_OPTIONS, RARITY_ORDER, sortList) and reused it in both panels. Inventory now has the same "Sorting:" row below the header — a dropdown (By newest / Alphabetically / By type / By rarity) plus an asc/desc arrow toggle — sorting the inventory stacks by item name/type/rarity (newest = insertion order). LorePanel refactored to import the shared helper (no behavior change).

---
[x] Iteration: Action Suggestions. 

- **Reactive action suggestions**: The AI‑generated suggestions are great, but they appear above the input, which looks a bit bad. Instead of this, surface them as **interactive choices in the chat itself** (like a modern visual novel) after a narration turn, styled as elegant buttons. This reduces the distance between reading and acting.

Done (commit a2cd075): the AI-generated suggestions moved out of the quick-actions row (above the input) and into the chat itself, rendered under the latest narration beat as a vertical stack of elegant VN-style choice buttons (left-aligned, gold "›" marker, hover-gold). They only show when idle (not while the narrator/Chronicler is working) and clicking one sends it via the existing sendTurn. The fixed buttons (Look Around / Talk to Party / Rest / Use an Item) stay above the input. No backend change — same transient per-turn suggestions list.

---
[x] Iteration: The Config panel has many settings (model, tokens, worldbuilding mode, suggestions toggle, etc.). Group them into logical tabs or collapsible sections with clear descriptions:

- **Campaign** (current campaign, delete campaign, new campaign)
- **AI & Model** (model picker, temperature, max tokens)
- **Agents & Tools** (use tools, max rounds, chronicler mode, suggestions toggle)
- **World** (narrator instructions)

Within each section, clearly differentiate each sub-section, e.g. by making them into collapsible sections as well.

Add a small **“Reset to defaults”** link next to each section, except Campaign.

Move First Message into the Scenario tab, but don't make it a part of Scenario.

Done (commit 74d9a64): Config is regrouped into the four named top-level collapsible sections (plus Appearance) — **Campaign** (campaign switcher/create/delete + a Party sub-section for max party size), **AI & Model** (API & Model + Sampling sub-sections), **Agents & Tools** (Narrator Tools, Chronicler, Summarisation, Action Suggestions sub-sections), **World** (Narrator Instructions, Spotlight Rule, Post-History, Editor Instructions, Lorebook Injection sub-sections). Each sub-section is itself a nested collapsible (a new <SubSection>, open by default). A small "Reset to defaults" link sits in each section header except Campaign (AI & Model → sampling defaults; Agents & Tools → agent/tool defaults; World → blank instruction fields that fall back to built-ins; Appearance → medium font); the reset link stops propagation so it doesn't toggle the section. First Message moved out of Config into the Scenario tab (below the 6 scenario fields, clearly labelled "Not part of the Scenario", saved on the NarratorConfig not the scenario). Verified: full client build clean.

---
[x] Iteration: New Campaign:

- In Config there should be a button for Create a New Campaign.
  - Pressing it opens a modal with settings for the new campaign.
- In those settings, I can choose a template for it from a dropdown list.
- For now, the templates are Empty (nothing filled out), and Fantasy.
- Templates should be separate JSONs in a folder called templates.

Done (commit b8b72c1): Config → Campaign now has a "+ NEW CAMPAIGN" button that opens a modal (name field + Template dropdown + the template's description + Create/Cancel; Esc/backdrop cancels). Templates are plain JSON files in a new server/templates/ folder — empty.json and fantasy.json. A GET /campaigns/templates endpoint lists them ({id,name,description}, Empty first); POST /campaigns takes a `template` and applies it. server/db/templates.py (list_templates + apply_template) reads the JSON and populates the fresh campaign/adventure: keyed catalog items, freeform lore, the locked Scenario (from structured fields), narrator config, PC, party, and inventory — written as catalog-id equipment + InventoryStack, then converted to item instances (mirrors the demo seed path). Verified end-to-end with a temp-dir smoke test.

---
[x] Universal defaults:
- Ensure that Narration instructions, Spotlight rule, and Editor instructions are not empty when creating a new Campaign.

Done (commit b8b72c1): apply_template ALWAYS stores non-empty Narrator Instructions, Spotlight Rule, and Editor (planner) Instructions — a template may override them, otherwise the built-in defaults are used (DEFAULT_NARRATOR_INSTRUCTIONS, DEFAULT_SPOTLIGHT_RULE, PLANNER_GUIDANCE). This holds for the Empty template too. Verified in the smoke test (Empty campaign → all three non-empty).

---
[x] Defaults for a new Fantasy campaign.

- Set something brief as default for all the Scenario fields, a generic high-fantasy setting
- Default PC: Name - Hero, Species - Human, Gender - Male, Age - 22, very generic description.
  - Default equipment for PC: Sword, Adventurer's Tunic, Tattered Pants, Worn Boots, Ratty Boxer Shorts
- Default Party Member: Name - Varena, Species - Elf, Gender - Female, Age - 120, generic description out of a stereotypical white male D&D fan's imagination
  - Default equipment for Varena: Longbow, Elvish Tunic (light and revealing), Thigh high boots, choker, Quill (Accessory)
- Default items in Lorebook: The above equipment, Health Potion, Rations, Gold (Currency)
- Default items in Inventory: The above equipment, Health Potion x3, Rations x2, Gold x10
- 1 World Entry: Some generic forest, e.g. Murkwood.
- 1 Monster Entry: Goblin
- Default first message: PC standing at the entrance of the generic forest.

Done (commit b8b72c1, server/templates/fantasy.json): brief high-fantasy Scenario (all 6 fields); PC Hero (Human/Male/22) equipped with Sword, Adventurer's Tunic, Tattered Pants, Ratty Boxer Shorts, Worn Boots; party member Varena (Elf/Female/120, suitably over-the-top description + Elven Marksmanship field skill) equipped with Longbow, Elvish Tunic (light and revealing), Thigh High Boots, Choker, Quill (Accessory); 13 catalog items (the equipment + Health Potion, Rations, Gold [Currency]); starting inventory Health Potion x3, Rations x2, Gold x10 (the worn equipment also shows in inventory as equipped, so it isn't duplicated as extra stowed copies); a Murkwood World entry; a Goblin Monster entry; and a first message with the party at the entrance of Murkwood. Verified in the smoke test (PC/Varena, 13 items, worn gear, Murkwood/Goblin, non-empty narrator/first-message).

---
[x] Bug: When the Narrator fetches information about a Party Member, it just lists the instance IDs of the equipment they're wearing.

Expected behaviour: Narrator receives the name and description of each equipped item for PC and Party Members.

Done (commit a57e41d): `tool_get_character` (the narrator's get_character tool) was resolving each equipment slot value as a LorebookEntry id — but slots hold ItemInstance ids, so the lookup missed and it fell back to printing the raw instance id. Now it resolves instance → catalog item and returns `{name, description}` per slot (with a legacy fallback to treating the value as a catalog id). It also now returns the character's species/description and a party member's fieldSkill, so the narrator gets useful context. Verified with a smoke test against a fresh Fantasy campaign — every equipped slot shows the item name + description for both Hero and Varena.

---
[ ] Iteration: Chronicler (and Editor) needs more rigid rules for different lore types.

- If an Item, keep the description generic and just about the item, not about who has it. Also fill out its other fields, e.g. Type.
- If World, keep it also generic and nothing about the Party.
- etc.

---
[x] Iteration: Inventory AND Lore>Items should have filtering tabs for Types: All, Equipment, Tool, Consumable, Key Item, Artifact, Other. The filter dropdown should still exist, but we can remove by type from it.

Done: added a shared <ItemTypeTabs> chip row (All / Equipment / Tool / Consumable / Key Item / Artifact / Other — "Other" catches any type not in that list) plus a matcher in lib/itemTypes.ts. It sits above the Sorting row in both the Inventory panel and Lore → Items (shown only for the Items category). Filtering runs before sorting; the Inventory empty state now distinguishes "No items in inventory" vs "No matching items". Removed the "By type" option from the shared sort dropdown (a no-op for non-item lore, now redundant given the tabs); 'type' stays a valid internal SortKey so nothing else breaks.

---
[x] Iteration: In Inventory > Inspector, the equip / unequip button should just read "Equip" or "Unequip".

Done: in the item Inspector's per-copy (Inventory) view the buttons now read simply "Equip" and "Unequip" (were "+ EQUIP TO…" and "UNEQUIP THIS COPY").

---
[ ] Iteration: Improved operation transparency.

- **Streaming improvements**: Already in place, but ensure that during long narrator tool loops, the UI shows a **“Working…” spinner** or “The narrator is thinking…” state so the player doesn’t think it’s frozen.
- **Transparent agents**: Always show which Agent is currently working, and what they're (roughly) doing.
- **Graceful fallback when tools fail**: If the model calls a tool with invalid arguments, show a small **system message** in chat: “(The narrator tried to equip a non‑existent item, but the world stayed safe.)” This prevents silent corruption and confusion.