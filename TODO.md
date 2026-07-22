# Wayward feedback list

## INSTRUCTIONS
This is the running log of change requests and new features for the project. How to work it:

- **Pick up tasks from the top down**, but use judgement — group related items when it's more efficient.
- When you finish a task, **flip its checkbox** (`[ ]` → `[x]`) and write a short **Done** note directly under it: what actually changed, which files, and any follow-ups or deliberate omissions. Include the **commit ID**.
- **Commit and push** each finished task (or a coherent batch) to the working branch.
- If a task turns out to be infeasible, ambiguous, or a bad idea, **say so under the task** instead of silently skipping it — note why and what you'd do instead.
- **Keep the format**: one task per entry, `[ ]`/`[x]` checkbox, separated by `---`. **Newest tasks go at the bottom.**
- Related tasks are grouped under `###` sub-headings for readability; keep new items near their theme when it's obvious, otherwise append at the end.

> The full history of completed work lives in `TODO_old.md`.

## FEEDBACK ITEMS

### Config & the Editor
---
[x] Restrict the Editor so it can only edit the **Custom Instructions** (the free-text field within Story Style / Narrator Instructions), never the core Narrator Instructions.
  Done: removed the Editor's `set_narrator_instructions`/`get_narrator_instructions` tools + handlers from `server/ai/planner.py`. The Editor now shapes narration guidance through `set_story_style`'s `customInstructions` field (already supported) instead of overwriting the core Narrator role/behaviour. Updated the PLANNER_GUIDANCE (CONSISTENCY / SENSITIVE OVERWRITES lines) and module docstring to reflect the restriction, and the `prompt_builder.py` comment noting `NarratorConfig.instructions` is now a legacy override the Editor no longer writes. Commit: 3358014.

---
[x] Make the Editor's changes apply **live** in the UI. Right now most edits only show up after a refresh or an app relaunch.
  Done: `refreshWorldPanels()` (`client/src/state/chatStore.ts`, run after every planner turn + delete-apply) already refetched lore/tasks/party/items/inventory/narrator, but **not** the structured-config stores the Editor edits via `set_scenario`/`set_story_style`/`set_world_rules` — those went stale until reload. Added `useScenarioStore.fetchScenario()`, `useStoryStyleStore.fetchFields()`, and `useCampaignRulesStore.fetchRules()` to the refresh. Commit: 3358014.

---
[x] Allow a **separate model** to be assigned to the Editor (the same way the Chronicler and summariser already support model overrides).
  Done: added `OpenRouterSettings.planner_model_id` (app-scoped, blank → main model) with an additive ALTER migration (`database.py`), wired through `schemas.py`/`settings.py` as `plannerModelId`, resolved in `run_planner_agent` (`planner.py`) exactly like the Chronicler's `worldbuilding_model_id`. Client: `plannerModelId` on the shared type + `settingsStore`, and a new **Editor** subsection (Global, with a `ModelPicker`) in Config → AI & Model. Commit: 3358014.

### Models, parameters & reasoning
---
[ ] Clarify whether the **custom sampling parameters actually take effect when Reasoning is enabled**, and add a way to **turn Reasoning off**.

---
[ ] Make **adjusting sampling parameters usable on mobile** (currently difficult), and add a **"Reset to default parameters"** option.

---
[ ] Investigate **instruct templates**: do we use them, and should we? Does OpenRouter / the model expose which instruct template it uses? Automate as much as possible — ideally applying the **best per-model parameters for our use case** (stick to instructions, be creative within the frame of the system) without the user tuning them by hand.

---
[ ] Build a **more reliable tool-calling path**. The best *narrative* models aren't necessarily the newest, so they often struggle with complex formatting and tool calling — we need a system that keeps them working well regardless.

---
[ ] Fix models (notably the **DeepSeek** family, which is preferred for narration) that write out a reply, delete it, and immediately write a follow-up that continues the deleted text.

### The Chronicler & the Lorebook
---
[ ] Make the Chronicler's lore updates **additive** — append new information (with timestamps) instead of replacing an entry's whole content — and only touch an entry **when there is genuinely something new to add**, rather than rewriting the same entries every turn.

---
[ ] Give **item creation clearer, deterministic logic**. For example: only **bolded** words become Lore entries (whether an item or something else), and the Narrator gets explicit rules for **what to bold**. The Chronicler currently struggles to create items reliably.

### Tasks, Objectives & narrative direction
---
[ ] Add **Objectives** alongside Tasks — larger, direction-setting goals that steer the Narrator (e.g. "Gather a party of five", "Defeat the Demon Queen before the next Blood Moon rises"). Bigger than a Task. Look to **Dungeon World's Fronts, Stakes, and Portents** for inspiration.

---
[ ] Add a player **Wishlist** the Narrator keeps in mind (e.g. "I want to recruit an Elf to my party"), optionally with a **priority rating** per wish.

---
[ ] Make a **Task's Notes visible to the Narrator** and **editable by the Chronicler and the Editor**.

### Party members → Followers
---
[ ] **Replace the Party Member system with a Follower system.** Today there are two parallel systems — Lorebook characters and Party Members. Instead, drop the dedicated Party Member system entirely and reuse the Lorebook: recruited characters are ordinary character entries **tagged as Followers**. Expand the lore character entry with **more fields**, give Followers a **simpler, freeform-but-grounded equipment model**, and keep the current structured Equipment system for the **PC only**.

### Action Suggestions
---
[ ] Simplify Action Suggestions to a **single shared instruction** for all options. Drop the per-option instructions — situations vary too much for universal per-slot rules to work well.
