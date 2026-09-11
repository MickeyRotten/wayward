"""The Item Steward — a second, tool-capable pass that reads the FINISHED
narration and performs item-possession mutations (take/equip/drop) via
validated tool calls, so a narrator model that can't (or won't) call tools
reliably still gets a working inventory. See CLAUDE.md > The Chronicler > The
Steward.

Each test creates its own throwaway adventure (in the shared, boot-seeded
Fantasy campaign, so the template catalog — Sword, Health Potion, Longbow,
Rations, ... — already exists) instead of touching the ``boot_adventure_id``
adventure other test modules depend on.
"""

import json

import pytest
from sqlalchemy import select

from server.ai import worldbuilder as wb
from server.db import inventory as inv_ops
from server.db import party as party_ops
from server.db.database import new_session
from server.db.models import (
    ChatEvent,
    ChatMessage,
    ItemInstance,
    LorebookEntry,
    OpenRouterSettings,
    WorldbuildingProposal,
)
from server.tests.conftest import run


def _new_adventure(client, name: str) -> str:
    res = client.post("/api/adventures", json={"name": name})
    assert res.status_code == 200, res.text
    return res.json()["id"]


def _seed_pc(name: str) -> None:
    async def go():
        async with new_session() as s:
            await party_ops.set_pc_identity(s, {"name": name})
            await s.commit()
    run(go())


def _configure_settings() -> None:
    async def go():
        async with new_session() as s:
            st = (await s.execute(select(OpenRouterSettings))).scalars().first()
            if not st:
                st = OpenRouterSettings()
                s.add(st)
            st.api_key, st.model_id = "sk-test", "test/model"
            st.worldbuilding_mode = "confirmation"
            await s.commit()
    run(go())


def _catalog_entry(title: str) -> LorebookEntry | None:
    async def go():
        async with new_session() as s:
            return (
                await s.execute(select(LorebookEntry).where(LorebookEntry.title == title))
            ).scalars().first()
    return run(go())


def _stowed_count(item_id: str) -> int:
    async def go():
        async with new_session() as s:
            insts = (
                await s.execute(select(ItemInstance).where(ItemInstance.item_id == item_id))
            ).scalars().all()
            return sum(i.count or 1 for i in insts)
    return run(go())


def _grant(title: str, count: int = 1) -> None:
    async def go():
        async with new_session() as s:
            item = (
                await s.execute(select(LorebookEntry).where(LorebookEntry.title == title))
            ).scalars().first()
            await inv_ops.grant_items(s, item, count, "test_seed")
            await s.commit()
    run(go())


@pytest.fixture()
def adventure(client):
    """A fresh adventure with a named PC, in the shared Fantasy campaign (so
    Sword/Health Potion/Longbow/Rations from the template catalog already
    exist and can be reused for take/equip/drop tests)."""
    aid = _new_adventure(client, "Steward Test")
    _seed_pc("Hero")
    return aid


# ── _worth_stewarding ────────────────────────────────────────────


@pytest.mark.parametrize("text,expected", [
    ("She picks up the lantern.", True),
    ("He grabs the torch from the wall.", True),
    ("The merchant hands her a small vial.", True),
    ("Tifa equips the gauntlets.", True),
    ("He drops the empty flask.", True),
    ("She sells the old boots to the tinker.", True),
    ("She nods and walks to the door.", False),
    ("The room is quiet and cold.", False),
])
def test_worth_stewarding(text, expected):
    assert wb._worth_stewarding(text) is expected


# ── apply_proposal: take ─────────────────────────────────────────


def test_take_brand_new_item_creates_catalog_entry_and_grants(client, adventure):
    async def go():
        async with new_session() as s:
            prop = WorldbuildingProposal(
                turn_number=1, kind="item", operation="take",
                payload={
                    "itemName": "Rusty Key", "description": "A small, rust-flecked iron key.",
                    "itemType": "Key Item",
                },
            )
            ok, note = await wb.apply_proposal(prop, s)
            await s.commit()
            entry = (
                await s.execute(select(LorebookEntry).where(LorebookEntry.title == "Rusty Key"))
            ).scalars().first()
            instances = (
                (await s.execute(select(ItemInstance).where(ItemInstance.item_id == entry.id))).scalars().all()
                if entry else []
            )
            return ok, note, entry, instances, prop.payload
    ok, note, entry, instances, payload = run(go())
    assert ok, note
    assert entry is not None and entry.cat == "items" and entry.item_type == "Key Item"
    assert len(instances) == 1
    assert payload["_createdNew"] is True
    assert payload["_invDeltas"]


def test_take_existing_item_grants_only_no_duplicate_catalog_entry(client, adventure):
    assert _catalog_entry("Sword") is not None

    async def go():
        async with new_session() as s:
            prop = WorldbuildingProposal(
                turn_number=1, kind="item", operation="take",
                payload={"itemName": "Sword", "count": 1},
            )
            ok, note = await wb.apply_proposal(prop, s)
            await s.commit()
            return ok, note, prop.payload
    ok, note, payload = run(go())
    assert ok, note
    assert payload.get("_createdNew") is False

    async def count_swords():
        async with new_session() as s:
            return len(
                (await s.execute(select(LorebookEntry).where(LorebookEntry.title == "Sword"))).scalars().all()
            )
    assert run(count_swords()) == 1, "no duplicate catalog entry"


def test_take_unknown_item_with_no_description_is_refused(client, adventure):
    async def go():
        async with new_session() as s:
            prop = WorldbuildingProposal(
                turn_number=1, kind="item", operation="take",
                payload={"itemName": "Something Nobody Described"},
            )
            return await wb.apply_proposal(prop, s)
    ok, note = run(go())
    assert not ok
    assert "description" in (note or "").lower()


def test_take_with_equip_on_character_grants_and_equips(client, adventure):
    async def go():
        async with new_session() as s:
            prop = WorldbuildingProposal(
                turn_number=1, kind="item", operation="take",
                payload={
                    "itemName": "Iron Helm", "description": "A dented iron helmet.",
                    "itemType": "Equipment", "slot": "Head", "equipOnCharacter": "Hero",
                },
            )
            ok, note = await wb.apply_proposal(prop, s)
            await s.commit()
            pc = await party_ops.load_pc(s)
            return ok, note, pc.equipment.get("head"), prop.payload
    ok, note, head_instance, payload = run(go())
    assert ok, note
    assert head_instance, "the helm should be equipped in the head slot"
    assert payload["_equipChanges"]


def test_redundant_take_with_no_explicit_count_is_a_noop(client, adventure):
    entry = _catalog_entry("Health Potion")
    _grant("Health Potion", 1)
    before = _stowed_count(entry.id)
    assert before >= 1

    async def go():
        async with new_session() as s:
            prop = WorldbuildingProposal(
                turn_number=1, kind="item", operation="take",
                payload={"itemName": "Health Potion"},  # no explicit count
            )
            ok, note = await wb.apply_proposal(prop, s)
            await s.commit()
            return ok, note, prop.payload
    ok, note, payload = run(go())
    assert ok, note
    assert payload["_invDeltas"] == [], "a restatement of already-held gear must record no delta"
    assert _stowed_count(entry.id) == before


# ── apply_proposal: equip ────────────────────────────────────────


def test_equip_already_held_item(client, adventure):
    _grant("Longbow", 1)

    async def go():
        async with new_session() as s:
            prop = WorldbuildingProposal(
                turn_number=1, kind="item", operation="equip",
                payload={"characterName": "Hero", "itemName": "Longbow", "slot": "rightHand"},
            )
            ok, note = await wb.apply_proposal(prop, s)
            await s.commit()
            pc = await party_ops.load_pc(s)
            return ok, note, pc.equipment.get("rightHand"), prop.payload
    ok, note, right_hand, payload = run(go())
    assert ok, note
    assert right_hand
    assert payload["_equipChanges"]


# ── apply_proposal: drop ─────────────────────────────────────────


def test_drop_full_removal(client, adventure):
    _grant("Rations", 2)
    entry = _catalog_entry("Rations")

    async def go():
        async with new_session() as s:
            prop = WorldbuildingProposal(
                turn_number=1, kind="item", operation="drop",
                payload={"itemName": "Rations", "count": 1},
            )
            ok, note = await wb.apply_proposal(prop, s)
            await s.commit()
            return ok, note, prop.payload
    ok, note, payload = run(go())
    assert ok, note
    assert payload["_invDeltas"]
    assert _stowed_count(entry.id) == 1


def test_drop_unequip_only(client, adventure):
    async def equip_bow():
        async with new_session() as s:
            item = (
                await s.execute(select(LorebookEntry).where(LorebookEntry.title == "Longbow"))
            ).scalars().first()
            pc = await party_ops.load_pc(s)
            await inv_ops.equip_instance(s, pc, pc.id, "rightHand", item)
            await s.commit()
    run(equip_bow())

    async def go():
        async with new_session() as s:
            prop = WorldbuildingProposal(
                turn_number=1, kind="item", operation="drop",
                payload={"itemName": "Longbow", "characterName": "Hero", "unequipOnly": True},
            )
            ok, note = await wb.apply_proposal(prop, s)
            await s.commit()
            pc = await party_ops.load_pc(s)
            return ok, note, pc.equipment.get("rightHand"), prop.payload
    ok, note, right_hand, payload = run(go())
    assert ok, note
    assert not right_hand, "the slot should be empty after unequip"
    assert payload["_equipChanges"]
    assert payload["_invDeltas"] == [], "unequipping doesn't touch inventory — the item just becomes stowed"


# ── Integration: a full Steward pass, then reversal ──────────────


def test_steward_pass_end_to_end_with_reversal(client, adventure, monkeypatch):
    _configure_settings()

    async def seed_narration():
        async with new_session() as s:
            s.add(ChatMessage(
                role="assistant", mode="narrator", turn_number=1, variant=0,
                content="Hero picks up a Brass Whistle from the chest and straps on a Steel Cap.",
            ))
            await s.commit()
    run(seed_narration())

    calls = {"n": 0}

    async def fake_agent_turn(**kwargs):
        calls["n"] += 1
        yield {
            "type": "result",
            "content": "",
            "tool_calls": [
                {
                    "id": "1", "name": "take_item",
                    "arguments": json.dumps({
                        "itemName": "Brass Whistle",
                        "description": "A small brass whistle on a cord.",
                        "itemType": "Key Item",
                    }),
                },
                {
                    "id": "2", "name": "take_item",
                    "arguments": json.dumps({
                        "itemName": "Steel Cap",
                        "description": "A dented steel cap.",
                        "itemType": "Equipment", "slot": "Head",
                        "equipOnCharacter": "Hero",
                    }),
                },
            ],
            "finish_reason": "tool_calls",
            "usage": None,
        }

    monkeypatch.setattr(wb, "chat_completion_agent_turn", fake_agent_turn)

    proposals = run(wb.run_worldbuilder(1))
    assert calls["n"] == 1, "the Steward should call the model exactly once"
    item_proposals = [p for p in proposals if p.kind == "item"]
    assert len(item_proposals) == 2
    assert all(p.status == "accepted" for p in item_proposals)

    async def check_state():
        async with new_session() as s:
            key_entry = (
                await s.execute(select(LorebookEntry).where(LorebookEntry.title == "Brass Whistle"))
            ).scalars().first()
            helm_entry = (
                await s.execute(select(LorebookEntry).where(LorebookEntry.title == "Steel Cap"))
            ).scalars().first()
            key_instances = (
                (await s.execute(select(ItemInstance).where(ItemInstance.item_id == key_entry.id))).scalars().all()
                if key_entry else []
            )
            pc = await party_ops.load_pc(s)
            events = (
                await s.execute(select(ChatEvent).where(ChatEvent.kind == "item", ChatEvent.tethered == 1))
            ).scalars().all()
            return key_entry, helm_entry, key_instances, pc.equipment.get("head"), events
    key_entry, helm_entry, key_instances, head_slot, events = run(check_state())
    assert key_entry is not None and helm_entry is not None
    assert len(key_instances) == 1
    assert head_slot, "the helm should have been equipped"
    assert len(events) == 2, "one tethered toast per accepted item proposal"

    # Reverse exactly as swipe/regenerate/delete would.
    async def reverse():
        async with new_session() as s:
            n = await wb.reverse_chronicler_effects(s, 1, exact=True)
            await s.commit()
            return n
    n = run(reverse())
    assert n >= 2

    async def check_reversed():
        async with new_session() as s:
            key_entry = (
                await s.execute(select(LorebookEntry).where(LorebookEntry.title == "Brass Whistle"))
            ).scalars().first()
            helm_entry = (
                await s.execute(select(LorebookEntry).where(LorebookEntry.title == "Steel Cap"))
            ).scalars().first()
            pc = await party_ops.load_pc(s)
            remaining_props = (
                await s.execute(select(WorldbuildingProposal).where(WorldbuildingProposal.turn_number == 1))
            ).scalars().all()
            events = (
                await s.execute(select(ChatEvent).where(ChatEvent.kind == "item", ChatEvent.tethered == 1))
            ).scalars().all()
            return key_entry, helm_entry, pc.equipment.get("head"), remaining_props, events
    key_entry2, helm_entry2, head_slot2, remaining_props, events2 = run(check_reversed())
    assert key_entry2 is None, "the newly-created catalog entry must be deleted on reversal"
    assert helm_entry2 is None, "the newly-created equipment catalog entry must be deleted on reversal"
    assert not head_slot2, "the equipment slot must be cleared on reversal"
    assert remaining_props == []
    assert events2 == []


def test_steward_skips_when_narration_has_no_possession_signal(client, adventure, monkeypatch):
    _configure_settings()

    async def seed_narration():
        async with new_session() as s:
            s.add(ChatMessage(
                role="assistant", mode="narrator", turn_number=1, variant=0,
                content="The wind sighs through the rafters. Nothing else stirs.",
            ))
            await s.commit()
    run(seed_narration())

    calls = {"n": 0}

    async def fake_agent_turn(**kwargs):
        calls["n"] += 1
        yield {"type": "result", "content": "", "tool_calls": [], "finish_reason": "stop", "usage": None}

    monkeypatch.setattr(wb, "chat_completion_agent_turn", fake_agent_turn)
    # turn_number=1 with the default worldbuilding_interval (2) is also not a
    # Chronicler turn (chronicler_span returns None), so this call count is
    # driven purely by the Steward's own pre-filter, not cadence.
    run(wb.run_worldbuilder(1))
    assert calls["n"] == 0, "the pre-filter must skip the LLM call entirely"
