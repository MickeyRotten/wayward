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
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)
    equipment: Mapped[dict] = mapped_column(JSON, default=dict)


class PartyMember(Base):
    __tablename__ = "party_members"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    basic_info: Mapped[dict] = mapped_column(JSON, default=dict)
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)
    equipment: Mapped[dict] = mapped_column(JSON, default=dict)
    field_skill: Mapped[dict] = mapped_column(JSON, default=dict)
    last_spoke_turn: Mapped[int] = mapped_column(Integer, default=0)


class Scenario(Base):
    __tablename__ = "scenarios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    description: Mapped[str] = mapped_column(Text, default="")


class NarratorConfig(Base):
    __tablename__ = "narrator_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    instructions: Mapped[str] = mapped_column(Text, default="")


class OpenRouterSettings(Base):
    __tablename__ = "openrouter_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    api_key: Mapped[str] = mapped_column(String, default="")
    model_id: Mapped[str] = mapped_column(String, default="")
    temperature: Mapped[float] = mapped_column(Float, default=0.7)
    max_tokens_response: Mapped[int] = mapped_column(Integer, default=1000)
    max_context_tokens: Mapped[int] = mapped_column(Integer, default=128000)


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
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
