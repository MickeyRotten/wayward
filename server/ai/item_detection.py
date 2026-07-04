"""Deterministic item-use detection and inventory-delta application.

When the player's message describes using/consuming an item that's currently in
the party inventory, we deterministically decrement that stack *before* the
narrator generates — so the narration is grounded in the post-use state and the
UI can surface an inventory notice.

This is intentionally simple, local, and LLM-free — keyword/phrase based, not
semantic. It powers the **legacy** (non-agentic) turn path; when the agentic
tool loop is active the narrator's `consume_item` tool handles item use instead
(see server/ai/narrator_agent.py). The apply/reverse helpers below are shared by
both paths.

This module also owns the apply / reverse helpers for inventory deltas (shared
by the chat-turn route and the swipe/regenerate/delete reversal paths) so the
mutation logic lives in one place.

See CLAUDE.md and Task 6.2 of the alpha overhaul plan.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from server.db import inventory as inv_ops
from server.db.models import ItemInstance

log = logging.getLogger("wayward.item_detection")

# Phrases that indicate the player is expending an item this turn.
USE_VERBS = [
    "use", "drink", "eat", "consume", "apply",
    "throw", "pull out", "take out", "swallow", "down",
]


def detect_item_use(message: str, inventory: list[dict]) -> list[dict]:
    """Scan a player message for item-use phrasing against the current inventory.

    Args:
        message: the player's raw message text.
        inventory: list of inventory stacks. Each stack is expected to look like
            ``{"itemId": str, "count": int, "item": {"name": str, ...}}`` (the
            shape returned by the /inventory route and _list_inventory_dicts).

    Returns:
        A list of ``{"itemId", "delta", "source"}`` dicts, one per detected
        item use (delta -1, source "player_action"). At most one delta per
        stack per turn.
    """
    deltas: list[dict] = []
    if not message:
        return deltas

    msg_lower = message.lower()

    # Only consider an item "used" if a use-verb actually appears in the message.
    if not any(verb in msg_lower for verb in USE_VERBS):
        return deltas

    seen_item_ids: set[str] = set()
    for stack in inventory:
        if not stack:
            continue
        item = stack.get("item")
        if not item:
            continue
        item_name = (item.get("name") or "").strip().lower()
        item_id = stack.get("itemId")
        if not item_name or not item_id:
            continue
        if item_id in seen_item_ids:
            continue
        if item_name not in msg_lower:
            continue

        # Item name present AND a use-verb present somewhere in the message.
        deltas.append({
            "itemId": item_id,
            "delta": -1,
            "source": "player_action",
        })
        seen_item_ids.add(item_id)

    return deltas


async def apply_inventory_deltas(
    deltas: list[dict],
    session: AsyncSession,
) -> None:
    """Apply a list of inventory deltas to the DB, operating on ``ItemInstance``
    rows (the source of truth for owned copies).

    A delta may carry an ``instanceId`` (equipment / minted copies) — then that
    exact instance is created or deleted, so reversal restores the precise copy
    an equip/grant used. Without one (stackables) a stowed instance is bumped or
    decremented, created/deleted at the boundaries. Positive delta adds, negative
    removes.

    Capacity is intentionally not enforced here — these deltas reflect events
    that already happened in the fiction (player used an item, narrator granted
    one); blocking them would desync the UI from the narration.
    """
    for d in deltas:
        item_id = d.get("itemId")
        delta = d.get("delta", 0)
        instance_id = d.get("instanceId")
        if not item_id or not delta:
            continue

        # Instance-targeted delta: create / delete that exact copy.
        if instance_id:
            existing = await session.get(ItemInstance, instance_id)
            if delta > 0:
                if existing is None:
                    session.add(ItemInstance(id=instance_id, item_id=item_id, count=1))
            else:
                if existing is not None:
                    await session.delete(existing)
                else:
                    log.info("apply_inventory_deltas: instance '%s' already gone, skipping", instance_id)
            continue

        # Stackable delta: bump / decrement a stowed instance.
        stowed = await inv_ops.find_stowed_instance(session, item_id)
        if delta > 0:
            if stowed is not None:
                stowed.count += delta
            else:
                inv_ops.create_instance(session, item_id, delta)
        else:  # delta < 0
            if stowed is None:
                log.info("apply_inventory_deltas: nothing stowed for '%s' to decrement, skipping", item_id)
                continue
            stowed.count += delta  # delta is negative
            if stowed.count <= 0:
                await session.delete(stowed)


async def reverse_inventory_deltas(
    deltas: list[dict],
    session: AsyncSession,
) -> None:
    """Reverse a list of previously-applied inventory deltas.

    Negates each delta and applies it (add back what was removed, remove what
    was added). Used when a narrator message that carried deltas is swiped,
    regenerated, or deleted.
    """
    inverted = [
        {
            "itemId": d.get("itemId"),
            "delta": -d.get("delta", 0),
            "source": d.get("source", "reversal"),
            "instanceId": d.get("instanceId"),
        }
        for d in deltas
    ]
    await apply_inventory_deltas(inverted, session)
