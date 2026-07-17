"""R13: alternate openings — the narrator config carries a pool of alternate
first messages, and each adventure anchors the one the player selected."""

from server.tests.conftest import run


def test_narrator_alternates_round_trip(client):
    res = client.put("/api/narrator", json={
        "firstMessage": "The primary opening.",
        "firstMessageAlternates": ["  A second way in.  ", "", "A third."],
    })
    assert res.status_code == 200, res.text
    # Blanks are dropped; whitespace trimmed (mirrors firstMessageOptions).
    assert res.json()["firstMessageAlternates"] == ["A second way in.", "A third."]
    assert client.get("/api/narrator").json()["firstMessageAlternates"] == ["A second way in.", "A third."]


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
