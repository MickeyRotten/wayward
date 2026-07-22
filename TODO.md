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
[x] Clarify whether the **custom sampling parameters actually take effect when Reasoning is enabled**, and add a way to **turn Reasoning off**.
  Done: (1) **Clarification** — sampling params DO take effect with reasoning on. In `_apply_sampling` (`server/ai/openrouter.py`) the sampling keys (`top_p`/`min_p`/`top_k`/penalties) and the `reasoning` key are independent entries on the same request body; nothing suppresses sampling when reasoning is set. (Any clamping of `temperature`/`top_p` during a thinking phase is provider-side, not Wayward's.) (2) **Turn Reasoning off** — the backend already supported an `"off"` sentinel (`reasoning:{enabled:false}`) used only by the narrator's budget recovery; now surfaced as an explicit **Off** option in Config → AI & Model → Reasoning Effort (distinct from "Provider default", which leaves the model's own setting untouched). Accepted server-side (`settings.py` whitelist now includes `off`) and round-trip tested. Commit: e3d8bb5. Follow-up (separate task, not done here): mobile slider ergonomics + a sampling-only "Reset to default parameters" — see the next item.

---
[ ] Make **adjusting sampling parameters usable on mobile** (currently difficult), and add a **"Reset to default parameters"** option.

---
[ ] Investigate **instruct templates**: do we use them, and should we? Does OpenRouter / the model expose which instruct template it uses? Automate as much as possible — ideally applying the **best per-model parameters for our use case** (stick to instructions, be creative within the frame of the system) without the user tuning them by hand.

---
[ ] Build a **more reliable tool-calling path**. The best *narrative* models aren't necessarily the newest, so they often struggle with complex formatting and tool calling — we need a system that keeps them working well regardless.
  Progress (front-loadable slice done; broader convergence still open): shipped the two highest-value pieces. (1) **Tool Mode** (`OpenRouterSettings.tool_mode`, Config → Agents & Tools): **Auto** (native tools if the model supports them, else the text protocol), **Native** (force the tool loop), **Text protocol** (force `<<<ACTIONS>>>` — reliable on strong narrative models weak at tool calling), **Off** (pure prose). Replaces the old binary that always sent a tool-capable-flagged model down the native path even when it called tools badly; `_resolve_narration_mode` (`server/api/chat.py`) resolves it, additive migration seeds it from the legacy `use_tools`. (2) **Hardened the `<<<ACTIONS>>>` text parser** (`parse_action_block`, `narrator_actions.py`): tolerant markers (spacing/casing), accepts a missing END marker, salvages the JSON via brace-matching, and ALWAYS strips the block from prose so malformed JSON can't leak. Also added **validate-and-repair** for native calls — malformed argument JSON is reported back to the model to resend instead of running with silent empty args (`narrator_agent.py`). Commits: 9735b0c, e3d8bb5, f4e83f0. **Still open** (deliberately not done): unifying the two paths onto one forgiving protocol with native as an accelerator, and shrinking the per-turn tool surface (carry scene state in a trailing block instead of a tool round). Those are the larger redesign; revisit as a dedicated task.

---
[x] Fix models (notably the **DeepSeek** family, which is preferred for narration) that write out a reply, delete it, and immediately write a follow-up that continues the deleted text.
  Done: two distinct root causes, both fixed. (1) **Preamble discard in the agentic loop** (the primary cause) — DeepSeek narrates the whole beat and THEN appends a state-write tool call in the same message; the loop treated that prose as throwaway "preamble", discarded it from the player's view, KEPT it in the transcript, and forced a re-narration — so the next round *continued* text the player could no longer see. Now: when the streamed content is a substantial narration and every requested tool is a non-prose-shaping safe write (`set_scene`/`grant`/`remove`/`consume`/`equip`/`unequip`), the loop keeps the beat and stops — no re-narration (`_SAFE_WRITE_TOOLS`, `narrator_agent.py`); and when content genuinely IS preamble and is discarded, it's dropped from the transcript too (`content=None`) so the model re-narrates cleanly instead of continuing deleted text. `skill_check`/read tools still force a clean redo (their result must be free to shape the prose). (2) **Inline `<think>…</think>` leak** — some DeepSeek deployments (custom/NIM providers, or providers without a reasoning parser) emit chain-of-thought inline in `delta.content` instead of a dedicated reasoning field, so it rendered as narration and then the real answer followed. Added a streaming-aware `_ThinkStripper` (`openrouter.py`) that routes a LEADING think block to the reasoning channel in both stream parsers, tolerant of a tag split across deltas; only a leading block is stripped, so ordinary prose containing the token is untouched. Commits: f92da11, f4e83f0. Tests: `test_think_stripping.py`, `test_narrator_preamble.py`.

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
