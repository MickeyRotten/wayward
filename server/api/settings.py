"""App-wide LLM settings (provider, model, sampling, agents) and the model-list
proxy for the active provider."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.ai.openrouter import OPENROUTER_BASE, fetch_models, provider_endpoint
from server.ai.vision import VISION_DEFAULT_INSTRUCTIONS
from server.api.schemas import OpenRouterSettingsResponse, OpenRouterSettingsUpdate
from server.db.database import get_session
from server.db.models import OpenRouterSettings

router = APIRouter()


# ── OpenRouter Settings ───────────────────────────────────────────

def _or_response(s: OpenRouterSettings) -> OpenRouterSettingsResponse:
    return OpenRouterSettingsResponse(
        provider=getattr(s, "llm_provider", "") or "openrouter",
        modelId=s.model_id,
        nimModelId=getattr(s, "nim_model_id", "") or "",
        nimApiKeySet=bool(getattr(s, "nim_api_key", "")),
        customBaseUrl=getattr(s, "custom_base_url", "") or "",
        customModelId=getattr(s, "custom_model_id", "") or "",
        customApiKeySet=bool(getattr(s, "custom_api_key", "")),
        temperature=s.temperature,
        topP=s.top_p,
        minP=s.min_p,
        topK=s.top_k,
        frequencyPenalty=s.frequency_penalty,
        presencePenalty=s.presence_penalty,
        repetitionPenalty=s.repetition_penalty,
        maxTokensResponse=s.max_tokens_response,
        maxContextTokens=s.max_context_tokens,
        maxPartySize=s.max_party_size,
        maxToolRounds=s.max_tool_rounds,
        autoRetryCount=int(getattr(s, "auto_retry_count", 2) or 0),
        reasoningEffort=getattr(s, "reasoning_effort", "") or "",
        useTools=bool(s.use_tools),
        toolMode=getattr(s, "tool_mode", "auto") or "auto",
        worldbuildingMode=s.worldbuilding_mode,
        worldbuildingModelId=s.worldbuilding_model_id,
        actionSuggestionsModelId=getattr(s, "action_suggestions_model_id", "") or "",
        plannerModelId=getattr(s, "planner_model_id", "") or "",
        summaryThreshold=getattr(s, "summary_threshold", 0.7) or 0.7,
        summaryModelId=getattr(s, "summary_model_id", "") or "",
        visionModelId=getattr(s, "vision_model_id", "") or "google/gemma-3-4b-it",
        visionUseSameKey=bool(getattr(s, "vision_use_same_key", True)),
        visionApiKeySet=bool(getattr(s, "vision_api_key", "")),
        visionInstructions=(getattr(s, "vision_instructions", "") or "").strip() or VISION_DEFAULT_INSTRUCTIONS,
        ttsEnabled=bool(getattr(s, "tts_enabled", False)),
        ttsAutoplay=bool(getattr(s, "tts_autoplay", True)),
        apiKeySet=bool(s.api_key),
    )


@router.get("/settings/openrouter", response_model=OpenRouterSettingsResponse)
async def get_openrouter_settings(session: AsyncSession = Depends(get_session)):
    s = (await session.execute(select(OpenRouterSettings))).scalars().first()
    if not s:
        s = OpenRouterSettings()
        session.add(s)
        await session.commit()
    return _or_response(s)


@router.put("/settings/openrouter", response_model=OpenRouterSettingsResponse)
async def update_openrouter_settings(
    data: OpenRouterSettingsUpdate,
    session: AsyncSession = Depends(get_session),
):
    s = (await session.execute(select(OpenRouterSettings))).scalars().first()
    if not s:
        s = OpenRouterSettings()
        session.add(s)
    s.llm_provider = data.provider or "openrouter"
    if data.apiKey is not None:
        s.api_key = data.apiKey
    s.model_id = data.modelId
    if data.nimApiKey is not None:  # write-only, like apiKey
        s.nim_api_key = data.nimApiKey
    s.nim_model_id = data.nimModelId
    s.custom_base_url = data.customBaseUrl
    if data.customApiKey is not None:  # write-only, like apiKey
        s.custom_api_key = data.customApiKey
    s.custom_model_id = data.customModelId
    s.temperature = data.temperature
    s.top_p = data.topP
    s.min_p = data.minP
    s.top_k = data.topK
    s.frequency_penalty = data.frequencyPenalty
    s.presence_penalty = data.presencePenalty
    s.repetition_penalty = data.repetitionPenalty
    s.max_tokens_response = data.maxTokensResponse
    s.max_context_tokens = data.maxContextTokens
    s.max_party_size = data.maxPartySize
    s.max_tool_rounds = data.maxToolRounds
    s.auto_retry_count = max(0, min(5, data.autoRetryCount))
    s.reasoning_effort = data.reasoningEffort if data.reasoningEffort in ("", "low", "medium", "high", "off") else ""
    s.tool_mode = data.toolMode if data.toolMode in ("auto", "native", "text", "off") else "auto"
    # use_tools is legacy (superseded by tool_mode); keep it coherent for any
    # old reader — text/off imply the non-native path.
    s.use_tools = data.toolMode in ("auto", "native")
    s.worldbuilding_mode = data.worldbuildingMode
    s.worldbuilding_model_id = data.worldbuildingModelId
    s.action_suggestions_model_id = data.actionSuggestionsModelId
    s.planner_model_id = data.plannerModelId
    s.summary_threshold = data.summaryThreshold
    s.summary_model_id = data.summaryModelId
    s.vision_model_id = data.visionModelId
    s.vision_use_same_key = data.visionUseSameKey
    if data.visionApiKey is not None:  # write-only, like apiKey
        s.vision_api_key = data.visionApiKey
    # Storing the default text verbatim is treated as "unset" so future
    # default improvements reach users who never customized it.
    s.vision_instructions = "" if data.visionInstructions.strip() == VISION_DEFAULT_INSTRUCTIONS else data.visionInstructions
    s.tts_enabled = data.ttsEnabled
    s.tts_autoplay = data.ttsAutoplay
    await session.commit()
    return _or_response(s)


# ── Models Proxy ──────────────────────────────────────────────────

@router.get("/models")
async def list_models(session: AsyncSession = Depends(get_session)):
    # Resolve the active provider (OpenRouter / NVIDIA NIM / custom) so the
    # dropdown lists that provider's models. OpenRouter's list is public, so it
    # works without a key; NIM/custom require their key (empty → empty list).
    settings = (await session.execute(select(OpenRouterSettings))).scalars().first()
    if settings is None:
        base_url, api_key = OPENROUTER_BASE, ""
    else:
        base_url, api_key, _main_model = provider_endpoint(settings)
    try:
        models = await fetch_models(api_key, base_url=base_url)
        return models
    except Exception as e:
        raise HTTPException(502, f"Failed to fetch models: {e}")
