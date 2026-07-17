"""Integration tests against the real app on a throwaway data dir (see
conftest). Boot seeds the Fantasy template campaign (Hero + Varena + catalog);
tests that touch chat/adventure state create their own adventure so they don't
interfere, while tests needing the template's party/inventory explicitly load
the boot adventure."""

import pytest

from server.tests.conftest import run


@pytest.fixture(scope="session")
def boot_adventure_id(client) -> str:
    """The template-seeded adventure that was active at app boot."""
    return client.get("/api/adventures").json()["activeId"]


def _new_adventure(client, name: str) -> str:
    res = client.post("/api/adventures", json={"name": name})
    assert res.status_code == 200, res.text
    return res.json()["id"]


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_boot_seeded_fantasy_template(client, boot_adventure_id):
    client.post(f"/api/adventures/{boot_adventure_id}/load")
    pc = client.get("/api/player-character").json()
    assert pc["basicInfo"]["name"] == "Hero"
    items = client.get("/api/items").json()
    assert any(i["name"] == "Sword" for i in items)


def test_lore_config_round_trip_and_clamp(client):
    assert client.get("/api/lore/config").json()["scanDepth"] == 3
    assert client.put("/api/lore/config", json={"scanDepth": 5}).json()["scanDepth"] == 5
    assert client.put("/api/lore/config", json={"scanDepth": 99}).json()["scanDepth"] == 20
    # Partial updates must not reset it.
    res = client.put("/api/lore/config", json={"injectionOrder": {"world": 1}})
    assert res.json()["scanDepth"] == 20
    client.put("/api/lore/config", json={"scanDepth": 3})  # restore default


def test_story_export(client):
    _new_adventure(client, "Export Test")
    import asyncio

    from server.db.database import new_session
    from server.db.models import ChatMessage

    async def seed():
        async with new_session() as s:
            s.add_all([
                ChatMessage(role="user", content="I enter the woods.", turn_number=1, mode="narrator"),
                ChatMessage(role="assistant", content="OLD TELLING", turn_number=1, variant=0,
                            mode="narrator", location="Murkwood", day=1),
                ChatMessage(role="assistant", content="The trees close in.", turn_number=1, variant=1,
                            mode="narrator", location="Murkwood", day=1),
                ChatMessage(role="user", content="PLANNER NOISE", turn_number=1, mode="planner"),
            ])
            await s.commit()
    run(seed())

    res = client.get("/api/adventure/story-export")
    assert res.status_code == 200
    md = res.text
    assert res.headers["content-disposition"].endswith('.md"')
    assert md.startswith("# ")
    assert "## Day 1 — Murkwood" in md
    assert "The trees close in." in md
    assert "OLD TELLING" not in md, "only the active (highest) variant exports"
    assert "PLANNER NOISE" not in md, "planner thread is excluded"


def test_narrator_item_tools_and_reversal(client, boot_adventure_id):
    """Grant/equip through the real narrator tools, then reverse — the item
    instance model must restore the exact prior state."""
    client.post(f"/api/adventures/{boot_adventure_id}/load")
    from server.ai.item_detection import reverse_inventory_deltas
    from server.ai.narrator_actions import reverse_equipment_changes, tool_equip, tool_grant_item
    from server.db import party as party_ops
    from server.db.database import new_session

    def stowed_potions() -> int:
        inv = client.get("/api/inventory").json()
        return sum(s["count"] for s in inv if s["item"]["name"] == "Health Potion" and not s.get("equippedBy"))

    before = stowed_potions()

    async def grant():
        async with new_session() as s:
            effect = await tool_grant_item({"itemName": "Health Potion", "count": 2}, s)
            await s.commit()
            return effect
    effect = run(grant())
    assert effect.ok and effect.inv_deltas
    assert stowed_potions() == before + 2

    async def undo_grant():
        async with new_session() as s:
            await reverse_inventory_deltas(effect.inv_deltas, s)
            await s.commit()
    run(undo_grant())
    assert stowed_potions() == before, "reversal restores the exact count"

    # Equip mints/reuses an instance; the slot must hold an instance id that
    # resolves as equipped; reversal restores the previous occupant.
    async def read_slot():
        async with new_session() as s:
            pc = await party_ops.load_pc(s)
            return pc.equipment.get("rightHand")
    prev_slot = run(read_slot())

    async def equip():
        async with new_session() as s:
            eff = await tool_equip({"characterName": "Hero", "slot": "rightHand", "itemName": "Sword"}, s)
            await s.commit()
            return eff
    eff = run(equip())
    assert eff.ok and eff.equip_changes
    new_slot = run(read_slot())
    assert new_slot, "slot holds an instance id"
    inv = client.get("/api/inventory").json()
    worn = next(s for s in inv if s["instanceId"] == new_slot)
    assert worn["item"]["name"] == "Sword" and worn["equippedBy"]

    async def undo_equip():
        async with new_session() as s:
            await reverse_equipment_changes(eff.equip_changes, s)
            await s.commit()
    run(undo_equip())
    assert run(read_slot()) == prev_slot, "reversal restores the prior occupant"

    async def undo_equip_inv():
        async with new_session() as s:
            await reverse_inventory_deltas(eff.inv_deltas, s)
            await s.commit()
    if eff.inv_deltas:  # a minted copy is deleted again on reversal
        run(undo_equip_inv())


def test_chronicler_update_prev_snapshot_restores(client):
    _new_adventure(client, "Chronicler Test")
    from sqlalchemy import select

    from server.ai.worldbuilder import apply_proposal, reverse_chronicler_effects
    from server.db.database import new_session
    from server.db.models import LorebookEntry, WorldbuildingProposal

    entry_id = client.post("/api/lore", json={
        "title": "Test Shrine", "content": "ORIGINAL", "cat": "world", "keywords": ["shrine"],
    }).json()["id"]

    async def apply_update():
        async with new_session() as s:
            prop = WorldbuildingProposal(
                turn_number=900, kind="lore", operation="update", status="pending",
                target_id=entry_id, payload={"content": "EDITED BY CHRONICLER"},
            )
            s.add(prop)
            ok, note = await apply_proposal(prop, s)
            assert ok, note
            prop.status = "accepted"
            await s.commit()
            return prop.payload.get("_prev")
    prev = run(apply_update())
    assert prev == {"content": "ORIGINAL", "keywords": ["shrine"]}
    assert client.get(f"/api/lore/{entry_id}").json()["content"] == "EDITED BY CHRONICLER"

    async def reverse():
        async with new_session() as s:
            n = await reverse_chronicler_effects(s, 900, exact=True)
            await s.commit()
            remaining = (await s.execute(
                select(WorldbuildingProposal).where(WorldbuildingProposal.turn_number == 900)
            )).scalars().all()
            return n, remaining
    n, remaining = run(reverse())
    assert n >= 1 and remaining == []
    assert client.get(f"/api/lore/{entry_id}").json()["content"] == "ORIGINAL"

    client.delete(f"/api/lore/{entry_id}")


def test_background_summary_with_stubbed_llm(client):
    _new_adventure(client, "Summary Test")
    from sqlalchemy import select

    from server.api import chat as chat_routes
    from server.db.database import new_session
    from server.db.models import ChatMessage, OpenRouterSettings, StorySummary

    async def seed():
        async with new_session() as s:
            st = (await s.execute(select(OpenRouterSettings))).scalars().first()
            if not st:
                st = OpenRouterSettings()
                s.add(st)
            st.api_key, st.model_id = "sk-test", "test/model"
            for t in range(1, 9):
                s.add(ChatMessage(role="user", content=f"action {t}", turn_number=t, mode="narrator"))
                s.add(ChatMessage(role="assistant", content=f"narration {t} " + "x" * 50,
                                  turn_number=t, variant=0, mode="narrator"))
            await s.commit()
    run(seed())

    async def fake_generate_summary(api_key, model_id, messages_to_summarize, existing_summary, base_url):
        return "THE STORY SO FAR (stub)."
    real = chat_routes.generate_summary
    chat_routes.generate_summary = fake_generate_summary
    try:
        run(chat_routes._summarize_in_background())
    finally:
        chat_routes.generate_summary = real

    async def check():
        async with new_session() as s:
            summ = (await s.execute(select(StorySummary))).scalars().first()
            return summ.content if summ else None, summ.summary_up_to_turn if summ else 0
    content, boundary = run(check())
    assert content == "THE STORY SO FAR (stub)." and boundary > 0
    assert client.get("/api/journal").json()["summary"] == "THE STORY SO FAR (stub)."
