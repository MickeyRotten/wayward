"""Wishlist — player wants the Narrator keeps in mind.

A player-authored list of things they'd like to see happen in the story
("I want to recruit an Elf to my party"), each with an optional priority. These
are injected into the narrator prompt as a soft steer — never mutated by the
agents, unlike Tasks/Objectives which the Chronicler and Editor can touch.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.api.schemas import WishCreate, WishSchema, WishUpdate
from server.db.database import get_session
from server.db.models import Wish

router = APIRouter()


def _clamp_priority(p: int) -> int:
    return max(0, min(int(p or 0), 3))


def _to_schema(w: Wish) -> WishSchema:
    return WishSchema(id=w.id, text=w.text, priority=w.priority)


@router.get("/wishes", response_model=list[WishSchema])
async def list_wishes(session: AsyncSession = Depends(get_session)):
    # High-priority wishes first, then by insertion order.
    wishes = (await session.execute(
        select(Wish).order_by(Wish.priority.desc(), Wish.sort_order)
    )).scalars().all()
    return [_to_schema(w) for w in wishes]


@router.post("/wishes", response_model=WishSchema, status_code=201)
async def create_wish(
    data: WishCreate,
    session: AsyncSession = Depends(get_session),
):
    max_order = (await session.execute(
        select(func.coalesce(func.max(Wish.sort_order), -1))
    )).scalar()
    wish = Wish(
        text=data.text,
        priority=_clamp_priority(data.priority),
        sort_order=(max_order or 0) + 1,
    )
    session.add(wish)
    await session.commit()
    await session.refresh(wish)
    return _to_schema(wish)


@router.put("/wishes/{wish_id}", response_model=WishSchema)
async def update_wish(
    wish_id: str,
    data: WishUpdate,
    session: AsyncSession = Depends(get_session),
):
    wish = await session.get(Wish, wish_id)
    if not wish:
        raise HTTPException(404, "Wish not found")
    if data.text is not None:
        wish.text = data.text
    if data.priority is not None:
        wish.priority = _clamp_priority(data.priority)
    await session.commit()
    await session.refresh(wish)
    return _to_schema(wish)


@router.delete("/wishes/{wish_id}", status_code=204)
async def delete_wish(
    wish_id: str,
    session: AsyncSession = Depends(get_session),
):
    wish = await session.get(Wish, wish_id)
    if not wish:
        raise HTTPException(404, "Wish not found")
    await session.delete(wish)
    await session.commit()
