import json
import time
from collections.abc import AsyncGenerator

import httpx

OPENROUTER_BASE = "https://openrouter.ai/api/v1"

_model_cache: dict[str, tuple[float, list[dict]]] = {}
MODEL_CACHE_TTL = 300  # 5 minutes


async def fetch_models(api_key: str = "") -> list[dict]:
    # OpenRouter's /models endpoint is public; the key is optional. Cache under a
    # stable key so the keyless list is reused too.
    now = time.time()
    cache_key = api_key or "_public"
    cached = _model_cache.get(cache_key)
    if cached and now - cached[0] < MODEL_CACHE_TTL:
        return cached[1]

    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    async with httpx.AsyncClient() as client:
        res = await client.get(
            f"{OPENROUTER_BASE}/models",
            headers=headers,
            timeout=30,
        )
        res.raise_for_status()

    data = res.json().get("data", [])
    models = [
        {
            "id": m["id"],
            "name": m.get("name", m["id"]),
            "contextLength": m.get("context_length", 0),
            # OpenRouter exposes per-model capabilities in supported_parameters;
            # "tools" means the model can do function/tool calling (required for
            # the agentic narrator loop).
            "supportsTools": "tools" in (m.get("supported_parameters") or []),
        }
        for m in data
    ]
    models.sort(key=lambda m: m["name"])
    _model_cache[cache_key] = (now, models)
    return models


def _apply_sampling(
    body: dict,
    top_p: float | None,
    min_p: float | None,
    top_k: int | None,
    frequency_penalty: float | None,
    presence_penalty: float | None,
    repetition_penalty: float | None,
) -> None:
    """Forward optional sampling params only when set to a meaningful (non-no-op)
    value, so default settings don't constrain providers that reject e.g.
    top_k=0. OpenRouter passes these through to the underlying model."""
    if top_p is not None and top_p < 1.0:
        body["top_p"] = top_p
    if min_p is not None and min_p > 0:
        body["min_p"] = min_p
    if top_k is not None and top_k > 0:
        body["top_k"] = top_k
    if frequency_penalty:
        body["frequency_penalty"] = frequency_penalty
    if presence_penalty:
        body["presence_penalty"] = presence_penalty
    if repetition_penalty is not None and repetition_penalty != 1.0:
        body["repetition_penalty"] = repetition_penalty


async def chat_completion_stream(
    api_key: str,
    model_id: str,
    messages: list[dict],
    temperature: float,
    max_tokens: int,
    top_p: float | None = None,
    min_p: float | None = None,
    top_k: int | None = None,
    frequency_penalty: float | None = None,
    presence_penalty: float | None = None,
    repetition_penalty: float | None = None,
) -> AsyncGenerator[str, None]:
    body: dict = {
        "model": model_id,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": True,
    }
    _apply_sampling(body, top_p, min_p, top_k, frequency_penalty, presence_penalty, repetition_penalty)

    async with httpx.AsyncClient() as client:
        async with client.stream(
            "POST",
            f"{OPENROUTER_BASE}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=120,
        ) as res:
            res.raise_for_status()
            async for line in res.aiter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[6:]
                if payload.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(payload)
                    delta = chunk["choices"][0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        yield content
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue


async def chat_completion_agent_turn(
    api_key: str,
    model_id: str,
    messages: list[dict],
    temperature: float,
    max_tokens: int,
    tools: list[dict] | None = None,
    tool_choice: str = "auto",
    top_p: float | None = None,
    min_p: float | None = None,
    top_k: int | None = None,
    frequency_penalty: float | None = None,
    presence_penalty: float | None = None,
    repetition_penalty: float | None = None,
) -> AsyncGenerator[dict, None]:
    """One streaming model turn with tool calling.

    Yields content deltas as ``{"type": "content", "text": ...}`` while they
    arrive, then a single terminal ``{"type": "result", "content": <full text>,
    "tool_calls": [...], "finish_reason": ...}``. Tool-call argument fragments
    are accumulated by index into the OpenAI/OpenRouter tool-call shape.
    """
    body: dict = {
        "model": model_id,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": True,
    }
    if tools:
        body["tools"] = tools
        body["tool_choice"] = tool_choice
    _apply_sampling(body, top_p, min_p, top_k, frequency_penalty, presence_penalty, repetition_penalty)

    content_parts: list[str] = []
    tool_acc: dict[int, dict] = {}
    finish_reason: str | None = None

    async with httpx.AsyncClient() as client:
        async with client.stream(
            "POST",
            f"{OPENROUTER_BASE}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=180,
        ) as res:
            res.raise_for_status()
            async for line in res.aiter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[6:]
                if payload.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(payload)
                    choice = chunk["choices"][0]
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue

                if choice.get("finish_reason"):
                    finish_reason = choice["finish_reason"]

                delta = choice.get("delta", {})
                content = delta.get("content")
                if content:
                    content_parts.append(content)
                    yield {"type": "content", "text": content}

                for tc in delta.get("tool_calls") or []:
                    idx = tc.get("index", 0)
                    acc = tool_acc.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                    if tc.get("id"):
                        acc["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        acc["name"] = fn["name"]
                    if fn.get("arguments"):
                        acc["arguments"] += fn["arguments"]

    tool_calls = [tool_acc[i] for i in sorted(tool_acc)]
    yield {
        "type": "result",
        "content": "".join(content_parts),
        "tool_calls": tool_calls,
        "finish_reason": finish_reason,
    }
