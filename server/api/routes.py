import asyncio
import base64
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
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

PORTRAITS_DIR = Path(__file__).resolve().parent.parent / "portraits"
BACKDROPS_DIR = Path(__file__).resolve().parent.parent / "backdrops"

from server.ai.narrator_actions import ACTION_INSTRUCTION, execute_actions, parse_action_block, reverse_equipment_changes
from server.ai.item_detection import (
    apply_inventory_deltas,
    detect_item_use,
    reverse_inventory_deltas,
)
from server.ai.narrator_agent import run_narrator_agent
from server.ai import tts
from server.ai.worldbuilder import apply_proposal, reverse_chronicler_effects, run_worldbuilder
from server.ai.action_suggester import (
    ACTION_SUGGESTIONS_GUIDANCE,
    build_inline_options_guidance,
    normalize_option_rules,
    parse_inline_options,
    run_action_suggester,
)
from server.ai.scenario import compose_scenario_content, migrate_legacy_fields
from server.ai.planner import PLANNER_GUIDANCE, run_planner_agent
from server.ai.openrouter import chat_completion_stream, fetch_models
from server.ai.prompt_builder import augment_user_content, build_prompt, estimate_prompt_tokens
from server.ai.vision import VISION_DEFAULT_INSTRUCTIONS, describe_image
from server.ai.spotlight import DEFAULT_SPOTLIGHT_RULE, SpotlightSignal, _name_mentioned, compute_spotlight_signals, detect_speakers, format_spotlight_block
from server.ai.summarizer import (
    format_messages_for_summary,
    generate_summary,
    pick_messages_to_summarize,
    should_summarize,
)
from server.db.database import new_session, switch_active
from server.db import characters as char_files
from server.db import events as event_ops
from server.db import inventory as inv_ops
from server.db import party as party_ops
from server.db import storage
from server.api.schemas import (
    ActionSuggestionsResponse,
    ActionSuggestionsRunRequest,
    ChatEventResponse,
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
    TaskCreate,
    TaskSchema,
    TaskUpdate,
    ScenarioResponse,
    ScenarioUpdate,
    TtsSpeakRequest,
    TtsSpeakResponse,
    TtsStatusResponse,
    WorldbuildProposalSchema,
    WorldbuildRunRequest,
)
from server.db.database import get_session
from server.db.models import (
    ChatEvent,
    ChatMessage,
    InventoryStack,
    ItemInstance,
    LorebookConfig,
    LorebookEntry,
    NarratorConfig,
    OpenRouterSettings,
    PartyBinding,
    AppState,
    Task,
    StorySummary,
    WorldbuildingProposal,
)

router = APIRouter(prefix="/api")


def _portrait_full_url(cid: str) -> str | None:
    return f"/api/characters/{cid}/portrait/full" if char_files.full_path(cid) else None


def _portrait_crop_url(cid: str) -> str | None:
    return f"/api/characters/{cid}/portrait/crop" if char_files.crop_path(cid) else None


def _pc_to_response(pc) -> PlayerCharacterResponse:
    """Build the PC response from a RuntimeCharacter composite (identity file +
    binding)."""
    return PlayerCharacterResponse(
        id=pc.id,
        schemaVersion=1,
        basicInfo=pc.basic_info,
        equipment=pc.equipment,
        portraitFull=_portrait_full_url(pc.id),
        portraitCrop=_portrait_crop_url(pc.id),
        hasVoice=char_files.voice_path(pc.id) is not None,
    )


def _pm_to_response(pm) -> PartyMemberResponse:
    return PartyMemberResponse(
        id=pm.id,
        schemaVersion=1,
        basicInfo=pm.basic_info,
        equipment=pm.equipment,
        fieldSkill=pm.field_skill,
        lastSpokeTurn=pm.last_spoke_turn,
        inParty=bool(pm.in_party),
        portraitFull=_portrait_full_url(pm.id),
        portraitCrop=_portrait_crop_url(pm.id),
        hasVoice=char_files.voice_path(pm.id) is not None,
    )


async def _active_party_count(session: AsyncSession) -> int:
    return await party_ops.active_count(session)


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
        if await party_ops.pc_binding(s) is None:
            await party_ops.set_pc_identity(s, {})
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
    "4. **A hook** — the task or trouble that gets things moving.\n\n"
    "Describe any of these and I'll create the lore, characters, items, and tasks. "
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


@router.get("/campaigns/templates")
async def list_campaign_templates_route():
    from server.db import templates as tpl
    return {"templates": tpl.list_templates()}


@router.post("/campaigns")
async def create_campaign_route(
    data: dict = Body(default={}),
    session: AsyncSession = Depends(get_session),
):
    name = (data.get("name") or "New Campaign").strip() or "New Campaign"
    template = (data.get("template") or "empty").strip() or "empty"
    await storage.refresh_active_adventure_meta()
    cid = await storage.create_campaign(name)
    aid = await storage.create_adventure(cid, "Adventure 1")
    await switch_active(storage.campaign_db_path(cid), storage.adventure_db_path(cid, aid))
    await _set_active(cid, aid)

    from server.db import templates as tpl
    created_pc = await tpl.apply_template(template)

    async with new_session() as s:
        if not created_pc and await party_ops.pc_binding(s) is None:
            await party_ops.set_pc_identity(s, {})
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
            if await party_ops.pc_binding(s) is None:
                await party_ops.set_pc_identity(s, {})
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


def _character_ids(db_path: Path) -> set[str]:
    """Character ids referenced by an adventure's party bindings (their identity
    files carry the portraits, bundled into the export separately)."""
    ids: set[str] = set()
    if not db_path.exists():
        return ids
    con = sqlite3.connect(str(db_path))
    try:
        try:
            for (cid,) in con.execute("SELECT character_id FROM party_bindings"):
                if cid:
                    ids.add(cid)
        except sqlite3.OperationalError:
            pass
    finally:
        con.close()
    return ids


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

    char_ids: set[str] = set()
    for a in advs:
        char_ids |= _character_ids(storage.adventure_db_path(cid, a["id"]))

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("campaign.json", json.dumps(meta, ensure_ascii=False))
        z.write(storage.campaign_db_path(cid), "campaign.db")
        nv = storage.narrator_voice_path(cid)
        if nv:
            z.write(nv, nv.name)
        for a in advs:
            base = f"adventures/{a['id']}"
            z.writestr(f"{base}/adventure.json", json.dumps(a, ensure_ascii=False))
            z.write(storage.adventure_db_path(cid, a["id"]), f"{base}/adventure.db")
        # Bundle each referenced character's folder (identity json + portraits).
        for ch_id in char_ids:
            ch_dir = char_files.char_dir(ch_id)
            if ch_dir.exists():
                for p in ch_dir.iterdir():
                    if p.is_file():
                        z.write(p, f"characters/{ch_id}/{p.name}")
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
        # Narrator voice sample (campaign-level TTS cloning reference).
        if n.startswith("narrator-voice.") and "/" not in n:
            storage.set_narrator_voice(new_cid, z.read(n), Path(n).suffix)
        # Legacy exports carried loose portraits/ files → the global dir (the
        # characters→files migration picks them up when the campaign is loaded).
        elif n.startswith("portraits/") and not n.endswith("/"):
            fn = n.split("/", 1)[1]
            dest = PORTRAITS_DIR / fn
            if fn and not dest.exists():
                dest.write_bytes(z.read(n))
        # New exports carry character folders (identity + portraits). Restore
        # them into the global library, keeping any character id we already have.
        elif n.startswith("characters/") and not n.endswith("/"):
            parts = n.split("/", 2)
            if len(parts) == 3:
                ch_id, fname = parts[1], parts[2]
                dest = char_files.char_dir(ch_id) / fname
                if not dest.exists():
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(z.read(n))

    return {"id": new_cid, "name": name}


# ── Player Character ──────────────────────────────────────────────

@router.get("/player-character", response_model=PlayerCharacterResponse | None)
async def get_player_character(session: AsyncSession = Depends(get_session)):
    pc = await party_ops.load_pc(session)
    if not pc:
        return None
    return _pc_to_response(pc)


@router.put("/player-character", response_model=PlayerCharacterResponse)
async def upsert_player_character(
    data: PlayerCharacterUpdate,
    session: AsyncSession = Depends(get_session),
):
    # Identity → the persona's character file; equipment → the pc binding.
    pc = await party_ops.set_pc_identity(session, data.basicInfo.model_dump())
    await party_ops.set_equipment(session, pc.id, data.equipment.model_dump())
    await session.commit()
    reloaded = await party_ops.load_pc(session)
    return _pc_to_response(reloaded)


# ── Portrait Upload (legacy generic dir; character portraits live per-file) ──

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


# ── Party Members (identity → character files, state → bindings) ──

@router.get("/party-members", response_model=list[PartyMemberResponse])
async def list_party_members(session: AsyncSession = Depends(get_session)):
    return [_pm_to_response(m) for m in await party_ops.load_party(session)]


@router.post("/party-members", response_model=PartyMemberResponse, status_code=201)
async def add_party_member(
    data: PartyMemberCreate,
    session: AsyncSession = Depends(get_session),
):
    if await _active_party_count(session) >= await _max_party_size(session):
        raise HTTPException(400, "Party is full — increase the party size limit in Config.")
    m = await party_ops.add_member(
        session,
        basic_info=data.basicInfo.model_dump(),
        field_skill=data.fieldSkill.model_dump(),
    )
    await session.commit()
    return _pm_to_response(m)


@router.put("/party-members/{member_id}/in-party", response_model=PartyMemberResponse)
async def set_party_membership(
    member_id: str,
    data: PartyMembershipUpdate,
    session: AsyncSession = Depends(get_session),
):
    m = await party_ops.load_character(session, member_id)
    if m is None or m.role != "member":
        raise HTTPException(404, "Party member not found")
    if data.inParty and not m.in_party:
        if await _active_party_count(session) >= await _max_party_size(session):
            raise HTTPException(400, "Party is full — increase the party size limit in Config.")
    await party_ops.set_in_party(session, member_id, data.inParty)
    await session.commit()
    return _pm_to_response(await party_ops.load_character(session, member_id))


@router.put("/party-members/{member_id}", response_model=PartyMemberResponse)
async def update_party_member(
    member_id: str,
    data: PartyMemberUpdate,
    session: AsyncSession = Depends(get_session),
):
    m = await party_ops.load_character(session, member_id)
    if m is None or m.role != "member":
        raise HTTPException(404, "Party member not found")
    await party_ops.update_member_identity(
        session, member_id, data.basicInfo.model_dump(), data.fieldSkill.model_dump()
    )
    await party_ops.set_equipment(session, member_id, data.equipment.model_dump())
    await session.commit()
    return _pm_to_response(await party_ops.load_character(session, member_id))


@router.delete("/party-members/{member_id}", status_code=204)
async def remove_party_member(
    member_id: str,
    session: AsyncSession = Depends(get_session),
):
    # Unbind from THIS adventure; the character identity file stays in the
    # library (delete it explicitly from the Character Library).
    if not await party_ops.remove_member(session, member_id):
        raise HTTPException(404, "Party member not found")
    await session.commit()


# ── Character Library (portable identity files) ───────────────────

def _character_meta(data: dict) -> dict:
    cid = data.get("id", "")
    return {
        "id": cid,
        "type": data.get("type", "character"),
        "basicInfo": data.get("basicInfo", {}),
        "fieldSkill": data.get("fieldSkill", {}),
        "hasFull": char_files.full_path(cid) is not None,
        "hasCrop": char_files.crop_path(cid) is not None,
        "hasVoice": char_files.voice_path(cid) is not None,
        "fullUrl": f"/api/characters/{cid}/portrait/full" if char_files.full_path(cid) else None,
        "cropUrl": f"/api/characters/{cid}/portrait/crop" if char_files.crop_path(cid) else None,
        "voiceUrl": f"/api/characters/{cid}/voice" if char_files.voice_path(cid) else None,
    }


@router.get("/characters")
async def list_characters():
    return [_character_meta(c) for c in char_files.list_characters()]


# Portrait/chat-image URLs are stable while the underlying file can be
# replaced, so no `immutable` here — a short max-age plus the automatic
# ETag/Last-Modified revalidation keeps re-renders off the network without
# pinning stale art.
_MEDIA_CACHE = {"Cache-Control": "private, max-age=300"}


# ── Chat Backdrops ──────────────────────────────────────────────
# Static scene art in server/backdrops (repo-shipped, not per-campaign). The
# client picks one deterministically from the declared scene — location +
# time-of-day tokens matched against the filename (city_day.png, …), defaulting
# to forest_day.png (see client lib/backdrops.ts). This doubles as the
# foundation for a future narrator-driven pick: drop in more images and they
# start matching, no narrator changes needed.

_BACKDROP_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


@router.get("/backdrops")
async def list_backdrops():
    if not BACKDROPS_DIR.is_dir():
        return []
    return [
        {"file": p.name, "url": f"/api/backdrops/{p.name}"}
        for p in sorted(BACKDROPS_DIR.iterdir(), key=lambda p: p.name.lower())
        if p.is_file() and p.suffix.lower() in _BACKDROP_EXTS
    ]


@router.get("/backdrops/{filename}")
async def get_backdrop(filename: str):
    if Path(filename).name != filename:
        raise HTTPException(400, "Bad filename")
    path = BACKDROPS_DIR / filename
    if not path.is_file() or path.suffix.lower() not in _BACKDROP_EXTS:
        raise HTTPException(404, "No such backdrop")
    return FileResponse(str(path), headers=_MEDIA_CACHE)


@router.get("/characters/{cid}/portrait/{which}")
async def get_character_portrait(cid: str, which: str):
    path = char_files.full_path(cid) if which == "full" else char_files.crop_path(cid)
    if path is None:
        raise HTTPException(404, "No portrait")
    return FileResponse(str(path), headers=_MEDIA_CACHE)


@router.post("/characters/{cid}/portrait")
async def upload_character_portrait(
    cid: str,
    full: UploadFile | None = None,
    crop: UploadFile | None = None,
):
    """Set a character's full and/or crop portrait (replacing the old image)."""
    if not char_files.exists(cid):
        raise HTTPException(404, "Character not found")
    if full is not None:
        ext = Path(full.filename or "full.png").suffix or ".png"
        char_files.set_full(cid, await full.read(), ext)
    if crop is not None:
        char_files.set_crop(cid, await crop.read())
    return _character_meta(char_files.read_character(cid) or {"id": cid})


@router.get("/characters/{cid}/voice")
async def get_character_voice(cid: str):
    path = char_files.voice_path(cid)
    if path is None:
        raise HTTPException(404, "No voice sample")
    return FileResponse(str(path))


@router.post("/characters/{cid}/voice")
async def upload_character_voice(cid: str, file: UploadFile):
    """Set a character's TTS voice sample (~10s of clean speech; replaces the old)."""
    if not char_files.exists(cid):
        raise HTTPException(404, "Character not found")
    if not (file.content_type or "").startswith("audio/"):
        raise HTTPException(400, "Voice sample must be an audio file")
    ext = Path(file.filename or "voice.wav").suffix or ".wav"
    char_files.set_voice(cid, await file.read(), ext)
    return _character_meta(char_files.read_character(cid) or {"id": cid})


@router.delete("/characters/{cid}/voice", status_code=204)
async def delete_character_voice(cid: str):
    if not char_files.exists(cid):
        raise HTTPException(404, "Character not found")
    char_files.clear_voice(cid)


@router.post("/characters/{cid}/duplicate")
async def duplicate_character(cid: str):
    new = char_files.duplicate_character(cid)
    if new is None:
        raise HTTPException(404, "Character not found")
    return _character_meta(new)


@router.post("/characters/{cid}/import", response_model=PartyMemberResponse, status_code=201)
async def import_character(cid: str, session: AsyncSession = Depends(get_session)):
    """Bind an existing library character into the active adventure as a member."""
    if not char_files.exists(cid):
        raise HTTPException(404, "Character not found")
    in_party = await _active_party_count(session) < await _max_party_size(session)
    m = await party_ops.bind_existing(session, cid, in_party=in_party)
    if m is None:
        raise HTTPException(404, "Character not found")
    await session.commit()
    return _pm_to_response(m)


@router.delete("/characters/{cid}", status_code=204)
async def delete_character(cid: str, session: AsyncSession = Depends(get_session)):
    """Delete a character file from the library and unbind it from this adventure."""
    await party_ops.remove_member(session, cid)
    await session.commit()
    char_files.delete_character(cid)


@router.get("/characters/{cid}/export")
async def export_character(cid: str):
    raw = char_files.export_zip(cid)
    if raw is None:
        raise HTTPException(404, "Character not found")
    name = (char_files.read_character(cid) or {}).get("basicInfo", {}).get("name") or "character"
    safe = re.sub(r"[^\w\-]+", "_", name).strip("_") or "character"
    return StreamingResponse(
        io.BytesIO(raw), media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{safe}.zip"'},
    )


@router.post("/characters/import-file")
async def import_character_file(file: UploadFile):
    new = char_files.import_zip(await file.read())
    if new is None:
        raise HTTPException(400, "Not a valid character file")
    return _character_meta(new)


# ── Scenario ───────────────────────────────────────────────────────

async def _get_or_create_scenario_entry(session: AsyncSession) -> LorebookEntry:
    """Fetch the Scenario LorebookEntry — matched by title, case-insensitively,
    the same lookup server/ai/planner.py's set_scenario/get_scenario tools
    already use. Creates it if a from-scratch campaign somehow lacks it."""
    scn = (await session.execute(
        select(LorebookEntry).where(func.lower(LorebookEntry.title) == "scenario")
    )).scalars().first()
    if not scn:
        scn = LorebookEntry(title="Scenario", cat="world", permanent=True, locked=True)
        session.add(scn)
        await session.commit()
        await session.refresh(scn)
    return scn


def _scenario_to_schema(scn: LorebookEntry) -> ScenarioResponse:
    fields = scn.scenario_fields or {}
    return ScenarioResponse(
        setting=fields.get("setting", ""),
        historyBrief=fields.get("historyBrief", ""),
        species=fields.get("species", ""),
        geography=fields.get("geography", ""),
        techAndMagic=fields.get("techAndMagic", ""),
        other=fields.get("other", ""),
    )


@router.get("/scenario", response_model=ScenarioResponse)
async def get_scenario(session: AsyncSession = Depends(get_session)):
    scn = await _get_or_create_scenario_entry(session)
    migrated = migrate_legacy_fields(scn.scenario_fields, scn.content)
    if migrated != (scn.scenario_fields or {}):
        scn.scenario_fields = migrated
        await session.commit()
        await session.refresh(scn)
    return _scenario_to_schema(scn)


@router.put("/scenario", response_model=ScenarioResponse)
async def update_scenario(
    data: ScenarioUpdate,
    session: AsyncSession = Depends(get_session),
):
    scn = await _get_or_create_scenario_entry(session)
    fields = dict(scn.scenario_fields or {})
    if data.setting is not None:
        fields["setting"] = data.setting
    if data.historyBrief is not None:
        fields["historyBrief"] = data.historyBrief
    if data.species is not None:
        fields["species"] = data.species
    if data.geography is not None:
        fields["geography"] = data.geography
    if data.techAndMagic is not None:
        fields["techAndMagic"] = data.techAndMagic
    if data.other is not None:
        fields["other"] = data.other
    scn.scenario_fields = fields
    scn.content = compose_scenario_content(fields)
    # Defensive: keep the invariants the prompt-injection pipeline depends on,
    # in case a row predates these being set correctly.
    scn.cat = "world"
    scn.permanent = True
    scn.locked = True
    await session.commit()
    await session.refresh(scn)
    return _scenario_to_schema(scn)


# ── Narrator Config ───────────────────────────────────────────────

def _narrator_response(n: NarratorConfig, has_voice: bool = False) -> NarratorResponse:
    # Fall back to the built-in defaults for the protocol blocks so Config shows
    # the effective text the narrator actually receives (and the user can edit it).
    return NarratorResponse(
        instructions=n.instructions or "",
        actionInstruction=n.action_instruction or ACTION_INSTRUCTION,
        spotlightRule=n.spotlight_rule or DEFAULT_SPOTLIGHT_RULE,
        firstMessage=n.first_message or "",
        postHistoryInstructions=n.post_history_instructions or "",
        plannerInstructions=getattr(n, "planner_instructions", "") or PLANNER_GUIDANCE,
        actionSuggestionsEnabled=bool(getattr(n, "action_suggestions_enabled", False)),
        actionSuggestionsInstructions=getattr(n, "action_suggestions_instructions", "") or ACTION_SUGGESTIONS_GUIDANCE,
        actionSuggestionsMode=getattr(n, "action_suggestions_mode", "separate") or "separate",
        actionOptionRules=normalize_option_rules(getattr(n, "action_option_rules", None)),
        firstMessageOptions=[str(o) for o in (getattr(n, "first_message_options", None) or [])],
        diceEnabled=bool(getattr(n, "dice_enabled", True)),
        hasVoice=has_voice,
    )


async def _narrator_has_voice(session: AsyncSession) -> bool:
    cid, _ = await _active_ids(session)
    return bool(cid and storage.narrator_voice_path(cid))


@router.get("/narrator", response_model=NarratorResponse)
async def get_narrator(session: AsyncSession = Depends(get_session)):
    n = (await session.execute(select(NarratorConfig))).scalars().first()
    if not n:
        n = NarratorConfig(instructions="")
        session.add(n)
        await session.commit()
    return _narrator_response(n, await _narrator_has_voice(session))


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
    if data.actionSuggestionsEnabled is not None:
        n.action_suggestions_enabled = data.actionSuggestionsEnabled
    if data.actionSuggestionsInstructions is not None:
        n.action_suggestions_instructions = data.actionSuggestionsInstructions
    if data.actionSuggestionsMode is not None and data.actionSuggestionsMode in ("separate", "inline"):
        n.action_suggestions_mode = data.actionSuggestionsMode
    if data.actionOptionRules is not None:
        # Store exactly what the player configured; blanks are dropped and the
        # defaults kick in when the list ends up empty (mirrors read path).
        n.action_option_rules = [r.strip() for r in data.actionOptionRules if r.strip()]
    if data.firstMessageOptions is not None:
        n.first_message_options = [o.strip() for o in data.firstMessageOptions if o.strip()]
    if data.diceEnabled is not None:
        n.dice_enabled = data.diceEnabled
    await session.commit()
    return _narrator_response(n, await _narrator_has_voice(session))


# ── Journal ("The Story So Far") ──────────────────────────────────

@router.get("/journal")
async def get_journal(session: AsyncSession = Depends(get_session)):
    """Read-only view of the auto-maintained story summary. The narrator (or
    the threshold summarizer) keeps StorySummary current; this just surfaces
    it to the player as a recap."""
    s = (await session.execute(select(StorySummary))).scalars().first()
    return {
        "summary": (s.content or "") if s else "",
        "upToTurn": (s.summary_up_to_turn or 0) if s else 0,
    }


# ── Narrator voice sample (per-campaign TTS cloning reference) ─────

@router.get("/narrator/voice")
async def get_narrator_voice(session: AsyncSession = Depends(get_session)):
    cid, _ = await _active_ids(session)
    path = storage.narrator_voice_path(cid) if cid else None
    if path is None:
        raise HTTPException(404, "No narrator voice sample")
    return FileResponse(str(path))


@router.post("/narrator/voice")
async def upload_narrator_voice(
    file: UploadFile, session: AsyncSession = Depends(get_session)
):
    cid, _ = await _active_ids(session)
    if not cid:
        raise HTTPException(404, "No active campaign")
    if not (file.content_type or "").startswith("audio/"):
        raise HTTPException(400, "Voice sample must be an audio file")
    ext = Path(file.filename or "voice.wav").suffix or ".wav"
    storage.set_narrator_voice(cid, await file.read(), ext)
    return {"hasVoice": True}


@router.delete("/narrator/voice", status_code=204)
async def delete_narrator_voice(session: AsyncSession = Depends(get_session)):
    cid, _ = await _active_ids(session)
    if cid:
        storage.clear_narrator_voice(cid)


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
        # Items are lorebook entries and share the same entry rules.
        "keywords": item.keywords or [],
        "enabled": bool(item.enabled),
        "permanent": bool(item.permanent),
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
        maxPartySize=s.max_party_size,
        maxToolRounds=s.max_tool_rounds,
        useTools=bool(s.use_tools),
        worldbuildingMode=s.worldbuilding_mode,
        worldbuildingModelId=s.worldbuilding_model_id,
        actionSuggestionsModelId=getattr(s, "action_suggestions_model_id", "") or "",
        summaryThreshold=getattr(s, "summary_threshold", 0.7) or 0.7,
        summaryModelId=getattr(s, "summary_model_id", "") or "",
        visionModelId=getattr(s, "vision_model_id", "") or "google/gemma-3-4b-it",
        visionUseSameKey=bool(getattr(s, "vision_use_same_key", True)),
        visionApiKeySet=bool(getattr(s, "vision_api_key", "")),
        visionInstructions=(getattr(s, "vision_instructions", "") or "").strip() or VISION_DEFAULT_INSTRUCTIONS,
        ttsEnabled=bool(getattr(s, "tts_enabled", False)),
        ttsAutoplay=bool(getattr(s, "tts_autoplay", True)),
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
    s.max_party_size = data.maxPartySize
    s.max_tool_rounds = data.maxToolRounds
    s.use_tools = data.useTools
    s.worldbuilding_mode = data.worldbuildingMode
    s.worldbuilding_model_id = data.worldbuildingModelId
    s.action_suggestions_model_id = data.actionSuggestionsModelId
    s.summary_threshold = data.summaryThreshold
    s.summary_model_id = data.summaryModelId
    s.vision_model_id = data.visionModelId
    s.vision_use_same_key = data.visionUseSameKey
    if data.visionApiKey is not None:  # write-only, like apiKey
        s.vision_api_key = data.visionApiKey
    # Storing the default text verbatim is treated as "unset" so future
    # default improvements reach users who never customized it.
    s.vision_instructions = "" if data.visionInstructions.strip() == VISION_DEFAULT_INSTRUCTIONS else data.visionInstructions
    s.tts_enabled = data.ttsEnabled
    s.tts_autoplay = data.ttsAutoplay
    await session.commit()
    return _or_response(s)


# ── TTS (text-to-speech; optional Chatterbox install) ─────────────

@router.get("/tts/status", response_model=TtsStatusResponse)
async def tts_status(session: AsyncSession = Depends(get_session)):
    s = (await session.execute(select(OpenRouterSettings))).scalars().first()
    return TtsStatusResponse(
        enabled=bool(getattr(s, "tts_enabled", False)) if s else False,
        **tts.status(),
    )


@router.post("/tts/speak", response_model=TtsSpeakResponse)
async def tts_speak(
    data: TtsSpeakRequest,
    session: AsyncSession = Depends(get_session),
):
    """Synthesize one chat segment. `voice` is 'narrator' (narration + NPC lines,
    cloned from the campaign's narrator sample) or a character id (cloned from
    that character's voice.<ext>). A missing sample falls back to the default
    voice — never an error."""
    if not tts.is_installed():
        raise HTTPException(
            503, "TTS is not installed — pip install -r server/requirements-tts.txt"
        )
    s = (await session.execute(select(OpenRouterSettings))).scalars().first()
    if not s or not getattr(s, "tts_enabled", False):
        raise HTTPException(400, "TTS is disabled in Settings")
    text_in = (data.text or "").strip()
    if not text_in:
        raise HTTPException(400, "No text to speak")
    if len(text_in) > tts.MAX_TTS_CHARS:
        raise HTTPException(400, f"Text too long (max {tts.MAX_TTS_CHARS} chars)")

    if data.voice == "narrator":
        cid, _ = await _active_ids(session)
        voice_path = storage.narrator_voice_path(cid) if cid else None
    else:
        voice_path = char_files.voice_path(data.voice)

    try:
        filename, cached = await tts.synthesize(text_in, voice_path)
    except RuntimeError as e:
        raise HTTPException(500, f"TTS synthesis failed: {e}")
    return TtsSpeakResponse(url=f"/api/tts/audio/{filename}", cached=cached)


@router.get("/tts/audio/{name}")
async def tts_audio(name: str):
    if not re.fullmatch(r"[0-9a-f]{64}\.wav", name):
        raise HTTPException(404, "Not found")
    path = tts.cache_dir() / name
    if not path.exists():
        raise HTTPException(404, "Not found")
    # Content-addressed (sha256) → safe to cache aggressively client-side.
    return FileResponse(str(path), media_type="audio/wav",
                        headers={"Cache-Control": "public, max-age=31536000, immutable"})


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
        keywords=data.keywords or [],
        enabled=data.enabled,
        permanent=data.permanent,
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
    if data.keywords is not None:
        item.keywords = data.keywords
    if data.enabled is not None:
        item.enabled = data.enabled
    if data.permanent is not None:
        item.permanent = data.permanent
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

# The 12 valid equipment slot keys (used to validate /characters/equip|unequip).
EQUIP_SLOT_KEYS = {
    "head", "neck", "torsoOver", "torsoUnder", "leftHand", "rightHand",
    "waist", "legsOver", "legsUnder", "feet", "accessory1", "accessory2",
}


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
    qty = f" ×{data.count}" if data.count and data.count > 1 else ""
    await event_ops.add_player_event(session, f"Added {item.title}{qty} to the pack")
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
    qty = f" ×{data.count}" if data.count and data.count > 1 else ""
    await event_ops.add_player_event(session, f"Dropped {item.title}{qty}")
    await session.commit()
    return {"ok": True}


@router.post("/inventory/remove-instance")
async def remove_inventory_instance(
    data: dict = Body(default={}),
    session: AsyncSession = Depends(get_session),
):
    """Delete a specific stowed instance by its instance id (equipment-aware UI)."""
    instance_id = data.get("instanceId")
    inst = await session.get(ItemInstance, instance_id) if instance_id else None
    if not inst:
        raise HTTPException(404, "Instance not found")
    equipped = await inv_ops.equipped_map(session)
    if inst.id in equipped:
        raise HTTPException(400, "Item is equipped — unequip it first")
    item = await _get_item(session, inst.item_id)
    await session.delete(inst)
    await event_ops.add_player_event(session, f"Dropped {item.title if item else 'an item'}")
    await session.commit()
    return {"ok": True}


async def _resolve_character_by_id(session: AsyncSession, char_id: str):
    return await party_ops.load_character(session, char_id)


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
    who = (char.basic_info or {}).get("name", "Someone").split(" ")[0]
    await event_ops.add_player_event(session, f"{who} equipped {item.title}")
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
        inst = await session.get(ItemInstance, equipment[slot])
        item = await _get_item(session, inst.item_id) if inst else None
        equipment[slot] = None
        await party_ops.set_equipment(session, char.id, equipment)
        who = (char.basic_info or {}).get("name", "Someone").split(" ")[0]
        await event_ops.add_player_event(session, f"{who} unequipped {item.title if item else 'an item'}")
        await session.commit()
    return {"ok": True}


def _task_to_schema(task: Task) -> TaskSchema:
    return TaskSchema(id=task.id, text=task.text, status=task.status, notes=task.notes)


@router.get("/tasks", response_model=list[TaskSchema])
async def list_tasks(session: AsyncSession = Depends(get_session)):
    tasks = (await session.execute(select(Task).order_by(Task.sort_order))).scalars().all()
    return [_task_to_schema(t) for t in tasks]


@router.post("/tasks", response_model=TaskSchema, status_code=201)
async def create_task(
    data: TaskCreate,
    session: AsyncSession = Depends(get_session),
):
    max_order = (await session.execute(
        select(func.coalesce(func.max(Task.sort_order), -1))
    )).scalar()
    task = Task(
        text=data.text,
        status=data.status,
        notes=data.notes,
        sort_order=(max_order or 0) + 1,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return _task_to_schema(task)


@router.get("/tasks/{task_id}", response_model=TaskSchema)
async def get_task(
    task_id: str,
    session: AsyncSession = Depends(get_session),
):
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return _task_to_schema(task)


@router.put("/tasks/{task_id}", response_model=TaskSchema)
async def update_task(
    task_id: str,
    data: TaskUpdate,
    session: AsyncSession = Depends(get_session),
):
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    if data.text is not None:
        task.text = data.text
    if data.status is not None:
        task.status = data.status
    if data.notes is not None:
        task.notes = data.notes
    await session.commit()
    await session.refresh(task)
    return _task_to_schema(task)


@router.delete("/tasks/{task_id}", status_code=204)
async def delete_task(
    task_id: str,
    session: AsyncSession = Depends(get_session),
):
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    await session.delete(task)
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


# ── Chat images (player-attached, described by the vision agent) ──

_IMAGE_MIME_EXT = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif"}
_MAX_CHAT_IMAGE_BYTES = 10 * 1024 * 1024
_DATA_URL_RE = re.compile(r"^data:(image/[a-z+.-]+);base64,(.+)$", re.DOTALL)


async def _chat_images_dir(session: AsyncSession, create: bool = True) -> Path | None:
    """The active adventure's chat_images/ folder (images live with the save)."""
    cid, aid = await _active_ids(session)
    if not cid or not aid:
        return None
    d = storage.adventure_dir(cid, aid) / "chat_images"
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


async def _store_chat_image(session: AsyncSession, data_url: str) -> str:
    """Decode + save a data-URL image into the adventure folder; returns the
    stored filename. Raises HTTPException on bad/oversized input."""
    m = _DATA_URL_RE.match(data_url or "")
    if not m:
        raise HTTPException(400, "Image must be a base64 image data URL")
    mime, b64 = m.group(1), m.group(2)
    ext = _IMAGE_MIME_EXT.get(mime)
    if not ext:
        raise HTTPException(400, f"Unsupported image type: {mime}")
    try:
        raw = base64.b64decode(b64, validate=True)
    except Exception:
        raise HTTPException(400, "Invalid base64 image data")
    if len(raw) > _MAX_CHAT_IMAGE_BYTES:
        raise HTTPException(400, "Image too large (max 10 MB)")
    directory = await _chat_images_dir(session)
    if directory is None:
        raise HTTPException(409, "No active adventure")
    name = f"{uuid.uuid4().hex}.{ext}"
    (directory / name).write_bytes(raw)
    return name


async def _delete_chat_images(session: AsyncSession, names: list[str]) -> None:
    directory = await _chat_images_dir(session, create=False)
    if directory is None:
        return
    for name in names:
        if name:
            (directory / Path(name).name).unlink(missing_ok=True)


def _image_url(m: ChatMessage) -> str | None:
    path = getattr(m, "image_path", None)
    return f"/api/chat/images/{path}" if path else None


@router.get("/chat/images/{filename}")
async def get_chat_image(filename: str, session: AsyncSession = Depends(get_session)):
    directory = await _chat_images_dir(session, create=False)
    if directory is None:
        raise HTTPException(404, "No active adventure")
    path = directory / Path(filename).name  # basename only — no traversal
    if not path.is_file():
        raise HTTPException(404, "Image not found")
    return FileResponse(path, headers=_MEDIA_CACHE)


# ── Chat Messages ─────────────────────────────────────────────────

def _msg_response(m: ChatMessage) -> ChatMessageResponse:
    return ChatMessageResponse(
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
        editorActions=getattr(m, "editor_actions", None),
        imageUrl=_image_url(m),
        imageDescription=getattr(m, "image_description", None),
        createdAt=m.created_at.isoformat() if m.created_at else "",
    )


@router.get("/chat/messages", response_model=list[ChatMessageResponse])
async def get_chat_messages(session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(ChatMessage).order_by(ChatMessage.id)
    )
    return [_msg_response(m) for m in result.scalars().all()]


@router.get("/chat/events", response_model=list[ChatEventResponse])
async def get_chat_events(session: AsyncSession = Depends(get_session)):
    """Persistent in-chat toasts (Chronicler notices + player item actions),
    rendered inline in the story log alongside the messages."""
    return [
        ChatEventResponse(
            id=e.id,
            turnNumber=e.turn_number,
            kind=e.kind,
            text=e.text,
            tethered=bool(e.tethered),
            createdAt=e.created_at.isoformat() if e.created_at else "",
        )
        for e in await event_ops.list_events(session)
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
    await reverse_chronicler_effects(session, msg.turn_number)
    # ...and their in-chat toasts. Untethered player-action toasts are kept.
    await event_ops.delete_tethered(session, msg.turn_number)

    # Remove attached image files of the deleted messages from the adventure folder.
    doomed = (
        await session.execute(select(ChatMessage).where(ChatMessage.id >= msg.id))
    ).scalars().all()
    await _delete_chat_images(session, [m.image_path for m in doomed if getattr(m, "image_path", None)])

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
    # Wipe attached image files along with the messages that referenced them.
    with_images = (
        await session.execute(select(ChatMessage).where(ChatMessage.image_path.is_not(None)))
    ).scalars().all()
    await _delete_chat_images(session, [m.image_path for m in with_images])
    await session.execute(delete(ChatMessage))
    await event_ops.clear_events(session)  # wipe all toasts with the chat
    for b in await party_ops.all_bindings(session):
        b.last_spoke_turn = 0
    await session.commit()


# ── Adventure Export / Import / Reset ─────────────────────────────

@router.get("/adventure/export")
async def export_adventure(session: AsyncSession = Depends(get_session)):
    pc = await party_ops.load_pc(session)
    members = await party_ops.load_party(session)
    narrator = (await session.execute(select(NarratorConfig))).scalars().first()
    messages = (await session.execute(select(ChatMessage).order_by(ChatMessage.id))).scalars().all()
    summary = (await session.execute(select(StorySummary))).scalars().first()
    settings = (await session.execute(select(OpenRouterSettings))).scalars().first()
    inventory = (await session.execute(select(InventoryStack))).scalars().all()
    tasks = (await session.execute(select(Task).order_by(Task.sort_order))).scalars().all()
    lore_entries = (await session.execute(select(LorebookEntry))).scalars().all()
    lore_config = (await session.execute(select(LorebookConfig))).scalars().first()

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
            "actionSuggestionsEnabled": bool(getattr(narrator, "action_suggestions_enabled", False)) if narrator else False,
            "actionSuggestionsInstructions": getattr(narrator, "action_suggestions_instructions", "") if narrator else "",
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
            "maxPartySize": settings.max_party_size if settings else 3,
            "maxToolRounds": settings.max_tool_rounds if settings else 6,
            "useTools": bool(settings.use_tools) if settings else True,
            "worldbuildingMode": settings.worldbuilding_mode if settings else "confirmation",
            "worldbuildingModelId": settings.worldbuilding_model_id if settings else "",
            "actionSuggestionsModelId": getattr(settings, "action_suggestions_model_id", "") if settings else "",
            "summaryThreshold": getattr(settings, "summary_threshold", 0.7) if settings else 0.7,
            "summaryModelId": getattr(settings, "summary_model_id", "") if settings else "",
        },
        "inventory": [{"itemId": s.item_id, "count": s.count} for s in inventory],
        "tasks": [
            {
                "id": t.id,
                "text": t.text,
                "status": t.status,
                "notes": t.notes,
                "sortOrder": t.sort_order,
            }
            for t in tasks
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
    await session.execute(delete(Task))
    await session.execute(delete(InventoryStack))
    await session.execute(delete(ChatMessage))
    await session.execute(delete(PartyBinding))
    await session.execute(delete(NarratorConfig))
    await session.execute(delete(StorySummary))
    await session.execute(delete(WorldbuildingProposal))
    await session.execute(delete(OpenRouterSettings))

    # Restore player character (identity → new persona file, equipment → binding)
    if data.get("playerCharacter"):
        pc_data = data["playerCharacter"]
        pc = await party_ops.set_pc_identity(session, pc_data.get("basicInfo", {}))
        await party_ops.set_equipment(session, pc.id, pc_data.get("equipment", {}))

    # Restore party members
    for pm_data in data.get("partyMembers", []):
        m = await party_ops.add_member(
            session,
            basic_info=pm_data.get("basicInfo", {}),
            field_skill=pm_data.get("fieldSkill", {}),
            in_party=pm_data.get("inParty", True),
        )
        await party_ops.set_equipment(session, m.id, pm_data.get("equipment", {}))

    # Restore narrator
    nar = data.get("narrator", {})
    session.add(NarratorConfig(
        instructions=nar.get("instructions", ""),
        action_instruction=nar.get("actionInstruction", ""),
        spotlight_rule=nar.get("spotlightRule", ""),
        first_message=nar.get("firstMessage", ""),
        post_history_instructions=nar.get("postHistoryInstructions", ""),
        planner_instructions=nar.get("plannerInstructions", ""),
        action_suggestions_enabled=nar.get("actionSuggestionsEnabled", False),
        action_suggestions_instructions=nar.get("actionSuggestionsInstructions", ""),
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
        max_party_size=s.get("maxPartySize", 3),
        max_tool_rounds=s.get("maxToolRounds", 6),
        use_tools=s.get("useTools", True),
        worldbuilding_mode=s.get("worldbuildingMode", "confirmation"),
        worldbuilding_model_id=s.get("worldbuildingModelId", ""),
        action_suggestions_model_id=s.get("actionSuggestionsModelId", ""),
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

    # Restore tasks. New exports carry a flat "tasks" list; older exports carry
    # "quests" (with objectives) — flatten those into tasks on the way in.
    if data.get("tasks") is not None:
        for t_data in data.get("tasks", []):
            session.add(Task(
                id=t_data.get("id"),
                text=t_data.get("text", ""),
                status=t_data.get("status", "active"),
                notes=t_data.get("notes", ""),
                sort_order=t_data.get("sortOrder", 0),
            ))
    else:
        order = 0
        for q_data in data.get("quests", []):
            session.add(Task(
                text=q_data.get("title", ""),
                status=q_data.get("status", "active"),
                notes=q_data.get("desc", ""),
                sort_order=order,
            ))
            order += 1
            for obj_data in q_data.get("objectives", []):
                session.add(Task(
                    text=obj_data.get("text", ""),
                    status="completed" if obj_data.get("done") else "active",
                    sort_order=order,
                ))
                order += 1

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
    await session.execute(delete(Task))
    await session.execute(delete(InventoryStack))
    await session.execute(delete(ChatMessage))
    await session.execute(delete(PartyBinding))
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


async def _save_prompt_log(messages: list[dict]):
    # Serialization + disk write of the full prompt (can be ~MB) — keep it off
    # the event loop so it never stalls the SSE stream.
    payload = json.dumps(messages, ensure_ascii=False)
    await asyncio.to_thread(_PROMPT_LOG_PATH.write_text, payload, encoding="utf-8")


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


# Newest messages loaded per turn. The prompt is token-trimmed far below this
# and older history lives in the StorySummary, so nothing above the window can
# ever reach the model — loading it would be pure waste on long adventures.
_HISTORY_WINDOW = 500


async def _load_game_context(session: AsyncSession):
    """Load all game state needed for a chat turn."""
    settings = (await session.execute(select(OpenRouterSettings))).scalars().first()
    if not settings or not settings.api_key:
        raise HTTPException(400, "OpenRouter API key not configured")
    if not settings.model_id:
        raise HTTPException(400, "No model selected")

    narrator = (await session.execute(select(NarratorConfig))).scalars().first() or NarratorConfig(instructions="")
    pc = await party_ops.load_pc(session)
    if not pc:
        raise HTTPException(400, "No player character created")

    # Only active (in-party) members participate in narration and spotlight.
    party = [m for m in await party_ops.load_party(session) if m.in_party]
    # Narration only ever sees the 'narrator' thread — Planning-mode messages
    # live in their own thread and never enter narration context. Bounded to the
    # newest window (ascending after reversal); the newest turn is always inside
    # it, so max()/variant lookups on recent turns behave exactly as before.
    recent = (await session.execute(
        select(ChatMessage)
        .where(func.coalesce(ChatMessage.mode, "narrator") != "planner")
        .order_by(ChatMessage.id.desc())
        .limit(_HISTORY_WINDOW)
    )).scalars().all()
    all_messages = list(reversed(recent))
    summary = (await session.execute(select(StorySummary))).scalars().first()
    if not summary:
        summary = StorySummary(content="", summary_up_to_turn=0)
        session.add(summary)
    catalog = list((await session.execute(select(LorebookEntry).where(LorebookEntry.cat == "items"))).scalars().all())
    tasks = list((await session.execute(select(Task).order_by(Task.sort_order))).scalars().all())
    lore_entries = list((await session.execute(select(LorebookEntry))).scalars().all())
    lore_config = (await session.execute(select(LorebookConfig))).scalars().first()
    if not lore_config:
        lore_config = LorebookConfig()
        session.add(lore_config)
        await session.commit()

    return settings, narrator, pc, party, all_messages, summary, catalog, tasks, lore_entries, lore_config


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
    tasks: list[Task] | None = None,
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
    benched = [m for m in await party_ops.load_party(session) if not m.in_party]
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
        tasks=tasks,
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
        tasks=tasks,
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

    settings, narrator, pc, party, all_messages, summary, catalog, tasks, lore_entries, lore_config = await _load_game_context(session)

    max_turn = max((m.turn_number for m in all_messages), default=0)
    current_turn = max_turn + 1

    # Player-attached image: save it with the adventure, have the vision agent
    # describe it (the narrator itself may be text-only), and record both on the
    # user message so swipes/regenerates reuse the description.
    image_path: str | None = None
    image_desc: str | None = None
    if data.image:
        image_path = await _store_chat_image(session, data.image)
        image_desc = await describe_image(settings, data.image, data.message)

    user_msg = ChatMessage(
        role="user", content=data.message, turn_number=current_turn, speaker=pc.id,
        image_path=image_path, image_description=image_desc,
    )
    session.add(user_msg)

    # What the narrator sees: the message text plus the image description.
    prompt_message = augment_user_content(data.message, image_desc) if image_path else data.message

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
        player_message=prompt_message,
        current_turn=current_turn,
        session=session,
        agentic=agentic,
        item_catalog=catalog,
        tasks=tasks,
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
            user_message_id=user_msg.id,
            dice_enabled=bool(getattr(narrator, "dice_enabled", True)),
            inline_option_rules=_inline_option_rules(narrator),
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
        user_message_id=user_msg.id,
        inline_option_rules=_inline_option_rules(narrator),
    )


# ── Swipe (new variant for a specific turn) ─────────────────────

@router.post("/chat/messages/{turn}/swipe")
async def swipe(turn: int, session: AsyncSession = Depends(get_session)):
    """Generate a new variant for a specific turn. Appends to existing variants."""
    settings, narrator, pc, party, all_messages, summary, catalog, tasks, lore_entries, lore_config = await _load_game_context(session)

    # Find the user message for this turn — targeted query (not the bounded
    # window) so swiping a turn older than the window still resolves.
    user_msg = (await session.execute(
        select(ChatMessage)
        .where(
            ChatMessage.turn_number == turn,
            ChatMessage.role == "user",
            func.coalesce(ChatMessage.mode, "narrator") != "planner",
        )
        .order_by(ChatMessage.id)
    )).scalars().first()
    if not user_msg:
        raise HTTPException(400, f"No user message found for turn {turn}")

    # Build history up to (but not including) this turn
    history = [m for m in all_messages if m.turn_number < turn]

    # Reverse the effects of the currently-live variant for this turn (the most
    # recent assistant variant carries the combined deltas reflected in state),
    # then re-run detection on the same player message and apply fresh. This
    # keeps inventory idempotent across repeated swipes.
    turn_variants = list((await session.execute(
        select(ChatMessage)
        .where(
            ChatMessage.turn_number == turn,
            ChatMessage.role == "assistant",
            func.coalesce(ChatMessage.mode, "narrator") != "planner",
        )
    )).scalars().all())
    if turn_variants:
        latest_variant = max(turn_variants, key=lambda m: m.variant)
        await _reverse_message_effects(latest_variant, session)
    # The prior variant's Chronicler lore/quests belong to the discarded telling
    # of this turn — drop them; the re-run's Chronicler pass will record fresh.
    await reverse_chronicler_effects(session, turn, exact=True)
    await session.commit()
    agentic = await _should_use_tools(settings)
    # Re-detect against the now-restored inventory (legacy path only); agentic
    # mode re-derives item use through the consume_item tool during the loop.
    player_deltas = [] if agentic else await _detect_player_deltas(user_msg.content, session)

    messages, did_summarize, spotlight_signals, summarize_hint = await _maybe_summarize_and_build(
        settings, narrator, pc, party,
        history=history,
        summary=summary,
        player_message=(
            augment_user_content(user_msg.content, getattr(user_msg, "image_description", None))
            if getattr(user_msg, "image_path", None) else user_msg.content
        ),
        current_turn=turn,
        session=session,
        agentic=agentic,
        item_catalog=catalog,
        tasks=tasks,
        lore_entries=lore_entries,
        lore_config=lore_config,
    )

    # Count existing variants for this turn to determine next variant number
    variant_count = len(turn_variants)

    if agentic:
        return _stream_agent_response(
            messages=messages,
            settings=settings,
            party_list=party,
            current_turn=turn,
            variant=variant_count,
            spotlight_signals=spotlight_signals,
            summarize_hint=summarize_hint,
            dice_enabled=bool(getattr(narrator, "dice_enabled", True)),
            inline_option_rules=_inline_option_rules(narrator),
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
        inline_option_rules=_inline_option_rules(narrator),
    )


# ── Regenerate ────────────────────────────────────────────────────

@router.post("/chat/regenerate")
async def regenerate(
    data: dict = Body(default={}),
    session: AsyncSession = Depends(get_session),
):
    guidance = (data.get("guidance") or "").strip() if isinstance(data, dict) else ""
    settings, narrator, pc, party, all_messages, summary, catalog, tasks, lore_entries, lore_config = await _load_game_context(session)

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
    await reverse_chronicler_effects(session, last_turn, exact=True)

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
        player_message=(
            augment_user_content(last_user_msg.content, getattr(last_user_msg, "image_description", None))
            if getattr(last_user_msg, "image_path", None) else last_user_msg.content
        ),
        current_turn=last_turn,
        session=session,
        agentic=agentic,
        item_catalog=catalog,
        tasks=tasks,
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
            dice_enabled=bool(getattr(narrator, "dice_enabled", True)),
            inline_option_rules=_inline_option_rules(narrator),
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
        inline_option_rules=_inline_option_rules(narrator),
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
    # Strip the internal ``_prev`` reversal snapshot from the client-facing payload.
    payload = {k: v for k, v in (p.payload or {}).items() if k != "_prev"}
    return WorldbuildProposalSchema(
        id=p.id, turnNumber=p.turn_number, kind=p.kind, operation=p.operation,
        targetId=p.target_id, payload=payload, summary=p.summary,
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


# ── Action Suggestions ─────────────────────────────────────────────

@router.post("/action-suggestions/run", response_model=ActionSuggestionsResponse)
async def action_suggestions_run(
    data: ActionSuggestionsRunRequest,
    session: AsyncSession = Depends(get_session),
):
    turn = data.turn
    if turn is None:
        turn = (
            await session.execute(select(func.max(ChatMessage.turn_number)))
        ).scalar() or 0
    if turn <= 0:
        return ActionSuggestionsResponse(suggestions=[])

    narrator = (await session.execute(select(NarratorConfig))).scalars().first()
    if not narrator or not narrator.action_suggestions_enabled:
        return ActionSuggestionsResponse(suggestions=[])

    suggestions = await run_action_suggester(turn)
    return ActionSuggestionsResponse(suggestions=suggestions)


# ── Planner (Planning mode) ───────────────────────────────────────

async def _planner_turn(data: ChatTurnRequest, session: AsyncSession):
    settings = (await session.execute(select(OpenRouterSettings))).scalars().first()
    if not settings or not settings.api_key:
        raise HTTPException(400, "OpenRouter API key not configured")
    if not settings.model_id:
        raise HTTPException(400, "No model selected")
    pc = await party_ops.load_pc(session)

    max_turn = (
        await session.execute(
            select(func.max(ChatMessage.turn_number)).where(ChatMessage.mode == "planner")
        )
    ).scalar() or 0
    turn = max_turn + 1

    # Player-attached image — same treatment as the narrator path. The Editor's
    # history loader folds the description in via _augment_message.
    image_path: str | None = None
    image_desc: str | None = None
    if data.image:
        image_path = await _store_chat_image(session, data.image)
        image_desc = await describe_image(settings, data.image, data.message)

    session.add(ChatMessage(
        role="user", content=data.message, turn_number=turn,
        speaker=pc.id if pc else "player", mode="planner",
        image_path=image_path, image_description=image_desc,
    ))
    await session.commit()
    return _stream_planner_response(settings, turn)


def _stream_planner_response(settings: OpenRouterSettings, turn: int):
    max_context = settings.max_context_tokens

    async def stream():
        yield f"data: {json.dumps({'type': 'meta', 'maxContextTokens': max_context})}\n\n"

        final_content = ""
        pending_deletes: list[dict] = []
        editor_actions: list[dict] = []  # {name, result} per tool the Editor ran
        try:
            async for ev in run_planner_agent(turn):
                t = ev["type"]
                if t == "content":
                    yield f"data: {json.dumps({'type': 'chunk', 'content': ev['text']})}\n\n"
                elif t == "discard":
                    yield f"data: {json.dumps({'type': 'discard'})}\n\n"
                elif t == "tool":
                    editor_actions.append({"name": ev["name"], "result": ev["result"]})
                    yield f"data: {json.dumps({'type': 'tool', 'name': ev['name'], 'result': ev['result']})}\n\n"
                elif t == "final":
                    final_content = ev["content"]
                    pending_deletes = ev["pendingDeletes"]
        except Exception as e:
            log.exception("Planner loop failed")
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"
            return

        log.info("PLANNER RESPONSE turn=%s (%d chars) | actions=%d pendingDeletes=%d",
                 turn, len(final_content), len(editor_actions), len(pending_deletes))

        try:
            async with new_session() as save_session:
                save_session.add(ChatMessage(
                    role="assistant", content=final_content, turn_number=turn,
                    variant=0, speaker="planner", mode="planner",
                    editor_actions=editor_actions or None,
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
        elif d.kind == "task":
            t = await session.get(Task, d.targetId)
            if t:
                await session.delete(t)
                applied += 1
        elif d.kind == "member":
            # Unbind the member from this adventure (identity file stays in the
            # library); targetId is the character id.
            if await party_ops.remove_member(session, d.targetId):
                applied += 1
    await session.commit()
    return {"applied": applied}


# ── Shared streaming helper ───────────────────────────────────────

def _inline_option_rules(narrator) -> list[str] | None:
    """The option rules when suggestions ride the main narration call
    (action_suggestions_mode == 'inline'), else None."""
    if not getattr(narrator, "action_suggestions_enabled", False):
        return None
    if (getattr(narrator, "action_suggestions_mode", "separate") or "separate") != "inline":
        return None
    return normalize_option_rules(getattr(narrator, "action_option_rules", None))


def _stream_llm_response(
    messages: list[dict],
    settings: OpenRouterSettings,
    party_list: list,
    current_turn: int,
    variant: int,
    did_summarize: bool = False,
    spotlight_signals: list[SpotlightSignal] | None = None,
    player_deltas: list[dict] | None = None,
    user_message_id: int | None = None,
    inline_option_rules: list[str] | None = None,
):
    player_deltas = player_deltas or []
    if inline_option_rules:
        # Suggestions ride this call: teach the <<<OPTIONS>>> ending.
        messages = [{"role": "system", "content": build_inline_options_guidance(inline_option_rules)}, *messages]

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

    # Terminal log: model + sampling settings at INFO; the full assembled prompt
    # (potentially hundreds of KB) only when DEBUG logging is on.
    log.info(
        "LLM REQUEST turn=%s variant=%s | model=%s | temp=%s top_p=%s min_p=%s top_k=%s "
        "freq=%s pres=%s rep=%s | max_tokens=%s max_context=%s | ~%s prompt tokens | %d messages",
        current_turn, variant, model_id, temperature, top_p, min_p, top_k,
        frequency_penalty, presence_penalty, repetition_penalty,
        max_tokens, max_context, context_tokens, len(messages),
    )
    if log.isEnabledFor(logging.DEBUG):
        log.debug(
            "LLM PROMPT (%d messages):\n%s",
            len(messages),
            "\n".join(f"  ── [{m['role']}] ──\n{m['content']}" for m in messages),
        )

    async def stream():
        await _save_prompt_log(messages)
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

        # Terminal log: size at INFO, full raw output only at DEBUG.
        log.info("LLM RESPONSE turn=%s variant=%s (%d chars)", current_turn, variant, len(full_text))
        log.debug("LLM RESPONSE text:\n%s", full_text)

        # Parse and strip the action block before saving
        clean_text, actions = parse_action_block(full_text)
        if actions:
            log.info("LLM ACTIONS parsed: %s", json.dumps(actions, ensure_ascii=False))
        inline_suggestions: list[str] = []
        if inline_option_rules:
            clean_text, inline_suggestions = parse_inline_options(clean_text)
            log.info("LLM INLINE OPTIONS parsed: %s", json.dumps(inline_suggestions, ensure_ascii=False))
        inv_deltas: list[dict] = []
        equip_changes: list[dict] = []
        saved_message: dict | None = None

        try:
            async with new_session() as save_session:
                speaker_ids: list[str] = []
                if party_list:
                    speaker_ids = detect_speakers(full_text, party_list)
                    for pm in party_list:
                        if pm.id in speaker_ids:
                            await party_ops.set_last_spoke(save_session, pm.id, current_turn)

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
                await save_session.refresh(assistant_msg)
                saved_message = _msg_response(assistant_msg).model_dump()
        except Exception as e:
            log.exception("Failed to save response to DB")

        response_tokens = len(clean_text) // 4
        combined_inv_deltas = [*player_deltas, *inv_deltas]
        done_payload: dict = {
            'type': 'done',
            'contextTokens': context_tokens + response_tokens,
            'maxContextTokens': max_context,
        }
        # The persisted message rides on `done` so a plain send can append it
        # locally instead of refetching the entire history.
        if saved_message is not None:
            done_payload['message'] = saved_message
        if user_message_id is not None:
            done_payload['userMessageId'] = user_message_id
        if combined_inv_deltas:
            done_payload['appliedInventoryDeltas'] = combined_inv_deltas
        if equip_changes:
            done_payload['appliedEquipmentChanges'] = equip_changes
        if inline_suggestions:
            done_payload['suggestions'] = inline_suggestions
        yield f"data: {json.dumps(done_payload)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


# ── Agentic streaming driver ──────────────────────────────────────

def _stream_agent_response(
    messages: list[dict],
    settings: OpenRouterSettings,
    party_list: list,
    current_turn: int,
    variant: int,
    spotlight_signals: list[SpotlightSignal] | None = None,
    summarize_hint: bool = False,
    user_message_id: int | None = None,
    dice_enabled: bool = True,
    inline_option_rules: list[str] | None = None,
):
    """Drive the agentic narrator loop and stream its final narration.

    Tool calls mutate the DB *during* the loop (inside run_narrator_agent), so
    here we only record the accumulated deltas/scene on the ChatMessage for
    reversal — we do not re-apply them."""
    if inline_option_rules:
        # Suggestions ride this call: teach the <<<OPTIONS>>> ending.
        messages = [{"role": "system", "content": build_inline_options_guidance(inline_option_rules)}, *messages]
    context_tokens = estimate_prompt_tokens(messages)
    max_context = settings.max_context_tokens

    log.info(
        "LLM AGENT REQUEST turn=%s variant=%s | model=%s | temp=%s | max_tokens=%s "
        "max_context=%s max_tool_rounds=%s | ~%s prompt tokens",
        current_turn, variant, settings.model_id, settings.temperature,
        settings.max_tokens_response, max_context, settings.max_tool_rounds, context_tokens,
    )
    if log.isEnabledFor(logging.DEBUG):
        log.debug(
            "LLM AGENT PROMPT (%d messages):\n%s",
            len(messages),
            "\n".join(f"  ── [{m['role']}] ──\n{m.get('content', '')}" for m in messages),
        )

    async def stream():
        await _save_prompt_log(messages)
        yield f"data: {json.dumps({'type': 'meta', 'contextTokens': context_tokens, 'maxContextTokens': max_context})}\n\n"

        final_content = ""
        scene: dict = {}
        inv_deltas: list[dict] = []
        equip_changes: list[dict] = []
        tool_failures: list[str] = []
        saved_message: dict | None = None

        try:
            async for ev in run_narrator_agent(
                settings=settings,
                base_messages=messages,
                current_turn=current_turn,
                summarize_hint=summarize_hint,
                dice_enabled=dice_enabled,
            ):
                etype = ev["type"]
                if etype == "content":
                    yield f"data: {json.dumps({'type': 'chunk', 'content': ev['text']})}\n\n"
                elif etype == "discard":
                    yield f"data: {json.dumps({'type': 'discard'})}\n\n"
                elif etype == "tool":
                    yield f"data: {json.dumps({'type': 'tool', 'name': ev['name'], 'result': ev['result'], 'ok': ev.get('ok', True)})}\n\n"
                elif etype == "final":
                    final_content = ev["content"]
                    scene = ev["scene"]
                    inv_deltas = ev["inv_deltas"]
                    equip_changes = ev["equip_changes"]
                    tool_failures = ev.get("tool_failures", [])
        except Exception as e:
            log.exception("Agent loop failed")
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"
            return

        log.info(
            "LLM AGENT RESPONSE turn=%s variant=%s (%d chars) | scene=%s | inv_deltas=%s | equip_changes=%s",
            current_turn, variant, len(final_content), scene, inv_deltas, equip_changes,
        )

        inline_suggestions: list[str] = []
        if inline_option_rules:
            final_content, inline_suggestions = parse_inline_options(final_content)
            log.info("LLM INLINE OPTIONS parsed: %s", json.dumps(inline_suggestions, ensure_ascii=False))

        try:
            async with new_session() as save_session:
                speaker_ids: list[str] = []
                if party_list:
                    speaker_ids = detect_speakers(final_content, party_list)
                    for pm in party_list:
                        if pm.id in speaker_ids:
                            await party_ops.set_last_spoke(save_session, pm.id, current_turn)

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
                await save_session.refresh(assistant_msg)
                saved_message = _msg_response(assistant_msg).model_dump()
        except Exception:
            log.exception("Failed to save agent response to DB")

        response_tokens = len(final_content) // 4
        done_payload: dict = {
            'type': 'done',
            'contextTokens': context_tokens + response_tokens,
            'maxContextTokens': max_context,
        }
        # The persisted message rides on `done` so a plain send can append it
        # locally instead of refetching the entire history.
        if saved_message is not None:
            done_payload['message'] = saved_message
        if user_message_id is not None:
            done_payload['userMessageId'] = user_message_id
        if inv_deltas:
            done_payload['appliedInventoryDeltas'] = inv_deltas
        if equip_changes:
            done_payload['appliedEquipmentChanges'] = equip_changes
        if tool_failures:
            done_payload['toolFailures'] = tool_failures
        if inline_suggestions:
            done_payload['suggestions'] = inline_suggestions
        yield f"data: {json.dumps(done_payload)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")
