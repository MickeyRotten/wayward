"""In-chat event toasts — small persistent notices rendered inline in the story
log (see ``ChatEvent`` in models.py).

Chronicler notices are *tethered* to their turn (removed when the turn is
deleted / regenerated / swiped); player-action notices (equip, drop, add an
item) are *untethered* and survive turn edits. These helpers keep that policy in
one place so the routes and the Chronicler don't reinvent it.
"""

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.db.models import ChatEvent, ChatMessage


async def current_turn(session: AsyncSession) -> int:
    """The turn in play right now — the highest narrator-thread turn number (0
    if the story hasn't started). Used to anchor an untethered player event."""
    turn = (
        await session.execute(
            select(func.max(ChatMessage.turn_number)).where(ChatMessage.mode == "narrator")
        )
    ).scalar()
    return int(turn or 0)


async def add_event(
    session: AsyncSession, *, turn_number: int, kind: str, text: str, tethered: bool
) -> ChatEvent:
    """Record a toast. Caller commits."""
    ev = ChatEvent(turn_number=turn_number, kind=kind, text=text, tethered=1 if tethered else 0)
    session.add(ev)
    return ev


async def add_player_event(session: AsyncSession, text: str) -> ChatEvent:
    """An untethered player-action toast anchored to the current turn."""
    return await add_event(
        session, turn_number=await current_turn(session),
        kind="item", text=text, tethered=False,
    )


async def delete_tethered(session: AsyncSession, from_turn: int, *, exact: bool = False) -> None:
    """Drop tethered (Chronicler) toasts for a turn — ``exact`` for a single
    turn (swipe/regenerate), otherwise that turn and everything after
    (delete-and-after). Untethered player toasts are left untouched."""
    cond = (
        ChatEvent.turn_number == from_turn if exact
        else ChatEvent.turn_number >= from_turn
    )
    await session.execute(
        delete(ChatEvent).where(ChatEvent.tethered == 1, cond)
    )


async def clear_events(session: AsyncSession) -> None:
    """Remove every toast (used when the whole chat is cleared)."""
    await session.execute(delete(ChatEvent))


async def list_events(session: AsyncSession) -> list[ChatEvent]:
    return list(
        (await session.execute(select(ChatEvent).order_by(ChatEvent.id))).scalars().all()
    )
