"""TTS routes (text-to-speech; optional Chatterbox install)."""

import re

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.ai import tts
from server.api.common import _active_ids
from server.api.schemas import TtsSpeakRequest, TtsSpeakResponse, TtsStatusResponse
from server.db import characters as char_files
from server.db import storage
from server.db.database import get_session
from server.db.models import OpenRouterSettings

router = APIRouter()


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
