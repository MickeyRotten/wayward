"""R3/R6: reasoning-delta surfacing and real usage accounting, driven through
the actual SSE parsers against a mocked OpenAI-compatible transport."""

import json

import httpx
import pytest

from server.ai import openrouter
from server.tests.conftest import run


def _sse(chunks: list[dict]) -> bytes:
    lines = [f"data: {json.dumps(c)}\n\n" for c in chunks]
    lines.append("data: [DONE]\n\n")
    return "".join(lines).encode()


CHUNKS = [
    {"choices": [{"delta": {"reasoning": "Let me think about the scene. "}}]},
    {"choices": [{"delta": {"reasoning_content": "The party is in the woods."}}]},
    {"choices": [{"delta": {"content": "The trees "}}]},
    {"choices": [{"delta": {"content": "close in."}, "finish_reason": "stop"}]},
    {"choices": [], "usage": {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150, "cost": 0.0021}},
]


@pytest.fixture
def mock_llm(monkeypatch):
    """Point the shared HTTP client at a mocked SSE endpoint."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_sse(CHUNKS),
                              headers={"content-type": "text/event-stream"})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(openrouter, "_shared_client", client)
    yield
    run(client.aclose())


def test_stream_default_mode_yields_content_strings_only(mock_llm):
    async def collect():
        out = []
        async for item in openrouter.chat_completion_stream(
            api_key="k", model_id="m", messages=[], temperature=0.7, max_tokens=100,
        ):
            out.append(item)
        return out
    items = run(collect())
    assert items == ["The trees ", "close in."], "original contract unchanged"


def test_stream_events_mode_surfaces_reasoning_and_usage(mock_llm):
    async def collect():
        out = []
        async for item in openrouter.chat_completion_stream(
            api_key="k", model_id="m", messages=[], temperature=0.7, max_tokens=100,
            yield_events=True,
        ):
            out.append(item)
        return out
    items = run(collect())
    kinds = [i["type"] for i in items]
    assert kinds == ["reasoning", "reasoning", "content", "content", "usage"]
    assert items[0]["text"].startswith("Let me think")
    assert items[1]["text"] == "The party is in the woods.", "reasoning_content variant handled"
    assert items[-1]["prompt_tokens"] == 120 and items[-1]["cost"] == 0.0021


def test_agent_turn_surfaces_reasoning_and_usage(mock_llm):
    async def collect():
        out = []
        async for ev in openrouter.chat_completion_agent_turn(
            api_key="k", model_id="m", messages=[], temperature=0.7, max_tokens=100,
        ):
            out.append(ev)
        return out
    events = run(collect())
    assert [e["type"] for e in events] == ["reasoning", "reasoning", "content", "content", "result"]
    result = events[-1]
    assert result["content"] == "The trees close in."
    assert result["usage"]["completion_tokens"] == 30
    assert result["usage"]["cost"] == 0.0021


def test_stream_with_retry_forwards_events(mock_llm):
    def make():
        return openrouter.chat_completion_stream(
            api_key="k", model_id="m", messages=[], temperature=0.7, max_tokens=100,
            yield_events=True,
        )

    async def collect():
        out = []
        async for ev in openrouter.stream_with_retry(make, 0):
            out.append(ev)
        return out
    events = run(collect())
    assert [e["type"] for e in events] == ["reasoning", "reasoning", "chunk", "chunk", "usage"]


def test_settings_round_trip_reasoning_effort(client):
    current = client.get("/api/settings/openrouter").json()
    payload = {**{k: v for k, v in current.items() if not k.endswith("KeySet")}, "reasoningEffort": "high"}
    res = client.put("/api/settings/openrouter", json=payload)
    assert res.status_code == 200, res.text
    assert res.json()["reasoningEffort"] == "high"
    # Bogus values are stored as '' (provider default).
    payload["reasoningEffort"] = "maximum-overdrive"
    assert client.put("/api/settings/openrouter", json=payload).json()["reasoningEffort"] == ""


def test_usage_fields_round_trip_on_messages(client):
    client.post("/api/adventures", json={"name": "Usage Test"})
    from sqlalchemy import select

    from server.db.database import new_session
    from server.db.models import ChatMessage

    async def seed():
        async with new_session() as s:
            s.add(ChatMessage(role="assistant", content="A beat.", turn_number=1, variant=0,
                              mode="narrator", prompt_tokens=1200, completion_tokens=340, gen_cost=0.004))
            await s.commit()
    run(seed())
    msgs = client.get("/api/chat/messages").json()
    m = next(m for m in msgs if m["role"] == "assistant")
    assert m["promptTokens"] == 1200 and m["completionTokens"] == 340
    assert abs(m["cost"] - 0.004) < 1e-9
