import asyncio
import json
import time
from collections.abc import AsyncGenerator

import httpx

OPENROUTER_BASE = "https://openrouter.ai/api/v1"

# Transient statuses worth retrying once or twice (rate limit / provider hiccup).
_RETRY_STATUSES = {429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 3


def _retry_delay(res, attempt: int) -> float:
    """Backoff before a retry: honor Retry-After if present, else exponential."""
    if res is not None:
        ra = res.headers.get("retry-after")
        if ra:
            try:
                return min(float(ra), 10.0)
            except ValueError:
                pass
    return min(0.5 * (2 ** attempt), 8.0)

_model_cache: dict[str, tuple[float, list[dict]]] = {}
MODEL_CACHE_TTL = 300  # 5 minutes

# One shared client for every OpenRouter call (narrator rounds, Chronicler,
# suggester, vision, summaries) — connection pooling / TLS keep-alive instead
# of a fresh handshake per call. Closed via close_client() on app shutdown.
_shared_client: httpx.AsyncClient | None = None


def _client() -> httpx.AsyncClient:
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        _shared_client = httpx.AsyncClient(timeout=180)
    return _shared_client


async def close_client() -> None:
    if _shared_client is not None and not _shared_client.is_closed:
        await _shared_client.aclose()


async def fetch_models(api_key: str = "") -> list[dict]:
    # OpenRouter's /models endpoint is public; the key is optional. Cache under a
    # stable key so the keyless list is reused too.
    now = time.time()
    cache_key = api_key or "_public"
    cached = _model_cache.get(cache_key)
    if cached and now - cached[0] < MODEL_CACHE_TTL:
        return cached[1]

    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    res = await _client().get(
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
            # Image input capability (for the vision agent's model picker).
            "supportsImages": "image" in ((m.get("architecture") or {}).get("input_modalities") or []),
        }
        for m in data
    ]
    models.sort(key=lambda m: m["name"])
    _model_cache[cache_key] = (now, models)
    return models


async def chat_completion_text(
    api_key: str,
    model_id: str,
    messages: list[dict],
    temperature: float = 0.2,
    max_tokens: int = 500,
) -> str:
    """One plain, non-streaming completion; returns the assistant text.

    Used by the vision agent (image description) — message ``content`` may be
    the OpenAI multi-part shape (text + image_url parts).
    """
    body = {
        "model": model_id,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    client = _client()
    for attempt in range(_MAX_ATTEMPTS):
        res = await client.post(
            f"{OPENROUTER_BASE}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=120,
        )
        if res.status_code in _RETRY_STATUSES and attempt < _MAX_ATTEMPTS - 1:
            await asyncio.sleep(_retry_delay(res, attempt))
            continue
        if res.status_code >= 400:
            try:
                msg = _error_text(res.json().get("error", {}))
            except Exception:
                msg = f"{res.status_code} {res.reason_phrase}"
            raise RuntimeError(f"Model error: {msg}")
        data = res.json()
        if data.get("error"):
            raise RuntimeError(f"Model error: {_error_text(data['error'])}")
        return ((data.get("choices") or [{}])[0].get("message", {}).get("content") or "").strip()
    raise RuntimeError("Model error: retries exhausted")


def _error_text(err) -> str:
    if isinstance(err, dict):
        meta = err.get("metadata") or {}
        raw = meta.get("raw") if isinstance(meta, dict) else None
        return err.get("message") or (str(raw) if raw else "") or json.dumps(err)
    return str(err)


async def _raise_on_http_error(res) -> None:
    """On a non-2xx streaming response, read the body and raise with the real
    provider/error message (so it can be surfaced to the player)."""
    if res.status_code < 400:
        return
    try:
        body = await res.aread()
        data = json.loads(body)
        msg = _error_text(data.get("error", data))
    except Exception:
        msg = f"{res.status_code} {res.reason_phrase}"
    raise RuntimeError(f"Model error: {msg}")


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

    client = _client()
    for attempt in range(_MAX_ATTEMPTS):
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
            # Retry transient failures before any content is streamed.
            if res.status_code in _RETRY_STATUSES and attempt < _MAX_ATTEMPTS - 1:
                await res.aread()
                await asyncio.sleep(_retry_delay(res, attempt))
                continue
            await _raise_on_http_error(res)
            async for line in res.aiter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[6:]
                if payload.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                if isinstance(chunk, dict) and chunk.get("error"):
                    raise RuntimeError(f"Model error: {_error_text(chunk['error'])}")
                try:
                    choice = chunk["choices"][0]
                except (KeyError, IndexError):
                    continue
                if choice.get("finish_reason") == "content_filter":
                    raise RuntimeError("The model's safety filter blocked this response.")
                content = (choice.get("delta") or {}).get("content", "")
                if content:
                    yield content
            return


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

    client = _client()
    for attempt in range(_MAX_ATTEMPTS):
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
            # Retry transient failures before any content is streamed.
            if res.status_code in _RETRY_STATUSES and attempt < _MAX_ATTEMPTS - 1:
                await res.aread()
                await asyncio.sleep(_retry_delay(res, attempt))
                continue
            await _raise_on_http_error(res)
            async for line in res.aiter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[6:]
                if payload.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                if isinstance(chunk, dict) and chunk.get("error"):
                    raise RuntimeError(f"Model error: {_error_text(chunk['error'])}")
                try:
                    choice = chunk["choices"][0]
                except (KeyError, IndexError):
                    continue

                if choice.get("finish_reason"):
                    finish_reason = choice["finish_reason"]
                    if finish_reason == "content_filter":
                        raise RuntimeError("The model's safety filter blocked this response.")

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
            break  # streamed successfully; stop retrying

    tool_calls = [tool_acc[i] for i in sorted(tool_acc)]
    yield {
        "type": "result",
        "content": "".join(content_parts),
        "tool_calls": tool_calls,
        "finish_reason": finish_reason,
    }
