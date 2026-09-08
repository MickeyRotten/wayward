"""HTTP-level tests for the block-tree editing routes added for the
block-tree UI (PUT /player-character/blocks, /party-members/{id}/blocks, and
the equipment-only counterparts) — see TODO.md's Character system rebuild
follow-ups.

Each test creates its own throwaway adventure rather than reusing the
session-wide boot adventure other test files share — the fantasy template's
seeded PC/party member are mutated by tests elsewhere in the suite in ways
that make their exact state (name, membership) unsafe to assume here."""

import pytest


@pytest.fixture()
def fresh_adventure(client) -> str:
    """A brand-new, empty adventure — its own blank PC, no party members —
    switched active for the duration of the test."""
    res = client.post("/api/adventures", json={"name": "Blocks API Test"})
    assert res.status_code == 200, res.text
    return res.json()["id"]


def test_get_player_character_includes_blocks(client, fresh_adventure):
    pc = client.get("/api/player-character").json()
    assert isinstance(pc["blocks"], list) and pc["blocks"]
    names = [b["name"] for b in pc["blocks"]]
    assert "Open Tag" in names and "Close Tag" in names


def test_put_player_character_blocks_round_trips_and_renames(client, fresh_adventure):
    pc = client.get("/api/player-character").json()
    blocks = pc["blocks"]

    # Toggle the first non-tag text block off, and append a new one.
    for b in blocks:
        if b["type"] == "text" and b["name"] not in ("Open Tag", "Close Tag"):
            b["enabled"] = False
            break
    blocks.append({"id": "custom1", "type": "text", "name": "Quirks", "content": "Hums when nervous.", "enabled": True})

    res = client.put("/api/player-character/blocks", json={"blocks": blocks, "name": "Renamed Hero"})
    assert res.status_code == 200, res.text
    body = res.json()
    saved_names = {b["name"]: b for b in body["blocks"]}
    assert "Quirks" in saved_names
    assert saved_names["Quirks"]["content"] == "Hums when nervous."
    assert body["basicInfo"]["name"] == "Renamed Hero"

    # Persisted — a fresh GET reflects it too.
    reget = client.get("/api/player-character").json()
    assert any(b["name"] == "Quirks" for b in reget["blocks"])
    assert reget["basicInfo"]["name"] == "Renamed Hero"


def test_put_player_character_blocks_omits_name_leaves_it_untouched(client, fresh_adventure):
    pc = client.get("/api/player-character").json()
    res = client.put("/api/player-character/blocks", json={"blocks": pc["blocks"]})
    assert res.status_code == 200, res.text
    assert res.json()["basicInfo"]["name"] == pc["basicInfo"]["name"]


def test_put_player_character_equipment_does_not_touch_blocks(client, fresh_adventure):
    pc = client.get("/api/player-character").json()
    empty_equipment = {k: None for k in pc["equipment"]}
    res = client.put("/api/player-character/equipment", json=empty_equipment)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["blocks"] == pc["blocks"]
    assert all(v is None for v in body["equipment"].values())


def test_party_member_blocks_round_trip(client, fresh_adventure):
    created = client.post("/api/party-members", json={}).json()
    member_id = created["id"]
    assert isinstance(created["blocks"], list) and created["blocks"]

    blocks = created["blocks"]
    blocks.append({"id": "custom2", "type": "text", "name": "Fears", "content": "Deep water.", "enabled": True})
    res = client.put(f"/api/party-members/{member_id}/blocks", json={"blocks": blocks})
    assert res.status_code == 200, res.text
    assert any(b["name"] == "Fears" for b in res.json()["blocks"])

    reget = client.get("/api/party-members").json()
    saved = next(m for m in reget if m["id"] == member_id)
    assert any(b["name"] == "Fears" for b in saved["blocks"])


def test_party_member_equipment_does_not_touch_blocks(client, fresh_adventure):
    created = client.post("/api/party-members", json={}).json()
    member_id = created["id"]
    empty_equipment = {k: None for k in created["equipment"]}
    res = client.put(f"/api/party-members/{member_id}/equipment", json=empty_equipment)
    assert res.status_code == 200, res.text
    assert res.json()["blocks"] == created["blocks"]


def test_party_member_blocks_404_for_unknown_id(client, fresh_adventure):
    res = client.put("/api/party-members/does-not-exist/blocks", json={"blocks": []})
    assert res.status_code == 404


def test_party_member_equipment_404_for_unknown_id(client, fresh_adventure):
    res = client.put("/api/party-members/does-not-exist/equipment", json={})
    assert res.status_code == 404
