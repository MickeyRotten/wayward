"""The item catalog (items are lorebook entries, cat == "items"), the party
inventory (owned ItemInstance copies), and equip/unequip."""

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.api.common import _get_item, _item_to_dict, _list_inventory_dicts
from server.api.schemas import (
    InventoryAddRequest,
    InventoryRemoveRequest,
    ItemCatalogCreate,
    ItemCatalogUpdate,
)
from server.db import events as event_ops
from server.db import inventory as inv_ops
from server.db import party as party_ops
from server.db.database import get_session
from server.db.models import ItemInstance, LorebookEntry

router = APIRouter()


# ── Items (unified into the lorebook — cat == "items") ─────────────

@router.get("/items")
async def list_items(
    type: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    query = select(LorebookEntry).where(LorebookEntry.cat == "items")
    if type:
        query = query.where(LorebookEntry.item_type == type)
    items = (await session.execute(query)).scalars().all()
    return [_item_to_dict(i) for i in items]


@router.get("/items/search")
async def search_items(
    q: str,
    session: AsyncSession = Depends(get_session),
):
    if len(q) < 3:
        return []
    items = (await session.execute(
        select(LorebookEntry).where(
            LorebookEntry.cat == "items",
            LorebookEntry.title.ilike(f"%{q}%"),
        )
    )).scalars().all()
    return [_item_to_dict(i) for i in items]


@router.get("/items/{item_id}")
async def get_item(
    item_id: str,
    session: AsyncSession = Depends(get_session),
):
    item = await _get_item(session, item_id)
    if not item:
        raise HTTPException(404, "Item not found")
    return _item_to_dict(item)


@router.post("/items", status_code=201)
async def create_item(
    data: ItemCatalogCreate,
    session: AsyncSession = Depends(get_session),
):
    item = LorebookEntry(
        cat="items",
        title=data.name,
        content=data.desc,
        keywords=data.keywords or [],
        enabled=data.enabled,
        permanent=data.permanent,
        item_type=data.type,
        slot=data.slot,
        max_stack=data.maxStack,
        uses=data.uses,
        rarity=data.rarity,
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return _item_to_dict(item)


@router.put("/items/{item_id}")
async def update_item(
    item_id: str,
    data: ItemCatalogUpdate,
    session: AsyncSession = Depends(get_session),
):
    item = await _get_item(session, item_id)
    if not item:
        raise HTTPException(404, "Item not found")
    if data.name is not None:
        item.title = data.name
    if data.type is not None:
        item.item_type = data.type
    if data.slot is not None:
        item.slot = data.slot
    if data.maxStack is not None:
        item.max_stack = data.maxStack
    if data.uses is not None:
        item.uses = data.uses
    if data.rarity is not None:
        item.rarity = data.rarity
    if data.desc is not None:
        item.content = data.desc
    if data.keywords is not None:
        item.keywords = data.keywords
    if data.enabled is not None:
        item.enabled = data.enabled
    if data.permanent is not None:
        item.permanent = data.permanent
    await session.commit()
    await session.refresh(item)
    return _item_to_dict(item)


@router.delete("/items/{item_id}", status_code=204)
async def delete_item(
    item_id: str,
    session: AsyncSession = Depends(get_session),
):
    item = await _get_item(session, item_id)
    if not item:
        raise HTTPException(404, "Item not found")
    if item.locked:
        raise HTTPException(403, "This item is locked and cannot be deleted")
    await session.delete(item)
    await session.commit()


# ── Inventory ─────────────────────────────────────────────────────

# The 12 valid equipment slot keys (used to validate /characters/equip|unequip).
EQUIP_SLOT_KEYS = {
    "head", "neck", "torsoOver", "torsoUnder", "leftHand", "rightHand",
    "waist", "legsOver", "legsUnder", "feet", "accessory1", "accessory2",
}


@router.get("/inventory")
async def list_inventory(session: AsyncSession = Depends(get_session)):
    return await _list_inventory_dicts(session)


@router.post("/inventory/add")
async def add_to_inventory(
    data: InventoryAddRequest,
    session: AsyncSession = Depends(get_session),
):
    item = await _get_item(session, data.itemId)
    if not item:
        raise HTTPException(404, "Item not in catalog")

    message, deltas = await inv_ops.grant_items(session, item, data.count, "manual_add")
    if not deltas:
        raise HTTPException(400, message)
    qty = f" ×{data.count}" if data.count and data.count > 1 else ""
    await event_ops.add_player_event(session, f"Added {item.title}{qty} to the pack")
    await session.commit()
    return {"ok": True}


@router.post("/inventory/remove")
async def remove_from_inventory(
    data: InventoryRemoveRequest,
    session: AsyncSession = Depends(get_session),
):
    item = await _get_item(session, data.itemId)
    if not item:
        raise HTTPException(404, "Item not in inventory")
    message, deltas = await inv_ops.remove_items(session, item, data.count, "manual_remove")
    if not deltas:
        raise HTTPException(404, message)
    qty = f" ×{data.count}" if data.count and data.count > 1 else ""
    await event_ops.add_player_event(session, f"Dropped {item.title}{qty}")
    await session.commit()
    return {"ok": True}


@router.post("/inventory/remove-instance")
async def remove_inventory_instance(
    data: dict = Body(default={}),
    session: AsyncSession = Depends(get_session),
):
    """Delete a specific stowed instance by its instance id (equipment-aware UI)."""
    instance_id = data.get("instanceId")
    inst = await session.get(ItemInstance, instance_id) if instance_id else None
    if not inst:
        raise HTTPException(404, "Instance not found")
    equipped = await inv_ops.equipped_map(session)
    if inst.id in equipped:
        raise HTTPException(400, "Item is equipped — unequip it first")
    item = await _get_item(session, inst.item_id)
    await session.delete(inst)
    await event_ops.add_player_event(session, f"Dropped {item.title if item else 'an item'}")
    await session.commit()
    return {"ok": True}


async def _resolve_character_by_id(session: AsyncSession, char_id: str):
    return await party_ops.load_character(session, char_id)


@router.post("/characters/equip")
async def equip_item(data: dict = Body(default={}), session: AsyncSession = Depends(get_session)):
    """Equip a catalog item onto a character slot (reusing a stowed instance or
    minting one). Any instance previously in that slot becomes stowed."""
    char = await _resolve_character_by_id(session, data.get("characterId"))
    if char is None:
        raise HTTPException(404, "Character not found")
    item = await _get_item(session, data.get("itemId"))
    if not item:
        raise HTTPException(404, "Item not in catalog")
    slot = data.get("slot")
    if slot not in EQUIP_SLOT_KEYS:
        raise HTTPException(400, "Invalid equipment slot")
    await inv_ops.equip_instance(session, char, char.id, slot, item, instance_id=data.get("instanceId"))
    who = (char.basic_info or {}).get("name", "Someone").split(" ")[0]
    await event_ops.add_player_event(session, f"{who} equipped {item.title}")
    await session.commit()
    return {"ok": True}


@router.post("/characters/unequip")
async def unequip_item(data: dict = Body(default={}), session: AsyncSession = Depends(get_session)):
    """Clear a character's equipment slot — the instance becomes stowed."""
    char = await _resolve_character_by_id(session, data.get("characterId"))
    if char is None:
        raise HTTPException(404, "Character not found")
    slot = data.get("slot")
    if slot not in EQUIP_SLOT_KEYS:
        raise HTTPException(400, "Invalid equipment slot")
    equipment = dict(char.equipment or {})
    if equipment.get(slot):
        inst = await session.get(ItemInstance, equipment[slot])
        item = await _get_item(session, inst.item_id) if inst else None
        equipment[slot] = None
        await party_ops.set_equipment(session, char.id, equipment)
        who = (char.basic_info or {}).get("name", "Someone").split(" ")[0]
        await event_ops.add_player_event(session, f"{who} unequipped {item.title if item else 'an item'}")
        await session.commit()
    return {"ok": True}
