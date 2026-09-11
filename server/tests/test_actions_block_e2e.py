"""The unified <<<ACTIONS>>> block, end to end through the real chat route.

Proves the vocabulary/handler unification actually holds through the full
stack (not just the unit-level ``execute_actions`` tests in
test_execute_actions.py): a ``tool_mode: text`` narrator emitting the new
canonical ``{"actions": [{"tool": ..., ...}]}`` shape alongside the trailing
``<<<TURN>>>`` block gets both parsed correctly, the item lands in inventory,
and a failed action surfaces as ``done.toolFailures`` — the same field the
native tool-calling path already populates.
"""

import json

import pytest

from server.tests.test_turn_block_e2e import _configure, _done_event, _send, _stub


def _new_adventure(client, name: str) -> str:
    aid = client.post("/api/adventures", json={"name": name}).json()["id"]
    client.post(f"/api/adventures/{aid}/load")
    return aid


def _seed_pc(client, name: str) -> None:
    pc = client.get("/api/player-character").json()
    pc["basicInfo"]["name"] = name
    assert client.put("/api/player-character", json=pc).status_code == 200


@pytest.fixture()
def isolated_adventure(client):
    """A fresh, loaded adventure for the duration of one test — restores
    whichever adventure was active before, so switching here can't leak into
    session-scoped fixtures elsewhere (e.g. test_app_integration.py's
    ``boot_adventure_id``, which captures 'whatever is active' on first use)."""
    prev_active = client.get("/api/adventures").json().get("activeId")
    yield
    if prev_active:
        client.post(f"/api/adventures/{prev_active}/load")


BEAT = "The chest creaks open, and Hero pockets a small brass key."


def test_actions_block_grants_an_item_end_to_end(client, isolated_adventure, monkeypatch):
    _new_adventure(client, "Actions Block E2E")
    _seed_pc(client, "Hero")
    _configure(client)
    _stub(monkeypatch, BEAT + '\n<<<ACTIONS>>>' + json.dumps({
        "actions": [{"tool": "grant_item", "itemName": "Brass Key"}],
    }) + '<<<END ACTIONS>>>\n<<<TURN>>>' + json.dumps({
        "duration": "moment", "options": ["I pocket the key.", "I leave it."],
    }))

    # grant_item resolves by exact catalog name — seed the catalog entry first
    # via the Editor-less lore route (a Chronicler/Editor create would also
    # work; this keeps the test focused on execute_actions, not lore CRUD).
    assert client.post("/api/lore", json={
        "title": "Brass Key", "content": "A small brass key.", "cat": "items",
        "itemType": "Key Item",
    }).status_code == 201

    done = _done_event(_send(client, "I search the chest."))
    msg = done["message"]

    assert "<<<" not in msg["content"], "both blocks must be stripped from the displayed prose"
    assert msg["content"].strip() == BEAT
    assert done["suggestions"] == ["I pocket the key.", "I leave it."]
    assert done.get("appliedInventoryDeltas"), "the grant must be recorded for reversal"
    assert not done.get("toolFailures")

    inv = client.get("/api/inventory").json()
    assert any(s["item"]["name"] == "Brass Key" for s in inv)


def test_actions_block_failure_surfaces_as_tool_failure(client, isolated_adventure, monkeypatch):
    _new_adventure(client, "Actions Block E2E Failure")
    _seed_pc(client, "Hero")
    _configure(client)
    _stub(monkeypatch, BEAT + '\n<<<ACTIONS>>>' + json.dumps({
        "actions": [{"tool": "equip", "characterName": "Hero", "slot": "rightHand",
                     "itemName": "A Sword That Does Not Exist"}],
    }) + '<<<END ACTIONS>>>')

    done = _done_event(_send(client, "I reach for my sword."))
    assert done.get("toolFailures"), "a failed mutating action must surface, not vanish silently"
    assert "world stayed safe" in done["toolFailures"][0]
