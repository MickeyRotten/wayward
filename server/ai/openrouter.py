import asyncio
import json
import time
from collections.abc import AsyncGenerator

import httpx

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
# NVIDIA NIM's hosted API is OpenAI-compatible — same streaming/tool-call shape
# as OpenRouter, so it reuses every function here; only the base URL + key differ.
NVIDIA_NIM_BASE = "https://integrate.api.nvidia.com/v1"
NIM_DEFAULT_MODEL = "deepseek-ai/deepseek-v4-pro"


def provider_endpoint(settings) -> tuple[str, str, str]:
    """Resolve the active LLM provider to ``(base_url, api_key, main_model_id)``.

    All three providers are OpenAI-compatible; only these three values change.
    'openrouter' (default) keeps the original api_key/model_id; 'nvidia_nim' and
    'custom' carry their own credential + model (custom also its own base URL)."""
    provider = (getattr(settings, "llm_provider", "") or "openrouter")
    if provider == "nvidia_nim":
        return (NVIDIA_NIM_BASE,
                getattr(settings, "nim_api_key", "") or "",
                getattr(settings, "nim_model_id", "") or "")
    if provider == "custom":
        base = (getattr(settings, "custom_base_url", "") or "").rstrip("/") or OPENROUTER_BASE
        return (base,
                getattr(settings, "custom_api_key", "") or "",
                getattr(settings, "custom_model_id", "") or "")
    return (OPENROUTER_BASE, settings.api_key or "", settings.model_id or "")


def is_openrouter(base_url: str) -> bool:
    """OpenRouter accepts the extra sampling params (min_p/top_k/repetition_penalty)
    and returns rich model metadata; other OpenAI-compatible providers may not."""
    return base_url.rstrip("/") == OPENROUTER_BASE

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


async def fetch_models(api_key: str = "", base_url: str = OPENROUTER_BASE) -> list[dict]:
    """List the provider's models in the normalized shape
    ``{id, name, contextLength, supportsTools, supportsImages}``.

    OpenRouter's ``/models`` is public + rich (capabilities in
    ``supported_parameters``/``architecture``). Other OpenAI-compatible providers
    (NVIDIA NIM, custom) return a plain ``{data:[{id}]}`` with no capability
    metadata, so their models are marked tool-capable (NIM supports tool calling;
    vision keeps its own model picker)."""
    now = time.time()
    cache_key = f"{base_url}|{api_key or '_public'}"
    cached = _model_cache.get(cache_key)
    if cached and now - cached[0] < MODEL_CACHE_TTL:
        return cached[1]

    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    res = await _client().get(f"{base_url}/models", headers=headers, timeout=30)
    res.raise_for_status()
    data = res.json().get("data", [])

    if is_openrouter(base_url):
        models = [
            {
                "id": m["id"],
                "name": m.get("name", m["id"]),
                "contextLength": m.get("context_length", 0),
                # "tools" in supported_parameters => function/tool calling (needed
                # for the agentic narrator loop); image => vision picker capable.
                "supportsTools": "tools" in (m.get("supported_parameters") or []),
                "supportsImages": "image" in ((m.get("architecture") or {}).get("input_modalities") or []),
            }
            for m in data
        ]
    else:
        # Plain OpenAI-compatible list (id only). NIM/custom models are assumed
        # tool-capable; context length is unknown (client only uses it to prefill).
        models = [
            {
                "id": m["id"],
                "name": m.get("id", ""),
                "contextLength": int(m.get("context_length") or 0),
                "supportsTools": True,
                "supportsImages": False,
            }
            for m in data if m.get("id")
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
    base_url: str = OPENROUTER_BASE,
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
            f"{base_url}/chat/completions",
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
    openai_strict: bool = False,
    reasoning_effort: str | None = None,
) -> None:
    """Forward optional sampling params only when set to a meaningful (non-no-op)
    value, so default settings don't constrain providers that reject e.g.
    top_k=0. OpenRouter passes its superset through to the underlying model; when
    ``openai_strict`` (NVIDIA NIM / custom endpoints) only the OpenAI-standard
    params are sent — min_p/top_k/repetition_penalty (and the OpenRouter
    ``reasoning``/``usage`` extensions) would be rejected."""
    if top_p is not None and top_p < 1.0:
        body["top_p"] = top_p
    if frequency_penalty:
        body["frequency_penalty"] = frequency_penalty
    if presence_penalty:
        body["presence_penalty"] = presence_penalty
    if openai_strict:
        return
    if min_p is not None and min_p > 0:
        body["min_p"] = min_p
    if top_k is not None and top_k > 0:
        body["top_k"] = top_k
    if repetition_penalty is not None and repetition_penalty != 1.0:
        body["repetition_penalty"] = repetition_penalty
    # Reasoning effort for reasoning-capable models (OpenRouter extension).
    # The "off" sentinel explicitly DISABLES reasoning (used by the narrator's
    # recovery when a model spent its whole budget thinking and wrote nothing) —
    # this frees the entire response budget for narration.
    if reasoning_effort in ("low", "medium", "high"):
        body["reasoning"] = {"effort": reasoning_effort}
    elif reasoning_effort == "off":
        body["reasoning"] = {"enabled": False}
    # Ask for real token/cost accounting in the final stream chunk.
    body["usage"] = {"include": True}


def _delta_reasoning(delta: dict) -> str:
    """Reasoning text from a stream delta — OpenRouter normalizes to
    ``reasoning``; some OpenAI-compatible providers (DeepSeek-style) send
    ``reasoning_content``."""
    return delta.get("reasoning") or delta.get("reasoning_content") or ""


_THINK_OPEN = "<think>"
_THINK_CLOSE = "</think>"


def _partial_suffix(text: str, marker: str) -> int:
    """Longest k (0 < k < len(marker)) such that ``text`` ends with ``marker[:k]``
    — i.e. a marker possibly split across streaming deltas. 0 if none."""
    for k in range(min(len(text), len(marker) - 1), 0, -1):
        if text.endswith(marker[:k]):
            return k
    return 0


class _ThinkStripper:
    """Split a content stream into visible narration and inline
    ``<think>…</think>`` reasoning, tolerant of a tag split across deltas.

    Some DeepSeek deployments (self-hosted vLLM/SGLang behind the custom/NIM
    providers, or providers without a reasoning parser) emit chain-of-thought
    *inline* in ``delta.content`` instead of a dedicated ``reasoning`` field.
    Left alone it renders as narration and then the real answer follows, which
    reads as the model writing a reply, deleting it, and rewriting it. This
    routes a **leading** think block to the reasoning channel instead.

    Only a leading block (optionally after whitespace) is stripped — once real
    visible content has streamed, a later ``<think>`` is treated as literal text,
    so ordinary prose containing the token is never mangled. Providers that use a
    real reasoning field never emit these tags, so this is a passthrough there.
    """

    def __init__(self) -> None:
        self._in_think = False
        self._closed = False  # leading block consumed or real content seen
        self._buf = ""        # a partial tag held across a delta boundary

    def feed(self, s: str) -> tuple[str, str]:
        """Consume one content delta → ``(visible, reasoning)``."""
        text = self._buf + s
        self._buf = ""
        vis: list[str] = []
        rea: list[str] = []
        while text:
            if self._closed:
                vis.append(text)
                break
            if not self._in_think:
                i = text.find(_THINK_OPEN)
                if i != -1 and text[:i].strip() == "":
                    vis.append(text[:i])  # leading whitespace, harmless
                    text = text[i + len(_THINK_OPEN):]
                    self._in_think = True
                    continue
                hold = _partial_suffix(text, _THINK_OPEN)
                if hold and text[: len(text) - hold].strip() == "":
                    # still only whitespace before a possible tag — wait for more
                    vis.append(text[: len(text) - hold])
                    self._buf = text[len(text) - hold:]
                    break
                # real content precedes any tag — emit and lock out stripping
                vis.append(text)
                if text.strip():
                    self._closed = True
                break
            # inside the leading think block
            i = text.find(_THINK_CLOSE)
            if i != -1:
                rea.append(text[:i])
                text = text[i + len(_THINK_CLOSE):]
                self._in_think = False
                self._closed = True  # only the first block is stripped
                continue
            hold = _partial_suffix(text, _THINK_CLOSE)
            if hold:
                rea.append(text[: len(text) - hold])
                self._buf = text[len(text) - hold:]
            else:
                rea.append(text)
            break
        return "".join(vis), "".join(rea)

    def flush(self) -> tuple[str, str]:
        """Emit any held partial at stream end (the tag never completed)."""
        if not self._buf:
            return "", ""
        b, self._buf = self._buf, ""
        return ("", b) if self._in_think else (b, "")


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
    base_url: str = OPENROUTER_BASE,
    reasoning_effort: str | None = None,
    yield_events: bool = False,
) -> AsyncGenerator[str | dict, None]:
    """Stream one completion. Default: yields content strings (the original
    contract — summariser/continue callers unchanged). With ``yield_events``
    it yields dicts instead — ``{"type":"content"|"reasoning","text"}`` plus a
    terminal ``{"type":"usage", ...}`` when the provider reports usage — so a
    reasoning model's thinking phase is visible instead of a silent stall."""
    body: dict = {
        "model": model_id,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": True,
    }
    _apply_sampling(body, top_p, min_p, top_k, frequency_penalty, presence_penalty,
                    repetition_penalty, openai_strict=not is_openrouter(base_url),
                    reasoning_effort=reasoning_effort)

    client = _client()
    for attempt in range(_MAX_ATTEMPTS):
        usage: dict | None = None
        stripper = _ThinkStripper()
        async with client.stream(
            "POST",
            f"{base_url}/chat/completions",
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
                if isinstance(chunk, dict) and chunk.get("usage"):
                    usage = chunk["usage"]
                try:
                    choice = chunk["choices"][0]
                except (KeyError, IndexError):
                    continue
                if choice.get("finish_reason") == "content_filter":
                    raise RuntimeError("The model's safety filter blocked this response.")
                delta = choice.get("delta") or {}
                if yield_events:
                    reasoning = _delta_reasoning(delta)
                    if reasoning:
                        yield {"type": "reasoning", "text": reasoning}
                content = delta.get("content", "")
                if content:
                    vis, think = stripper.feed(content)
                    if think and yield_events:
                        yield {"type": "reasoning", "text": think}
                    if vis:
                        yield {"type": "content", "text": vis} if yield_events else vis
            # Flush any think-tag partial held across the final delta boundary.
            vis, think = stripper.flush()
            if think and yield_events:
                yield {"type": "reasoning", "text": think}
            if vis:
                yield {"type": "content", "text": vis} if yield_events else vis
            if yield_events and usage:
                yield {"type": "usage", **usage}
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
    base_url: str = OPENROUTER_BASE,
    reasoning_effort: str | None = None,
) -> AsyncGenerator[dict, None]:
    """One streaming model turn with tool calling.

    Yields content deltas as ``{"type": "content", "text": ...}`` (and reasoning
    deltas as ``{"type": "reasoning", "text": ...}`` for reasoning models) while
    they arrive, then a single terminal ``{"type": "result", "content": <full
    text>, "tool_calls": [...], "finish_reason": ..., "usage": <dict|None>}``.
    Tool-call argument fragments are accumulated by index into the
    OpenAI/OpenRouter tool-call shape.
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
    _apply_sampling(body, top_p, min_p, top_k, frequency_penalty, presence_penalty,
                    repetition_penalty, openai_strict=not is_openrouter(base_url),
                    reasoning_effort=reasoning_effort)

    content_parts: list[str] = []
    tool_acc: dict[int, dict] = {}
    finish_reason: str | None = None
    usage: dict | None = None

    client = _client()
    for attempt in range(_MAX_ATTEMPTS):
        stripper = _ThinkStripper()
        async with client.stream(
            "POST",
            f"{base_url}/chat/completions",
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
                if isinstance(chunk, dict) and chunk.get("usage"):
                    usage = chunk["usage"]
                try:
                    choice = chunk["choices"][0]
                except (KeyError, IndexError):
                    continue

                if choice.get("finish_reason"):
                    finish_reason = choice["finish_reason"]
                    if finish_reason == "content_filter":
                        raise RuntimeError("The model's safety filter blocked this response.")

                delta = choice.get("delta", {})
                reasoning = _delta_reasoning(delta)
                if reasoning:
                    yield {"type": "reasoning", "text": reasoning}
                content = delta.get("content")
                if content:
                    vis, think = stripper.feed(content)
                    if think:
                        yield {"type": "reasoning", "text": think}
                    if vis:
                        content_parts.append(vis)
                        yield {"type": "content", "text": vis}

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
            # Flush any think-tag partial held across the final delta boundary.
            vis, think = stripper.flush()
            if think:
                yield {"type": "reasoning", "text": think}
            if vis:
                content_parts.append(vis)
                yield {"type": "content", "text": vis}
            break  # streamed successfully; stop retrying

    tool_calls = [tool_acc[i] for i in sorted(tool_acc)]
    yield {
        "type": "result",
        "content": "".join(content_parts),
        "tool_calls": tool_calls,
        "finish_reason": finish_reason,
        "usage": usage,
    }


async def agent_turn_with_retry(
    make_stream, retries: int, *, log_ctx: str = ""
) -> AsyncGenerator[dict, None]:
    """Run one ``chat_completion_agent_turn`` stream with up to ``retries`` extra
    attempts on an error or safety-filter block (both raised as RuntimeError).

    ``make_stream`` is a zero-arg callable returning a FRESH agent-turn generator
    (so each attempt re-sends the same, unmutated ``messages`` — a failed attempt
    never appended tool results, so re-attempting can't re-run tools). Yields the
    underlying ``content``/``result`` events; when an attempt streamed partial
    content before failing, yields ``{"type":"discard"}`` so the client clears it;
    before each retry yields ``{"type":"retry","attempt","of"}``. Re-raises if all
    attempts fail."""
    import logging
    log = logging.getLogger("wayward.retry")
    attempt = 0
    while True:
        streamed = False
        try:
            async for ev in make_stream():
                if ev.get("type") == "content":
                    streamed = True
                yield ev
            return
        except Exception as e:  # noqa: BLE001 — surface after retries exhausted
            if attempt >= max(0, retries):
                raise
            attempt += 1
            if streamed:
                yield {"type": "discard"}
            yield {"type": "retry", "attempt": attempt, "of": max(0, retries)}
            log.warning("agent-turn retry %s/%s%s after: %s", attempt, retries, log_ctx, e)


async def stream_with_retry(
    make_stream, retries: int, *, log_ctx: str = ""
) -> AsyncGenerator[dict, None]:
    """Like ``agent_turn_with_retry`` but for ``chat_completion_stream``. Accepts
    both of its modes: plain str chunks become ``{"type":"chunk","text"}``;
    event dicts (``yield_events=True``) pass through with content mapped to
    ``chunk`` and reasoning/usage forwarded as-is. Yields ``{"type":"discard"}``
    when a failed attempt had streamed content, ``{"type":"retry",...}`` before
    a retry. Re-raises if all attempts fail."""
    import logging
    log = logging.getLogger("wayward.retry")
    attempt = 0
    while True:
        streamed = False
        try:
            async for item in make_stream():
                if isinstance(item, dict):
                    if item.get("type") == "content":
                        streamed = True
                        yield {"type": "chunk", "text": item["text"]}
                    else:  # reasoning / usage
                        yield item
                else:
                    streamed = True
                    yield {"type": "chunk", "text": item}
            return
        except Exception as e:  # noqa: BLE001
            if attempt >= max(0, retries):
                raise
            attempt += 1
            if streamed:
                yield {"type": "discard"}
            yield {"type": "retry", "attempt": attempt, "of": max(0, retries)}
            log.warning("stream retry %s/%s%s after: %s", attempt, retries, log_ctx, e)
