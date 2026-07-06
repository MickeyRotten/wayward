"""Lightweight text-to-speech via Chatterbox (optional dependency).

Voices are cloned zero-shot from a short (~10s) reference sample: the narrator's
sample lives in the campaign folder (``narrator-voice.<ext>``), each character's
in their character folder (``voice.<ext>``). No sample → Chatterbox's built-in
default voice.

The heavy stack (torch/chatterbox) is NEVER imported at module scope — the base
install has no ML dependencies, and this module must stay importable without
them (`pip install -r server/requirements-tts.txt` enables synthesis).

Synthesis is synchronous torch code, so it runs in a worker thread
(``asyncio.to_thread``) serialized by a lock; the event loop (chat SSE) is
never blocked. Finished audio is cached in ``DATA_DIR/tts-cache/<sha256>.wav``
keyed on (model, voice sample bytes, text) so replays and swiped-back variants
are free.
"""

import asyncio
import hashlib
import importlib.util
import json
import logging
import re
import threading
from pathlib import Path

from server.db import database as db

logger = logging.getLogger("wayward")

MAX_TTS_CHARS = 2000          # request-level cap (a chat segment is far smaller)
_MAX_CHUNK_CHARS = 300        # per-generation cap; Chatterbox tops out ~40s audio

_model = None
_model_name: str | None = None
_device: str | None = None
_load_error: str | None = None
_model_lock = threading.Lock()   # guards lazy load
_synth_lock = threading.Lock()   # serializes generation (one model, one GPU)


def cache_dir() -> Path:
    d = db.DATA_DIR / "tts-cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def is_installed() -> bool:
    return importlib.util.find_spec("chatterbox") is not None


def status() -> dict:
    """Cheap status snapshot — never triggers a model load."""
    return {
        "installed": is_installed(),
        "loaded": _model is not None,
        "device": _device,
        "error": _load_error,
    }


def preload() -> dict:
    """Force the model download/load and report the outcome. Used by the
    Install-TTS launcher to warm the Hugging Face cache up-front, so the first
    line spoken at runtime isn't a multi-minute wait. Never raises — a failed
    or absent install is reported through the returned status()."""
    if is_installed():
        try:
            _load_model()
        except Exception:
            pass  # _load_error is captured inside _load_model; status() reports it
    return status()


def _pick_device() -> str:
    import torch

    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _load_model():
    """Lazy singleton load (worker thread only). Failures are cached so a broken
    install reports through /tts/status instead of re-downloading forever."""
    global _model, _model_name, _device, _load_error
    with _model_lock:
        if _model is not None:
            return _model
        if _load_error is not None:
            raise RuntimeError(_load_error)
        try:
            import torch

            try:  # prefer the smaller/faster Turbo variant when the package ships it
                from chatterbox.tts_turbo import ChatterboxTurboTTS as _Cls  # type: ignore
                name = "chatterbox-turbo"
            except ImportError:
                from chatterbox.tts import ChatterboxTTS as _Cls
                name = "chatterbox"

            device = _pick_device()
            # Chatterbox checkpoints are saved CUDA-side; off-GPU loads need
            # map_location redirected or torch.load raises.
            orig_load = torch.load
            if device != "cuda":
                torch.load = lambda *a, **kw: orig_load(*a, **{**kw, "map_location": device})
            try:
                try:
                    model = _Cls.from_pretrained(device=device)
                except Exception:
                    if device != "mps":
                        raise
                    device = "cpu"  # MPS support is spotty — retry on CPU
                    model = _Cls.from_pretrained(device=device)
            finally:
                torch.load = orig_load

            _model, _model_name, _device = model, name, device
            logger.info("TTS model %s loaded on %s", name, device)
            return _model
        except Exception as e:  # noqa: BLE001 — anything here means "TTS unavailable"
            _load_error = f"{type(e).__name__}: {e}"
            logger.error("TTS model load failed: %s", _load_error)
            raise RuntimeError(_load_error) from e


def _split_sentences(text: str, max_chars: int = _MAX_CHUNK_CHARS) -> list[str]:
    """Split on sentence boundaries and greedily re-pack into <=max_chars chunks
    (hard-splitting any single monster sentence)."""
    parts = [p.strip() for p in re.split(r'(?<=[.!?…"”])\s+', text) if p.strip()]
    chunks: list[str] = []
    cur = ""
    for p in parts:
        while len(p) > max_chars:
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(p[:max_chars])
            p = p[max_chars:].strip()
        if not p:
            continue
        if cur and len(cur) + 1 + len(p) > max_chars:
            chunks.append(cur)
            cur = p
        else:
            cur = f"{cur} {p}" if cur else p
    if cur:
        chunks.append(cur)
    return chunks or [text[:max_chars]]


def _cache_key(text: str, voice_path: Path | None) -> str:
    voice = "default"
    if voice_path is not None:
        voice = hashlib.sha256(voice_path.read_bytes()).hexdigest()
    blob = json.dumps(
        {"model": _model_name or "chatterbox", "voice": voice, "text": text},
        ensure_ascii=False,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _synthesize_sync(text: str, voice_path: Path | None) -> tuple[str, bool]:
    """Generate (or reuse) the wav for text+voice; returns (filename, was_cached)."""
    with _synth_lock:
        model = _load_model()
        import torch
        import torchaudio

        key = _cache_key(text, voice_path)
        final = cache_dir() / f"{key}.wav"
        if final.exists():
            return final.name, True

        waves = []
        for chunk in _split_sentences(text):
            if voice_path is not None:
                wav = model.generate(chunk, audio_prompt_path=str(voice_path))
            else:
                wav = model.generate(chunk)
            waves.append(wav)
        full = torch.cat(waves, dim=-1) if len(waves) > 1 else waves[0]

        tmp = final.with_suffix(".tmp.wav")
        torchaudio.save(str(tmp), full.cpu(), model.sr)
        tmp.rename(final)
        return final.name, False


async def synthesize(text: str, voice_path: Path | None) -> tuple[str, bool]:
    """Returns (cache filename, was_cached). Runs generation off the event loop."""
    # Fast path: an existing cache hit needs no model (and no thread) — but the
    # key includes the model name, so only check once a model has been loaded.
    if _model is not None:
        cached = cache_dir() / f"{_cache_key(text, voice_path)}.wav"
        if cached.exists():
            return cached.name, True
    return await asyncio.to_thread(_synthesize_sync, text, voice_path)
