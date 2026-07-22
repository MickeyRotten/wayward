"""Agentic-loop preamble handling and malformed-arg repair.

DeepSeek-family models often narrate the whole beat and only then append a
state-write tool call. The loop accepts that beat instead of discarding and
regenerating it (the write->delete->rewrite artifact), but only for safe state
writes — a skill_check / read tool still forces a clean re-narration. Malformed
tool arguments are reported back for the model to resend.
"""

import json
from types import SimpleNamespace

import httpx

from server.ai import openrouter
from server.ai.narrator_agent import run_narrator_agent
from server.tests.conftest import run

_LONG_BEAT = "The heavy oak door groans inward, revealing a torch-lit hall beyond."


def _sse(chunks: list[dict]) -> bytes:
    return ("".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n").encode()


def _tool_call_sse(name: str, arguments: str, preamble: str = "") -> list[dict]:
    chunks: list[dict] = []
    if preamble:
        chunks.append({"choices": [{"delta": {"content": preamble}}]})
    chunks.append({"choices": [{"delta": {"tool_calls": [
        {"index": 0, "id": "call_1", "type": "function",
         "function": {"name": name, "arguments": arguments}}
    ]}}]})
    chunks.append({"choices": [{"delta": {}, "finish_reason": "tool_calls"}]})
    return chunks


def _narration_sse(text: str) -> list[dict]:
    return [
        {"choices": [{"delta": {"content": text}}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}]},
    ]


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        llm_provider="openrouter", api_key="test", model_id="test-model",
        temperature=0.7, top_p=1.0, min_p=0.0, top_k=0,
        frequency_penalty=0.0, presence_penalty=0.0, repetition_penalty=1.0,
        max_tokens_response=1000, max_tool_rounds=6,
        reasoning_effort="", auto_retry_count=0,
    )


def _run(monkeypatch, responses: list[list[dict]]):
    """Serve each SSE response in order; return (events, request_count)."""
    state = {"n": 0}

    def handler(_req: httpx.Request) -> httpx.Response:
        i = min(state["n"], len(responses) - 1)
        state["n"] += 1
        return httpx.Response(200, content=_sse(responses[i]),
                              headers={"content-type": "text/event-stream"})

    mock = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(openrouter, "_shared_client", mock)

    async def _collect():
        out = []
        async for ev in run_narrator_agent(
            settings=_settings(),
            base_messages=[{"role": "system", "content": "Narrate."},
                           {"role": "user", "content": "I open the door."}],
            current_turn=1,
            dice_enabled=False,
        ):
            out.append(ev)
        return out

    events = run(_collect())
    run(mock.aclose())
    return events, state["n"]


def test_substantial_preamble_with_safe_write_is_kept(client, monkeypatch):
    # One response: full beat + set_scene. The loop should keep the beat and stop.
    events, calls = _run(monkeypatch, [
        _tool_call_sse("set_scene", '{"location": "Torch-lit Hall"}', preamble=_LONG_BEAT),
    ])
    assert calls == 1, "should not make a second (re-narration) call"
    assert not any(e["type"] == "discard" for e in events), "beat must not be discarded"
    final = next(e for e in events if e["type"] == "final")
    assert final["content"] == _LONG_BEAT
    assert final["scene"].get("location") == "Torch-lit Hall"


def test_short_preamble_is_discarded_and_regenerated(client, monkeypatch):
    # Too-short content is treated as throwaway preamble → discard + re-narrate.
    events, calls = _run(monkeypatch, [
        _tool_call_sse("set_scene", '{"location": "Hall"}', preamble="Okay."),
        _narration_sse(_LONG_BEAT),
    ])
    assert calls == 2
    assert any(e["type"] == "discard" for e in events)
    assert next(e for e in events if e["type"] == "final")["content"] == _LONG_BEAT


def test_read_tool_forces_clean_renarration(client, monkeypatch):
    # A read tool (not a safe write) alongside a beat still forces re-narration.
    events, calls = _run(monkeypatch, [
        _tool_call_sse("lookup_item", '{"name": "Sword"}', preamble=_LONG_BEAT),
        _narration_sse("A rusted blade, nothing more."),
    ])
    assert calls == 2
    assert any(e["type"] == "discard" for e in events)
    assert next(e for e in events if e["type"] == "final")["content"] == "A rusted blade, nothing more."


def test_malformed_tool_args_are_reported_for_resend(client, monkeypatch):
    events, calls = _run(monkeypatch, [
        _tool_call_sse("grant_item", "{not valid json"),
        _narration_sse(_LONG_BEAT),
    ])
    assert calls == 2
    repair = [e for e in events if e["type"] == "tool" and not e.get("ok", True)]
    assert repair, "a failed tool event should surface the malformed-args error"
    assert "not valid JSON" in repair[0]["result"]
    assert next(e for e in events if e["type"] == "final")["content"] == _LONG_BEAT
