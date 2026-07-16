from types import SimpleNamespace as NS

from server.ai.openrouter import (
    NIM_DEFAULT_MODEL,
    NVIDIA_NIM_BASE,
    OPENROUTER_BASE,
    _apply_sampling,
    is_openrouter,
    provider_endpoint,
)
from server.ai.summarizer import pick_messages_to_summarize, should_summarize


def _settings(**kw):
    base = dict(llm_provider="openrouter", api_key="or-key", model_id="or/model",
                nim_api_key="nvapi-key", nim_model_id=NIM_DEFAULT_MODEL,
                custom_base_url="", custom_api_key="", custom_model_id="")
    base.update(kw)
    return NS(**base)


# ── provider resolution ───────────────────────────────────────────

def test_openrouter_is_default_provider():
    assert provider_endpoint(_settings()) == (OPENROUTER_BASE, "or-key", "or/model")
    assert provider_endpoint(_settings(llm_provider="")) == (OPENROUTER_BASE, "or-key", "or/model")


def test_nim_provider_resolves_its_own_creds():
    base, key, model = provider_endpoint(_settings(llm_provider="nvidia_nim"))
    assert base == NVIDIA_NIM_BASE and key == "nvapi-key" and model == NIM_DEFAULT_MODEL


def test_custom_provider_strips_trailing_slash():
    s = _settings(llm_provider="custom", custom_base_url="http://localhost:8080/v1/",
                  custom_api_key="ck", custom_model_id="local/model")
    assert provider_endpoint(s) == ("http://localhost:8080/v1", "ck", "local/model")


def test_is_openrouter():
    assert is_openrouter(OPENROUTER_BASE)
    assert not is_openrouter(NVIDIA_NIM_BASE)


# ── sampling params (NIM rejects the OpenRouter superset) ─────────

def test_strict_sampling_drops_openrouter_only_params():
    body: dict = {}
    _apply_sampling(body, top_p=0.9, min_p=0.05, top_k=40,
                    frequency_penalty=0.1, presence_penalty=0.1,
                    repetition_penalty=1.1, openai_strict=True)
    assert "top_p" in body and "frequency_penalty" in body and "presence_penalty" in body
    assert "min_p" not in body and "top_k" not in body and "repetition_penalty" not in body


def test_openrouter_sampling_passes_superset_but_skips_noops():
    body: dict = {}
    _apply_sampling(body, top_p=1.0, min_p=0.05, top_k=0,
                    frequency_penalty=0.0, presence_penalty=0.0,
                    repetition_penalty=1.0, openai_strict=False)
    assert body == {"min_p": 0.05}, body  # every no-op default omitted


# ── summarisation helpers ─────────────────────────────────────────

def test_should_summarize_threshold():
    # budget = 10000 - 1000 = 9000; threshold 0.7 → trips above 6300 tokens
    assert not should_summarize(6000, 0, 10000, 1000, threshold=0.7)
    assert should_summarize(6500, 0, 10000, 1000, threshold=0.7)


def test_pick_messages_needs_at_least_four():
    msgs = [NS(turn_number=t, role="user", content="x") for t in (1, 2, 3)]
    to_sum, to_keep, boundary = pick_messages_to_summarize(msgs)
    assert to_sum == [] and to_keep == msgs and boundary == 0


def test_pick_messages_compresses_oldest_and_sets_boundary():
    msgs = [NS(turn_number=t, role="user", content="x") for t in range(1, 11)]
    to_sum, to_keep, boundary = pick_messages_to_summarize(msgs)
    assert to_sum and to_keep and to_sum + to_keep == msgs
    assert boundary == to_sum[-1].turn_number
