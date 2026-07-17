"""Narrator Config, the Journal ("The Story So Far"), and the narrator's
per-campaign TTS voice sample."""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.ai.action_suggester import ACTION_SUGGESTIONS_GUIDANCE, normalize_option_rules
from server.ai.narrator_actions import ACTION_INSTRUCTION
from server.ai.planner import PLANNER_GUIDANCE
from server.ai.scenario import normalize_openings
from server.ai.spotlight import DEFAULT_SPOTLIGHT_RULE
from server.api.common import _active_ids
from server.api.schemas import NarratorResponse, NarratorUpdate
from server.db import storage
from server.db.database import get_session
from server.db.models import NarratorConfig, StorySummary

router = APIRouter()


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
        firstMessageAlternates=normalize_openings(getattr(n, "first_message_alternates", None)),
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
    if data.firstMessageAlternates is not None:
        n.first_message_alternates = normalize_openings(
            [{"message": o.message, "options": o.options} for o in data.firstMessageAlternates]
        ) or None
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
