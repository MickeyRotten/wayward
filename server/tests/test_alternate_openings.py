"""R13/R19: alternate openings — the narrator config carries a pool of
alternate first messages (each with its own scripted options), and each
adventure anchors the one the player selected."""

from server.ai.scenario import normalize_openings
from server.tests.conftest import run


def test_normalize_openings_shapes():
    # Object shape: message trimmed, blank options dropped.
    assert normalize_openings([{"message": " Hi ", "options": ["a", "", " b "]}]) == [
        {"message": "Hi", "options": ["a", "b"]},
    ]
    # Legacy R13 bare-string shape coerces to {message, options: []}.
    assert normalize_openings(["A way in.", ""]) == [{"message": "A way in.", "options": []}]
    # Messageless entries are dropped entirely.
    assert normalize_openings([{"message": "", "options": ["x"]}]) == []
    assert normalize_openings(None) == []


def test_narrator_alternates_round_trip(client):
    res = client.put("/api/narrator", json={
        "firstMessage": "The primary opening.",
        "firstMessageAlternates": [
            {"message": "  A second way in.  ", "options": ["Look up", "", " Run "]},
            {"message": "", "options": ["dropped"]},
            {"message": "A third."},
        ],
    })
    assert res.status_code == 200, res.text
    # Messageless alt dropped; whitespace trimmed; blank options dropped.
    assert res.json()["firstMessageAlternates"] == [
        {"message": "A second way in.", "options": ["Look up", "Run"]},
        {"message": "A third.", "options": []},
    ]
    assert client.get("/api/narrator").json()["firstMessageAlternates"] == [
        {"message": "A second way in.", "options": ["Look up", "Run"]},
        {"message": "A third.", "options": []},
    ]


def test_opening_endpoint_null_until_anchored_then_resets(client):
    # Isolate in a throwaway adventure, then restore the active one so the
    # session-shared boot adventure stays active for later tests.
    original = client.get("/api/adventures").json()["activeId"]
    client.post("/api/adventures", json={"name": "Anchor Test"})

    # A fresh adventure has no anchored opening — the client cycles locally.
    assert client.get("/api/chat/opening").json()["message"] is None

    # Simulate the first-turn anchor writing the chosen greeting.
    from sqlalchemy import select

    from server.db.database import new_session
    from server.db.models import StorySummary

    async def anchor():
        async with new_session() as s:
            summary = (await s.execute(select(StorySummary))).scalars().first()
            if not summary:
                summary = StorySummary(content="", summary_up_to_turn=0)
                s.add(summary)
            summary.opening_message = "An alternate opening, anchored."
            await s.commit()
    run(anchor())

    assert client.get("/api/chat/opening").json()["message"] == "An alternate opening, anchored."

    # Clearing the chat returns to the opening — the anchor is released.
    assert client.delete("/api/chat/messages").status_code == 204
    assert client.get("/api/chat/opening").json()["message"] is None

    client.post(f"/api/adventures/{original}/load")
