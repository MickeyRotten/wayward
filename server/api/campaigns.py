"""Campaigns (worlds), Adventures (save files), automatic backups, and the
adventure-level export/import/reset + story export."""

import datetime
import io
import json
import re
import shutil
import uuid
import zipfile
from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.api.common import PORTRAITS_DIR, _active_ids, _pc_to_response, _pm_to_response
from server.db import characters as char_files
from server.db import party as party_ops
from server.db import storage
from server.db.database import get_session, new_session, switch_active
from server.db.models import (
    AppState,
    ChatMessage,
    InventoryStack,
    LorebookConfig,
    LorebookEntry,
    NarratorConfig,
    OpenRouterSettings,
    PartyBinding,
    StorySummary,
    Task,
    WorldbuildingProposal,
)

router = APIRouter()


# ── Adventures (save files in the active campaign) ────────────────

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
    # Safety net: snapshot the target campaign before its scope migrations run
    # (throttled + rotated; never raises).
    storage.snapshot_campaign(cid)
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
    wanted = {a for a in adventures.split(",") if a} if adventures is not None else None
    buf = storage.build_campaign_zip(cid, wanted)
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
    return await _import_campaign_bytes(raw)


async def _import_campaign_bytes(raw: bytes) -> dict:
    """The campaign-zip import core, shared by the upload endpoint and backup
    restore. Always creates a NEW campaign — never overwrites live data."""
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


# ── Automatic backups (see storage.snapshot_campaign) ─────────────

@router.get("/backups")
async def list_backups():
    """Rotating automatic campaign snapshots, newest first."""
    d = storage.backups_dir()
    if not d.is_dir():
        return []
    return [
        {
            "file": p.name,
            "size": p.stat().st_size,
            "createdAt": datetime.datetime.fromtimestamp(
                p.stat().st_mtime, datetime.timezone.utc
            ).isoformat(),
        }
        for p in sorted(d.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    ]


@router.post("/backups/{filename}/restore")
async def restore_backup(filename: str):
    """Restore a snapshot AS A NEW campaign (name-deduped, via the shared
    import path) — live data is never overwritten."""
    if Path(filename).name != filename or not filename.endswith(".zip"):
        raise HTTPException(400, "Bad filename")
    path = storage.backups_dir() / filename
    if not path.is_file():
        raise HTTPException(404, "No such backup")
    return await _import_campaign_bytes(path.read_bytes())


# ── Adventure Export / Import / Reset ─────────────────────────────

@router.get("/adventure/story-export")
async def export_story(session: AsyncSession = Depends(get_session)):
    """Export the active adventure's narrator thread as a readable Markdown
    story: active variants only (highest variant per turn — the client's
    default view), the player's actions italicised under the PC's name,
    day/location headers where the declared scene state changes, and no
    planner/tool noise. The narration is already markdown-ish (bold/italics,
    "> " inscriptions, "* * *" dividers), so prose passes through untouched."""
    narrator = (await session.execute(select(NarratorConfig))).scalars().first()
    pc = await party_ops.load_pc(session)
    msgs = (await session.execute(
        select(ChatMessage)
        .where(func.coalesce(ChatMessage.mode, "narrator") != "planner")
        .order_by(ChatMessage.id)
    )).scalars().all()

    latest_variant: dict[int, int] = {}
    for m in msgs:
        if m.role == "assistant" and m.variant > latest_variant.get(m.turn_number, -1):
            latest_variant[m.turn_number] = m.variant

    st = (await session.execute(select(AppState))).scalars().first()
    camp = storage.read_campaign_meta(st.active_campaign_id) if st and st.active_campaign_id else None
    adv = (storage.read_adventure_meta(st.active_campaign_id, st.active_adventure_id)
           if st and st.active_campaign_id and st.active_adventure_id else None)

    pc_name = ((pc.basic_info.get("name") if pc else "") or "You").strip() or "You"
    lines: list[str] = []
    title = " — ".join(b for b in [(camp or {}).get("name"), (adv or {}).get("name")] if b)
    lines += [f"# {title or 'A Wayward Adventure'}", ""]

    # Use the greeting anchored to this adventure (R13) if present, else primary.
    _summary = (await session.execute(select(StorySummary))).scalars().first()
    anchored = (getattr(_summary, "opening_message", None) if _summary else None)
    first_message = (anchored if anchored is not None else (getattr(narrator, "first_message", "") or "")).strip()
    if first_message:
        lines += [first_message, ""]

    day: int | None = None
    location: str | None = None
    for m in msgs:
        content = (m.content or "").strip()
        if not content:
            continue
        if m.role == "assistant":
            if m.variant != latest_variant.get(m.turn_number, 0):
                continue
            new_day = m.day or day
            new_loc = m.location or location
            if (m.day or m.location) and (new_day, new_loc) != (day, location):
                day, location = new_day, new_loc
                header = " — ".join(x for x in [f"Day {day}" if day else None, location] if x)
                lines += [f"## {header}", ""]
            lines += [content, ""]
        elif m.role == "user":
            lines += [f"**{pc_name}:** *{content}*", ""]

    md = "\n".join(lines).rstrip() + "\n"
    safe = re.sub(r"[^\w\-]+", "_", ((adv or {}).get("name") or "story")).strip("_") or "story"
    return StreamingResponse(
        io.BytesIO(md.encode("utf-8")),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{safe}.md"'},
    )


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
            "firstMessageAlternates": (getattr(narrator, "first_message_alternates", None) or []) if narrator else [],
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
            "provider": (getattr(settings, "llm_provider", "") or "openrouter") if settings else "openrouter",
            "modelId": settings.model_id if settings else "",
            "nimModelId": (getattr(settings, "nim_model_id", "") or "") if settings else "",
            "customBaseUrl": (getattr(settings, "custom_base_url", "") or "") if settings else "",
            "customModelId": (getattr(settings, "custom_model_id", "") or "") if settings else "",
            "temperature": settings.temperature if settings else 0.7,
            "maxTokensResponse": settings.max_tokens_response if settings else 1000,
            "maxContextTokens": settings.max_context_tokens if settings else 128000,
            "maxPartySize": settings.max_party_size if settings else 3,
            "maxToolRounds": settings.max_tool_rounds if settings else 6,
            "autoRetryCount": int(getattr(settings, "auto_retry_count", 2) or 0) if settings else 2,
            "reasoningEffort": (getattr(settings, "reasoning_effort", "") or "") if settings else "",
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
            "injectionOrder": lore_config.injection_order if lore_config else {"pillars": 0, "world": 10, "characters": 20, "items": 30, "monsters": 40, "spells": 50},
            "injectionPosition": lore_config.injection_position if lore_config else {"pillars": "top", "world": "top", "characters": "top", "items": "top", "monsters": "top", "spells": "top"},
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
        first_message_alternates=nar.get("firstMessageAlternates") or None,
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

    # Restore settings (keys are never exported — preserve the existing ones)
    existing_settings = (await session.execute(select(OpenRouterSettings))).scalars().first()
    old_api_key = existing_settings.api_key if existing_settings else ""
    old_nim_key = getattr(existing_settings, "nim_api_key", "") if existing_settings else ""
    old_custom_key = getattr(existing_settings, "custom_api_key", "") if existing_settings else ""
    s = data.get("settings", {})
    session.add(OpenRouterSettings(
        llm_provider=s.get("provider", "openrouter"),
        api_key=old_api_key,
        model_id=s.get("modelId", ""),
        nim_api_key=old_nim_key,
        nim_model_id=s.get("nimModelId", ""),
        custom_base_url=s.get("customBaseUrl", ""),
        custom_api_key=old_custom_key,
        custom_model_id=s.get("customModelId", ""),
        temperature=s.get("temperature", 0.7),
        max_tokens_response=s.get("maxTokensResponse", 1000),
        max_context_tokens=s.get("maxContextTokens", 128000),
        max_party_size=s.get("maxPartySize", 3),
        max_tool_rounds=s.get("maxToolRounds", 6),
        auto_retry_count=s.get("autoRetryCount", 2),
        reasoning_effort=s.get("reasoningEffort", ""),
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
        injection_order=lc_data.get("injectionOrder", {"pillars": 0, "world": 10, "characters": 20, "items": 30, "monsters": 40, "spells": 50}),
        injection_position=lc_data.get("injectionPosition", {"pillars": "top", "world": "top", "characters": "top", "items": "top", "monsters": "top", "spells": "top"}),
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
