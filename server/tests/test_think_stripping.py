"""Inline ``<think>…</think>`` stripping.

Some DeepSeek deployments emit chain-of-thought inline in ``delta.content``
instead of a dedicated reasoning field; left alone it renders as narration and
then the real answer follows (the "write, delete, rewrite" artifact). The stream
parsers route a leading think block to the reasoning channel instead.
"""

import json

import httpx

from server.ai import openrouter
from server.ai.openrouter import _ThinkStripper
from server.tests.conftest import run


# ── Unit: the stateful stripper ──────────────────────────────────

def _feed_all(chunks: list[str]) -> tuple[str, str]:
    s = _ThinkStripper()
    vis, rea = [], []
    for c in chunks:
        v, r = s.feed(c)
        vis.append(v)
        rea.append(r)
    v, r = s.flush()
    vis.append(v)
    rea.append(r)
    return "".join(vis), "".join(rea)


def test_passthrough_when_no_think_tags():
    vis, rea = _feed_all(["The door ", "creaks open."])
    assert vis == "The door creaks open."
    assert rea == ""


def test_leading_think_block_in_one_chunk():
    vis, rea = _feed_all(["<think>plan the scene</think>The door creaks open."])
    assert vis == "The door creaks open."
    assert rea == "plan the scene"


def test_think_open_tag_split_across_deltas():
    # The opening tag itself arrives in fragments.
    vis, rea = _feed_all(["<th", "ink>hmm", "</think>", "Real narration."])
    assert vis == "Real narration."
    assert rea == "hmm"


def test_close_tag_split_across_deltas():
    vis, rea = _feed_all(["<think>weighing it </thi", "nk>Narration here."])
    assert vis == "Narration here."
    assert rea == "weighing it "


def test_leading_whitespace_before_think():
    vis, rea = _feed_all(["\n  <think>x</think>Beat."])
    assert vis.strip() == "Beat."
    assert rea == "x"


def test_non_leading_think_is_literal():
    # Once real content has streamed, a later <think> is ordinary prose.
    vis, rea = _feed_all(["She frowned. <think>odd</think> He left."])
    assert vis == "She frowned. <think>odd</think> He left."
    assert rea == ""


def test_incomplete_partial_tag_is_flushed_as_visible():
    # A trailing "<" that never becomes <think> must not be swallowed.
    vis, rea = _feed_all(["All done. <"])
    assert vis == "All done. <"
    assert rea == ""


# ── Integration: through the real SSE parsers ────────────────────

def _sse(chunks: list[dict]) -> bytes:
    return ("".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n").encode()


def _mock(monkeypatch, chunks: list[dict]):
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_sse(chunks),
                              headers={"content-type": "text/event-stream"})
    mock = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(openrouter, "_shared_client", mock)
    return mock


def test_stream_events_route_inline_think_to_reasoning(monkeypatch):
    chunks = [
        {"choices": [{"delta": {"content": "<think>let me consider</think>The gate opens."}}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}]},
    ]
    _mock(monkeypatch, chunks)

    async def _collect():
        out = []
        async for ev in openrouter.chat_completion_stream(
            "k", "m", [{"role": "user", "content": "hi"}], 0.7, 100, yield_events=True,
        ):
            out.append(ev)
        return out

    events = run(_collect())
    content = "".join(e["text"] for e in events if e["type"] == "content")
    reasoning = "".join(e["text"] for e in events if e["type"] == "reasoning")
    assert content == "The gate opens."
    assert reasoning == "let me consider"


def test_stream_plain_mode_drops_inline_think(monkeypatch):
    chunks = [
        {"choices": [{"delta": {"content": "<think>hmm</think>Just the prose."}}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}]},
    ]
    _mock(monkeypatch, chunks)

    async def _collect():
        return [c async for c in openrouter.chat_completion_stream(
            "k", "m", [{"role": "user", "content": "hi"}], 0.7, 100,
        )]

    assert "".join(run(_collect())) == "Just the prose."


def test_agent_turn_strips_inline_think_from_result(monkeypatch):
    chunks = [
        {"choices": [{"delta": {"content": "<think>route</think>You step inside."}}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}]},
    ]
    _mock(monkeypatch, chunks)

    async def _collect():
        return [ev async for ev in openrouter.chat_completion_agent_turn(
            "k", "m", [{"role": "user", "content": "hi"}], 0.7, 100,
        )]

    events = run(_collect())
    result = next(e for e in events if e["type"] == "result")
    assert result["content"] == "You step inside."
    reasoning = "".join(e["text"] for e in events if e["type"] == "reasoning")
    assert reasoning == "route"
