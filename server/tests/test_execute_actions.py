"""``execute_actions`` — the text-protocol ``<<<ACTIONS>>>`` block's executor.

Unified with the native tool-calling loop: both now speak the same five-verb
vocabulary (grant_item/remove_item/consume_item/equip/unequip) through the
same handlers (``ACTION_HANDLERS``), so this path gets the native loop's
no-op guarantees and failure reporting for free instead of re-implementing
them. See CLAUDE.md > The Narrator Agent Loop.

Each test creates its own throwaway adventure (in the shared, boot-seeded
Fantasy campaign, so the template catalog — Sword, Health Potion, Longbow,
Rations, ... — already exists) instead of touching the ``boot_adventure_id``
adventure other test modules depend on.
"""

import pytest
from sqlalchemy import select

from server.ai.narrator_actions import execute_actions
from server.db import inventory as inv_ops
from server.db import party as party_ops
from server.db.database import new_session
from server.db.models import ItemInstance, LorebookEntry
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


@pytest.fixture()
def adventure(client):
    """A fresh adventure with a named PC, in the shared Fantasy campaign (so
    Sword/Health Potion/Longbow/Rations from the template catalog already
    exist). Restores whichever adventure was active before, so switching here
    can't leak into session-scoped fixtures elsewhere (e.g.
    test_app_integration.py's ``boot_adventure_id``, which captures 'whatever
    is active' on first use — independent of test file execution order)."""
    prev_active = client.get("/api/adventures").json().get("activeId")
    aid = _new_adventure(client, "Execute Actions Test")
    _seed_pc("Hero")
    yield aid
    if prev_active:
        client.post(f"/api/adventures/{prev_active}/load")


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


def _run_actions(actions: dict):
    async def go():
        async with new_session() as s:
            result = await execute_actions(actions, s)
            await s.commit()
            return result
    return run(go())


def _equipped_slot(slot: str) -> str | None:
    async def go():
        async with new_session() as s:
            pc = await party_ops.load_pc(s)
            return pc.equipment.get(slot)
    return run(go())


# ── Canonical shape: {"actions": [{"tool": ..., ...}]} ────────────


def test_grant_via_canonical_shape(client, adventure):
    entry = _catalog_entry("Health Potion")
    before = _stowed_count(entry.id)

    inv_deltas, equip_changes, failures = _run_actions(
        {"actions": [{"tool": "grant_item", "itemName": "Health Potion", "count": 2}]}
    )
    assert inv_deltas and not equip_changes and not failures
    assert _stowed_count(entry.id) == before + 2


def test_consume_via_canonical_shape(client, adventure):
    _grant("Health Potion", 3)
    entry = _catalog_entry("Health Potion")
    before = _stowed_count(entry.id)

    inv_deltas, equip_changes, failures = _run_actions(
        {"actions": [{"tool": "consume_item", "itemName": "Health Potion", "count": 1}]}
    )
    assert inv_deltas and not failures
    assert _stowed_count(entry.id) == before - 1


def test_equip_via_canonical_shape(client, adventure):
    _grant("Longbow", 1)

    inv_deltas, equip_changes, failures = _run_actions(
        {"actions": [{"tool": "equip", "characterName": "Hero", "slot": "rightHand", "itemName": "Longbow"}]}
    )
    assert equip_changes and not failures
    assert _equipped_slot("rightHand")


def test_unequip_via_canonical_shape(client, adventure):
    _grant("Longbow", 1)
    _run_actions({"actions": [{"tool": "equip", "characterName": "Hero", "slot": "rightHand", "itemName": "Longbow"}]})
    assert _equipped_slot("rightHand")

    inv_deltas, equip_changes, failures = _run_actions(
        {"actions": [{"tool": "unequip", "characterName": "Hero", "slot": "rightHand"}]}
    )
    assert equip_changes and not failures
    assert not _equipped_slot("rightHand")


def test_remove_via_canonical_shape(client, adventure):
    # The regression test for the real bug: removeItems was documented in
    # ACTION_INSTRUCTION but execute_actions never implemented it at all.
    _grant("Rations", 2)
    entry = _catalog_entry("Rations")
    before = _stowed_count(entry.id)

    inv_deltas, equip_changes, failures = _run_actions(
        {"actions": [{"tool": "remove_item", "itemName": "Rations", "count": 1}]}
    )
    assert inv_deltas and not failures
    assert _stowed_count(entry.id) == before - 1


# ── Legacy shape backward compatibility ───────────────────────────


def test_legacy_add_items_still_works(client, adventure):
    entry = _catalog_entry("Health Potion")
    before = _stowed_count(entry.id)

    inv_deltas, _equip_changes, failures = _run_actions(
        {"addItems": [{"itemName": "Health Potion", "count": 1}]}
    )
    assert inv_deltas and not failures
    assert _stowed_count(entry.id) == before + 1


def test_legacy_remove_items_now_actually_works(client, adventure):
    # Same bug, proven through the legacy key: a pre-existing custom
    # action_instruction override describing the old shape must keep working.
    _grant("Rations", 2)
    entry = _catalog_entry("Rations")
    before = _stowed_count(entry.id)

    inv_deltas, _equip_changes, failures = _run_actions(
        {"removeItems": [{"itemName": "Rations", "count": 1}]}
    )
    assert inv_deltas and not failures
    assert _stowed_count(entry.id) == before - 1


def test_legacy_equip_and_unequip_still_work(client, adventure):
    _grant("Longbow", 1)
    _inv, equip_changes, failures = _run_actions(
        {"equip": [{"characterName": "Hero", "slot": "rightHand", "itemName": "Longbow"}]}
    )
    assert equip_changes and not failures
    assert _equipped_slot("rightHand")

    _inv, equip_changes, failures = _run_actions(
        {"unequip": [{"characterName": "Hero", "slot": "rightHand"}]}
    )
    assert equip_changes and not failures
    assert not _equipped_slot("rightHand")


# ── Dedup, no-op guarantees, failures ─────────────────────────────


def test_duplicate_entry_in_one_block_is_suppressed(client, adventure):
    entry = _catalog_entry("Health Potion")
    before = _stowed_count(entry.id)

    inv_deltas, _equip, _fail = _run_actions({"actions": [
        {"tool": "grant_item", "itemName": "Health Potion", "count": 1},
        {"tool": "grant_item", "itemName": "Health Potion", "count": 1},
    ]})
    # Two IDENTICAL entries in one block collapse to a single grant.
    assert _stowed_count(entry.id) == before + 1
    assert len(inv_deltas) == 1


def test_redundant_grant_no_explicit_count_is_noop(client, adventure):
    _grant("Health Potion", 1)
    entry = _catalog_entry("Health Potion")
    before = _stowed_count(entry.id)

    inv_deltas, _equip, failures = _run_actions(
        {"actions": [{"tool": "grant_item", "itemName": "Health Potion"}]}  # no count
    )
    assert inv_deltas == [] and not failures
    assert _stowed_count(entry.id) == before


def test_redundant_equip_already_worn_is_noop(client, adventure):
    _grant("Longbow", 1)
    _run_actions({"actions": [{"tool": "equip", "characterName": "Hero", "slot": "rightHand", "itemName": "Longbow"}]})

    _inv, equip_changes, failures = _run_actions(
        {"actions": [{"tool": "equip", "characterName": "Hero", "slot": "rightHand", "itemName": "Longbow"}]}
    )
    assert equip_changes == [] and not failures


def test_equip_nonexistent_item_reports_a_tool_failure(client, adventure):
    _inv, _equip, failures = _run_actions(
        {"actions": [{"tool": "equip", "characterName": "Hero", "slot": "rightHand", "itemName": "Nonexistent Blade"}]}
    )
    assert failures
    assert "world stayed safe" in failures[0]


def test_unknown_tool_name_is_skipped_not_a_crash(client, adventure):
    inv_deltas, equip_changes, failures = _run_actions(
        {"actions": [{"tool": "set_scene", "location": "Nowhere"}]}
    )
    # set_scene is native-only (no round-trip to react to in a one-shot block)
    # and read tools are never offered here — an unsupported tool is silently
    # skipped, never a crash and never a player-facing failure note.
    assert inv_deltas == [] and equip_changes == [] and failures == []


def test_no_actions_is_a_noop(client, adventure):
    inv_deltas, equip_changes, failures = _run_actions({})
    assert inv_deltas == [] and equip_changes == [] and failures == []
