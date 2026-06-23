import json
import time
from collections.abc import AsyncGenerator

import httpx

OPENROUTER_BASE = "https://openrouter.ai/api/v1"

_model_cache: dict[str, tuple[float, list[dict]]] = {}
MODEL_CACHE_TTL = 300  # 5 minutes


async def fetch_models(api_key: str) -> list[dict]:
    now = time.time()
    cached = _model_cache.get(api_key)
    if cached and now - cached[0] < MODEL_CACHE_TTL:
        return cached[1]

    async with httpx.AsyncClient() as client:
        res = await client.get(
            f"{OPENROUTER_BASE}/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30,
        )
        res.raise_for_status()

    data = res.json().get("data", [])
    models = [
        {
            "id": m["id"],
            "name": m.get("name", m["id"]),
            "contextLength": m.get("context_length", 0),
        }
        for m in data
    ]
    models.sort(key=lambda m: m["name"])
    _model_cache[api_key] = (now, models)
    return models


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
    # Forward optional sampling params only when set to a meaningful (non-no-op)
    # value, so default settings don't constrain providers that reject e.g.
    # top_k=0. OpenRouter passes these through to the underlying model.
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
