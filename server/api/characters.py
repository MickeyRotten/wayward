"""Player Character, Party Members (adventure bindings), and the Character
Library (portable identity files: portraits, voices, import/export)."""

import io
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from server.api.common import (
    PORTRAITS_DIR,
    _MEDIA_CACHE,
    _active_party_count,
    _max_party_size,
    _pc_to_response,
    _pm_to_response,
)
from server.api.schemas import (
    PartyMemberCreate,
    PartyMemberResponse,
    PartyMembershipUpdate,
    PartyMemberUpdate,
    PlayerCharacterResponse,
    PlayerCharacterUpdate,
)
from server.db import characters as char_files
from server.db import party as party_ops
from server.db.database import get_session

router = APIRouter()


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
