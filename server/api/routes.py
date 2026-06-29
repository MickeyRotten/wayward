import datetime
import io
import json
import logging
import re
import shutil
import sqlite3
import uuid
import zipfile
from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

PORTRAITS_DIR = Path(__file__).resolve().parent.parent / "portraits"

from server.ai.narrator_actions import ACTION_INSTRUCTION, execute_actions, parse_action_block, reverse_equipment_changes
from server.ai.item_detection import (
    apply_inventory_deltas,
    detect_item_use,
    reverse_inventory_deltas,
)
from server.ai.narrator_agent import run_narrator_agent
from server.ai.worldbuilder import apply_proposal, reverse_chronicler_creations, run_worldbuilder
from server.ai.planner import PLANNER_GUIDANCE, run_planner_agent
from server.ai.openrouter import chat_completion_stream, fetch_models
from server.ai.prompt_builder import build_prompt, estimate_prompt_tokens
from server.ai.spotlight import DEFAULT_SPOTLIGHT_RULE, SpotlightSignal, _name_mentioned, compute_spotlight_signals, detect_speakers, format_spotlight_block
from server.ai.summarizer import (
    format_messages_for_summary,
    generate_summary,
    pick_messages_to_summarize,
    should_summarize,
)
from server.db.database import new_session, switch_active
from server.db import inventory as inv_ops
from server.db import storage
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
    PartyMembershipUpdate,
    PartyMemberResponse,
    PartyMemberUpdate,
    PlannerDeletesApply,
    PlayerCharacterResponse,
    PlayerCharacterUpdate,
    QuestCreate,
    QuestObjectiveCreate,
    QuestObjectiveUpdate,
    QuestSchema,
    QuestUpdate,
    WorldbuildProposalSchema,
    WorldbuildRunRequest,
)
from server.db.database import get_session
from server.db.models import (
    ChatMessage,
    InventoryStack,
    ItemInstance,
    LorebookConfig,
    LorebookEntry,
    NarratorConfig,
    OpenRouterSettings,
    PartyMember,
    AppState,
    PlayerCharacter,
    Quest,
    QuestObjective,
    StorySummary,
    WorldbuildingProposal,
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
        inParty=bool(pm.in_party),
    )


async def _active_party_count(session: AsyncSession) -> int:
    return (
        await session.execute(
            select(func.count()).select_from(PartyMember).where(PartyMember.in_party == True)  # noqa: E712
        )
    ).scalar() or 0


async def _max_party_size(session: AsyncSession) -> int:
    settings = (await session.execute(select(OpenRouterSettings))).scalars().first()
    return settings.max_party_size if settings else 3


# ── Adventures (save files in the active campaign) ────────────────

async def _active_ids(session: AsyncSession) -> tuple[str | None, str | None]:
    st = (await session.execute(select(AppState))).scalars().first()
    return (st.active_campaign_id, st.active_adventure_id) if st else (None, None)


async def _set_active_adventure(aid: str) -> None:
    async with new_session() as s:
        st = (await s.execute(select(AppState))).scalars().first()
        if st:
            st.active_adventure_id = aid
            await s.commit()


@router.get("/adventures")
async def list_adventures_route(session: AsyncSession = Depends(get_session)):
    cid, aid = await _active_ids(session)
    if not cid:
        return {"activeId": None, "adventures": []}
    await storage.refresh_active_adventure_meta()
    return {"activeId": aid, "adventures": storage.list_adventures(cid)}


@router.post("/adventures")
async def create_adventure_route(
    data: dict = Body(default={}),
    session: AsyncSession = Depends(get_session),
):
    cid, _ = await _active_ids(session)
    if not cid:
        raise HTTPException(400, "No active campaign")
    name = (data.get("name") or "New Adventure").strip() or "New Adventure"
    await storage.refresh_active_adventure_meta()  # save the one we're leaving
    aid = await storage.create_adventure(cid, name)
    await switch_active(storage.campaign_db_path(cid), storage.adventure_db_path(cid, aid))
    await _set_active_adventure(aid)
    # Blank slate: seed an empty editable PC so the sheet renders.
    async with new_session() as s:
        if not (await s.execute(select(PlayerCharacter))).scalars().first():
            s.add(PlayerCharacter())
            await s.commit()
    await storage.refresh_active_adventure_meta()
    return {"id": aid, "switched": True}


@router.post("/adventures/{aid}/load")
async def load_adventure_route(aid: str, session: AsyncSession = Depends(get_session)):
    cid, _ = await _active_ids(session)
    if not cid or not storage.adventure_dir(cid, aid).exists():
        raise HTTPException(404, "Adventure not found")
    await storage.refresh_active_adventure_meta()  # save current
    await switch_active(storage.campaign_db_path(cid), storage.adventure_db_path(cid, aid))
    await _set_active_adventure(aid)
    return {"id": aid, "switched": True}


@router.put("/adventures/{aid}")
async def rename_adventure_route(
    aid: str,
    data: dict = Body(default={}),
    session: AsyncSession = Depends(get_session),
):
    cid, _ = await _active_ids(session)
    meta = storage.read_adventure_meta(cid, aid) if cid else None
    if not meta:
        raise HTTPException(404, "Adventure not found")
    if data.get("name"):
        meta["name"] = data["name"].strip()
        storage.write_adventure_meta(cid, aid, meta)
    return meta


@router.delete("/adventures/{aid}")
async def delete_adventure_route(aid: str, session: AsyncSession = Depends(get_session)):
    cid, cur = await _active_ids(session)
    if not cid:
        raise HTTPException(400, "No active campaign")
    advs = storage.list_adventures(cid)
    if len(advs) <= 1:
        raise HTTPException(400, "Can't delete the only adventure in a campaign")
    switched_to: str | None = None
    if aid == cur:
        other = next(a for a in advs if a["id"] != aid)
        await switch_active(storage.campaign_db_path(cid), storage.adventure_db_path(cid, other["id"]))
        await _set_active_adventure(other["id"])
        switched_to = other["id"]
    shutil.rmtree(storage.adventure_dir(cid, aid), ignore_errors=True)
    return {"deleted": aid, "switchedTo": switched_to}


# ── Campaigns (worlds) ────────────────────────────────────────────

CAMPAIGN_STARTER = (
    "Welcome to your new campaign — you're in **Edit Mode**, where we build the world.\n\n"
    "Tell me what kind of adventure you want and I'll shape it for you. A good start:\n\n"
    "1. **Setting & tone** — the world, genre, mood (e.g. \"a grim coastal fantasy of drowned gods\").\n"
    "2. **A starting location** — where the first scene opens.\n"
    "3. **Key characters** — any NPCs, and a starting party if you'd like one.\n"
    "4. **A hook** — the quest or trouble that gets things moving.\n\n"
    "Describe any of these and I'll create the lore, characters, items, and quests. "
    "When the world feels ready, switch off Edit Mode to start playing."
)


async def _set_active(campaign_id: str, adventure_id: str) -> None:
    async with new_session() as s:
        st = (await s.execute(select(AppState))).scalars().first()
        if st:
            st.active_campaign_id = campaign_id
            st.active_adventure_id = adventure_id
            await s.commit()


@router.get("/campaigns")
async def list_campaigns_route(session: AsyncSession = Depends(get_session)):
    cid, _ = await _active_ids(session)
    return {"activeId": cid, "campaigns": storage.list_campaigns()}


@router.post("/campaigns")
async def create_campaign_route(
    data: dict = Body(default={}),
    session: AsyncSession = Depends(get_session),
):
    name = (data.get("name") or "New Campaign").strip() or "New Campaign"
    await storage.refresh_active_adventure_meta()
    cid = await storage.create_campaign(name)
    aid = await storage.create_adventure(cid, "Adventure 1")
    await switch_active(storage.campaign_db_path(cid), storage.adventure_db_path(cid, aid))
    await _set_active(cid, aid)
    async with new_session() as s:
        if not (await s.execute(select(PlayerCharacter))).scalars().first():
            s.add(PlayerCharacter())
        # Structured Editor starter shown in Edit Mode for the new campaign.
        s.add(ChatMessage(
            role="assistant", content=CAMPAIGN_STARTER, turn_number=1, variant=0,
            speaker="planner", mode="planner",
        ))
        await s.commit()
    await storage.refresh_active_adventure_meta()
    return {"id": cid, "adventureId": aid, "switched": True, "editMode": True}


@router.post("/campaigns/{cid}/load")
async def load_campaign_route(cid: str, session: AsyncSession = Depends(get_session)):
    if not storage.campaign_dir(cid).exists():
        raise HTTPException(404, "Campaign not found")
    advs = storage.list_adventures(cid)
    await storage.refresh_active_adventure_meta()
    if advs:
        aid = advs[-1]["id"]
        seed_pc = False
    else:
        aid = await storage.create_adventure(cid, "Adventure 1")
        seed_pc = True
    await switch_active(storage.campaign_db_path(cid), storage.adventure_db_path(cid, aid))
    await _set_active(cid, aid)
    if seed_pc:
        async with new_session() as s:
            if not (await s.execute(select(PlayerCharacter))).scalars().first():
                s.add(PlayerCharacter())
                await s.commit()
    return {"id": cid, "adventureId": aid, "switched": True}


@router.put("/campaigns/{cid}")
async def rename_campaign_route(cid: str, data: dict = Body(default={})):
    meta = storage.read_campaign_meta(cid)
    if not meta:
        raise HTTPException(404, "Campaign not found")
    if data.get("name"):
        meta["name"] = data["name"].strip()
        storage.write_campaign_meta(cid, meta)
    return meta


@router.delete("/campaigns/{cid}")
async def delete_campaign_route(cid: str, session: AsyncSession = Depends(get_session)):
    cur_cid, _ = await _active_ids(session)
    camps = storage.list_campaigns()
    if len(camps) <= 1:
        raise HTTPException(400, "Can't delete the only campaign")
    switched_to = None
    if cid == cur_cid:
        other = next(c for c in camps if c["id"] != cid)
        advs = storage.list_adventures(other["id"])
        aid = advs[-1]["id"] if advs else await storage.create_adventure(other["id"], "Adventure 1")
        await switch_active(storage.campaign_db_path(other["id"]), storage.adventure_db_path(other["id"], aid))
        await _set_active(other["id"], aid)
        switched_to = {"campaignId": other["id"], "adventureId": aid}
    shutil.rmtree(storage.campaign_dir(cid), ignore_errors=True)
    return {"deleted": cid, "switchedTo": switched_to}


def _portrait_refs(db_path: Path) -> set[str]:
    """Portrait filenames referenced by an adventure's PC + party members."""
    refs: set[str] = set()
    if not db_path.exists():
        return refs
    con = sqlite3.connect(str(db_path))
    try:
        for tbl in ("player_characters", "party_members"):
            try:
                for (bi,) in con.execute(f"SELECT basic_info FROM {tbl}"):
                    try:
                        p = (json.loads(bi) or {}).get("portrait")
                    except (json.JSONDecodeError, TypeError):
                        p = None
                    if p:
                        refs.add(p)
            except sqlite3.OperationalError:
                pass
    finally:
        con.close()
    return refs


@router.get("/campaigns/{cid}/export")
async def export_campaign(cid: str, adventures: str | None = None):
    """Export a campaign as a self-contained .zip (campaign + chosen adventures +
    referenced portraits). `adventures` = comma-separated adventure ids, or omit
    for all."""
    cdir = storage.campaign_dir(cid)
    if not cdir.exists():
        raise HTTPException(404, "Campaign not found")
    await storage.refresh_active_adventure_meta()
    meta = storage.read_campaign_meta(cid) or {"id": cid, "name": "Campaign"}
    all_advs = storage.list_adventures(cid)
    if adventures is not None:
        wanted = {a for a in adventures.split(",") if a}
        advs = [a for a in all_advs if a["id"] in wanted]
    else:
        advs = all_advs

    portraits: set[str] = set()
    for a in advs:
        portraits |= _portrait_refs(storage.adventure_db_path(cid, a["id"]))

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("campaign.json", json.dumps(meta, ensure_ascii=False))
        z.write(storage.campaign_db_path(cid), "campaign.db")
        for a in advs:
            base = f"adventures/{a['id']}"
            z.writestr(f"{base}/adventure.json", json.dumps(a, ensure_ascii=False))
            z.write(storage.adventure_db_path(cid, a["id"]), f"{base}/adventure.db")
        for fn in portraits:
            p = PORTRAITS_DIR / fn
            if p.exists():
                z.write(p, f"portraits/{fn}")
    buf.seek(0)
    safe = re.sub(r"[^\w\-]+", "_", meta.get("name", "campaign")).strip("_") or "campaign"
    return StreamingResponse(
        buf, media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{safe}.zip"'},
    )


@router.post("/campaigns/import")
async def import_campaign(file: UploadFile):
    """Import a campaign zip as a NEW campaign (deduping its name). DB files are
    portable as-is (scope is folder location, not a column); only folder ids +
    json id fields are regenerated. Portraits are restored to the global dir."""
    raw = await file.read()
    try:
        z = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        raise HTTPException(400, "Not a valid zip file")
    names = set(z.namelist())
    if "campaign.db" not in names:
        raise HTTPException(400, "Zip is not a Wayward campaign export")

    try:
        cmeta = json.loads(z.read("campaign.json")) if "campaign.json" in names else {}
    except json.JSONDecodeError:
        cmeta = {}
    base_name = (cmeta.get("name") or "Imported Campaign").strip() or "Imported Campaign"
    existing = {c.get("name") for c in storage.list_campaigns()}
    name, i = base_name, 2
    while name in existing:
        name = f"{base_name} ({i})"
        i += 1

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    new_cid = str(uuid.uuid4())
    cdir = storage.campaign_dir(new_cid)
    (cdir / "adventures").mkdir(parents=True, exist_ok=True)
    (cdir / "portraits").mkdir(parents=True, exist_ok=True)
    storage.campaign_db_path(new_cid).write_bytes(z.read("campaign.db"))
    storage.write_campaign_meta(new_cid, {"id": new_cid, "name": name, "createdAt": now})

    adv_ids = sorted({
        n.split("/")[1] for n in names
        if n.startswith("adventures/") and n.endswith("/adventure.db")
    })
    for old_aid in adv_ids:
        new_aid = str(uuid.uuid4())
        adir = storage.adventure_dir(new_cid, new_aid)
        adir.mkdir(parents=True, exist_ok=True)
        (adir / "portraits").mkdir(parents=True, exist_ok=True)
        storage.adventure_db_path(new_cid, new_aid).write_bytes(
            z.read(f"adventures/{old_aid}/adventure.db")
        )
        try:
            ameta = json.loads(z.read(f"adventures/{old_aid}/adventure.json"))
        except (KeyError, json.JSONDecodeError):
            ameta = {}
        ameta.update({"id": new_aid})
        ameta.setdefault("name", "Adventure")
        ameta.setdefault("createdAt", now)
        ameta.setdefault("lastPlayedAt", now)
        ameta.setdefault("day", 1)
        storage.write_adventure_meta(new_cid, new_aid, ameta)

    if not adv_ids:
        await storage.create_adventure(new_cid, "Adventure 1")

    for n in names:
        if n.startswith("portraits/") and not n.endswith("/"):
            fn = n.split("/", 1)[1]
            dest = PORTRAITS_DIR / fn
            if fn and not dest.exists():
                dest.write_bytes(z.read(n))

    return {"id": new_cid, "name": name}


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
    if await _active_party_count(session) >= await _max_party_size(session):
        raise HTTPException(400, "Party is full — increase the party size limit in Config.")
    pm = PartyMember(
        basic_info=data.basicInfo.model_dump(),
        equipment=data.equipment.model_dump(),
        field_skill=data.fieldSkill.model_dump(),
    )
    session.add(pm)
    await session.commit()
    await session.refresh(pm)
    return _pm_to_response(pm)


@router.put("/party-members/{member_id}/in-party", response_model=PartyMemberResponse)
async def set_party_membership(
    member_id: str,
    data: PartyMembershipUpdate,
    session: AsyncSession = Depends(get_session),
):
    pm = await session.get(PartyMember, member_id)
    if not pm:
        raise HTTPException(404, "Party member not found")
    if data.inParty and not pm.in_party:
        if await _active_party_count(session) >= await _max_party_size(session):
            raise HTTPException(400, "Party is full — increase the party size limit in Config.")
    pm.in_party = data.inParty
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


# ── Narrator Config ───────────────────────────────────────────────

def _narrator_response(n: NarratorConfig) -> NarratorResponse:
    # Fall back to the built-in defaults for the protocol blocks so Config shows
    # the effective text the narrator actually receives (and the user can edit it).
    return NarratorResponse(
        instructions=n.instructions or "",
        actionInstruction=n.action_instruction or ACTION_INSTRUCTION,
        spotlightRule=n.spotlight_rule or DEFAULT_SPOTLIGHT_RULE,
        firstMessage=n.first_message or "",
        postHistoryInstructions=n.post_history_instructions or "",
        plannerInstructions=getattr(n, "planner_instructions", "") or PLANNER_GUIDANCE,
    )


@router.get("/narrator", response_model=NarratorResponse)
async def get_narrator(session: AsyncSession = Depends(get_session)):
    n = (await session.execute(select(NarratorConfig))).scalars().first()
    if not n:
        n = NarratorConfig(instructions="")
        session.add(n)
        await session.commit()
    return _narrator_response(n)


@router.put("/narrator", response_model=NarratorResponse)
async def update_narrator(
    data: NarratorUpdate,
    session: AsyncSession = Depends(get_session),
):
    n = (await session.execute(select(NarratorConfig))).scalars().first()
    if not n:
        n = NarratorConfig()
        session.add(n)
    if data.instructions is not None:
        n.instructions = data.instructions
    if data.actionInstruction is not None:
        n.action_instruction = data.actionInstruction
    if data.spotlightRule is not None:
        n.spotlight_rule = data.spotlightRule
    if data.firstMessage is not None:
        n.first_message = data.firstMessage
    if data.postHistoryInstructions is not None:
        n.post_history_instructions = data.postHistoryInstructions
    if data.plannerInstructions is not None:
        n.planner_instructions = data.plannerInstructions
    await session.commit()
    return _narrator_response(n)


# ── OpenRouter Settings ───────────────────────────────────────────

def _item_to_dict(item: LorebookEntry) -> dict:
    """Build the /items API shape from a lorebook item entry (cat == 'items')."""
    return {
        "id": item.id,
        "kind": "item",
        "name": item.title,
        "type": item.item_type,
        "slot": item.slot,
        "maxStack": item.max_stack,
        "uses": item.uses,
        "rarity": item.rarity,
        "desc": item.content,
    }


async def _get_item(session: AsyncSession, item_id: str) -> LorebookEntry | None:
    """Fetch a lorebook entry only if it is an item (cat == 'items')."""
    e = await session.get(LorebookEntry, item_id)
    return e if e and e.cat == "items" else None


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
        maxPartySize=s.max_party_size,
        maxToolRounds=s.max_tool_rounds,
        useTools=bool(s.use_tools),
        worldbuildingMode=s.worldbuilding_mode,
        worldbuildingModelId=s.worldbuilding_model_id,
        summaryThreshold=getattr(s, "summary_threshold", 0.7) or 0.7,
        summaryModelId=getattr(s, "summary_model_id", "") or "",
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
    s.max_party_size = data.maxPartySize
    s.max_tool_rounds = data.maxToolRounds
    s.use_tools = data.useTools
    s.worldbuilding_mode = data.worldbuildingMode
    s.worldbuilding_model_id = data.worldbuildingModelId
    s.summary_threshold = data.summaryThreshold
    s.summary_model_id = data.summaryModelId
    await session.commit()
    return _or_response(s)


# ── Items (unified into the lorebook — cat == "items") ─────────────

@router.get("/items")
async def list_items(
    type: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    query = select(LorebookEntry).where(LorebookEntry.cat == "items")
    if type:
        query = query.where(LorebookEntry.item_type == type)
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
        select(LorebookEntry).where(
            LorebookEntry.cat == "items",
            LorebookEntry.title.ilike(f"%{q}%"),
        )
    )).scalars().all()
    return [_item_to_dict(i) for i in items]


@router.get("/items/{item_id}")
async def get_item(
    item_id: str,
    session: AsyncSession = Depends(get_session),
):
    item = await _get_item(session, item_id)
    if not item:
        raise HTTPException(404, "Item not found")
    return _item_to_dict(item)


@router.post("/items", status_code=201)
async def create_item(
    data: ItemCatalogCreate,
    session: AsyncSession = Depends(get_session),
):
    item = LorebookEntry(
        cat="items",
        title=data.name,
        content=data.desc,
        keywords=[],
        enabled=True,
        permanent=False,
        item_type=data.type,
        slot=data.slot,
        max_stack=data.maxStack,
        uses=data.uses,
        rarity=data.rarity,
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
    item = await _get_item(session, item_id)
    if not item:
        raise HTTPException(404, "Item not found")
    if data.name is not None:
        item.title = data.name
    if data.type is not None:
        item.item_type = data.type
    if data.slot is not None:
        item.slot = data.slot
    if data.maxStack is not None:
        item.max_stack = data.maxStack
    if data.uses is not None:
        item.uses = data.uses
    if data.rarity is not None:
        item.rarity = data.rarity
    if data.desc is not None:
        item.content = data.desc
    await session.commit()
    await session.refresh(item)
    return _item_to_dict(item)


@router.delete("/items/{item_id}", status_code=204)
async def delete_item(
    item_id: str,
    session: AsyncSession = Depends(get_session),
):
    item = await _get_item(session, item_id)
    if not item:
        raise HTTPException(404, "Item not found")
    if item.locked:
        raise HTTPException(403, "This item is locked and cannot be deleted")
    await session.delete(item)
    await session.commit()


# ── Inventory ─────────────────────────────────────────────────────

MAX_CARRY_SLOTS_DEFAULT = 12


async def _list_inventory_dicts(session: AsyncSession) -> list[dict]:
    """Return the current inventory as a list of stack dicts.

    Shape: ``{"itemId", "count", "item": {...} | None}`` — the same shape the
    /inventory route returns and that detect_item_use expects.
    """
    equipped = await inv_ops.equipped_map(session)
    instances = (await session.execute(select(ItemInstance))).scalars().all()
    result = []
    for inst in instances:
        item = await _get_item(session, inst.item_id)
        const_data = {
            "itemId": inst.item_id,
            "count": inst.count,
            "instanceId": inst.id,
            "item": _item_to_dict(item) if item else None,
        }
        const_data = {
            **const_data,
            **({
                "equippedBy": equip["characterId"],
                "equippedByName": equip["characterName"],
                "slot": equip["slot"],
            } if (equip := equipped.get(inst.id)) else {}),
        }
        result.append(const_data)
    return result


@router.get("/inventory")
async def list_inventory(session: AsyncSession = Depends(get_session)):
    return await _list_inventory_dicts(session)


@router.post("/inventory/add")
async def add_to_inventory(
    data: InventoryAddRequest,
    session: AsyncSession = Depends(get_session),
):
    item = await _get_item(session, data.itemId)
    if not item:
        raise HTTPException(404, "Item not in catalog")

    message, deltas = await inv_ops.grant_items(session, item, data.count, "manual_add")
    if not deltas:
        raise HTTPException(400, message)
    await session.commit()
    return {"ok": True}


@router.post("/inventory/remove")
async def remove_from_inventory(
    data: InventoryRemoveRequest,
    session: AsyncSession = Depends(get_session),
):
    item = await _get_item(session, data.itemId)
    if not item:
        raise HTTPException(404, "Item not in inventory")
    message, deltas = await inv_ops.remove_items(session, item, data.count, "manual_remove")
    if not deltas:
        raise HTTPException(404, message)
    await session.commit()
    return {"ok": True}


@router.get("/inventory/capacity")
async def get_inventory_capacity(session: AsyncSession = Depends(get_session)):
    used = await inv_ops.capacity_used(session)
    settings = (await session.execute(select(OpenRouterSettings))).scalars().first()
    max_slots = settings.max_carry_slots if settings else MAX_CARRY_SLOTS_DEFAULT
    return {"used": used, "max": max_slots}


async def _resolve_character_by_id(session: AsyncSession, char_id: str):
    ch = await session.get(PlayerCharacter, char_id)
    if ch is None:
        ch = await session.get(PartyMember, char_id)
    return ch


@router.post("/characters/equip")
async def equip_item(data: dict = Body(default={}), session: AsyncSession = Depends(get_session)):
    """Equip a catalog item onto a character slot (reusing a stowed instance or
    minting one). Any instance previously in that slot becomes stowed."""
    char = await _resolve_character_by_id(session, data.get("characterId"))
    if char is None:
        raise HTTPException(404, "Character not found")
    item = await _get_item(session, data.get("itemId"))
    if not item:
        raise HTTPException(404, "Item not in catalog")
    slot = data.get("slot")
    if slot not in EQUIP_SLOT_KEYS:
        raise HTTPException(400, "Invalid equipment slot")
    await inv_ops.equip_instance(session, char, char.id, slot, item, instance_id=data.get("instanceId"))
    await session.commit()
    return {"ok": True}


@router.post("/characters/unequip")
async def unequip_item(data: dict = Body(default={}), session: AsyncSession = Depends(get_session)):
    """Clear a character's equipment slot — the instance becomes stowed."""
    char = await _resolve_character_by_id(session, data.get("characterId"))
    if char is None:
        raise HTTPException(404, "Character not found")
    slot = data.get("slot")
    if slot not in EQUIP_SLOT_KEYS:
        raise HTTPException(400, "Invalid equipment slot")
    equipment = dict(char.equipment or {})
    if equipment.get(slot):
        equipment[slot] = None
        char.equipment = equipment
        await session.commit()
    return {"ok": True}


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
        locked=bool(entry.locked),
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
    if entry.locked:
        raise HTTPException(403, "This entry is locked and cannot be deleted")
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
            mode=m.mode or "narrator",
            location=m.location,
            timeOfDay=m.time_of_day,
            weather=m.weather,
            day=m.day,
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
        mode=msg.mode or "narrator",
        day=msg.day,
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

    # Chronicler facts are tied to their message: drop lore/quests the Chronicler
    # created on this turn and every turn after it (the ones being deleted).
    await reverse_chronicler_creations(session, msg.turn_number)

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
    messages = (await session.execute(select(ChatMessage).order_by(ChatMessage.id))).scalars().all()
    summary = (await session.execute(select(StorySummary))).scalars().first()
    settings = (await session.execute(select(OpenRouterSettings))).scalars().first()
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
        "narrator": {
            "instructions": narrator.instructions if narrator else "",
            "actionInstruction": narrator.action_instruction if narrator else "",
            "spotlightRule": narrator.spotlight_rule if narrator else "",
            "firstMessage": narrator.first_message if narrator else "",
            "postHistoryInstructions": narrator.post_history_instructions if narrator else "",
            "plannerInstructions": getattr(narrator, "planner_instructions", "") if narrator else "",
        },
        "chatMessages": [
            {
                "role": m.role, "content": m.content,
                "turnNumber": m.turn_number, "variant": m.variant,
                "speaker": m.speaker or ("narrator" if m.role == "assistant" else "player"),
                "mode": m.mode or "narrator",
                "location": m.location,
                "timeOfDay": m.time_of_day,
                "weather": m.weather,
                "day": m.day,
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
            "maxPartySize": settings.max_party_size if settings else 3,
            "maxToolRounds": settings.max_tool_rounds if settings else 6,
            "useTools": bool(settings.use_tools) if settings else True,
            "worldbuildingMode": settings.worldbuilding_mode if settings else "confirmation",
            "worldbuildingModelId": settings.worldbuilding_model_id if settings else "",
            "summaryThreshold": getattr(settings, "summary_threshold", 0.7) if settings else 0.7,
            "summaryModelId": getattr(settings, "summary_model_id", "") if settings else "",
        },
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
                "locked": bool(e.locked),
                "cat": e.cat,
                "itemType": e.item_type,
                "slot": e.slot,
                "maxStack": e.max_stack,
                "uses": e.uses,
                "rarity": e.rarity,
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
    await session.execute(delete(ChatMessage))
    await session.execute(delete(PartyMember))
    await session.execute(delete(PlayerCharacter))
    await session.execute(delete(NarratorConfig))
    await session.execute(delete(StorySummary))
    await session.execute(delete(WorldbuildingProposal))
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
            in_party=pm_data.get("inParty", True),
        )
        session.add(pm)

    # Restore narrator
    nar = data.get("narrator", {})
    session.add(NarratorConfig(
        instructions=nar.get("instructions", ""),
        action_instruction=nar.get("actionInstruction", ""),
        spotlight_rule=nar.get("spotlightRule", ""),
        first_message=nar.get("firstMessage", ""),
        post_history_instructions=nar.get("postHistoryInstructions", ""),
        planner_instructions=nar.get("plannerInstructions", ""),
    ))

    # Restore chat
    for msg in data.get("chatMessages", []):
        session.add(ChatMessage(
            role=msg["role"], content=msg["content"],
            turn_number=msg.get("turnNumber", 0), variant=msg.get("variant", 0),
            speaker=msg.get("speaker", "narrator" if msg["role"] == "assistant" else "player"),
            mode=msg.get("mode", "narrator"),
            location=msg.get("location"),
            time_of_day=msg.get("timeOfDay"),
            weather=msg.get("weather"),
            day=msg.get("day"),
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
        max_party_size=s.get("maxPartySize", 3),
        max_tool_rounds=s.get("maxToolRounds", 6),
        use_tools=s.get("useTools", True),
        worldbuilding_mode=s.get("worldbuildingMode", "confirmation"),
        worldbuilding_model_id=s.get("worldbuildingModelId", ""),
        summary_threshold=s.get("summaryThreshold", 0.7),
        summary_model_id=s.get("summaryModelId", ""),
    ))

    # (Items are restored as part of the lorebook below — cat == "items".)

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
            locked=le_data.get("locked", False),
            cat=le_data.get("cat", "world"),
            item_type=le_data.get("itemType"),
            slot=le_data.get("slot"),
            max_stack=le_data.get("maxStack", 1),
            uses=le_data.get("uses"),
            rarity=le_data.get("rarity", "c"),
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
    # OpenRouterSettings (API key, model, sampling, context, carry slots) is
    # user configuration, not adventure progress — intentionally NOT cleared so
    # "New Adventure" preserves it.
    await session.execute(delete(LorebookEntry))
    await session.execute(delete(LorebookConfig))
    await session.execute(delete(QuestObjective))
    await session.execute(delete(Quest))
    await session.execute(delete(InventoryStack))
    await session.execute(delete(ChatMessage))
    await session.execute(delete(PartyMember))
    await session.execute(delete(PlayerCharacter))
    await session.execute(delete(NarratorConfig))
    await session.execute(delete(StorySummary))
    await session.execute(delete(WorldbuildingProposal))
    await session.commit()

    # Re-seed (seed_defaults does not touch OpenRouterSettings)
    from server.db.seed import seed_defaults
    await seed_defaults()

    return {"ok": True}


# ── Models Proxy ──────────────────────────────────────────────────

@router.get("/models")
async def list_models(session: AsyncSession = Depends(get_session)):
    # OpenRouter's model list is public, so this works without an API key —
    # the dropdown can be populated before the user has entered one.
    settings = (await session.execute(select(OpenRouterSettings))).scalars().first()
    api_key = settings.api_key if settings else ""
    try:
        models = await fetch_models(api_key)
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
    pc = (await session.execute(select(PlayerCharacter))).scalars().first()
    if not pc:
        raise HTTPException(400, "No player character created")

    # Only active (in-party) members participate in narration and spotlight.
    party = list(
        (await session.execute(select(PartyMember).where(PartyMember.in_party == True))).scalars().all()  # noqa: E712
    )
    # Narration only ever sees the 'narrator' thread — Planning-mode messages
    # live in their own thread and never enter narration context.
    all_messages = list(
        (await session.execute(
            select(ChatMessage)
            .where(func.coalesce(ChatMessage.mode, "narrator") != "planner")
            .order_by(ChatMessage.id)
        )).scalars().all()
    )
    summary = (await session.execute(select(StorySummary))).scalars().first()
    if not summary:
        summary = StorySummary(content="", summary_up_to_turn=0)
        session.add(summary)
    catalog = list((await session.execute(select(LorebookEntry).where(LorebookEntry.cat == "items"))).scalars().all())
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

    return settings, narrator, pc, party, all_messages, summary, catalog, quests, quest_objectives, lore_entries, lore_config


async def _should_use_tools(settings: OpenRouterSettings) -> bool:
    """Agentic tool loop runs when enabled AND the selected model supports tools.

    Falls back to the legacy text-block path otherwise. Model support is read
    from the (cached) OpenRouter model list; on any failure we trust the toggle
    and let the call surface an error rather than silently downgrading."""
    if not settings.use_tools:
        return False
    try:
        models = await fetch_models(settings.api_key)
        m = next((x for x in models if x["id"] == settings.model_id), None)
        if m is not None:
            return bool(m.get("supportsTools"))
    except Exception:
        log.info("_should_use_tools: model list fetch failed; assuming tool support")
    return True


async def _maybe_summarize_and_build(
    settings, narrator, pc, party_list,
    history: list[ChatMessage],
    summary: StorySummary,
    player_message: str,
    current_turn: int,
    session: AsyncSession,
    agentic: bool = False,
    item_catalog: list[LorebookEntry] | None = None,
    quests: list[Quest] | None = None,
    quest_objectives: list[QuestObjective] | None = None,
    lore_entries: list[LorebookEntry] | None = None,
    lore_config: LorebookConfig | None = None,
):
    """Check if summarization is needed, do it, then build the prompt.
    Returns (prompt_messages, did_summarize, spotlight_signals, summarize_hint).

    In agentic mode the deterministic second summarization call is skipped (the
    model owns summarization via the update_summary tool); instead we return a
    ``summarize_hint`` flag when context is getting long. The legacy path keeps
    threshold-triggered auto-summary as before."""

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
        spotlight_block = format_spotlight_block(
            spotlight_signals, getattr(narrator, "spotlight_rule", "") or None
        )

    # If the player addressed a benched (not-in-party) member by name, hint the
    # narrator to acknowledge their absence rather than silently ignoring it.
    benched = (await session.execute(
        select(PartyMember).where(PartyMember.in_party == False)  # noqa: E712
    )).scalars().all()
    absent = [
        pm.basic_info["name"] for pm in benched
        if pm.basic_info.get("name") and _name_mentioned(pm.basic_info["name"], player_message)
    ]
    if absent:
        note = (
            "NOTE — ABSENT PARTY MEMBER: The player named "
            + ", ".join(absent)
            + (", who is" if len(absent) == 1 else ", who are")
            + " not currently travelling with the party. Acknowledge that they "
            "aren't here rather than voicing them as if present."
        )
        spotlight_block = f"{spotlight_block}\n\n{note}" if spotlight_block else note

    # Build a test prompt to check size
    test_prompt = build_prompt(
        narrator_config=narrator,
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
        include_action_protocol=not agentic,
    )

    preamble_tokens = estimate_prompt_tokens(test_prompt)
    did_summarize = False
    summarize_hint = False  # kept for signature; deterministic summarisation below
    over_threshold = should_summarize(
        preamble_tokens, 0, settings.max_context_tokens, settings.max_tokens_response,
        threshold=getattr(settings, "summary_threshold", None) or 0.7,
    )

    # Deterministic summarisation in BOTH modes (reliable — not dependent on the
    # model choosing to call update_summary). Uses the optional summary model.
    if over_threshold:
        to_summarize, to_keep, new_boundary = pick_messages_to_summarize(filtered)
        if to_summarize:
            new_summary = await generate_summary(
                api_key=settings.api_key,
                model_id=(getattr(settings, "summary_model_id", "") or settings.model_id),
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
        include_action_protocol=not agentic,
    )

    return messages, did_summarize, spotlight_signals, summarize_hint


@router.post("/chat/turn")
async def chat_turn(
    data: ChatTurnRequest,
    session: AsyncSession = Depends(get_session),
):
    if data.mode == "planner":
        return await _planner_turn(data, session)

    settings, narrator, pc, party, all_messages, summary, catalog, quests, quest_objectives, lore_entries, lore_config = await _load_game_context(session)

    max_turn = max((m.turn_number for m in all_messages), default=0)
    current_turn = max_turn + 1

    user_msg = ChatMessage(role="user", content=data.message, turn_number=current_turn, speaker=pc.id)
    session.add(user_msg)

    agentic = await _should_use_tools(settings)

    # Legacy path: deterministic item-use detection on the player's message
    # (decrement deferred to the save transaction). In agentic mode the
    # consume_item tool replaces this, so detection is skipped.
    player_deltas = [] if agentic else await _detect_player_deltas(data.message, session)
    await session.commit()

    messages, did_summarize, spotlight_signals, summarize_hint = await _maybe_summarize_and_build(
        settings, narrator, pc, party,
        history=all_messages,
        summary=summary,
        player_message=data.message,
        current_turn=current_turn,
        session=session,
        agentic=agentic,
        item_catalog=catalog,
        quests=quests,
        quest_objectives=quest_objectives,
        lore_entries=lore_entries,
        lore_config=lore_config,
    )

    variant_count = sum(
        1 for m in all_messages if m.turn_number == current_turn and m.role == "assistant"
    )

    if agentic:
        return _stream_agent_response(
            messages=messages,
            settings=settings,
            party_list=party,
            current_turn=current_turn,
            variant=variant_count,
            spotlight_signals=spotlight_signals,
            summarize_hint=summarize_hint,
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
    settings, narrator, pc, party, all_messages, summary, catalog, quests, quest_objectives, lore_entries, lore_config = await _load_game_context(session)

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
    # The prior variant's Chronicler lore/quests belong to the discarded telling
    # of this turn — drop them; the re-run's Chronicler pass will record fresh.
    await reverse_chronicler_creations(session, turn, exact=True)
    await session.commit()
    agentic = await _should_use_tools(settings)
    # Re-detect against the now-restored inventory (legacy path only); agentic
    # mode re-derives item use through the consume_item tool during the loop.
    player_deltas = [] if agentic else await _detect_player_deltas(user_msg.content, session)

    messages, did_summarize, spotlight_signals, summarize_hint = await _maybe_summarize_and_build(
        settings, narrator, pc, party,
        history=history,
        summary=summary,
        player_message=user_msg.content,
        current_turn=turn,
        session=session,
        agentic=agentic,
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

    if agentic:
        return _stream_agent_response(
            messages=messages,
            settings=settings,
            party_list=party,
            current_turn=turn,
            variant=variant_count,
            spotlight_signals=spotlight_signals,
            summarize_hint=summarize_hint,
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
async def regenerate(
    data: dict = Body(default={}),
    session: AsyncSession = Depends(get_session),
):
    guidance = (data.get("guidance") or "").strip() if isinstance(data, dict) else ""
    settings, narrator, pc, party, all_messages, summary, catalog, quests, quest_objectives, lore_entries, lore_config = await _load_game_context(session)

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

    # Drop the discarded telling's Chronicler lore/quests for this turn; the
    # re-run's Chronicler pass records fresh ones tied to the new message.
    await reverse_chronicler_creations(session, last_turn, exact=True)

    # REGENERATE wipes all existing assistant variants for this turn
    await session.execute(
        delete(ChatMessage).where(
            ChatMessage.turn_number == last_turn,
            ChatMessage.role == "assistant",
        )
    )

    await session.commit()
    agentic = await _should_use_tools(settings)
    # Re-run detection on the same player message against the restored inventory
    # (legacy path only; agentic mode uses the consume_item tool).
    player_deltas = [] if agentic else await _detect_player_deltas(last_user_msg.content, session)

    history = [m for m in all_messages if m.turn_number < last_turn]

    messages, did_summarize, spotlight_signals, summarize_hint = await _maybe_summarize_and_build(
        settings, narrator, pc, party,
        history=history,
        summary=summary,
        player_message=last_user_msg.content,
        current_turn=last_turn,
        session=session,
        agentic=agentic,
        item_catalog=catalog,
        quests=quests,
        quest_objectives=quest_objectives,
        lore_entries=lore_entries,
        lore_config=lore_config,
    )

    # Optional steering note for THIS regeneration only — injected right before
    # the player's message and never persisted to history.
    if guidance:
        note = {
            "role": "system",
            "content": (
                "RETELLING DIRECTION (applies only to this regeneration of the "
                "last turn; not world canon): " + guidance
            ),
        }
        insert_at = next(
            (i for i in range(len(messages) - 1, -1, -1) if messages[i].get("role") == "user"),
            len(messages),
        )
        messages.insert(insert_at, note)

    if agentic:
        return _stream_agent_response(
            messages=messages,
            settings=settings,
            party_list=party,
            current_turn=last_turn,
            variant=0,
            spotlight_signals=spotlight_signals,
            summarize_hint=summarize_hint,
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


# ── World-building (Chronicler) ───────────────────────────────────

def _proposal_to_schema(p: WorldbuildingProposal) -> WorldbuildProposalSchema:
    return WorldbuildProposalSchema(
        id=p.id, turnNumber=p.turn_number, kind=p.kind, operation=p.operation,
        targetId=p.target_id, payload=p.payload or {}, summary=p.summary,
        status=p.status, note=p.note,
    )


@router.post("/worldbuild/run", response_model=list[WorldbuildProposalSchema])
async def worldbuild_run(
    data: WorldbuildRunRequest,
    session: AsyncSession = Depends(get_session),
):
    turn = data.turn
    if turn is None:
        turn = (
            await session.execute(select(func.max(ChatMessage.turn_number)))
        ).scalar() or 0
    if turn <= 0:
        return []
    proposals = await run_worldbuilder(turn)
    return [_proposal_to_schema(p) for p in proposals]


@router.get("/worldbuild/proposals", response_model=list[WorldbuildProposalSchema])
async def worldbuild_list(
    status: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    query = select(WorldbuildingProposal).order_by(WorldbuildingProposal.id.desc())
    if status:
        query = query.where(WorldbuildingProposal.status == status)
    rows = (await session.execute(query)).scalars().all()
    return [_proposal_to_schema(p) for p in rows]


@router.get("/worldbuild/proposals/count")
async def worldbuild_count(session: AsyncSession = Depends(get_session)):
    n = (
        await session.execute(
            select(func.count()).select_from(WorldbuildingProposal)
            .where(WorldbuildingProposal.status == "pending")
        )
    ).scalar()
    return {"pending": n or 0}


@router.post("/worldbuild/proposals/{proposal_id}/accept", response_model=WorldbuildProposalSchema)
async def worldbuild_accept(
    proposal_id: str,
    session: AsyncSession = Depends(get_session),
):
    p = await session.get(WorldbuildingProposal, proposal_id)
    if not p:
        raise HTTPException(404, "Proposal not found")
    if p.status == "accepted":
        return _proposal_to_schema(p)
    ok, note = await apply_proposal(p, session)
    p.status = "accepted" if ok else "failed"
    p.note = note
    await session.commit()
    return _proposal_to_schema(p)


@router.post("/worldbuild/proposals/{proposal_id}/reject", response_model=WorldbuildProposalSchema)
async def worldbuild_reject(
    proposal_id: str,
    session: AsyncSession = Depends(get_session),
):
    p = await session.get(WorldbuildingProposal, proposal_id)
    if not p:
        raise HTTPException(404, "Proposal not found")
    p.status = "rejected"
    await session.commit()
    return _proposal_to_schema(p)


@router.post("/worldbuild/proposals/accept-all", response_model=list[WorldbuildProposalSchema])
async def worldbuild_accept_all(session: AsyncSession = Depends(get_session)):
    rows = (
        await session.execute(
            select(WorldbuildingProposal).where(WorldbuildingProposal.status == "pending")
        )
    ).scalars().all()
    for p in rows:
        ok, note = await apply_proposal(p, session)
        p.status = "accepted" if ok else "failed"
        p.note = note
    await session.commit()
    return [_proposal_to_schema(p) for p in rows]


@router.post("/worldbuild/proposals/reject-all", status_code=204)
async def worldbuild_reject_all(session: AsyncSession = Depends(get_session)):
    rows = (
        await session.execute(
            select(WorldbuildingProposal).where(WorldbuildingProposal.status == "pending")
        )
    ).scalars().all()
    for p in rows:
        p.status = "rejected"
    await session.commit()


# ── Planner (Planning mode) ───────────────────────────────────────

async def _planner_turn(data: ChatTurnRequest, session: AsyncSession):
    settings = (await session.execute(select(OpenRouterSettings))).scalars().first()
    if not settings or not settings.api_key:
        raise HTTPException(400, "OpenRouter API key not configured")
    if not settings.model_id:
        raise HTTPException(400, "No model selected")
    pc = (await session.execute(select(PlayerCharacter))).scalars().first()

    max_turn = (
        await session.execute(
            select(func.max(ChatMessage.turn_number)).where(ChatMessage.mode == "planner")
        )
    ).scalar() or 0
    turn = max_turn + 1

    session.add(ChatMessage(
        role="user", content=data.message, turn_number=turn,
        speaker=pc.id if pc else "player", mode="planner",
    ))
    await session.commit()
    return _stream_planner_response(settings, turn)


def _stream_planner_response(settings: OpenRouterSettings, turn: int):
    max_context = settings.max_context_tokens

    async def stream():
        yield f"data: {json.dumps({'type': 'meta', 'maxContextTokens': max_context})}\n\n"

        final_content = ""
        pending_deletes: list[dict] = []
        try:
            async for ev in run_planner_agent(turn):
                t = ev["type"]
                if t == "content":
                    yield f"data: {json.dumps({'type': 'chunk', 'content': ev['text']})}\n\n"
                elif t == "discard":
                    yield f"data: {json.dumps({'type': 'discard'})}\n\n"
                elif t == "tool":
                    yield f"data: {json.dumps({'type': 'tool', 'name': ev['name'], 'result': ev['result']})}\n\n"
                elif t == "final":
                    final_content = ev["content"]
                    pending_deletes = ev["pendingDeletes"]
        except Exception as e:
            log.exception("Planner loop failed")
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"
            return

        log.info("PLANNER RESPONSE turn=%s (%d chars) | pendingDeletes=%d",
                 turn, len(final_content), len(pending_deletes))

        try:
            async with new_session() as save_session:
                save_session.add(ChatMessage(
                    role="assistant", content=final_content, turn_number=turn,
                    variant=0, speaker="planner", mode="planner",
                ))
                await save_session.commit()
        except Exception:
            log.exception("Failed to save planner response")

        done: dict = {"type": "done"}
        if pending_deletes:
            done["pendingDeletes"] = pending_deletes
        yield f"data: {json.dumps(done)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.post("/planner/deletes/apply")
async def planner_apply_deletes(
    data: PlannerDeletesApply,
    session: AsyncSession = Depends(get_session),
):
    applied = 0
    for d in data.deletes:
        if d.kind == "lore":
            e = await session.get(LorebookEntry, d.targetId)
            if e and not e.locked:
                await session.delete(e)
                applied += 1
        elif d.kind == "quest":
            q = await session.get(Quest, d.targetId)
            if q:
                await session.execute(delete(QuestObjective).where(QuestObjective.quest_id == q.id))
                await session.delete(q)
                applied += 1
        elif d.kind == "quest_objective":
            o = await session.get(QuestObjective, d.targetId)
            if o:
                await session.delete(o)
                applied += 1
        elif d.kind == "member":
            m = await session.get(PartyMember, d.targetId)
            if m:
                await session.delete(m)
                applied += 1
    await session.commit()
    return {"applied": applied}


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

    # Terminal log: full request — model, all sampling settings, and the full
    # assembled prompt — for troubleshooting.
    log.info(
        "LLM REQUEST turn=%s variant=%s | model=%s | temp=%s top_p=%s min_p=%s top_k=%s "
        "freq=%s pres=%s rep=%s | max_tokens=%s max_context=%s | ~%s prompt tokens",
        current_turn, variant, model_id, temperature, top_p, min_p, top_k,
        frequency_penalty, presence_penalty, repetition_penalty,
        max_tokens, max_context, context_tokens,
    )
    log.info(
        "LLM PROMPT (%d messages):\n%s",
        len(messages),
        "\n".join(f"  ── [{m['role']}] ──\n{m['content']}" for m in messages),
    )

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

        # Terminal log: full raw output from the LLM.
        log.info("LLM RESPONSE turn=%s variant=%s (%d chars):\n%s", current_turn, variant, len(full_text), full_text)

        # Parse and strip the action block before saving
        clean_text, actions = parse_action_block(full_text)
        if actions:
            log.info("LLM ACTIONS parsed: %s", json.dumps(actions, ensure_ascii=False))
        inv_deltas: list[dict] = []
        equip_changes: list[dict] = []

        try:
            async with new_session() as save_session:
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

                # Narrator-declared scene state (parsed from the action block).
                location: str | None = None
                time_of_day: str | None = None
                weather: str | None = None
                day: int | None = None
                if actions:
                    loc = actions.get("location")
                    if isinstance(loc, str) and loc.strip():
                        location = loc.strip()
                    tod = actions.get("timeOfDay")
                    if isinstance(tod, str) and tod.strip():
                        time_of_day = tod.strip()
                    wx = actions.get("weather")
                    if isinstance(wx, str) and wx.strip():
                        weather = wx.strip()
                    dy = actions.get("day")
                    if isinstance(dy, int) and dy > 0:
                        day = dy
                    elif isinstance(dy, str) and dy.strip().isdigit():
                        day = int(dy.strip())

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
                    location=location,
                    time_of_day=time_of_day,
                    weather=weather,
                    day=day,
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


# ── Agentic streaming driver ──────────────────────────────────────

def _stream_agent_response(
    messages: list[dict],
    settings: OpenRouterSettings,
    party_list: list[PartyMember],
    current_turn: int,
    variant: int,
    spotlight_signals: list[SpotlightSignal] | None = None,
    summarize_hint: bool = False,
):
    """Drive the agentic narrator loop and stream its final narration.

    Tool calls mutate the DB *during* the loop (inside run_narrator_agent), so
    here we only record the accumulated deltas/scene on the ChatMessage for
    reversal — we do not re-apply them."""
    _save_prompt_log(messages)

    context_tokens = estimate_prompt_tokens(messages)
    max_context = settings.max_context_tokens

    log.info(
        "LLM AGENT REQUEST turn=%s variant=%s | model=%s | temp=%s | max_tokens=%s "
        "max_context=%s max_tool_rounds=%s | ~%s prompt tokens",
        current_turn, variant, settings.model_id, settings.temperature,
        settings.max_tokens_response, max_context, settings.max_tool_rounds, context_tokens,
    )
    log.info(
        "LLM AGENT PROMPT (%d messages):\n%s",
        len(messages),
        "\n".join(f"  ── [{m['role']}] ──\n{m.get('content', '')}" for m in messages),
    )

    async def stream():
        yield f"data: {json.dumps({'type': 'meta', 'contextTokens': context_tokens, 'maxContextTokens': max_context})}\n\n"

        final_content = ""
        scene: dict = {}
        inv_deltas: list[dict] = []
        equip_changes: list[dict] = []

        try:
            async for ev in run_narrator_agent(
                settings=settings,
                base_messages=messages,
                current_turn=current_turn,
                summarize_hint=summarize_hint,
            ):
                etype = ev["type"]
                if etype == "content":
                    yield f"data: {json.dumps({'type': 'chunk', 'content': ev['text']})}\n\n"
                elif etype == "discard":
                    yield f"data: {json.dumps({'type': 'discard'})}\n\n"
                elif etype == "tool":
                    yield f"data: {json.dumps({'type': 'tool', 'name': ev['name'], 'result': ev['result']})}\n\n"
                elif etype == "final":
                    final_content = ev["content"]
                    scene = ev["scene"]
                    inv_deltas = ev["inv_deltas"]
                    equip_changes = ev["equip_changes"]
        except Exception as e:
            log.exception("Agent loop failed")
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"
            return

        log.info(
            "LLM AGENT RESPONSE turn=%s variant=%s (%d chars) | scene=%s | inv_deltas=%s | equip_changes=%s",
            current_turn, variant, len(final_content), scene, inv_deltas, equip_changes,
        )

        try:
            async with new_session() as save_session:
                speaker_ids: list[str] = []
                if party_list:
                    speaker_ids = detect_speakers(final_content, party_list)
                    for pm in party_list:
                        if pm.id in speaker_ids:
                            db_pm = await save_session.get(PartyMember, pm.id)
                            if db_pm:
                                db_pm.last_spoke_turn = current_turn

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

                assistant_msg = ChatMessage(
                    role="assistant", content=final_content,
                    turn_number=current_turn, variant=variant,
                    speaker="narrator",
                    location=scene.get("location"),
                    time_of_day=scene.get("timeOfDay"),
                    weather=scene.get("weather"),
                    day=scene.get("day"),
                    spotlight_reason=spot_reason,
                    applied_inventory_deltas=inv_deltas if inv_deltas else None,
                    applied_equipment_changes=equip_changes if equip_changes else None,
                )
                save_session.add(assistant_msg)
                await save_session.commit()
        except Exception:
            log.exception("Failed to save agent response to DB")

        response_tokens = len(final_content) // 4
        done_payload: dict = {
            'type': 'done',
            'contextTokens': context_tokens + response_tokens,
            'maxContextTokens': max_context,
        }
        if inv_deltas:
            done_payload['appliedInventoryDeltas'] = inv_deltas
        if equip_changes:
            done_payload['appliedEquipmentChanges'] = equip_changes
        yield f"data: {json.dumps(done_payload)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")
