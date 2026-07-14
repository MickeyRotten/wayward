import datetime
import uuid

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


# ── Scope schemas ─────────────────────────────────────────────────
# Each model is tagged with the attached-database schema it lives in:
#   (none)      → app.db    : global app config + the active-scope pointer
#   "campaign"  → campaign.db: the world (lore, items, narrator config)
#   "adventure" → adventure.db: a save file (PC, party, quests, chat, …)
# At runtime database.py ATTACHes the active campaign.db and adventure.db onto
# the app.db connection, so one session reads/writes all three transparently.
CAMPAIGN = {"schema": "campaign"}
ADVENTURE = {"schema": "adventure"}


# ── App (global) ──────────────────────────────────────────────────

class AppState(Base):
    """Singleton pointer to the active campaign + adventure (app.db)."""
    __tablename__ = "app_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    active_campaign_id: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    active_adventure_id: Mapped[str | None] = mapped_column(String, nullable=True, default=None)


class OpenRouterSettings(Base):
    __tablename__ = "openrouter_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    api_key: Mapped[str] = mapped_column(String, default="")
    model_id: Mapped[str] = mapped_column(String, default="")
    temperature: Mapped[float] = mapped_column(Float, default=0.7)
    top_p: Mapped[float] = mapped_column(Float, default=1.0)
    min_p: Mapped[float] = mapped_column(Float, default=0.0)
    top_k: Mapped[int] = mapped_column(Integer, default=0)
    frequency_penalty: Mapped[float] = mapped_column(Float, default=0.0)
    presence_penalty: Mapped[float] = mapped_column(Float, default=0.0)
    repetition_penalty: Mapped[float] = mapped_column(Float, default=1.0)
    max_tokens_response: Mapped[int] = mapped_column(Integer, default=1000)
    max_context_tokens: Mapped[int] = mapped_column(Integer, default=128000)
    # Adventure-ish setting kept app-global for now (move to per-adventure scope
    # in a later phase).
    max_party_size: Mapped[int] = mapped_column(Integer, default=3)
    # Agentic tool loop: cap on tool round-trips per turn, and a master toggle
    # for the agent loop vs. the legacy <<<ACTIONS>>> text-block path.
    max_tool_rounds: Mapped[int] = mapped_column(Integer, default=6)
    use_tools: Mapped[bool] = mapped_column(Integer, default=True)
    # Auto-retry a turn's model call on an error or safety-filter block, up to
    # this many extra attempts before surfacing the error (0 = off). Retries
    # happen per model call, so tools that already ran are never re-applied.
    auto_retry_count: Mapped[int] = mapped_column(Integer, default=2)
    # Chronicler (world-building agent): when/how it creates lore/quests/members.
    # 'disabled' | 'confirmation' | 'auto'. Optional separate model (blank => main).
    worldbuilding_mode: Mapped[str] = mapped_column(String, default="confirmation")
    worldbuilding_model_id: Mapped[str] = mapped_column(String, default="")
    # Action Suggestions (contextual quick-action buttons): optional separate
    # model (blank => main model). Enablement is per-campaign, on
    # NarratorConfig.action_suggestions_enabled — this only picks which model
    # runs it, kept app-wide like worldbuilding_model_id/summary_model_id.
    action_suggestions_model_id: Mapped[str] = mapped_column(String, default="")
    # History summarisation: compress older turns when context usage exceeds this
    # fraction of the budget; optional separate model (blank => main model).
    summary_threshold: Mapped[float] = mapped_column(Float, default=0.7)
    summary_model_id: Mapped[str] = mapped_column(String, default="")
    # Vision agent: describes player-attached chat images so the (possibly
    # text-only) narrator/editor can react to them. Blank model => the built-in
    # default (google/gemma-3-4b-it). Can run on a separate OpenRouter key
    # (e.g. a free-tier key) — vision_use_same_key toggles which one is used.
    vision_model_id: Mapped[str] = mapped_column(String, default="google/gemma-3-4b-it")
    vision_use_same_key: Mapped[bool] = mapped_column(Integer, default=True)
    vision_api_key: Mapped[str] = mapped_column(String, default="")
    # How the vision agent describes images (blank => built-in default).
    vision_instructions: Mapped[str] = mapped_column(Text, default="")
    # Text-to-speech (optional Chatterbox install — see server/ai/tts.py).
    # tts_autoplay: speak each finished narration turn automatically.
    tts_enabled: Mapped[bool] = mapped_column(Integer, default=False)
    tts_autoplay: Mapped[bool] = mapped_column(Integer, default=True)


# ── Campaign (the world) ──────────────────────────────────────────

class NarratorConfig(Base):
    __tablename__ = "narrator_configs"
    __table_args__ = CAMPAIGN

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    instructions: Mapped[str] = mapped_column(Text, default="")
    # Additional narrator-facing instruction blocks, editable in Config.
    # Empty string => fall back to the built-in default at prompt-build time.
    action_instruction: Mapped[str] = mapped_column(Text, default="")
    spotlight_rule: Mapped[str] = mapped_column(Text, default="")
    # Appended after everything else, immediately before the user's message.
    post_history_instructions: Mapped[str] = mapped_column(Text, default="")
    # The opening narration shown before the player's first turn (drop-capped,
    # included in context). Editable in Config.
    first_message: Mapped[str] = mapped_column(Text, default="")
    # Core instructions for the Planner persona (Planning mode). Editable in
    # Config; falls back to the built-in default when blank.
    planner_instructions: Mapped[str] = mapped_column(Text, default="")
    # Action Suggestions: AI-generated choice options rendered in-chat — the
    # primary text-adventure interaction. Default on for new campaigns (an
    # extra small LLM call per turn; existing campaigns keep their setting).
    action_suggestions_enabled: Mapped[bool] = mapped_column(Integer, default=True)
    # Custom guidance for the Action-Suggestion agent. Blank => the built-in
    # default (action_suggester.ACTION_SUGGESTIONS_GUIDANCE) is used.
    action_suggestions_instructions: Mapped[str] = mapped_column(Text, default="")
    # 'separate' (default): the options come from their own small LLM call after
    # the turn. 'inline': the narrator appends a machine-read <<<OPTIONS>>> line
    # to its narration — no extra call; reroll still uses the separate agent.
    action_suggestions_mode: Mapped[str] = mapped_column(Text, default="separate")
    # One generated option per rule, in order (each editable in Config). Null/
    # empty => action_suggester.DEFAULT_OPTION_RULES (good/neutral/dark/wildcard).
    action_option_rules = mapped_column(JSON, nullable=True)
    # Scripted choice options shown with the First Message (turn 0), where the
    # suggester can't run — authored alongside the first message itself.
    first_message_options = mapped_column(JSON, nullable=True)
    # Skill checks: offer the narrator a server-rolled d20 skill_check tool for
    # uncertain, consequential actions (rendered as dice chips in chat).
    dice_enabled: Mapped[bool] = mapped_column(Integer, default=True)


class LorebookEntry(Base):
    __tablename__ = "lorebook_entries"
    __table_args__ = CAMPAIGN

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String, default="")
    content: Mapped[str] = mapped_column(Text, default="")
    keywords: Mapped[list] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(Integer, default=True)
    permanent: Mapped[bool] = mapped_column(Integer, default=False)
    locked: Mapped[bool] = mapped_column(Integer, default=False)
    cat: Mapped[str] = mapped_column(String, default="world", index=True)

    # Structured Scenario fields — only meaningful on the single Scenario row
    # (title == "Scenario", permanent=True, locked=True). Holds a dict with
    # keys setting/historyBrief/species/geography/techAndMagic/other (all
    # strings). This is the source of truth for the Scenario tab; `content` is
    # derived from it via compose_scenario_content() (server/ai/scenario.py) so
    # the lore-injection pipeline needs no changes. May be `{}` or `None` for
    # rows that predate this column — always read via `entry.scenario_fields or {}`.
    scenario_fields: Mapped[dict] = mapped_column(JSON, default=dict)

    # Item fields — only meaningful when cat == "items" (the unified item
    # catalog lives in the lorebook). title == item name, content == item desc.
    item_type: Mapped[str | None] = mapped_column(String, nullable=True)
    slot: Mapped[str | None] = mapped_column(String, nullable=True)
    max_stack: Mapped[int] = mapped_column(Integer, default=1)
    uses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rarity: Mapped[str] = mapped_column(String, default="c")


class LorebookConfig(Base):
    __tablename__ = "lorebook_config"
    __table_args__ = CAMPAIGN

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    injection_order: Mapped[dict] = mapped_column(
        JSON,
        default=lambda: {
            "world": 0, "characters": 10, "items": 20,
            "monsters": 30, "spells": 40,
        },
    )
    injection_position: Mapped[dict] = mapped_column(
        JSON,
        default=lambda: {
            "world": "top", "characters": "top", "items": "top",
            "monsters": "top", "spells": "top",
        },
    )


# ── Adventure (a save file) ───────────────────────────────────────

class PartyBinding(Base):
    """A character's per-adventure state. Character *identity* (basicInfo,
    fieldSkill, portraits) lives in a portable file — see server/db/characters.py
    — keyed by ``character_id``. This binding holds only what's specific to THIS
    adventure: the role (the single pc vs a party member), worn equipment (slot →
    ItemInstance id), party membership, last-spoke turn, and list order.
    """
    __tablename__ = "party_bindings"
    __table_args__ = ADVENTURE

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    character_id: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, default="member")  # pc | member
    equipment: Mapped[dict] = mapped_column(JSON, default=dict)
    in_party: Mapped[bool] = mapped_column(Integer, default=True)
    last_spoke_turn: Mapped[int] = mapped_column(Integer, default=0)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


# Legacy — retained only so the one-time characters→files migration can read
# prior data. The app no longer writes these tables.
class PlayerCharacter(Base):
    __tablename__ = "player_characters"
    __table_args__ = ADVENTURE

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    basic_info: Mapped[dict] = mapped_column(JSON, default=dict)
    equipment: Mapped[dict] = mapped_column(JSON, default=dict)


class PartyMember(Base):
    __tablename__ = "party_members"
    __table_args__ = ADVENTURE

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    basic_info: Mapped[dict] = mapped_column(JSON, default=dict)
    equipment: Mapped[dict] = mapped_column(JSON, default=dict)
    field_skill: Mapped[dict] = mapped_column(JSON, default=dict)
    last_spoke_turn: Mapped[int] = mapped_column(Integer, default=0)
    in_party: Mapped[bool] = mapped_column(Integer, default=True)


class StorySummary(Base):
    __tablename__ = "story_summaries"
    __table_args__ = ADVENTURE

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    content: Mapped[str] = mapped_column(Text, default="")
    summary_up_to_turn: Mapped[int] = mapped_column(Integer, default=0)


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = ADVENTURE

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    role: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(Text)
    turn_number: Mapped[int] = mapped_column(Integer, index=True)
    variant: Mapped[int] = mapped_column(Integer, default=0)
    speaker: Mapped[str] = mapped_column(String, default="narrator")
    # Which chat thread this message belongs to: 'narrator' (the story) or
    # 'planner' (Planning mode). Planner messages never enter narration context.
    mode: Mapped[str] = mapped_column(String, default="narrator")
    location: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    time_of_day: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    weather: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    # In-game day number, declared by the narrator (like location/time/weather).
    day: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    spotlight_reason: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    applied_inventory_deltas: Mapped[list | None] = mapped_column(JSON, nullable=True, default=None)
    applied_equipment_changes: Mapped[list | None] = mapped_column(JSON, nullable=True, default=None)
    # Editor (planner) messages only: the ordered list of {name, result} tool
    # actions the Editor took that turn — a durable record of what it built/edited.
    editor_actions: Mapped[list | None] = mapped_column(JSON, nullable=True, default=None)
    # Player-attached image (user messages only): filename inside the adventure's
    # chat_images/ folder, plus the vision agent's description of it — the
    # description is what the (possibly text-only) narrator/editor actually sees.
    image_path: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    image_description: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )


class ChatEvent(Base):
    """A persistent in-chat toast — a small notice rendered inline in the story
    log, separate from the freeform ChatMessage prose.

    Two flavours, distinguished by ``tethered``:
      - Chronicler notices (``kind='chronicler'``, ``tethered=True``) belong to
        the turn that spawned them and are removed when that turn is deleted /
        regenerated / swiped (like the Chronicler's lore effects).
      - Player-action notices (``kind='item'``, ``tethered=False``) — equipping,
        dropping, adding an item — are not tied to any turn and are never removed
        by turn edits.
    ``turn_number`` is the anchor the client renders the toast *after* (the turn
    in play when it was created); it is not a foreign key.
    """
    __tablename__ = "chat_events"
    __table_args__ = ADVENTURE

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    turn_number: Mapped[int] = mapped_column(Integer, default=0)
    kind: Mapped[str] = mapped_column(String, default="item")
    text: Mapped[str] = mapped_column(Text, default="")
    tethered: Mapped[bool] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )


class InventoryStack(Base):
    __tablename__ = "inventory_stacks"
    __table_args__ = ADVENTURE

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_id: Mapped[str] = mapped_column(String, nullable=False)
    count: Mapped[int] = mapped_column(Integer, default=1)


class ItemInstance(Base):
    __tablename__ = "item_instances"
    __table_args__ = ADVENTURE

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    item_id: Mapped[str] = mapped_column(String, nullable=False)
    count: Mapped[int] = mapped_column(Integer, default=1)


class Task(Base):
    """A single to-do the party has taken on — the flat successor to the old
    Quest+QuestObjective system. A task can be big ("Save the World") or small
    ("Find someone who knows about the sigil"); there's no nesting. ``status`` is
    active | completed | failed; ``sort_order`` gives the dynamic list its order.
    """
    __tablename__ = "tasks"
    __table_args__ = ADVENTURE

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    text: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String, default="active", index=True)  # active | completed | failed
    notes: Mapped[str] = mapped_column(Text, default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


# Legacy — retained only so the one-time quests→tasks migration and old-zip
# imports can read prior data. The app no longer writes these tables.
class Quest(Base):
    __tablename__ = "quests"
    __table_args__ = ADVENTURE

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default="active")
    desc: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    related_lore: Mapped[list] = mapped_column(JSON, default=list)


class QuestObjective(Base):
    __tablename__ = "quest_objectives"
    __table_args__ = ADVENTURE

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    quest_id: Mapped[str] = mapped_column(String, nullable=False)
    text: Mapped[str] = mapped_column(String, default="")
    done: Mapped[bool] = mapped_column(Integer, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class WorldbuildingProposal(Base):
    """A Chronicler-proposed create/update to lore, quests, or party members.

    Tool calls from the world-building agent are captured here rather than
    executed directly, so Confirmation mode can surface them for approval and
    Auto mode can apply + record them. ``payload`` holds the operation fields.
    """
    __tablename__ = "worldbuilding_proposals"
    __table_args__ = ADVENTURE

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    turn_number: Mapped[int] = mapped_column(Integer, default=0, index=True)
    kind: Mapped[str] = mapped_column(String)          # lore | quest | quest_objective | member
    operation: Mapped[str] = mapped_column(String)     # create | update
    target_id: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    summary: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default="pending", index=True)  # pending | accepted | rejected | failed
    note: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )


# Convenience groupings for per-scope table creation/migration.
APP_TABLES = [AppState.__tablename__, OpenRouterSettings.__tablename__]
CAMPAIGN_SCHEMA = "campaign"
ADVENTURE_SCHEMA = "adventure"
