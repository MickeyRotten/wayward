"""Integration tests for the true Continue, automatic backups, and the
backdrop manager endpoints (R5/R12/R7)."""

import io
import json
import zipfile

from sqlalchemy import select

from server.tests.conftest import run


def _active_campaign_id(client) -> str:
    return client.get("/api/campaigns").json()["activeId"]


# ── R5: true Continue ─────────────────────────────────────────────

def _sse_events(body: str) -> list[dict]:
    return [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]


def test_continue_extends_latest_narration(client, monkeypatch):
    client.post("/api/adventures", json={"name": "Continue Test"})
    from server.api import routes
    from server.db.database import new_session
    from server.db.models import ChatMessage, OpenRouterSettings

    async def seed():
        async with new_session() as s:
            st = (await s.execute(select(OpenRouterSettings))).scalars().first()
            if not st:
                st = OpenRouterSettings()
                s.add(st)
            st.api_key, st.model_id = "sk-test", "test/model"
            s.add(ChatMessage(role="user", content="I step into the clearing.", turn_number=1, mode="narrator"))
            s.add(ChatMessage(role="assistant", content="The clearing is silent.", turn_number=1,
                              variant=0, mode="narrator"))
            await s.commit()
    run(seed())

    async def fake_stream(**_kwargs):
        yield "Then a twig snaps"
        yield " behind you."
    monkeypatch.setattr(routes, "chat_completion_stream", lambda **kw: fake_stream(**kw))

    res = client.post("/api/chat/continue")
    assert res.status_code == 200, res.text
    done = next(e for e in _sse_events(res.text) if e["type"] == "done")
    # Existing prose ended with '.', so the continuation starts a new paragraph.
    assert done["message"]["content"] == "The clearing is silent.\n\nThen a twig snaps behind you."

    async def check_db():
        async with new_session() as s:
            msgs = (await s.execute(select(ChatMessage).where(ChatMessage.role == "assistant"))).scalars().all()
            return [m.content for m in msgs]
    contents = run(check_db())
    assert "The clearing is silent.\n\nThen a twig snaps behind you." in contents
    assert len(contents) == 1, "continue must extend in place, not add a message/turn"


def test_continue_splices_a_clipped_beat_with_a_space(client, monkeypatch):
    client.post("/api/adventures", json={"name": "Continue Clip Test"})
    from server.api import routes
    from server.db.database import new_session
    from server.db.models import ChatMessage

    async def seed():
        async with new_session() as s:
            s.add(ChatMessage(role="user", content="Go on.", turn_number=1, mode="narrator"))
            s.add(ChatMessage(role="assistant", content="The corridor stretches into", turn_number=1,
                              variant=0, mode="narrator"))
            await s.commit()
    run(seed())

    async def fake_stream(**_kwargs):
        yield "darkness beyond the torchlight."
    monkeypatch.setattr(routes, "chat_completion_stream", lambda **kw: fake_stream(**kw))

    res = client.post("/api/chat/continue")
    done = next(e for e in _sse_events(res.text) if e["type"] == "done")
    assert done["message"]["content"] == "The corridor stretches into darkness beyond the torchlight."


def test_continue_without_narration_is_a_clean_error(client):
    client.post("/api/adventures", json={"name": "Continue Empty Test"})
    res = client.post("/api/chat/continue")
    assert res.status_code == 400


# ── R12: automatic backups ────────────────────────────────────────

def test_snapshot_backup_and_restore(client):
    from server.db import storage

    cid = _active_campaign_id(client)
    path = storage.snapshot_campaign(cid)
    assert path is not None and path.exists()
    with zipfile.ZipFile(path) as z:
        assert "campaign.db" in z.namelist() and "campaign.json" in z.namelist()

    # Throttled: an immediate second snapshot of the same campaign is skipped.
    assert storage.snapshot_campaign(cid) is None

    listed = client.get("/api/backups").json()
    assert any(b["file"] == path.name for b in listed)

    campaigns_before = client.get("/api/campaigns").json()["campaigns"]
    res = client.post(f"/api/backups/{path.name}/restore")
    assert res.status_code == 200, res.text
    restored = res.json()
    assert restored["id"] != cid, "restore creates a NEW campaign"
    campaigns_after = client.get("/api/campaigns").json()["campaigns"]
    assert len(campaigns_after) == len(campaigns_before) + 1
    assert any(c["id"] == restored["id"] for c in campaigns_after)

    # Missing snapshots 404; the path-param traversal guard is exercised by
    # calling the endpoint function directly (an HTTP client normalizes ../
    # away before the route would ever see it).
    assert client.post("/api/backups/nope.zip/restore").status_code == 404
    import pytest
    from fastapi import HTTPException

    from server.api import routes
    with pytest.raises(HTTPException):
        run(routes.restore_backup("../app.db.zip"))


def test_backup_rotation_keeps_newest(client):
    import os
    import time

    from server.db import storage

    d = storage.backups_dir()
    d.mkdir(parents=True, exist_ok=True)
    base = time.time() - 10_000
    for i in range(storage.BACKUP_KEEP + 4):
        p = d / f"zzz-dummy-{i}.zip"
        p.write_bytes(b"PK\x05\x06" + b"\x00" * 18)  # minimal empty zip
        os.utime(p, (base + i, base + i))

    cid = _active_campaign_id(client)
    # Bypass the per-campaign throttle by clearing this campaign's snapshots.
    for p in d.glob(f"{cid[:8]}-*.zip"):
        p.unlink()
    assert storage.snapshot_campaign(cid) is not None
    zips = list(d.glob("*.zip"))
    assert len(zips) <= storage.BACKUP_KEEP


# ── R7: backdrop manager endpoints ────────────────────────────────

def test_backdrop_upload_list_delete(client):
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
    fname = None
    try:
        res = client.post(
            "/api/backdrops/upload",
            files={"file": ("Test Scene day.png", io.BytesIO(png), "image/png")},
        )
        assert res.status_code == 200, res.text
        fname = res.json()["file"]
        assert fname.endswith(".png") and "/" not in fname

        listed = client.get("/api/backdrops").json()
        assert any(b["file"] == fname for b in listed)
        assert client.get(f"/api/backdrops/{fname}").status_code == 200
    finally:
        if fname:
            assert client.delete(f"/api/backdrops/{fname}").status_code == 204
    assert client.get(f"/api/backdrops/{fname}").status_code == 404


def test_backdrop_upload_rejects_bad_types_and_traversal(client):
    res = client.post(
        "/api/backdrops/upload",
        files={"file": ("evil.exe", io.BytesIO(b"MZ"), "application/octet-stream")},
    )
    assert res.status_code == 400
    # Missing files 404; the traversal guard is exercised on the function
    # directly (an HTTP client normalizes ../ before the route sees it).
    assert client.delete("/api/backdrops/nope.png").status_code == 404
    import pytest
    from fastapi import HTTPException

    from server.api import routes
    with pytest.raises(HTTPException):
        run(routes.delete_backdrop("../main.py"))
