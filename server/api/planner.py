"""The Editor (Edit Mode / "planner") turn — its own chat thread — and the
queued-delete apply endpoint. The /chat/turn route dispatches here when
mode == "planner"."""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.ai.openrouter import provider_endpoint
from server.ai.planner import run_planner_agent
from server.ai.vision import describe_image
from server.api.common import _store_chat_image
from server.api.schemas import ChatTurnRequest, PlannerDeletesApply
from server.db import party as party_ops
from server.db.database import get_session, new_session
from server.db.models import ChatMessage, LorebookEntry, Objective, OpenRouterSettings, Task

router = APIRouter()

log = logging.getLogger("wayward.chat")


async def _planner_turn(data: ChatTurnRequest, session: AsyncSession):
    settings = (await session.execute(select(OpenRouterSettings))).scalars().first()
    if not settings:
        raise HTTPException(400, "LLM provider not configured")
    _base_url, api_key, main_model = provider_endpoint(settings)
    if not api_key:
        raise HTTPException(400, "API key not configured for the selected provider")
    if not main_model:
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
                elif t == "retry":
                    yield f"data: {json.dumps({'type': 'retry', 'attempt': ev['attempt'], 'of': ev['of']})}\n\n"
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
        elif d.kind == "objective":
            o = await session.get(Objective, d.targetId)
            if o:
                await session.delete(o)
                applied += 1
        elif d.kind == "member":
            # Unbind the member from this adventure (identity file stays in the
            # library); targetId is the character id.
            if await party_ops.remove_member(session, d.targetId):
                applied += 1
    await session.commit()
    return {"applied": applied}
