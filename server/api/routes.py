import json
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

PORTRAITS_DIR = Path(__file__).resolve().parent.parent / "portraits"

from server.ai.narrator_actions import execute_actions, parse_action_block, reverse_equipment_changes
from server.ai.item_detection import (
    apply_inventory_deltas,
    detect_item_use,
    reverse_inventory_deltas,
)
from server.ai.openrouter import chat_completion_stream, fetch_models
from server.ai.prompt_builder import build_prompt, estimate_prompt_tokens
from server.ai.spotlight import SpotlightSignal, compute_spotlight_signals, detect_speakers, format_spotlight_block
from server.ai.summarizer import (
    format_messages_for_summary,
    generate_summary,
    pick_messages_to_summarize,
    should_summarize,
)
from server.db.database import async_session
from server.api.schemas import (
    ChatMessageResponse,
    ChatMessageUpdate,
    ChatTurnRequest,
    ItemCatalogCreate,
    ItemCatalogUpdate,
    InventoryAddRequest,
    InventoryRemoveRequest,
    LorebookConfigSchema,
    LorebookConfigUpdate,
    LorebookEntryCreate,
    LorebookEntrySchema,
    LorebookEntryUpdate,
    NarratorResponse,
    NarratorUpdate,
    OpenRouterSettingsResponse,
    OpenRouterSettingsUpdate,
    PartyMemberCreate,
    PartyMemberResponse,
    PartyMemberUpdate,
    PlayerCharacterResponse,
    PlayerCharacterUpdate,
    QuestCreate,
    QuestObjectiveCreate,
    QuestObjectiveUpdate,
    QuestSchema,
    QuestUpdate,
    ScenarioResponse,
    ScenarioUpdate,
)
from server.db.database import get_session
from server.db.models import (
    ChatMessage,
    InventoryStack,
    ItemCatalogEntry,
    LorebookConfig,
    LorebookEntry,
    NarratorConfig,
    OpenRouterSettings,
    PartyMember,
    PlayerCharacter,
    Quest,
    QuestObjective,
    StorySummary,
    Scenario,
)

router = APIRouter(prefix="/api")


def _pc_to_response(pc: PlayerCharacter) -> PlayerCharacterResponse:
    return PlayerCharacterResponse(
        id=pc.id,
        schemaVersion=pc.schema_version,
        basicInfo=pc.basic_info,
        equipment=pc.equipment,
    )


def _pm_to_response(pm: PartyMember) -> PartyMemberResponse:
    return PartyMemberResponse(
        id=pm.id,
        schemaVersion=pm.schema_version,
        basicInfo=pm.basic_info,
        equipment=pm.equipment,
        fieldSkill=pm.field_skill,
        lastSpokeTurn=pm.last_spoke_turn,
    )


# ── Player Character ──────────────────────────────────────────────

@router.get("/player-character", response_model=PlayerCharacterResponse | None)
async def get_player_character(session: AsyncSession = Depends(get_session)):
    pc = (await session.execute(select(PlayerCharacter))).scalars().first()
    if not pc:
        return None
    return _pc_to_response(pc)


@router.put("/player-character", response_model=PlayerCharacterResponse)
async def upsert_player_character(
    data: PlayerCharacterUpdate,
    session: AsyncSession = Depends(get_session),
):
    pc = (await session.execute(select(PlayerCharacter))).scalars().first()
    if not pc:
        pc = PlayerCharacter()
        session.add(pc)
    pc.basic_info = data.basicInfo.model_dump()
    pc.equipment = data.equipment.model_dump()
    await session.commit()
    await session.refresh(pc)
    return _pc_to_response(pc)


# ── Portrait Upload ───────────────────────────────────────────────

@router.post("/portraits/upload")
async def upload_portrait(file: UploadFile):
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(400, "File must be an image")
    ext = Path(file.filename or "img.png").suffix or ".png"
    filename = f"{uuid.uuid4().hex}{ext}"
    dest = PORTRAITS_DIR / filename
    content = await file.read()
    dest.write_bytes(content)
    return {"filename": filename, "url": f"/portraits/{filename}"}


# ── Party Members ─────────────────────────────────────────────────

@router.get("/party-members", response_model=list[PartyMemberResponse])
async def list_party_members(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(PartyMember))
    return [_pm_to_response(pm) for pm in result.scalars().all()]


@router.post("/party-members", response_model=PartyMemberResponse, status_code=201)
async def add_party_member(
    data: PartyMemberCreate,
    session: AsyncSession = Depends(get_session),
):
    pm = PartyMember(
        basic_info=data.basicInfo.model_dump(),
        equipment=data.equipment.model_dump(),
        field_skill=data.fieldSkill.model_dump(),
    )
    session.add(pm)
    await session.commit()
    await session.refresh(pm)
    return _pm_to_response(pm)


@router.put("/party-members/{member_id}", response_model=PartyMemberResponse)
async def update_party_member(
    member_id: str,
    data: PartyMemberUpdate,
    session: AsyncSession = Depends(get_session),
):
    pm = await session.get(PartyMember, member_id)
    if not pm:
        raise HTTPException(404, "Party member not found")
    pm.basic_info = data.basicInfo.model_dump()
    pm.equipment = data.equipment.model_dump()
    pm.field_skill = data.fieldSkill.model_dump()
    await session.commit()
    await session.refresh(pm)
    return _pm_to_response(pm)


@router.delete("/party-members/{member_id}", status_code=204)
async def remove_party_member(
    member_id: str,
    session: AsyncSession = Depends(get_session),
):
    pm = await session.get(PartyMember, member_id)
    if not pm:
        raise HTTPException(404, "Party member not found")
    await session.delete(pm)
    await session.commit()


# ── Scenario ──────────────────────────────────────────────────────

@router.get("/scenario", response_model=ScenarioResponse)
async def get_scenario(session: AsyncSession = Depends(get_session)):
    s = (await session.execute(select(Scenario))).scalars().first()
    if not s:
        s = Scenario(description="")
        session.add(s)
        await session.commit()
    return ScenarioResponse(description=s.description)


@router.put("/scenario", response_model=ScenarioResponse)
async def update_scenario(
    data: ScenarioUpdate,
    session: AsyncSession = Depends(get_session),
):
    s = (await session.execute(select(Scenario))).scalars().first()
    if not s:
        s = Scenario()
        session.add(s)
    s.description = data.description
    await session.commit()
    return ScenarioResponse(description=s.description)


# ── Narrator Config ───────────────────────────────────────────────

@router.get("/narrator", response_model=NarratorResponse)
async def get_narrator(session: AsyncSession = Depends(get_session)):
    n = (await session.execute(select(NarratorConfig))).scalars().first()
    if not n:
        n = NarratorConfig(instructions="")
        session.add(n)
        await session.commit()
    return NarratorResponse(instructions=n.instructions)


@router.put("/narrator", response_model=NarratorResponse)
async def update_narrator(
    data: NarratorUpdate,
    session: AsyncSession = Depends(get_session),
):
    n = (await session.execute(select(NarratorConfig))).scalars().first()
    if not n:
        n = NarratorConfig()
        session.add(n)
    n.instructions = data.instructions
    await session.commit()
    return NarratorResponse(instructions=n.instructions)


# ── OpenRouter Settings ───────────────────────────────────────────

def _item_to_dict(item: ItemCatalogEntry) -> dict:
    return {
        "id": item.id,
        "kind": "item",
        "name": item.name,
        "type": item.type,
        "slot": item.slot,
        "maxStack": item.max_stack,
        "uses": item.uses,
        "rarity": item.rarity,
        "desc": item.desc,
    }


def _or_response(s: OpenRouterSettings) -> OpenRouterSettingsResponse:
    return OpenRouterSettingsResponse(
        modelId=s.model_id,
        temperature=s.temperature,
        topP=s.top_p,
        minP=s.min_p,
        topK=s.top_k,
        frequencyPenalty=s.frequency_penalty,
        presencePenalty=s.presence_penalty,
        repetitionPenalty=s.repetition_penalty,
        maxTokensResponse=s.max_tokens_response,
        maxContextTokens=s.max_context_tokens,
        maxCarrySlots=s.max_carry_slots,
        apiKeySet=bool(s.api_key),
    )


@router.get("/settings/openrouter", response_model=OpenRouterSettingsResponse)
async def get_openrouter_settings(session: AsyncSession = Depends(get_session)):
    s = (await session.execute(select(OpenRouterSettings))).scalars().first()
    if not s:
        s = OpenRouterSettings()
        session.add(s)
        await session.commit()
    return _or_response(s)


@router.put("/settings/openrouter", response_model=OpenRouterSettingsResponse)
async def update_openrouter_settings(
    data: OpenRouterSettingsUpdate,
    session: AsyncSession = Depends(get_session),
):
    s = (await session.execute(select(OpenRouterSettings))).scalars().first()
    if not s:
        s = OpenRouterSettings()
        session.add(s)
    if data.apiKey is not None:
        s.api_key = data.apiKey
    s.model_id = data.modelId
    s.temperature = data.temperature
    s.top_p = data.topP
    s.min_p = data.minP
    s.top_k = data.topK
    s.frequency_penalty = data.frequencyPenalty
    s.presence_penalty = data.presencePenalty
    s.repetition_penalty = data.repetitionPenalty
    s.max_tokens_response = data.maxTokensResponse
    s.max_context_tokens = data.maxContextTokens
    s.max_carry_slots = data.maxCarrySlots
    await session.commit()
    return _or_response(s)


# ── Item Catalog ──────────────────────────────────────────────────

@router.get("/items")
async def list_items(
    type: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    query = select(ItemCatalogEntry)
    if type:
        query = query.where(ItemCatalogEntry.type == type)
    items = (await session.execute(query)).scalars().all()
    return [_item_to_dict(i) for i in items]


@router.get("/items/search")
async def search_items(
    q: str,
    session: AsyncSession = Depends(get_session),
):
    if len(q) < 3:
        return []
    items = (await session.execute(
        select(ItemCatalogEntry).where(ItemCatalogEntry.name.ilike(f"%{q}%"))
    )).scalars().all()
    return [_item_to_dict(i) for i in items]


@router.get("/items/{item_id}")
async def get_item(
    item_id: str,
    session: AsyncSession = Depends(get_session),
):
    item = await session.get(ItemCatalogEntry, item_id)
    if not item:
        raise HTTPException(404, "Item not found")
    return _item_to_dict(item)


@router.post("/items", status_code=201)
async def create_item(
    data: ItemCatalogCreate,
    session: AsyncSession = Depends(get_session),
):
    item = ItemCatalogEntry(
        name=data.name,
        type=data.type,
        slot=data.slot,
        max_stack=data.maxStack,
        uses=data.uses,
        rarity=data.rarity,
        desc=data.desc,
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return _item_to_dict(item)


@router.put("/items/{item_id}")
async def update_item(
    item_id: str,
    data: ItemCatalogUpdate,
    session: AsyncSession = Depends(get_session),
):
    item = await session.get(ItemCatalogEntry, item_id)
    if not item:
        raise HTTPException(404, "Item not found")
    if data.name is not None:
        item.name = data.name
    if data.type is not None:
        item.type = data.type
    if data.slot is not None:
        item.slot = data.slot
    if data.maxStack is not None:
        item.max_stack = data.maxStack
    if data.uses is not None:
        item.uses = data.uses
    if data.rarity is not None:
        item.rarity = data.rarity
    if data.desc is not None:
        item.desc = data.desc
    await session.commit()
    await session.refresh(item)
    return _item_to_dict(item)


@router.delete("/items/{item_id}", status_code=204)
async def delete_item(
    item_id: str,
    session: AsyncSession = Depends(get_session),
):
    item = await session.get(ItemCatalogEntry, item_id)
    if not item:
        raise HTTPException(404, "Item not found")
    await session.delete(item)
    await session.commit()


# ── Inventory ─────────────────────────────────────────────────────

MAX_CARRY_SLOTS_DEFAULT = 12


async def _list_inventory_dicts(session: AsyncSession) -> list[dict]:
    """Return the current inventory as a list of stack dicts.

    Shape: ``{"itemId", "count", "item": {...} | None}`` — the same shape the
    /inventory route returns and that detect_item_use expects.
    """
    stacks = (await session.execute(select(InventoryStack))).scalars().all()
    result = []
    for s in stacks:
        item = await session.get(ItemCatalogEntry, s.item_id)
        result.append({
            "itemId": s.item_id,
            "count": s.count,
            "item": _item_to_dict(item) if item else None,
        })
    return result


@router.get("/inventory")
async def list_inventory(session: AsyncSession = Depends(get_session)):
    return await _list_inventory_dicts(session)


@router.post("/inventory/add")
async def add_to_inventory(
    data: InventoryAddRequest,
    session: AsyncSession = Depends(get_session),
):
    item = await session.get(ItemCatalogEntry, data.itemId)
    if not item:
        raise HTTPException(404, "Item not in catalog")

    existing = (await session.execute(
        select(InventoryStack).where(InventoryStack.item_id == data.itemId)
    )).scalars().first()

    if existing:
        new_count = existing.count + data.count
        if item.max_stack > 1 and new_count > item.max_stack:
            raise HTTPException(400, f"Exceeds max stack of {item.max_stack}")
        existing.count = new_count
    else:
        # Check carry capacity
        total_stacks = (await session.execute(
            select(func.count()).select_from(InventoryStack)
        )).scalar()
        settings = (await session.execute(select(OpenRouterSettings))).scalars().first()
        max_slots = settings.max_carry_slots if settings else MAX_CARRY_SLOTS_DEFAULT
        if total_stacks >= max_slots:
            raise HTTPException(400, "Inventory full — no carry slots remaining")
        session.add(InventoryStack(item_id=data.itemId, count=data.count))

    await session.commit()
    return {"ok": True}


@router.post("/inventory/remove")
async def remove_from_inventory(
    data: InventoryRemoveRequest,
    session: AsyncSession = Depends(get_session),
):
    existing = (await session.execute(
        select(InventoryStack).where(InventoryStack.item_id == data.itemId)
    )).scalars().first()
    if not existing:
        raise HTTPException(404, "Item not in inventory")
    existing.count -= data.count
    if existing.count <= 0:
        await session.delete(existing)
    await session.commit()
    return {"ok": True}


@router.get("/inventory/capacity")
async def get_inventory_capacity(session: AsyncSession = Depends(get_session)):
    total_stacks = (await session.execute(
        select(func.count()).select_from(InventoryStack)
    )).scalar()
    settings = (await session.execute(select(OpenRouterSettings))).scalars().first()
    max_slots = settings.max_carry_slots if settings else MAX_CARRY_SLOTS_DEFAULT
    return {"used": total_stacks, "max": max_slots}


# ── Quests ────────────────────────────────────────────────────────

async def _quest_to_schema(quest: Quest, session: AsyncSession) -> QuestSchema:
    objectives = (
        await session.execute(
            select(QuestObjective)
            .where(QuestObjective.quest_id == quest.id)
            .order_by(QuestObjective.sort_order)
        )
    ).scalars().all()
    return QuestSchema(
        id=quest.id,
        title=quest.title,
        status=quest.status,
        desc=quest.desc,
        objectives=[
            {"id": o.id, "text": o.text, "done": bool(o.done)}
            for o in objectives
        ],
        notes=quest.notes,
        relatedLore=quest.related_lore or [],
    )


@router.get("/quests", response_model=list[QuestSchema])
async def list_quests(session: AsyncSession = Depends(get_session)):
    quests = (await session.execute(select(Quest))).scalars().all()
    return [await _quest_to_schema(q, session) for q in quests]


@router.post("/quests", response_model=QuestSchema, status_code=201)
async def create_quest(
    data: QuestCreate,
    session: AsyncSession = Depends(get_session),
):
    quest = Quest(
        title=data.title,
        status=data.status,
        desc=data.desc,
        notes=data.notes,
        related_lore=data.relatedLore,
    )
    session.add(quest)
    await session.commit()
    await session.refresh(quest)
    return await _quest_to_schema(quest, session)


@router.get("/quests/{quest_id}", response_model=QuestSchema)
async def get_quest(
    quest_id: str,
    session: AsyncSession = Depends(get_session),
):
    quest = await session.get(Quest, quest_id)
    if not quest:
        raise HTTPException(404, "Quest not found")
    return await _quest_to_schema(quest, session)


@router.put("/quests/{quest_id}", response_model=QuestSchema)
async def update_quest(
    quest_id: str,
    data: QuestUpdate,
    session: AsyncSession = Depends(get_session),
):
    quest = await session.get(Quest, quest_id)
    if not quest:
        raise HTTPException(404, "Quest not found")
    if data.title is not None:
        quest.title = data.title
    if data.status is not None:
        quest.status = data.status
    if data.desc is not None:
        quest.desc = data.desc
    if data.notes is not None:
        quest.notes = data.notes
    if data.relatedLore is not None:
        quest.related_lore = data.relatedLore
    await session.commit()
    await session.refresh(quest)
    return await _quest_to_schema(quest, session)


@router.delete("/quests/{quest_id}", status_code=204)
async def delete_quest(
    quest_id: str,
    session: AsyncSession = Depends(get_session),
):
    quest = await session.get(Quest, quest_id)
    if not quest:
        raise HTTPException(404, "Quest not found")
    await session.execute(
        delete(QuestObjective).where(QuestObjective.quest_id == quest_id)
    )
    await session.delete(quest)
    await session.commit()


@router.post("/quests/{quest_id}/objectives", response_model=QuestSchema, status_code=201)
async def add_objective(
    quest_id: str,
    data: QuestObjectiveCreate,
    session: AsyncSession = Depends(get_session),
):
    quest = await session.get(Quest, quest_id)
    if not quest:
        raise HTTPException(404, "Quest not found")
    max_order = (
        await session.execute(
            select(func.coalesce(func.max(QuestObjective.sort_order), -1))
            .where(QuestObjective.quest_id == quest_id)
        )
    ).scalar()
    obj = QuestObjective(
        quest_id=quest_id,
        text=data.text,
        done=data.done,
        sort_order=(max_order or 0) + 1,
    )
    session.add(obj)
    await session.commit()
    return await _quest_to_schema(quest, session)


@router.put("/quests/{quest_id}/objectives/{objective_id}", response_model=QuestSchema)
async def update_objective(
    quest_id: str,
    objective_id: str,
    data: QuestObjectiveUpdate,
    session: AsyncSession = Depends(get_session),
):
    quest = await session.get(Quest, quest_id)
    if not quest:
        raise HTTPException(404, "Quest not found")
    obj = await session.get(QuestObjective, objective_id)
    if not obj or obj.quest_id != quest_id:
        raise HTTPException(404, "Objective not found")
    if data.text is not None:
        obj.text = data.text
    if data.done is not None:
        obj.done = data.done
    await session.commit()
    return await _quest_to_schema(quest, session)


@router.delete("/quests/{quest_id}/objectives/{objective_id}", status_code=204)
async def delete_objective(
    quest_id: str,
    objective_id: str,
    session: AsyncSession = Depends(get_session),
):
    quest = await session.get(Quest, quest_id)
    if not quest:
        raise HTTPException(404, "Quest not found")
    obj = await session.get(QuestObjective, objective_id)
    if not obj or obj.quest_id != quest_id:
        raise HTTPException(404, "Objective not found")
    await session.delete(obj)
    await session.commit()


# ── Lorebook ─────────────────────────────────────────────────────

def _lore_to_schema(entry: LorebookEntry) -> LorebookEntrySchema:
    return LorebookEntrySchema(
        id=entry.id,
        title=entry.title,
        content=entry.content,
        keywords=entry.keywords or [],
        enabled=bool(entry.enabled),
        permanent=bool(entry.permanent),
        cat=entry.cat,
    )


@router.get("/lore/config", response_model=LorebookConfigSchema)
async def get_lore_config(session: AsyncSession = Depends(get_session)):
    cfg = (await session.execute(select(LorebookConfig))).scalars().first()
    if not cfg:
        cfg = LorebookConfig()
        session.add(cfg)
        await session.commit()
        await session.refresh(cfg)
    return LorebookConfigSchema(
        injectionOrder=cfg.injection_order,
        injectionPosition=cfg.injection_position,
    )


@router.put("/lore/config", response_model=LorebookConfigSchema)
async def update_lore_config(
    data: LorebookConfigUpdate,
    session: AsyncSession = Depends(get_session),
):
    cfg = (await session.execute(select(LorebookConfig))).scalars().first()
    if not cfg:
        cfg = LorebookConfig()
        session.add(cfg)
    if data.injectionOrder is not None:
        cfg.injection_order = data.injectionOrder
    if data.injectionPosition is not None:
        cfg.injection_position = data.injectionPosition
    await session.commit()
    await session.refresh(cfg)
    return LorebookConfigSchema(
        injectionOrder=cfg.injection_order,
        injectionPosition=cfg.injection_position,
    )


@router.get("/lore", response_model=list[LorebookEntrySchema])
async def list_lore_entries(
    cat: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    query = select(LorebookEntry)
    if cat:
        query = query.where(LorebookEntry.cat == cat)
    entries = (await session.execute(query)).scalars().all()
    return [_lore_to_schema(e) for e in entries]


@router.post("/lore", response_model=LorebookEntrySchema, status_code=201)
async def create_lore_entry(
    data: LorebookEntryCreate,
    session: AsyncSession = Depends(get_session),
):
    entry = LorebookEntry(
        title=data.title,
        content=data.content,
        keywords=data.keywords,
        enabled=data.enabled,
        permanent=data.permanent,
        cat=data.cat,
    )
    session.add(entry)
    await session.commit()
    await session.refresh(entry)
    return _lore_to_schema(entry)


@router.get("/lore/{entry_id}", response_model=LorebookEntrySchema)
async def get_lore_entry(
    entry_id: str,
    session: AsyncSession = Depends(get_session),
):
    entry = await session.get(LorebookEntry, entry_id)
    if not entry:
        raise HTTPException(404, "Lorebook entry not found")
    return _lore_to_schema(entry)


@router.put("/lore/{entry_id}", response_model=LorebookEntrySchema)
async def update_lore_entry(
    entry_id: str,
    data: LorebookEntryUpdate,
    session: AsyncSession = Depends(get_session),
):
    entry = await session.get(LorebookEntry, entry_id)
    if not entry:
        raise HTTPException(404, "Lorebook entry not found")
    if data.title is not None:
        entry.title = data.title
    if data.content is not None:
        entry.content = data.content
    if data.keywords is not None:
        entry.keywords = data.keywords
    if data.enabled is not None:
        entry.enabled = data.enabled
    if data.permanent is not None:
        entry.permanent = data.permanent
    if data.cat is not None:
        entry.cat = data.cat
    await session.commit()
    await session.refresh(entry)
    return _lore_to_schema(entry)


@router.delete("/lore/{entry_id}", status_code=204)
async def delete_lore_entry(
    entry_id: str,
    session: AsyncSession = Depends(get_session),
):
    entry = await session.get(LorebookEntry, entry_id)
    if not entry:
        raise HTTPException(404, "Lorebook entry not found")
    await session.delete(entry)
    await session.commit()


# ── Chat Messages ─────────────────────────────────────────────────

@router.get("/chat/messages", response_model=list[ChatMessageResponse])
async def get_chat_messages(session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(ChatMessage).order_by(ChatMessage.id)
    )
    return [
        ChatMessageResponse(
            id=m.id,
            role=m.role,
            content=m.content,
            turnNumber=m.turn_number,
            variant=m.variant,
            speaker=m.speaker or ("narrator" if m.role == "assistant" else "player"),
            spotlightReason=m.spotlight_reason,
            appliedInventoryDeltas=m.applied_inventory_deltas,
            appliedEquipmentChanges=m.applied_equipment_changes,
            createdAt=m.created_at.isoformat() if m.created_at else "",
        )
        for m in result.scalars().all()
    ]


@router.put("/chat/messages/{msg_id}", response_model=ChatMessageResponse)
async def edit_message(
    msg_id: int,
    data: ChatMessageUpdate,
    session: AsyncSession = Depends(get_session),
):
    msg = await session.get(ChatMessage, msg_id)
    if not msg:
        raise HTTPException(404, "Message not found")
    msg.content = data.content
    await session.commit()
    await session.refresh(msg)
    return ChatMessageResponse(
        id=msg.id,
        role=msg.role,
        content=msg.content,
        turnNumber=msg.turn_number,
        variant=msg.variant,
        speaker=msg.speaker or ("narrator" if msg.role == "assistant" else "player"),
        spotlightReason=msg.spotlight_reason,
        appliedInventoryDeltas=msg.applied_inventory_deltas,
        appliedEquipmentChanges=msg.applied_equipment_changes,
        createdAt=msg.created_at.isoformat() if msg.created_at else "",
    )


@router.delete("/chat/messages/{msg_id}/and-after", status_code=204)
async def delete_message_and_after(
    msg_id: int,
    session: AsyncSession = Depends(get_session),
):
    msg = await session.get(ChatMessage, msg_id)
    if not msg:
        raise HTTPException(404, "Message not found")

    # Reverse the effects of the most-recent message in the deleted range only
    # (the live state reflects the latest assistant message's combined deltas).
    # Per Task 6.2: don't walk back older messages — just the most recent one.
    latest_with_effects = (
        await session.execute(
            select(ChatMessage)
            .where(
                ChatMessage.id >= msg.id,
                ChatMessage.role == "assistant",
            )
            .order_by(ChatMessage.id.desc())
        )
    ).scalars().first()
    if latest_with_effects:
        await _reverse_message_effects(latest_with_effects, session)

    await session.execute(
        delete(ChatMessage).where(ChatMessage.id >= msg.id)
    )
    await session.commit()


@router.post("/chat/save-partial")
async def save_partial(
    data: ChatMessageUpdate,
    session: AsyncSession = Depends(get_session),
):
    """Save a partial response when the user stops generation."""
    all_msgs = (
        await session.execute(select(ChatMessage).order_by(ChatMessage.id.desc()))
    ).scalars().first()

    if not all_msgs:
        return {"ok": True}

    last_turn = all_msgs.turn_number
    existing_assistant = (
        await session.execute(
            select(ChatMessage).where(
                ChatMessage.turn_number == last_turn,
                ChatMessage.role == "assistant",
            )
        )
    ).scalars().all()

    variant = len(existing_assistant)
    partial_msg = ChatMessage(
        role="assistant",
        content=data.content,
        turn_number=last_turn,
        variant=variant,
        speaker="narrator",
    )
    session.add(partial_msg)
    await session.commit()
    return {"ok": True}


@router.delete("/chat/messages", status_code=204)
async def clear_chat(session: AsyncSession = Depends(get_session)):
    await session.execute(delete(ChatMessage))
    result = await session.execute(select(PartyMember))
    for pm in result.scalars().all():
        pm.last_spoke_turn = 0
    await session.commit()


# ── Adventure Export / Import / Reset ─────────────────────────────

@router.get("/adventure/export")
async def export_adventure(session: AsyncSession = Depends(get_session)):
    pc = (await session.execute(select(PlayerCharacter))).scalars().first()
    members = (await session.execute(select(PartyMember))).scalars().all()
    narrator = (await session.execute(select(NarratorConfig))).scalars().first()
    scenario_obj = (await session.execute(select(Scenario))).scalars().first()
    messages = (await session.execute(select(ChatMessage).order_by(ChatMessage.id))).scalars().all()
    summary = (await session.execute(select(StorySummary))).scalars().first()
    settings = (await session.execute(select(OpenRouterSettings))).scalars().first()
    items = (await session.execute(select(ItemCatalogEntry))).scalars().all()
    inventory = (await session.execute(select(InventoryStack))).scalars().all()
    quests = (await session.execute(select(Quest))).scalars().all()
    quest_objectives = (await session.execute(select(QuestObjective).order_by(QuestObjective.sort_order))).scalars().all()
    lore_entries = (await session.execute(select(LorebookEntry))).scalars().all()
    lore_config = (await session.execute(select(LorebookConfig))).scalars().first()

    # Group objectives by quest_id
    obj_by_quest: dict[str, list] = {}
    for o in quest_objectives:
        obj_by_quest.setdefault(o.quest_id, []).append({
            "id": o.id, "text": o.text, "done": bool(o.done), "sortOrder": o.sort_order,
        })

    return {
        "version": 1,
        "playerCharacter": _pc_to_response(pc).model_dump() if pc else None,
        "partyMembers": [_pm_to_response(m).model_dump() for m in members],
        "narrator": {"instructions": narrator.instructions} if narrator else {"instructions": ""},
        "scenario": {"description": scenario_obj.description} if scenario_obj else {"description": ""},
        "chatMessages": [
            {
                "role": m.role, "content": m.content,
                "turnNumber": m.turn_number, "variant": m.variant,
                "speaker": m.speaker or ("narrator" if m.role == "assistant" else "player"),
                "spotlightReason": m.spotlight_reason,
                "appliedInventoryDeltas": m.applied_inventory_deltas,
                "appliedEquipmentChanges": m.applied_equipment_changes,
            }
            for m in messages
        ],
        "storySummary": {
            "content": summary.content if summary else "",
            "summaryUpToTurn": summary.summary_up_to_turn if summary else 0,
        },
        "settings": {
            "modelId": settings.model_id if settings else "",
            "temperature": settings.temperature if settings else 0.7,
            "maxTokensResponse": settings.max_tokens_response if settings else 1000,
            "maxContextTokens": settings.max_context_tokens if settings else 128000,
            "maxCarrySlots": settings.max_carry_slots if settings else 12,
        },
        "items": [_item_to_dict(i) for i in items],
        "inventory": [{"itemId": s.item_id, "count": s.count} for s in inventory],
        "quests": [
            {
                "id": q.id,
                "title": q.title,
                "status": q.status,
                "desc": q.desc,
                "notes": q.notes,
                "relatedLore": q.related_lore or [],
                "objectives": obj_by_quest.get(q.id, []),
            }
            for q in quests
        ],
        "lorebook": [
            {
                "id": e.id,
                "title": e.title,
                "content": e.content,
                "keywords": e.keywords or [],
                "enabled": bool(e.enabled),
                "permanent": bool(e.permanent),
                "cat": e.cat,
            }
            for e in lore_entries
        ],
        "lorebookConfig": {
            "injectionOrder": lore_config.injection_order if lore_config else {"world": 0, "characters": 10, "items": 20, "monsters": 30, "spells": 40},
            "injectionPosition": lore_config.injection_position if lore_config else {"world": "top", "characters": "top", "items": "top", "monsters": "top", "spells": "top"},
        },
    }


@router.post("/adventure/import")
async def import_adventure(data: dict, session: AsyncSession = Depends(get_session)):
    # Clear everything
    await session.execute(delete(LorebookEntry))
    await session.execute(delete(LorebookConfig))
    await session.execute(delete(QuestObjective))
    await session.execute(delete(Quest))
    await session.execute(delete(InventoryStack))
    await session.execute(delete(ItemCatalogEntry))
    await session.execute(delete(ChatMessage))
    await session.execute(delete(PartyMember))
    await session.execute(delete(PlayerCharacter))
    await session.execute(delete(NarratorConfig))
    await session.execute(delete(Scenario))
    await session.execute(delete(StorySummary))
    await session.execute(delete(OpenRouterSettings))

    # Restore player character
    if data.get("playerCharacter"):
        pc_data = data["playerCharacter"]
        pc = PlayerCharacter(
            basic_info=pc_data.get("basicInfo", {}),
            equipment=pc_data.get("equipment", {}),
        )
        session.add(pc)

    # Restore party members
    for pm_data in data.get("partyMembers", []):
        pm = PartyMember(
            basic_info=pm_data.get("basicInfo", {}),
            equipment=pm_data.get("equipment", {}),
            field_skill=pm_data.get("fieldSkill", {}),
        )
        session.add(pm)

    # Restore narrator + scenario
    session.add(NarratorConfig(instructions=data.get("narrator", {}).get("instructions", "")))
    session.add(Scenario(description=data.get("scenario", {}).get("description", "")))

    # Restore chat
    for msg in data.get("chatMessages", []):
        session.add(ChatMessage(
            role=msg["role"], content=msg["content"],
            turn_number=msg.get("turnNumber", 0), variant=msg.get("variant", 0),
            speaker=msg.get("speaker", "narrator" if msg["role"] == "assistant" else "player"),
            spotlight_reason=msg.get("spotlightReason"),
            applied_inventory_deltas=msg.get("appliedInventoryDeltas"),
            applied_equipment_changes=msg.get("appliedEquipmentChanges"),
        ))

    # Restore summary
    summary_data = data.get("storySummary", {})
    session.add(StorySummary(
        content=summary_data.get("content", ""),
        summary_up_to_turn=summary_data.get("summaryUpToTurn", 0),
    ))

    # Restore settings (without apiKey)
    existing_settings = (await session.execute(select(OpenRouterSettings))).scalars().first()
    old_api_key = existing_settings.api_key if existing_settings else ""
    s = data.get("settings", {})
    session.add(OpenRouterSettings(
        api_key=old_api_key,
        model_id=s.get("modelId", ""),
        temperature=s.get("temperature", 0.7),
        max_tokens_response=s.get("maxTokensResponse", 1000),
        max_context_tokens=s.get("maxContextTokens", 128000),
        max_carry_slots=s.get("maxCarrySlots", 12),
    ))

    # Restore item catalog
    for item_data in data.get("items", []):
        session.add(ItemCatalogEntry(
            id=item_data.get("id"),
            name=item_data["name"],
            type=item_data["type"],
            slot=item_data.get("slot"),
            max_stack=item_data.get("maxStack", 1),
            uses=item_data.get("uses"),
            rarity=item_data.get("rarity", "c"),
            desc=item_data.get("desc", ""),
        ))

    # Restore inventory
    for inv_data in data.get("inventory", []):
        session.add(InventoryStack(
            item_id=inv_data["itemId"],
            count=inv_data.get("count", 1),
        ))

    # Restore quests
    for q_data in data.get("quests", []):
        quest = Quest(
            id=q_data.get("id"),
            title=q_data.get("title", ""),
            status=q_data.get("status", "active"),
            desc=q_data.get("desc", ""),
            notes=q_data.get("notes", ""),
            related_lore=q_data.get("relatedLore", []),
        )
        session.add(quest)
        for obj_data in q_data.get("objectives", []):
            session.add(QuestObjective(
                id=obj_data.get("id"),
                quest_id=quest.id,
                text=obj_data.get("text", ""),
                done=obj_data.get("done", False),
                sort_order=obj_data.get("sortOrder", 0),
            ))

    # Restore lorebook entries
    for le_data in data.get("lorebook", []):
        session.add(LorebookEntry(
            id=le_data.get("id"),
            title=le_data.get("title", ""),
            content=le_data.get("content", ""),
            keywords=le_data.get("keywords", []),
            enabled=le_data.get("enabled", True),
            permanent=le_data.get("permanent", False),
            cat=le_data.get("cat", "world"),
        ))

    # Restore lorebook config
    lc_data = data.get("lorebookConfig", {})
    session.add(LorebookConfig(
        injection_order=lc_data.get("injectionOrder", {"world": 0, "characters": 10, "items": 20, "monsters": 30, "spells": 40}),
        injection_position=lc_data.get("injectionPosition", {"world": "top", "characters": "top", "items": "top", "monsters": "top", "spells": "top"}),
    ))

    await session.commit()
    return {"ok": True}


@router.post("/adventure/reset")
async def reset_adventure(session: AsyncSession = Depends(get_session)):
    # Preserve API key
    settings = (await session.execute(select(OpenRouterSettings))).scalars().first()
    old_api_key = settings.api_key if settings else ""

    await session.execute(delete(LorebookEntry))
    await session.execute(delete(LorebookConfig))
    await session.execute(delete(QuestObjective))
    await session.execute(delete(Quest))
    await session.execute(delete(InventoryStack))
    await session.execute(delete(ItemCatalogEntry))
    await session.execute(delete(ChatMessage))
    await session.execute(delete(PartyMember))
    await session.execute(delete(PlayerCharacter))
    await session.execute(delete(NarratorConfig))
    await session.execute(delete(Scenario))
    await session.execute(delete(StorySummary))
    await session.execute(delete(OpenRouterSettings))
    await session.commit()

    # Re-seed
    from server.db.seed import seed_defaults
    await seed_defaults()

    # Restore API key
    if old_api_key:
        async with async_session() as s2:
            or_settings = (await s2.execute(select(OpenRouterSettings))).scalars().first()
            if or_settings:
                or_settings.api_key = old_api_key
                await s2.commit()

    return {"ok": True}


# ── Models Proxy ──────────────────────────────────────────────────

@router.get("/models")
async def list_models(session: AsyncSession = Depends(get_session)):
    settings = (await session.execute(select(OpenRouterSettings))).scalars().first()
    if not settings or not settings.api_key:
        raise HTTPException(400, "OpenRouter API key not configured")
    try:
        models = await fetch_models(settings.api_key)
        return models
    except Exception as e:
        raise HTTPException(502, f"Failed to fetch models: {e}")


# ── Prompt Log ────────────────────────────────────────────────────

import pathlib as _pathlib

_PROMPT_LOG_PATH = _pathlib.Path(__file__).resolve().parent.parent.parent / ".prompt_log.json"


def _save_prompt_log(messages: list[dict]):
    _PROMPT_LOG_PATH.write_text(json.dumps(messages, ensure_ascii=False), encoding="utf-8")


@router.get("/chat/prompt-log")
async def get_prompt_log():
    if not _PROMPT_LOG_PATH.exists():
        raise HTTPException(404, "No prompt log available")
    return json.loads(_PROMPT_LOG_PATH.read_text(encoding="utf-8"))


# ── Chat Turn ─────────────────────────────────────────────────────

log = logging.getLogger("wayward.chat")


async def _reverse_message_effects(msg: ChatMessage, session: AsyncSession) -> None:
    """Reverse the inventory deltas and equipment changes applied by a message.

    Used before re-generating a turn (swipe/regenerate) or when truncating
    (delete-and-after) so the world state doesn't accumulate stale effects.
    Reverses equipment first, then inventory: the inventory deltas already
    account for any item returned to the bag by a narrator unequip, so reversing
    them removes that returned item — keep both in sync by reversing both.
    """
    if msg.applied_equipment_changes:
        await reverse_equipment_changes(msg.applied_equipment_changes, session)
    if msg.applied_inventory_deltas:
        await reverse_inventory_deltas(msg.applied_inventory_deltas, session)


async def _detect_player_deltas(
    player_message: str, session: AsyncSession
) -> list[dict]:
    """Run deterministic item-use detection on a player message.

    Detection only — the deltas are *not* applied here. They are applied inside
    the streaming save transaction once the narrator message is successfully
    persisted, so a failed/cancelled generation never leaves the inventory
    decremented with no message to reverse it from (which would otherwise
    double-decrement on retry). Live inventory is not part of the prompt, so
    deferring application costs nothing in narration grounding.

    Returns the player-action inventory deltas (so they can be applied and merged
    into the narrator message's combined delta record).
    """
    inventory = await _list_inventory_dicts(session)
    return detect_item_use(player_message, inventory)


async def _load_game_context(session: AsyncSession):
    """Load all game state needed for a chat turn."""
    settings = (await session.execute(select(OpenRouterSettings))).scalars().first()
    if not settings or not settings.api_key:
        raise HTTPException(400, "OpenRouter API key not configured")
    if not settings.model_id:
        raise HTTPException(400, "No model selected")

    narrator = (await session.execute(select(NarratorConfig))).scalars().first() or NarratorConfig(instructions="")
    scenario = (await session.execute(select(Scenario))).scalars().first() or Scenario(description="")
    pc = (await session.execute(select(PlayerCharacter))).scalars().first()
    if not pc:
        raise HTTPException(400, "No player character created")

    party = list((await session.execute(select(PartyMember))).scalars().all())
    all_messages = list(
        (await session.execute(select(ChatMessage).order_by(ChatMessage.id))).scalars().all()
    )
    summary = (await session.execute(select(StorySummary))).scalars().first()
    if not summary:
        summary = StorySummary(content="", summary_up_to_turn=0)
        session.add(summary)
    catalog = list((await session.execute(select(ItemCatalogEntry))).scalars().all())
    quests = list((await session.execute(select(Quest))).scalars().all())
    quest_objectives = list(
        (await session.execute(select(QuestObjective).order_by(QuestObjective.sort_order))).scalars().all()
    )
    lore_entries = list((await session.execute(select(LorebookEntry))).scalars().all())
    lore_config = (await session.execute(select(LorebookConfig))).scalars().first()
    if not lore_config:
        lore_config = LorebookConfig()
        session.add(lore_config)
        await session.commit()

    return settings, narrator, scenario, pc, party, all_messages, summary, catalog, quests, quest_objectives, lore_entries, lore_config


async def _maybe_summarize_and_build(
    settings, narrator, scenario, pc, party_list,
    history: list[ChatMessage],
    summary: StorySummary,
    player_message: str,
    current_turn: int,
    session: AsyncSession,
    item_catalog: list[ItemCatalogEntry] | None = None,
    quests: list[Quest] | None = None,
    quest_objectives: list[QuestObjective] | None = None,
    lore_entries: list[LorebookEntry] | None = None,
    lore_config: LorebookConfig | None = None,
):
    """Check if summarization is needed, do it, then build the prompt.
    Returns (prompt_messages, did_summarize, spotlight_signals)."""

    # Filter history to only unsummarized turns
    filtered = [m for m in history if m.turn_number > summary.summary_up_to_turn]

    # Compute spotlight
    spotlight_block = None
    spotlight_signals = []
    if party_list:
        recent_assistant = [m.content for m in filtered if m.role == "assistant"][-3:]
        recent_context = " ".join(recent_assistant)
        spotlight_signals = compute_spotlight_signals(
            player_message=player_message,
            recent_context=recent_context,
            party_members=party_list,
            current_turn=current_turn,
        )
        spotlight_block = format_spotlight_block(spotlight_signals)

    # Build a test prompt to check size
    test_prompt = build_prompt(
        narrator_config=narrator,
        scenario=scenario,
        player_character=pc,
        party_members=party_list,
        chat_history=filtered,
        player_message=player_message,
        spotlight_block=spotlight_block,
        story_summary=summary.content or None,
        item_catalog=item_catalog,
        quests=quests,
        quest_objectives=quest_objectives,
        lore_entries=lore_entries,
        lore_config=lore_config,
        max_context_tokens=settings.max_context_tokens,
        max_response_tokens=settings.max_tokens_response,
    )

    preamble_tokens = estimate_prompt_tokens(test_prompt)
    did_summarize = False

    if should_summarize(preamble_tokens, 0, settings.max_context_tokens, settings.max_tokens_response):
        to_summarize, to_keep, new_boundary = pick_messages_to_summarize(filtered)
        if to_summarize:
            new_summary = await generate_summary(
                api_key=settings.api_key,
                model_id=settings.model_id,
                messages_to_summarize=to_summarize,
                existing_summary=summary.content,
            )
            summary.content = new_summary
            summary.summary_up_to_turn = new_boundary
            await session.commit()
            filtered = to_keep
            did_summarize = True

    messages = build_prompt(
        narrator_config=narrator,
        scenario=scenario,
        player_character=pc,
        party_members=party_list,
        chat_history=filtered,
        player_message=player_message,
        spotlight_block=spotlight_block,
        story_summary=summary.content or None,
        item_catalog=item_catalog,
        quests=quests,
        quest_objectives=quest_objectives,
        lore_entries=lore_entries,
        lore_config=lore_config,
        max_context_tokens=settings.max_context_tokens,
        max_response_tokens=settings.max_tokens_response,
    )

    return messages, did_summarize, spotlight_signals


@router.post("/chat/turn")
async def chat_turn(
    data: ChatTurnRequest,
    session: AsyncSession = Depends(get_session),
):
    settings, narrator, scenario, pc, party, all_messages, summary, catalog, quests, quest_objectives, lore_entries, lore_config = await _load_game_context(session)

    max_turn = max((m.turn_number for m in all_messages), default=0)
    current_turn = max_turn + 1

    user_msg = ChatMessage(role="user", content=data.message, turn_number=current_turn, speaker=pc.id)
    session.add(user_msg)

    # Deterministic item-use detection on the player's message. Detection runs
    # now (against current inventory) but the decrement is deferred to the save
    # transaction so a failed generation can't orphan the delta.
    player_deltas = await _detect_player_deltas(data.message, session)
    await session.commit()

    messages, did_summarize, spotlight_signals = await _maybe_summarize_and_build(
        settings, narrator, scenario, pc, party,
        history=all_messages,
        summary=summary,
        player_message=data.message,
        current_turn=current_turn,
        session=session,
        item_catalog=catalog,
        quests=quests,
        quest_objectives=quest_objectives,
        lore_entries=lore_entries,
        lore_config=lore_config,
    )

    variant_count = sum(
        1 for m in all_messages if m.turn_number == current_turn and m.role == "assistant"
    )

    return _stream_llm_response(
        messages=messages,
        settings=settings,
        party_list=party,
        current_turn=current_turn,
        variant=variant_count,
        did_summarize=did_summarize,
        spotlight_signals=spotlight_signals,
        player_deltas=player_deltas,
    )


# ── Swipe (new variant for a specific turn) ─────────────────────

@router.post("/chat/messages/{turn}/swipe")
async def swipe(turn: int, session: AsyncSession = Depends(get_session)):
    """Generate a new variant for a specific turn. Appends to existing variants."""
    settings, narrator, scenario, pc, party, all_messages, summary, catalog, quests, quest_objectives, lore_entries, lore_config = await _load_game_context(session)

    # Find the user message for this turn
    user_msg = next(
        (m for m in all_messages if m.turn_number == turn and m.role == "user"),
        None,
    )
    if not user_msg:
        raise HTTPException(400, f"No user message found for turn {turn}")

    # Build history up to (but not including) this turn
    history = [m for m in all_messages if m.turn_number < turn]

    # Reverse the effects of the currently-live variant for this turn (the most
    # recent assistant variant carries the combined deltas reflected in state),
    # then re-run detection on the same player message and apply fresh. This
    # keeps inventory idempotent across repeated swipes.
    turn_variants = [
        m for m in all_messages if m.turn_number == turn and m.role == "assistant"
    ]
    if turn_variants:
        latest_variant = max(turn_variants, key=lambda m: m.variant)
        await _reverse_message_effects(latest_variant, session)
    await session.commit()
    # Re-detect against the now-restored inventory; application is deferred to
    # the save transaction (see _detect_player_deltas).
    player_deltas = await _detect_player_deltas(user_msg.content, session)

    messages, did_summarize, spotlight_signals = await _maybe_summarize_and_build(
        settings, narrator, scenario, pc, party,
        history=history,
        summary=summary,
        player_message=user_msg.content,
        current_turn=turn,
        session=session,
        item_catalog=catalog,
        quests=quests,
        quest_objectives=quest_objectives,
        lore_entries=lore_entries,
        lore_config=lore_config,
    )

    # Count existing variants for this turn to determine next variant number
    variant_count = sum(
        1 for m in all_messages if m.turn_number == turn and m.role == "assistant"
    )

    return _stream_llm_response(
        messages=messages,
        settings=settings,
        party_list=party,
        current_turn=turn,
        variant=variant_count,
        did_summarize=did_summarize,
        spotlight_signals=spotlight_signals,
        player_deltas=player_deltas,
    )


# ── Regenerate ────────────────────────────────────────────────────

@router.post("/chat/regenerate")
async def regenerate(session: AsyncSession = Depends(get_session)):
    settings, narrator, scenario, pc, party, all_messages, summary, catalog, quests, quest_objectives, lore_entries, lore_config = await _load_game_context(session)

    if not all_messages:
        raise HTTPException(400, "No messages to regenerate")

    last_turn = max(m.turn_number for m in all_messages)
    last_user_msg = next(
        (m for m in reversed(all_messages) if m.turn_number == last_turn and m.role == "user"),
        None,
    )
    if not last_user_msg:
        raise HTTPException(400, "No user message found for last turn")

    # Reverse the effects of the live (latest) variant before wiping. Only the
    # latest variant's deltas are reflected in current state; earlier variants
    # were each reversed when superseded by a swipe.
    turn_variants = [
        m for m in all_messages if m.turn_number == last_turn and m.role == "assistant"
    ]
    if turn_variants:
        latest_variant = max(turn_variants, key=lambda m: m.variant)
        await _reverse_message_effects(latest_variant, session)

    # REGENERATE wipes all existing assistant variants for this turn
    await session.execute(
        delete(ChatMessage).where(
            ChatMessage.turn_number == last_turn,
            ChatMessage.role == "assistant",
        )
    )

    await session.commit()
    # Re-run detection on the same player message against the restored inventory.
    # Application is deferred to the save transaction (see _detect_player_deltas).
    player_deltas = await _detect_player_deltas(last_user_msg.content, session)

    history = [m for m in all_messages if m.turn_number < last_turn]

    messages, did_summarize, spotlight_signals = await _maybe_summarize_and_build(
        settings, narrator, scenario, pc, party,
        history=history,
        summary=summary,
        player_message=last_user_msg.content,
        current_turn=last_turn,
        session=session,
        item_catalog=catalog,
        quests=quests,
        quest_objectives=quest_objectives,
        lore_entries=lore_entries,
        lore_config=lore_config,
    )

    # Start fresh at variant 0 since we wiped all previous variants
    return _stream_llm_response(
        messages=messages,
        settings=settings,
        party_list=party,
        current_turn=last_turn,
        variant=0,
        did_summarize=did_summarize,
        spotlight_signals=spotlight_signals,
        player_deltas=player_deltas,
    )


# ── Summary endpoint ──────────────────────────────────────────────

@router.get("/chat/summary")
async def get_summary(session: AsyncSession = Depends(get_session)):
    s = (await session.execute(select(StorySummary))).scalars().first()
    if not s or not s.content:
        return {"content": "", "summaryUpToTurn": 0}
    return {"content": s.content, "summaryUpToTurn": s.summary_up_to_turn}


# ── Shared streaming helper ───────────────────────────────────────

def _stream_llm_response(
    messages: list[dict],
    settings: OpenRouterSettings,
    party_list: list[PartyMember],
    current_turn: int,
    variant: int,
    did_summarize: bool = False,
    spotlight_signals: list[SpotlightSignal] | None = None,
    player_deltas: list[dict] | None = None,
):
    player_deltas = player_deltas or []
    _save_prompt_log(messages)

    context_tokens = estimate_prompt_tokens(messages)
    api_key = settings.api_key
    model_id = settings.model_id
    temperature = settings.temperature
    top_p = settings.top_p
    min_p = settings.min_p
    top_k = settings.top_k
    frequency_penalty = settings.frequency_penalty
    presence_penalty = settings.presence_penalty
    repetition_penalty = settings.repetition_penalty
    max_tokens = settings.max_tokens_response
    max_context = settings.max_context_tokens

    async def stream():
        if did_summarize:
            yield f"data: {json.dumps({'type': 'summarized'})}\n\n"

        yield f"data: {json.dumps({'type': 'meta', 'contextTokens': context_tokens, 'maxContextTokens': max_context})}\n\n"

        full_text = ""
        try:
            async for chunk in chat_completion_stream(
                api_key=api_key,
                model_id=model_id,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                top_p=top_p,
                min_p=min_p,
                top_k=top_k,
                frequency_penalty=frequency_penalty,
                presence_penalty=presence_penalty,
                repetition_penalty=repetition_penalty,
            ):
                full_text += chunk
                yield f"data: {json.dumps({'type': 'chunk', 'content': chunk})}\n\n"
        except Exception as e:
            log.exception("OpenRouter stream failed")
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"
            return

        # Parse and strip the action block before saving
        clean_text, actions = parse_action_block(full_text)
        inv_deltas: list[dict] = []
        equip_changes: list[dict] = []

        try:
            async with async_session() as save_session:
                speaker_ids: list[str] = []
                if party_list:
                    speaker_ids = detect_speakers(full_text, party_list)
                    for pm in party_list:
                        if pm.id in speaker_ids:
                            db_pm = await save_session.get(PartyMember, pm.id)
                            if db_pm:
                                db_pm.last_spoke_turn = current_turn

                # Determine spotlight reason for the first speaking party member
                spot_reason: str | None = None
                if speaker_ids and spotlight_signals:
                    signal_map = {s.member_id: s for s in spotlight_signals}
                    for sid in speaker_ids:
                        sig = signal_map.get(sid)
                        if sig:
                            if sig.directly_addressed:
                                spot_reason = "Directly addressed"
                            elif sig.field_skill_relevant:
                                spot_reason = "Field skill · relevant"
                            elif sig.turns_since_last_spoke >= 5:
                                spot_reason = "Hasn't spoken in a while"
                            break

                # Execute narrator actions if present
                if actions:
                    inv_deltas, equip_changes = await execute_actions(
                        actions, save_session
                    )

                # Apply the player's item-use deltas now (deferred from detection
                # time) so they only ever hit the DB when the narrator message is
                # actually persisted — a failed/cancelled generation leaves the
                # inventory untouched. Merge them with the narrator-granted deltas
                # and store both on the narrator message so swipe/regenerate/delete
                # can reverse the full combined effect of this turn.
                if player_deltas:
                    await apply_inventory_deltas(player_deltas, save_session)
                combined_inv_deltas = [*player_deltas, *inv_deltas]

                assistant_msg = ChatMessage(
                    role="assistant", content=clean_text,
                    turn_number=current_turn, variant=variant,
                    speaker="narrator",
                    spotlight_reason=spot_reason,
                    applied_inventory_deltas=combined_inv_deltas if combined_inv_deltas else None,
                    applied_equipment_changes=equip_changes if equip_changes else None,
                )
                save_session.add(assistant_msg)
                await save_session.commit()
        except Exception as e:
            log.exception("Failed to save response to DB")

        response_tokens = len(clean_text) // 4
        combined_inv_deltas = [*player_deltas, *inv_deltas]
        done_payload: dict = {
            'type': 'done',
            'contextTokens': context_tokens + response_tokens,
            'maxContextTokens': max_context,
        }
        if combined_inv_deltas:
            done_payload['appliedInventoryDeltas'] = combined_inv_deltas
        if equip_changes:
            done_payload['appliedEquipmentChanges'] = equip_changes
        yield f"data: {json.dumps(done_payload)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")
