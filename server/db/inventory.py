"""Item-instance helpers shared by REST routes and the agent tools.

The party owns ``ItemInstance`` rows (one physical copy each; Equipment is
count==1 and never merged, stackables keep a count). "Equipped" is *derived*:
an instance is equipped iff some character's ``equipment[slot]`` references its
id, otherwise it's stowed in the pack. These helpers centralise that derivation
and the create/find operations so every caller stays consistent.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.db.models import (
    ItemInstance,
    LorebookEntry,
    PartyMember,
    PlayerCharacter,
)


async def equipped_map(session: AsyncSession) -> dict[str, dict]:
    """instance_id -> {characterId, characterName, slot} for every equipped instance."""
    out: dict[str, dict] = {}
    pc = (await session.execute(select(PlayerCharacter))).scalars().first()
    chars: list = [pc] if pc else []
    chars += (await session.execute(select(PartyMember))).scalars().all()
    for ch in chars:
        name = (ch.basic_info or {}).get("name", "") or ""
        for slot, val in (ch.equipment or {}).items():
            if val:
                out[val] = {"characterId": ch.id, "characterName": name, "slot": slot}
    return out


async def find_stowed_instance(session: AsyncSession, item_id: str) -> ItemInstance | None:
    """An unequipped instance of the given catalog item, if any."""
    equipped = set((await equipped_map(session)).keys())
    rows = (await session.execute(
        select(ItemInstance).where(ItemInstance.item_id == item_id)
    )).scalars().all()
    for inst in rows:
        if inst.id not in equipped:
            return inst
    return None


def create_instance(session: AsyncSession, item_id: str, count: int = 1) -> ItemInstance:
    """Create + add (not commit) a new stowed instance."""
    inst = ItemInstance(id=str(uuid.uuid4()), item_id=item_id, count=count)
    session.add(inst)
    return inst


async def is_equipment(session: AsyncSession, item_id: str) -> bool:
    e = await session.get(LorebookEntry, item_id)
    return bool(e and e.cat == "items" and (e.item_type or "") == "Equipment")


async def grant_items(session: AsyncSession, item: LorebookEntry, count: int, source: str) -> tuple[str, list[dict]]:
    """Add ``count`` of a catalog item to the pack.

    Equipment → ``count`` separate instances (records a per-instance delta with
    its id so reversal can delete that exact instance). Stackables → bump/create a
    single stowed instance (delta by item id). Returns (message, inventory_deltas).
    """
    deltas: list[dict] = []
    if (item.item_type or "") == "Equipment":
        for _ in range(count):
            inst = create_instance(session, item.id, 1)
            deltas.append({"itemId": item.id, "delta": 1, "source": source, "instanceId": inst.id})
        return (f"Added {count}× {item.title} to the party inventory.", deltas)

    existing = await find_stowed_instance(session, item.id)
    if existing:
        existing.count += count
    else:
        create_instance(session, item.id, count)
    deltas.append({"itemId": item.id, "delta": count, "source": source})
    return (f"Added {count}× {item.title} to the party inventory.", deltas)


async def remove_items(session: AsyncSession, item: LorebookEntry, count: int, source: str) -> tuple[str, list[dict]]:
    """Remove ``count`` of a catalog item from the pack (stowed copies only)."""
    deltas: list[dict] = []
    if (item.item_type or "") == "Equipment":
        removed = 0
        for _ in range(count):
            inst = await find_stowed_instance(session, item.id)
            if not inst:
                break
            deltas.append({"itemId": item.id, "delta": -1, "source": source, "instanceId": inst.id})
            await session.delete(inst)
            removed += 1
        if removed == 0:
            return (f"'{item.title}' is not stowed in the inventory; nothing removed.", [])
        return (f"Removed {removed}× {item.title} from the party inventory.", deltas)

    existing = await find_stowed_instance(session, item.id)
    if not existing:
        return (f"'{item.title}' is not in the inventory; nothing removed.", [])
    removed = min(existing.count, count)
    existing.count -= removed
    if existing.count <= 0:
        await session.delete(existing)
    deltas.append({"itemId": item.id, "delta": -removed, "source": source})
    return (f"Removed {removed}× {item.title} from the party inventory.", deltas)


async def equip_instance(
    session: AsyncSession, character, char_id: str, slot: str, item: LorebookEntry,
    instance_id: str | None = None,
) -> tuple[str, list[dict], list[dict]]:
    """Equip an item onto a character slot. If ``instance_id`` is given, equip
    that exact stowed copy; otherwise reuse any stowed instance or mint a new
    one. Returns (message, equip_changes, inventory_deltas)."""
    instance = None
    if instance_id:
        cand = await session.get(ItemInstance, instance_id)
        if cand and cand.item_id == item.id:
            instance = cand
    if instance is None:
        instance = await find_stowed_instance(session, item.id)
    inv_deltas: list[dict] = []
    if instance is None:
        instance = create_instance(session, item.id, 1)
        # Minting counts as an inventory addition for reversal purposes.
        inv_deltas.append({"itemId": item.id, "delta": 1, "source": "narrator_grant", "instanceId": instance.id})

    equipment = dict(character.equipment) if character.equipment else {}
    previous = equipment.get(slot)
    equipment[slot] = instance.id
    character.equipment = equipment
    changes = [{
        "characterId": char_id, "slot": slot,
        "previousItemId": previous, "newItemId": instance.id,
    }]
    return (f"equipped {item.title} in {slot}.", changes, inv_deltas)
