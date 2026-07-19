"""Reasoning-budget recovery: when a reasoning model spends its whole response
budget thinking and writes no narration, the narrator retries ONCE with reasoning
disabled instead of surfacing a hard error."""

import json

import httpx
import pytest

from server.ai import openrouter
from server.ai.narrator_agent import run_narrator_agent
from server.api import chat
from server.tests.conftest import run


# ── Unit: the request builder can disable reasoning ───────────────

def test_apply_sampling_reasoning_off_disables():
    body: dict = {}
    openrouter._apply_sampling(body, None, None, None, None, None, None, reasoning_effort="off")
    assert body["reasoning"] == {"enabled": False}

    # low/medium/high still map to effort; strict providers omit reasoning entirely.
    body2: dict = {}
    openrouter._apply_sampling(body2, None, None, None, None, None, None, reasoning_effort="low")
    assert body2["reasoning"] == {"effort": "low"}

    body3: dict = {}
    openrouter._apply_sampling(body3, None, None, None, None, None, None,
                               openai_strict=True, reasoning_effort="off")
    assert "reasoning" not in body3

    body4: dict = {}
    openrouter._apply_sampling(body4, None, None, None, None, None, None, reasoning_effort=None)
    assert "reasoning" not in body4


# ── Isolated: the shared prose-stream recovery helper ─────────────

def test_drive_prose_stream_recovers_without_reasoning():
    seen: list = []

    def make_stream(reasoning=None):
        seen.append(reasoning)

        async def gen():
            if reasoning == "off":
                yield {"type": "chunk", "text": "The door creaks open."}
                yield {"type": "usage", "completion_tokens": 5}
            else:
                # Reasoning model burns the whole budget thinking — no content.
                yield {"type": "reasoning", "text": "thinking hard about the scene"}

        return gen()

    async def _collect():
        out = []
        async for ev in chat._drive_prose_stream(make_stream, 0, " test"):
            out.append(ev)
        return out

    outs = run(_collect())
    kinds = [o["kind"] for o in outs]
    assert "retry" in kinds, "should signal a retry before recovering"
    done = next(o for o in outs if o["kind"] == "done")
    assert done["text"] == "The door creaks open."
    assert done["reasoning_seen"] is True
    # First attempt with the configured effort (None), recovery with reasoning off.
    assert seen == [None, "off"]


def test_drive_prose_stream_no_recovery_when_content_present():
    seen: list = []

    def make_stream(reasoning=None):
        seen.append(reasoning)

        async def gen():
            yield {"type": "reasoning", "text": "a little thinking"}
            yield {"type": "chunk", "text": "It works."}

        return gen()

    async def _collect():
        return [ev async for ev in chat._drive_prose_stream(make_stream, 0, " test")]

    outs = run(_collect())
    assert not any(o["kind"] == "retry" for o in outs)
    assert next(o for o in outs if o["kind"] == "done")["text"] == "It works."
    assert seen == [None]  # only one call — no recovery needed


# ── Integration: the agentic narrator loop recovers ───────────────

def _sse(chunks: list[dict]) -> bytes:
    return ("".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n").encode()

_BUDGET_EATEN = [
    {"choices": [{"delta": {"reasoning": "thinking hard about what happens next..."}}]},
    {"choices": [{"delta": {}, "finish_reason": "length"}]},
    {"choices": [], "usage": {"prompt_tokens": 100, "completion_tokens": 200, "total_tokens": 300}},
]
_NARRATION = [
    {"choices": [{"delta": {"content": "The door creaks open."}}]},
    {"choices": [{"delta": {}, "finish_reason": "stop"}]},
    {"choices": [], "usage": {"prompt_tokens": 100, "completion_tokens": 8, "total_tokens": 108}},
]


def test_agent_recovers_from_reasoning_budget(client, monkeypatch):
    """First model call burns the budget on reasoning (finish_reason=length, no
    content); the loop must retry with reasoning disabled and get narration."""
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        eaten = body.get("reasoning") != {"enabled": False}
        return httpx.Response(200, content=_sse(_BUDGET_EATEN if eaten else _NARRATION),
                              headers={"content-type": "text/event-stream"})

    mock = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(openrouter, "_shared_client", mock)

    from types import SimpleNamespace
    settings = SimpleNamespace(
        llm_provider="openrouter", api_key="test", model_id="test-model",
        temperature=0.7, top_p=1.0, min_p=0.0, top_k=0,
        frequency_penalty=0.0, presence_penalty=0.0, repetition_penalty=1.0,
        max_tokens_response=1000, max_tool_rounds=6,
        reasoning_effort="", auto_retry_count=0,
    )

    async def _collect():
        out = []
        async for ev in run_narrator_agent(
            settings=settings,
            base_messages=[{"role": "system", "content": "Be the narrator."},
                           {"role": "user", "content": "I open the door."}],
            current_turn=1,
            dice_enabled=False,
        ):
            out.append(ev)
        return out

    events = run(_collect())
    run(mock.aclose())

    types = [e["type"] for e in events]
    assert "retry" in types, "the loop should emit a retry when reasoning ate the budget"
    content = "".join(e["text"] for e in events if e["type"] == "content")
    assert content == "The door creaks open."
    final = next(e for e in events if e["type"] == "final")
    assert final["content"] == "The door creaks open."
    # Two calls: the budget-eaten one, then the reasoning-disabled recovery.
    assert len(requests) == 2
    assert requests[0].get("reasoning") != {"enabled": False}
    assert requests[1].get("reasoning") == {"enabled": False}
