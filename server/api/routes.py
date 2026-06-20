import json
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

PORTRAITS_DIR = Path(__file__).resolve().parent.parent / "portraits"

from server.ai.openrouter import chat_completion_stream, fetch_models
from server.ai.prompt_builder import build_prompt, estimate_prompt_tokens
from server.ai.spotlight import compute_spotlight_signals, detect_speakers, format_spotlight_block
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


@router.get("/inventory")
async def list_inventory(session: AsyncSession = Depends(get_session)):
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
    }


@router.post("/adventure/import")
async def import_adventure(data: dict, session: AsyncSession = Depends(get_session)):
    # Clear everything
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

    await session.commit()
    return {"ok": True}


@router.post("/adventure/reset")
async def reset_adventure(session: AsyncSession = Depends(get_session)):
    # Preserve API key
    settings = (await session.execute(select(OpenRouterSettings))).scalars().first()
    old_api_key = settings.api_key if settings else ""

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

    return settings, narrator, scenario, pc, party, all_messages, summary, catalog, quests, quest_objectives


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
):
    """Check if summarization is needed, do it, then build the prompt.
    Returns (prompt_messages, did_summarize)."""

    # Filter history to only unsummarized turns
    filtered = [m for m in history if m.turn_number > summary.summary_up_to_turn]

    # Compute spotlight
    spotlight_block = None
    if party_list:
        recent_assistant = [m.content for m in filtered if m.role == "assistant"][-3:]
        recent_context = " ".join(recent_assistant)
        signals = compute_spotlight_signals(
            player_message=player_message,
            recent_context=recent_context,
            party_members=party_list,
            current_turn=current_turn,
        )
        spotlight_block = format_spotlight_block(signals)

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
        max_context_tokens=settings.max_context_tokens,
        max_response_tokens=settings.max_tokens_response,
    )

    return messages, did_summarize


@router.post("/chat/turn")
async def chat_turn(
    data: ChatTurnRequest,
    session: AsyncSession = Depends(get_session),
):
    settings, narrator, scenario, pc, party, all_messages, summary, catalog, quests, quest_objectives = await _load_game_context(session)

    max_turn = max((m.turn_number for m in all_messages), default=0)
    current_turn = max_turn + 1

    user_msg = ChatMessage(role="user", content=data.message, turn_number=current_turn)
    session.add(user_msg)
    await session.commit()

    messages, did_summarize = await _maybe_summarize_and_build(
        settings, narrator, scenario, pc, party,
        history=all_messages,
        summary=summary,
        player_message=data.message,
        current_turn=current_turn,
        session=session,
        item_catalog=catalog,
        quests=quests,
        quest_objectives=quest_objectives,
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
    )


# ── Regenerate ────────────────────────────────────────────────────

@router.post("/chat/regenerate")
async def regenerate(session: AsyncSession = Depends(get_session)):
    settings, narrator, scenario, pc, party, all_messages, summary, catalog, quests, quest_objectives = await _load_game_context(session)

    if not all_messages:
        raise HTTPException(400, "No messages to regenerate")

    last_turn = max(m.turn_number for m in all_messages)
    last_user_msg = next(
        (m for m in reversed(all_messages) if m.turn_number == last_turn and m.role == "user"),
        None,
    )
    if not last_user_msg:
        raise HTTPException(400, "No user message found for last turn")

    history = [m for m in all_messages if m.turn_number < last_turn]

    messages, did_summarize = await _maybe_summarize_and_build(
        settings, narrator, scenario, pc, party,
        history=history,
        summary=summary,
        player_message=last_user_msg.content,
        current_turn=last_turn,
        session=session,
        item_catalog=catalog,
        quests=quests,
        quest_objectives=quest_objectives,
    )

    variant_count = sum(
        1 for m in all_messages if m.turn_number == last_turn and m.role == "assistant"
    )

    return _stream_llm_response(
        messages=messages,
        settings=settings,
        party_list=party,
        current_turn=last_turn,
        variant=variant_count,
        did_summarize=did_summarize,
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
):
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

        try:
            async with async_session() as save_session:
                if party_list:
                    speaker_ids = detect_speakers(full_text, party_list)
                    for pm in party_list:
                        if pm.id in speaker_ids:
                            db_pm = await save_session.get(PartyMember, pm.id)
                            if db_pm:
                                db_pm.last_spoke_turn = current_turn

                assistant_msg = ChatMessage(
                    role="assistant", content=full_text,
                    turn_number=current_turn, variant=variant,
                )
                save_session.add(assistant_msg)
                await save_session.commit()
        except Exception as e:
            log.exception("Failed to save response to DB")

        response_tokens = len(full_text) // 4
        yield f"data: {json.dumps({'type': 'done', 'contextTokens': context_tokens + response_tokens, 'maxContextTokens': max_context})}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")
