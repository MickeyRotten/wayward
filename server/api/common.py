"""Shared helpers used across the domain routers (split from the old
monolithic routes.py). Response builders, active-scope lookup, item/inventory
dict shapes, and chat-image storage — no routes live here."""

import base64
import re
import uuid
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.api.schemas import PartyMemberResponse, PlayerCharacterResponse
from server.db import characters as char_files
from server.db import inventory as inv_ops
from server.db import party as party_ops
from server.db import storage
from server.db.models import (
    AppState,
    ChatMessage,
    ItemInstance,
    LorebookEntry,
    OpenRouterSettings,
)

PORTRAITS_DIR = Path(__file__).resolve().parent.parent / "portraits"
BACKDROPS_DIR = Path(__file__).resolve().parent.parent / "backdrops"

# Portrait/chat-image URLs are stable while the underlying file can be
# replaced, so no `immutable` here — a short max-age plus the automatic
# ETag/Last-Modified revalidation keeps re-renders off the network without
# pinning stale art.
_MEDIA_CACHE = {"Cache-Control": "private, max-age=300"}


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


async def _active_ids(session: AsyncSession) -> tuple[str | None, str | None]:
    st = (await session.execute(select(AppState))).scalars().first()
    return (st.active_campaign_id, st.active_adventure_id) if st else (None, None)


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
