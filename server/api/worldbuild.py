"""World-building (the Chronicler's proposals) and the post-turn action
suggestions."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.ai.action_suggester import run_action_suggester
from server.ai.worldbuilder import apply_proposal, run_worldbuilder
from server.api.schemas import (
    ActionSuggestionsResponse,
    ActionSuggestionsRunRequest,
    WorldbuildProposalSchema,
    WorldbuildRunRequest,
)
from server.db.database import get_session
from server.db.models import ChatMessage, NarratorConfig, WorldbuildingProposal

router = APIRouter()


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
