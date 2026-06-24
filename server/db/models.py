import datetime
import uuid

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


class PlayerCharacter(Base):
    __tablename__ = "player_characters"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    basic_info: Mapped[dict] = mapped_column(JSON, default=dict)
    equipment: Mapped[dict] = mapped_column(JSON, default=dict)


class PartyMember(Base):
    __tablename__ = "party_members"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    basic_info: Mapped[dict] = mapped_column(JSON, default=dict)
    equipment: Mapped[dict] = mapped_column(JSON, default=dict)
    field_skill: Mapped[dict] = mapped_column(JSON, default=dict)
    last_spoke_turn: Mapped[int] = mapped_column(Integer, default=0)
    in_party: Mapped[bool] = mapped_column(Integer, default=True)


class NarratorConfig(Base):
    __tablename__ = "narrator_configs"

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
    max_carry_slots: Mapped[int] = mapped_column(Integer, default=12)
    max_party_size: Mapped[int] = mapped_column(Integer, default=3)


class StorySummary(Base):
    __tablename__ = "story_summaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    content: Mapped[str] = mapped_column(Text, default="")
    summary_up_to_turn: Mapped[int] = mapped_column(Integer, default=0)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    role: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(Text)
    turn_number: Mapped[int] = mapped_column(Integer)
    variant: Mapped[int] = mapped_column(Integer, default=0)
    speaker: Mapped[str] = mapped_column(String, default="narrator")
    location: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    time_of_day: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    weather: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    spotlight_reason: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    applied_inventory_deltas: Mapped[list | None] = mapped_column(JSON, nullable=True, default=None)
    applied_equipment_changes: Mapped[list | None] = mapped_column(JSON, nullable=True, default=None)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )


class InventoryStack(Base):
    __tablename__ = "inventory_stacks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_id: Mapped[str] = mapped_column(String, nullable=False)
    count: Mapped[int] = mapped_column(Integer, default=1)


class LorebookEntry(Base):
    __tablename__ = "lorebook_entries"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String, default="")
    content: Mapped[str] = mapped_column(Text, default="")
    keywords: Mapped[list] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(Integer, default=True)
    permanent: Mapped[bool] = mapped_column(Integer, default=False)
    locked: Mapped[bool] = mapped_column(Integer, default=False)
    cat: Mapped[str] = mapped_column(String, default="world")

    # Item fields — only meaningful when cat == "items" (the unified item
    # catalog lives in the lorebook). title == item name, content == item desc.
    item_type: Mapped[str | None] = mapped_column(String, nullable=True)
    slot: Mapped[str | None] = mapped_column(String, nullable=True)
    max_stack: Mapped[int] = mapped_column(Integer, default=1)
    uses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rarity: Mapped[str] = mapped_column(String, default="c")


class LorebookConfig(Base):
    __tablename__ = "lorebook_config"

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


class Quest(Base):
    __tablename__ = "quests"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default="active")
    desc: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    related_lore: Mapped[list] = mapped_column(JSON, default=list)


class QuestObjective(Base):
    __tablename__ = "quest_objectives"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    quest_id: Mapped[str] = mapped_column(String, nullable=False)
    text: Mapped[str] = mapped_column(String, default="")
    done: Mapped[bool] = mapped_column(Integer, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
