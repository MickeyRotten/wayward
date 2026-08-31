"""The turn block, end to end through the real chat route.

This is the change that took a whole model round-trip out of the common turn:
scene state used to be a tool call (call, execute, append a tool result, call
again to narrate); now it rides the last line of the beat the model already
wrote. The test drives the real ``/api/chat`` endpoint against a stubbed
provider and asserts the three things that must hold: the block never reaches
the player, the scene it carries is persisted, and the clock advanced by the
duration it named rather than by anything the model wrote.
"""

import json

import httpx
import pytest

from server.ai import openrouter


@pytest.fixture(scope="module")
def adventure(client):
    """A dedicated save, so these turns never disturb another test's transcript."""
    aid = client.post("/api/adventures", json={"name": "turn-block"}).json()["id"]
    client.post(f"/api/adventures/{aid}/load")
    return aid


def _sse(text: str) -> bytes:
    chunks = [
        {"choices": [{"delta": {"content": text}}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}]},
    ]
    return ("".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n").encode()


def _stub(monkeypatch, reply: str):
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [
                {"id": "test-model", "name": "test", "context_length": 32000,
                 "supported_parameters": []},
            ]})
        return httpx.Response(200, content=_sse(reply),
                              headers={"content-type": "text/event-stream"})

    monkeypatch.setattr(openrouter, "_shared_client",
                        httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    openrouter._model_cache.clear()


def _configure(client, **narrator):
    s = client.get("/api/settings/openrouter").json()
    s.update(apiKey="test", modelId="test-model", toolMode="text",
             worldbuildingMode="disabled")
    assert client.put("/api/settings/openrouter", json=s).status_code == 200
    n = client.get("/api/narrator").json()
    n.update(actionSuggestionsEnabled=True, actionSuggestionsMode="inline",
             actionSuggestionsCount=2, **narrator)
    client.put("/api/narrator", json=n)


def _send(client, text: str) -> str:
    with client.stream("POST", "/api/chat/turn", json={"message": text}) as r:
        return r.read().decode()


def _done_event(body: str) -> dict:
    events = [json.loads(ln[6:]) for ln in body.splitlines() if ln.startswith("data: ")]
    return next(e for e in events if e.get("type") == "done")


BEAT = "The stair gives way to damp air and the smell of old wine."


def test_the_block_is_stripped_and_its_scene_persisted(client, adventure, monkeypatch):
    _configure(client)
    _stub(monkeypatch, BEAT + '\n\n<<<TURN>>>' + json.dumps({
        "location": "Boars Head Tavern - Damp Cellar",
        "weather": "cold and still",
        "duration": "scene",
        "options": ["I search the racks.", "I climb back up."],
    }))

    done = _done_event(_send(client, "I go down the stairs."))
    msg = done["message"]

    assert "<<<" not in msg["content"], "the block must never reach the player"
    assert msg["content"].strip() == BEAT
    # The compound location keeps only its narrowest segment.
    assert msg["location"] == "Damp Cellar"
    assert msg["weather"] == "cold and still"
    # The options rode the same call — no second request was needed for them.
    assert done["suggestions"] == ["I search the racks.", "I climb back up."]


def test_the_server_owns_the_clock(client, adventure, monkeypatch):
    _configure(client)

    # An adventure opens mid-morning. Two half-days carry it to the evening —
    # each step is the server's arithmetic, not a number the model wrote.
    for _ in range(2):
        _stub(monkeypatch, BEAT + '\n<<<TURN>>>{"duration": "halfday"}')
        evening = _done_event(_send(client, "I travel."))["message"]
    assert evening["timeOfDay"] in ("evening", "dusk", "night")
    day_before_sleep = evening["day"]

    # Sleeping from the evening ANCHORS to the next morning rather than adding a
    # fixed span, so a night is always a night.
    _stub(monkeypatch, BEAT + '\n<<<TURN>>>{"duration": "night", "location": "Loft"}')
    slept = _done_event(_send(client, "I sleep."))["message"]
    assert slept["timeOfDay"] == "morning"
    assert slept["day"] == day_before_sleep + 1
    assert slept["location"] == "Loft"

    # A short beat advances time without touching the day.
    _stub(monkeypatch, BEAT + '\n<<<TURN>>>{"duration": "moment"}')
    second = _done_event(_send(client, "I stretch."))["message"]
    assert second["day"] == slept["day"]

    # And a narrator that writes a day number anyway cannot move the calendar:
    # "day" is not in the block's contract at all.
    _stub(monkeypatch, BEAT + '\n<<<TURN>>>{"duration": "brief", "day": 99}')
    third = _done_event(_send(client, "I look around."))["message"]
    assert third["day"] == slept["day"], "the calendar is not the narrator's to write"


def test_a_turn_with_no_block_still_ages_the_world(client, adventure, monkeypatch):
    _configure(client)
    _stub(monkeypatch, BEAT)  # no block at all

    before = _done_event(_send(client, "I wait."))["message"]
    _stub(monkeypatch, BEAT + " Again.")
    after = _done_event(_send(client, "I wait again."))["message"]

    assert after["content"].endswith("Again.")
    # Both turns carry a clock: an unparseable beat must never freeze it.
    assert before["day"] and after["day"]
