import { useEffect, useRef, useState } from 'react'
import { useSettingsStore } from '../../state/settingsStore'
import { useNarratorStore } from '../../state/narratorStore'
import { usePartyStore } from '../../state/partyStore'
import { useChatStore } from '../../state/chatStore'
import { useLoreStore } from '../../state/loreStore'
import { useItemsStore } from '../../state/itemsStore'
import { ConfirmDialog } from '../ConfirmDialog'
import { ExpandableTextarea } from '../common/ExpandableTextarea'
import { useCampaignsStore } from '../../state/campaignsStore'
import { useAppearanceStore, CHAT_FONT_SIZES, DEFAULT_CHAT_BG_OPACITY } from '../../state/appearanceStore'
import { useTtsStore } from '../../state/ttsStore'
import { api } from '../../lib/api'
import { fetchBackdrops, invalidateBackdrops, type Backdrop } from '../../lib/backdrops'
import { deleteNarratorVoice, uploadNarratorVoice } from '../../lib/voice'
import type { LlmProvider, LoreCategory, LorebookConfig, OpenRouterModel, OpenRouterSettings } from '@shared/types/models'

const LORE_CATEGORIES: { id: LoreCategory; label: string }[] = [
  { id: 'world', label: 'World' },
  { id: 'characters', label: 'Characters' },
  { id: 'items', label: 'Items' },
  { id: 'monsters', label: 'Monsters' },
  { id: 'spells', label: 'Spells' },
]

const INJECTION_POSITIONS: LorebookConfig['injectionPosition'][LoreCategory][] = [
  'top',
  'bottom',
  'before_input',
]

export function SettingsPanel() {
  const settings = useSettingsStore()
  const narrator = useNarratorStore()

  const [provider, setProvider] = useState(settings.provider)
  const [apiKey, setApiKey] = useState('')
  const [modelId, setModelId] = useState(settings.modelId)
  const [nimModelId, setNimModelId] = useState(settings.nimModelId)
  const [nimApiKey, setNimApiKey] = useState('')
  const [customBaseUrl, setCustomBaseUrl] = useState(settings.customBaseUrl)
  const [customModelId, setCustomModelId] = useState(settings.customModelId)
  const [customApiKey, setCustomApiKey] = useState('')
  const [temperature, setTemperature] = useState(settings.temperature)
  const [topP, setTopP] = useState(settings.topP)
  const [minP, setMinP] = useState(settings.minP)
  const [topK, setTopK] = useState(settings.topK)
  const [freqPen, setFreqPen] = useState(settings.frequencyPenalty)
  const [presPen, setPresPen] = useState(settings.presencePenalty)
  const [repPen, setRepPen] = useState(settings.repetitionPenalty)
  const [maxTokens, setMaxTokens] = useState(settings.maxTokensResponse)
  const [maxPartySize, setMaxPartySize] = useState(settings.maxPartySize)
  const [maxToolRounds, setMaxToolRounds] = useState(settings.maxToolRounds)
  const [autoRetryCount, setAutoRetryCount] = useState(settings.autoRetryCount)
  const [reasoningEffort, setReasoningEffort] = useState(settings.reasoningEffort)
  const [useTools, setUseTools] = useState(settings.useTools)
  const [wbMode, setWbMode] = useState(settings.worldbuildingMode)
  const [wbModelId, setWbModelId] = useState(settings.worldbuildingModelId)
  const [actionSuggestionsModelId, setActionSuggestionsModelId] = useState(settings.actionSuggestionsModelId)
  const [summaryThreshold, setSummaryThreshold] = useState(settings.summaryThreshold)
  const [summaryModelId, setSummaryModelId] = useState(settings.summaryModelId)
  const [visionModelId, setVisionModelId] = useState(settings.visionModelId)
  const [visionUseSameKey, setVisionUseSameKey] = useState(settings.visionUseSameKey)
  const [visionApiKey, setVisionApiKey] = useState('')
  const [visionInstructions, setVisionInstructions] = useState(settings.visionInstructions)
  const [ttsEnabled, setTtsEnabled] = useState(settings.ttsEnabled)
  const [ttsAutoplay, setTtsAutoplay] = useState(settings.ttsAutoplay)
  const [showAllModels, setShowAllModels] = useState(false)
  const [instructions, setInstructions] = useState(narrator.instructions)
  const [spotlightRule, setSpotlightRule] = useState(narrator.spotlightRule)
  const [postHistory, setPostHistory] = useState(narrator.postHistoryInstructions)
  const [plannerInstructions, setPlannerInstructions] = useState(narrator.plannerInstructions)
  const [actionSuggestionsEnabled, setActionSuggestionsEnabled] = useState(narrator.actionSuggestionsEnabled)
  const [actionSuggestionsInstructions, setActionSuggestionsInstructions] = useState(narrator.actionSuggestionsInstructions)
  const [actionOptionRules, setActionOptionRules] = useState<string[]>(narrator.actionOptionRules)
  const [actionSuggestionsMode, setActionSuggestionsMode] = useState(narrator.actionSuggestionsMode)
  const [diceEnabled, setDiceEnabled] = useState(narrator.diceEnabled)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    setProvider(settings.provider)
    setModelId(settings.modelId)
    setNimModelId(settings.nimModelId)
    setCustomBaseUrl(settings.customBaseUrl)
    setCustomModelId(settings.customModelId)
    setTemperature(settings.temperature)
    setTopP(settings.topP)
    setMinP(settings.minP)
    setTopK(settings.topK)
    setFreqPen(settings.frequencyPenalty)
    setPresPen(settings.presencePenalty)
    setRepPen(settings.repetitionPenalty)
    setMaxTokens(settings.maxTokensResponse)
    setMaxPartySize(settings.maxPartySize)
    setMaxToolRounds(settings.maxToolRounds)
    setAutoRetryCount(settings.autoRetryCount)
    setReasoningEffort(settings.reasoningEffort)
    setUseTools(settings.useTools)
    setWbMode(settings.worldbuildingMode)
    setWbModelId(settings.worldbuildingModelId)
    setActionSuggestionsModelId(settings.actionSuggestionsModelId)
    setSummaryThreshold(settings.summaryThreshold)
    setSummaryModelId(settings.summaryModelId)
    setVisionModelId(settings.visionModelId)
    setVisionUseSameKey(settings.visionUseSameKey)
    setVisionInstructions(settings.visionInstructions)
    setTtsEnabled(settings.ttsEnabled)
    setTtsAutoplay(settings.ttsAutoplay)
  }, [settings.provider, settings.modelId, settings.nimModelId, settings.customBaseUrl, settings.customModelId, settings.temperature, settings.topP, settings.minP, settings.topK, settings.frequencyPenalty, settings.presencePenalty, settings.repetitionPenalty, settings.maxTokensResponse, settings.maxPartySize, settings.maxToolRounds, settings.autoRetryCount, settings.reasoningEffort, settings.useTools, settings.worldbuildingMode, settings.worldbuildingModelId, settings.actionSuggestionsModelId, settings.summaryThreshold, settings.summaryModelId, settings.visionModelId, settings.visionUseSameKey, settings.visionInstructions, settings.ttsEnabled, settings.ttsAutoplay])

  useEffect(() => {
    setInstructions(narrator.instructions)
    setSpotlightRule(narrator.spotlightRule)
    setPostHistory(narrator.postHistoryInstructions)
    setPlannerInstructions(narrator.plannerInstructions)
    setActionSuggestionsEnabled(narrator.actionSuggestionsEnabled)
    setActionSuggestionsInstructions(narrator.actionSuggestionsInstructions)
    setActionOptionRules(narrator.actionOptionRules)
    setActionSuggestionsMode(narrator.actionSuggestionsMode)
    setDiceEnabled(narrator.diceEnabled)
  }, [narrator.instructions, narrator.spotlightRule, narrator.postHistoryInstructions, narrator.plannerInstructions, narrator.actionSuggestionsEnabled, narrator.actionSuggestionsInstructions, narrator.actionOptionRules, narrator.actionSuggestionsMode, narrator.diceEnabled])

  // Load the model list automatically when Config opens. OpenRouter's model
  // list is public, so this works even before an API key is entered — the
  // dropdown is ready to pick from immediately.
  useEffect(() => {
    const s = useSettingsStore.getState()
    if (s.availableModels.length === 0) {
      s.fetchModels()
    }
  }, [])

  const saveAll = async () => {
    await settings.saveSettings({
      provider,
      ...(apiKey ? { apiKey } : {}),
      modelId,
      nimModelId,
      ...(nimApiKey ? { nimApiKey } : {}),
      customBaseUrl,
      customModelId,
      ...(customApiKey ? { customApiKey } : {}),
      temperature,
      topP,
      minP,
      topK,
      frequencyPenalty: freqPen,
      presencePenalty: presPen,
      repetitionPenalty: repPen,
      maxTokensResponse: maxTokens,
      maxContextTokens: settings.maxContextTokens,
      maxPartySize,
      maxToolRounds,
      autoRetryCount,
      reasoningEffort,
      useTools,
      worldbuildingMode: wbMode,
      worldbuildingModelId: wbModelId,
      actionSuggestionsModelId,
      summaryThreshold,
      summaryModelId,
      visionModelId,
      visionUseSameKey,
      visionInstructions,
      ttsEnabled,
      ttsAutoplay,
      ...(visionApiKey ? { visionApiKey } : {}),
    })
    await narrator.save({ instructions, spotlightRule, postHistoryInstructions: postHistory, plannerInstructions, actionSuggestionsEnabled, actionSuggestionsInstructions, actionOptionRules, actionSuggestionsMode, diceEnabled })
    // The TTS enable toggle affects server-reported availability.
    void useTtsStore.getState().fetchStatus()
    setApiKey('')
    setVisionApiKey('')
    setNimApiKey('')
    setCustomApiKey('')
    setSaved(true)
    setTimeout(() => setSaved(false), 1500)
  }

  // Reset-to-defaults handlers (local edits; persisted on SAVE). Blank text
  // fields fall back to the built-in defaults server-side.
  const resetAiModel = () => {
    setTemperature(0.7); setTopP(1); setMinP(0); setTopK(0)
    setFreqPen(0); setPresPen(0); setRepPen(1); setMaxTokens(1000)
  }
  const resetAgents = () => {
    setUseTools(true); setMaxToolRounds(6); setAutoRetryCount(2)
    setWbMode('confirmation'); setWbModelId('')
    setSummaryThreshold(0.7); setSummaryModelId('')
    setActionSuggestionsEnabled(false); setActionSuggestionsModelId('')
    setVisionModelId('google/gemma-3-4b-it'); setVisionUseSameKey(true); setVisionInstructions('')
  }
  const resetWorld = () => {
    setInstructions(''); setSpotlightRule(''); setPostHistory(''); setPlannerInstructions('')
    setDiceEnabled(true)
  }
  const resetVoice = () => {
    setTtsEnabled(false); setTtsAutoplay(true)
  }
  const resetAppearance = () => {
    useAppearanceStore.getState().setChatFontSize('medium')
    useAppearanceStore.getState().setChatBgOpacity(DEFAULT_CHAT_BG_OPACITY)
    useAppearanceStore.getState().setWeatherFx(true)
  }

  // The active provider's model id is stored in a provider-specific field; the
  // model dropdown (fed by /models for the *saved* provider) drives whichever
  // one is active. Picking a model auto-saves it (as OpenRouter's flow does).
  const activeModelId = provider === 'nvidia_nim' ? nimModelId : provider === 'custom' ? customModelId : modelId
  const setActiveModelId = provider === 'nvidia_nim' ? setNimModelId : provider === 'custom' ? setCustomModelId : setModelId
  const modelSaveKey = provider === 'nvidia_nim' ? 'nimModelId' : provider === 'custom' ? 'customModelId' : 'modelId'

  const switchProvider = (p: LlmProvider) => {
    setProvider(p)
    // Persist immediately so /models serves the new provider, then reload its
    // list. Prefill NIM's default model on first switch.
    const patch: Partial<OpenRouterSettings> = { provider: p }
    if (p === 'nvidia_nim' && !nimModelId) {
      setNimModelId('deepseek-ai/deepseek-v4-pro')
      patch.nimModelId = 'deepseek-ai/deepseek-v4-pro'
    }
    void settings.saveSettings(patch).then(() => settings.fetchModels())
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-5 pt-5 pb-3">
        <h2 className="font-disp text-[24px] pt-[3px] leading-none text-text">CONFIG</h2>
      </div>

      <div className="flex-1 overflow-y-auto px-4 pb-4 space-y-2">
        {/* Campaign */}
        <Section title="Campaign" defaultOpen>
          <CampaignSection />
          <SubSection title="Party">
            <label className="block">
              <span className="text-[11px] text-textdim font-body">Max Party Size</span>
              <input
                type="number"
                min={1}
                className="w-full border border-line bg-bg0 px-2 py-1 text-sm font-body text-text outline-none focus:border-line2 focus:bg-bg2"
                value={maxPartySize}
                onChange={(e) => setMaxPartySize(Math.max(1, Number(e.target.value) || 3))}
              />
              <span className="text-[10px] text-textdim font-body">
                Active party members (excluding the player character).
              </span>
            </label>
          </SubSection>
        </Section>

        {/* AI & Model */}
        <Section title="AI &amp; Model" onReset={resetAiModel}>
          <SubSection title="API &amp; Model">
            <label className="block">
              <span className="text-[11px] text-textdim font-body">Provider</span>
              <select
                className="w-full border border-line2 bg-bg0 px-2 py-1 text-sm font-body text-text outline-none"
                value={provider}
                onChange={(e) => switchProvider(e.target.value as LlmProvider)}
              >
                <option value="openrouter">OpenRouter</option>
                <option value="nvidia_nim">NVIDIA NIM</option>
                <option value="custom">Custom (OpenAI-compatible)</option>
              </select>
            </label>

            {provider === 'openrouter' && (
              <label className="block">
                <span className="text-[11px] text-textdim font-body">
                  OpenRouter API Key {settings.apiKeySet && <span className="text-textsec">(set)</span>}
                </span>
                <input
                  type="password"
                  className="w-full border border-line2 bg-bg0 px-2 py-1 text-sm font-body text-text outline-none focus:bg-bg2"
                  placeholder={settings.apiKeySet ? '••••••••' : 'Enter your OpenRouter API key'}
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                />
                <span className="text-[10px] text-textdim font-body">Get a key at openrouter.ai/keys.</span>
              </label>
            )}

            {provider === 'nvidia_nim' && (
              <label className="block">
                <span className="text-[11px] text-textdim font-body">
                  NVIDIA NIM API Key {settings.nimApiKeySet && <span className="text-textsec">(set)</span>}
                </span>
                <input
                  type="password"
                  className="w-full border border-line2 bg-bg0 px-2 py-1 text-sm font-body text-text outline-none focus:bg-bg2"
                  placeholder={settings.nimApiKeySet ? '••••••••' : 'nvapi-...'}
                  value={nimApiKey}
                  onChange={(e) => setNimApiKey(e.target.value)}
                />
                <span className="text-[10px] text-textdim font-body">Get an <code>nvapi-…</code> key at build.nvidia.com.</span>
              </label>
            )}

            {provider === 'custom' && (
              <>
                <label className="block">
                  <span className="text-[11px] text-textdim font-body">API Base URL</span>
                  <input
                    type="text"
                    className="w-full border border-line2 bg-bg0 px-2 py-1 text-sm font-body text-text outline-none focus:bg-bg2"
                    placeholder="https://your-endpoint/v1"
                    value={customBaseUrl}
                    onChange={(e) => setCustomBaseUrl(e.target.value)}
                  />
                  <span className="text-[10px] text-textdim font-body">Any OpenAI-compatible endpoint (must end in /v1).</span>
                </label>
                <label className="block">
                  <span className="text-[11px] text-textdim font-body">
                    API Key {settings.customApiKeySet && <span className="text-textsec">(set)</span>}
                  </span>
                  <input
                    type="password"
                    className="w-full border border-line2 bg-bg0 px-2 py-1 text-sm font-body text-text outline-none focus:bg-bg2"
                    placeholder={settings.customApiKeySet ? '••••••••' : 'Enter the endpoint API key'}
                    value={customApiKey}
                    onChange={(e) => setCustomApiKey(e.target.value)}
                  />
                </label>
              </>
            )}
            {settings.availableModels.length === 0 && (
              <button
                type="button"
                className="font-ui text-[10px] text-textsec border border-line px-3 py-1 hover:border-line2"
                onClick={() => settings.fetchModels()}
              >
                LOAD MODELS
              </button>
            )}
            <label className="block">
              <div className="flex items-center justify-between">
                <span className="text-[11px] text-textdim font-body">Model</span>
                {settings.availableModels.length > 0 && (
                  <label className="flex items-center gap-1 text-[10px] text-textdim font-body cursor-pointer">
                    <input
                      type="checkbox"
                      checked={showAllModels}
                      onChange={(e) => setShowAllModels(e.target.checked)}
                    />
                    Show all models
                  </label>
                )}
              </div>
              {settings.availableModels.length > 0 ? (
                <select
                  className="w-full border border-line2 bg-bg0 px-2 py-1 text-sm font-body text-text outline-none"
                  value={activeModelId}
                  onChange={(e) => {
                    setActiveModelId(e.target.value)
                    const model = settings.availableModels.find((m) => m.id === e.target.value)
                    // OpenRouter reports contextLength; NIM/custom don't, so only
                    // update the context budget when we actually know it.
                    const patch: Partial<OpenRouterSettings> = { [modelSaveKey]: e.target.value }
                    if (model && model.contextLength > 0) patch.maxContextTokens = model.contextLength
                    void settings.saveSettings(patch)
                  }}
                >
                  <option value="">Select a model...</option>
                  {(showAllModels
                    ? settings.availableModels
                    : settings.availableModels.filter((m) => m.supportsTools)
                  ).map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.name}{m.supportsTools ? '' : ' (no tools)'}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  className="w-full border border-line2 bg-bg0 px-2 py-1 text-sm font-body text-text outline-none focus:bg-bg2"
                  placeholder={provider === 'nvidia_nim' ? 'deepseek-ai/deepseek-v4-pro' : 'e.g. anthropic/claude-sonnet-4.6'}
                  value={activeModelId}
                  onChange={(e) => setActiveModelId(e.target.value)}
                />
              )}
            </label>

            {(() => {
              const selected = settings.availableModels.find((m) => m.id === activeModelId)
              const legacyByModel = useTools && selected && !selected.supportsTools
              const legacyByToggle = !useTools
              if (!legacyByModel && !legacyByToggle) return null
              return (
                <p className="text-[10px] text-gold font-body border border-line bg-bg0 px-2 py-1">
                  {legacyByToggle
                    ? 'Tools are off — the narrator uses the legacy text-block action protocol.'
                    : 'This model does not support tool calling — the narrator will fall back to the legacy text-block action protocol.'}
                </p>
              )
            })()}

            <p className="text-[10px] text-textdim font-body">
              Max context: {settings.maxContextTokens.toLocaleString()} tokens
            </p>
          </SubSection>

          <SubSection title="Sampling">
            <div className="grid grid-cols-2 gap-3">
              <Slider label="Temperature" value={temperature} min={0} max={2} step={0.05} onChange={setTemperature} />
              <Slider label="Top P" value={topP} min={0} max={1} step={0.05} onChange={setTopP} />
              <Slider label="Min P" value={minP} min={0} max={1} step={0.05} onChange={setMinP} />
              <label className="block">
                <span className="text-[11px] text-textdim font-body">Top K ({topK})</span>
                <input
                  type="number"
                  className="w-full border border-line bg-bg0 px-2 py-1 text-sm font-body text-text outline-none focus:border-line2 focus:bg-bg2"
                  value={topK}
                  min={0}
                  onChange={(e) => setTopK(Math.max(0, Number(e.target.value) || 0))}
                />
              </label>
              <Slider label="Frequency Penalty" value={freqPen} min={-2} max={2} step={0.05} onChange={setFreqPen} />
              <Slider label="Presence Penalty" value={presPen} min={-2} max={2} step={0.05} onChange={setPresPen} />
              <Slider label="Repetition Penalty" value={repPen} min={0.5} max={2} step={0.05} onChange={setRepPen} />
              <label className="block">
                <span className="text-[11px] text-textdim font-body">Max Tokens</span>
                <input
                  type="number"
                  className="w-full border border-line bg-bg0 px-2 py-1 text-sm font-body text-text outline-none focus:border-line2 focus:bg-bg2"
                  value={maxTokens}
                  onChange={(e) => setMaxTokens(Number(e.target.value) || 1000)}
                />
              </label>
              <label className="block">
                <span className="text-[11px] text-textdim font-body">Reasoning Effort</span>
                <select
                  className="w-full border border-line bg-bg0 px-2 py-1 text-sm font-body text-text outline-none focus:border-line2"
                  value={reasoningEffort}
                  onChange={(e) => setReasoningEffort(e.target.value)}
                >
                  <option value="">Provider default</option>
                  <option value="low">Low</option>
                  <option value="medium">Medium</option>
                  <option value="high">High</option>
                </select>
                <span className="block text-[10px] text-textdim font-body mt-0.5">
                  Reasoning models only; sent via OpenRouter. Thinking spends the
                  Max Tokens budget — the chat shows the phase live.
                </span>
              </label>
            </div>
          </SubSection>
        </Section>

        {/* Agents & Tools */}
        <Section title="Agents &amp; Tools" onReset={resetAgents}>
          <p className="text-[10px] text-textdim font-body leading-relaxed">
            Wayward runs several LLM agents. The <span className="text-textsec">Narrator</span> tells the story. The <span className="text-textsec">Editor</span> builds the world in Edit Mode. The <span className="text-textsec">Chronicler</span> quietly records new lore/tasks/companions after each turn.
          </p>

          <SubSection title="Narrator Tools">
            <label className="flex items-center gap-2 text-[11px] text-textdim font-body">
              <input
                type="checkbox"
                checked={useTools}
                onChange={(e) => setUseTools(e.target.checked)}
              />
              Use tools (agent loop)
            </label>
            <label className="block">
              <span className="text-[11px] text-textdim font-body">Max Tool Rounds</span>
              <input
                type="number"
                min={1}
                className="w-full border border-line bg-bg0 px-2 py-1 text-sm font-body text-text outline-none focus:border-line2 focus:bg-bg2"
                value={maxToolRounds}
                onChange={(e) => setMaxToolRounds(Math.max(1, Number(e.target.value) || 6))}
              />
            </label>
            <p className="text-[10px] text-textdim font-body">
              When on, the narrator calls tools (grant/equip/scene/etc.) over up to this many round-trips per turn. When off, it uses the legacy text-block protocol.
            </p>
            <label className="block">
              <span className="text-[11px] text-textdim font-body">Auto-retry on error / safety block</span>
              <input
                type="number"
                min={0}
                max={5}
                className="w-full border border-line bg-bg0 px-2 py-1 text-sm font-body text-text outline-none focus:border-line2 focus:bg-bg2"
                value={autoRetryCount}
                onChange={(e) => setAutoRetryCount(Math.max(0, Math.min(5, Number(e.target.value) || 0)))}
              />
            </label>
            <p className="text-[10px] text-textdim font-body">
              If the model errors or its safety filter blocks a turn, silently regenerate up to this many times before showing the error (Narrator and Editor). 0 = off (manual RETRY only). Max 5.
            </p>
          </SubSection>

          <SubSection title="Chronicler">
            <label className="block">
              <span className="text-[11px] text-textdim font-body">Mode</span>
              <select
                className="w-full border border-line2 bg-bg0 px-2 py-1 text-sm font-body text-text outline-none"
                value={wbMode}
                onChange={(e) => setWbMode(e.target.value as typeof wbMode)}
              >
                <option value="disabled">Disabled — never creates or changes anything</option>
                <option value="confirmation">Confirmation — suggest, you approve</option>
                <option value="auto">Auto — apply changes automatically</option>
              </select>
              <span className="text-[10px] text-textdim font-body">
                The Chronicler reviews each turn and records new lore, tasks, and companions. New party members always need your approval, even in Auto.
              </span>
            </label>
            <label className="block">
              <span className="text-[11px] text-textdim font-body">Chronicler Model</span>
              <ModelPicker
                value={wbModelId}
                onChange={setWbModelId}
                models={settings.availableModels}
                showAll={showAllModels}
              />
              <span className="text-[10px] text-textdim font-body">
                Optional. Leave as "Use main model", or pick a cheaper/faster tool-capable model for bookkeeping.
              </span>
            </label>
          </SubSection>

          <SubSection title="Summarisation">
            <label className="block">
              <span className="text-[11px] text-textdim font-body">Summarise at {Math.round(summaryThreshold * 100)}% of context</span>
              <input
                type="range"
                min={0.3}
                max={0.95}
                step={0.05}
                value={summaryThreshold}
                onChange={(e) => setSummaryThreshold(Number(e.target.value))}
                className="w-full accent-gold"
              />
              <span className="text-[10px] text-textdim font-body">
                When the prompt reaches this fraction of the context budget, the oldest turns are compressed into a running "story so far" so the Narrator/Editor keep full history without overflowing.
              </span>
            </label>
            <label className="block">
              <span className="text-[11px] text-textdim font-body">Summarisation Model</span>
              <ModelPicker
                value={summaryModelId}
                onChange={setSummaryModelId}
                models={settings.availableModels}
                showAll={showAllModels}
                toolsOnly={false}
              />
              <span className="text-[10px] text-textdim font-body">
                Optional. A cheap/fast model is a good choice for summarising.
              </span>
            </label>
          </SubSection>

          <SubSection title="Action Suggestions">
            <label className="flex items-center gap-2 text-[11px] text-textdim font-body">
              <input
                type="checkbox"
                checked={actionSuggestionsEnabled}
                onChange={(e) => setActionSuggestionsEnabled(e.target.checked)}
              />
              Show AI-suggested actions in the chat
            </label>
            <span className="text-[10px] text-textdim font-body">
              After each narration, generates the numbered choice options in the chat's action panel — one option per rule below. The primary text-adventure interaction (an extra small LLM call per turn). The fixed actions (Continue, Look Around, Rest, Use an Item, Talk to Party) always show regardless.
            </span>
            <label className="block">
              <span className="text-[11px] text-textdim font-body">Generation Mode</span>
              <div className="mt-1 grid grid-cols-2 gap-1">
                {([
                  { value: 'separate', label: 'Separate call' },
                  { value: 'inline', label: 'With the narration' },
                ] as const).map((opt) => (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => setActionSuggestionsMode(opt.value)}
                    className={`font-ui text-[10px] tracking-wider uppercase px-2 py-1.5 border rounded transition-colors ${
                      actionSuggestionsMode === opt.value
                        ? 'border-gold text-gold bg-gold/10'
                        : 'border-line2 text-textdim hover:text-text hover:border-line'
                    }`}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
              <span className="mt-1 block text-[10px] text-textdim font-body">
                Separate call: options come from their own small LLM call after the turn (can use a cheaper model below). With the narration: the narrator writes the options at the end of its own reply — faster and no extra call, but ties them to the main model. Reroll always uses the separate call.
              </span>
            </label>
            <label className="block">
              <span className="text-[11px] text-textdim font-body">Action Suggestions Model</span>
              <ModelPicker
                value={actionSuggestionsModelId}
                onChange={setActionSuggestionsModelId}
                models={settings.availableModels}
                showAll={showAllModels}
              />
              <span className="text-[10px] text-textdim font-body">
                Optional. Leave as "Use main model", or pick a cheap/fast tool-capable model.
              </span>
            </label>
            <label className="block">
              <span className="text-[11px] text-textdim font-body">Suggestion Instructions</span>
              <ExpandableTextarea
                label="Action Suggestion Instructions"
                className="w-full border border-line bg-bg0 px-2 py-1 text-[12px] font-body text-text2 outline-none focus:bg-bg2 resize-y min-h-[80px]"
                rows={4}
                value={actionSuggestionsInstructions}
                onChange={setActionSuggestionsInstructions}
              />
              <span className="text-[10px] text-textdim font-body">
                Guides how the AI picks suggestions (tone, length, what to favor or avoid). Leave blank to use the built-in default.
              </span>
            </label>
            <div className="block">
              <span className="text-[11px] text-textdim font-body">Option Rules — one generated option per rule, in order</span>
              <div className="mt-1 space-y-1.5">
                {actionOptionRules.map((rule, i) => (
                  <div key={i} className="flex items-start gap-1.5">
                    <span className="font-ui text-[10px] text-golddeep pt-2 w-4 text-right shrink-0">{i + 1}.</span>
                    <textarea
                      className="flex-1 border border-line bg-bg0 px-2 py-1 text-[12px] font-body text-text2 outline-none focus:bg-bg2 resize-y min-h-[34px]"
                      rows={1}
                      value={rule}
                      onChange={(e) => setActionOptionRules(actionOptionRules.map((r, j) => (j === i ? e.target.value : r)))}
                    />
                    <button
                      type="button"
                      title="Remove this option slot"
                      disabled={actionOptionRules.length <= 1}
                      className="font-ui text-[11px] text-textdim border border-line px-2 py-1 hover:text-danger hover:border-danger-border transition-colors disabled:opacity-30"
                      onClick={() => setActionOptionRules(actionOptionRules.filter((_, j) => j !== i))}
                    >
                      ✕
                    </button>
                  </div>
                ))}
              </div>
              <div className="mt-1.5 flex gap-2">
                <button
                  type="button"
                  disabled={actionOptionRules.length >= 6}
                  className="font-ui text-[10px] tracking-wider text-textsec border border-line px-2 py-1 hover:text-text hover:border-line2 transition-colors disabled:opacity-30"
                  onClick={() => setActionOptionRules([...actionOptionRules, ''])}
                >
                  + ADD OPTION
                </button>
                <button
                  type="button"
                  className="font-ui text-[10px] tracking-wider text-textsec border border-line px-2 py-1 hover:text-text hover:border-line2 transition-colors"
                  onClick={() => void narrator.save({ actionOptionRules: [] })}
                  title="Restore the built-in good / neutral / dark / wildcard spread"
                >
                  RESET TO DEFAULTS
                </button>
              </div>
              <span className="mt-1 block text-[10px] text-textdim font-body">
                Each rule shapes one option — by default they differ morally (good / neutral / dark) plus a wildcard. 1-6 options; saved with SAVE (reset applies immediately).
              </span>
            </div>
          </SubSection>

          <SubSection title="Vision">
            <span className="text-[10px] text-textdim font-body">
              When you attach an image to a chat message, the Vision agent looks at it and describes it for the Narrator or Editor (which may be text-only models). Runs once per attached image.
            </span>
            <label className="block">
              <span className="text-[11px] text-textdim font-body">Vision Model</span>
              <ModelPicker
                value={visionModelId}
                onChange={setVisionModelId}
                models={settings.availableModels.filter((m) => m.supportsImages)}
                showAll
                blankLabel="Default — Gemma 3 4B"
              />
              <span className="text-[10px] text-textdim font-body">
                Must accept image input. Default: Google Gemma 3 4B (cheap and fast).
              </span>
            </label>
            <label className="block">
              <span className="text-[11px] text-textdim font-body">Vision Instructions</span>
              <ExpandableTextarea
                label="Vision Instructions"
                className="w-full border border-line bg-bg0 px-2 py-1 text-[12px] font-body text-text2 outline-none focus:bg-bg2 resize-y min-h-[80px]"
                rows={4}
                value={visionInstructions}
                onChange={setVisionInstructions}
              />
              <span className="text-[10px] text-textdim font-body">
                How the vision agent describes attached images (detail level, tone, what to focus on). Leave blank to use the built-in default.
              </span>
            </label>
            <label className="flex items-center gap-2 text-[11px] text-textdim font-body">
              <input
                type="checkbox"
                checked={visionUseSameKey}
                onChange={(e) => setVisionUseSameKey(e.target.checked)}
              />
              Use the main OpenRouter API key
            </label>
            {!visionUseSameKey && (
              <label className="block">
                <span className="text-[11px] text-textdim font-body">
                  Vision API Key {settings.visionApiKeySet ? '(set — enter to replace)' : ''}
                </span>
                <input
                  type="password"
                  className="w-full border border-line2 bg-bg0 px-2 py-1 text-sm font-body text-text outline-none focus:bg-bg2"
                  placeholder={settings.visionApiKeySet ? '••••••••' : 'sk-or-...'}
                  value={visionApiKey}
                  onChange={(e) => setVisionApiKey(e.target.value)}
                />
                <span className="text-[10px] text-textdim font-body">
                  A separate OpenRouter key just for the vision agent (e.g. a free-tier key).
                </span>
              </label>
            )}
          </SubSection>
        </Section>

        {/* World */}
        <Section title="World" onReset={resetWorld}>
          <SubSection title="Narrator Instructions">
            <ExpandableTextarea
              label="Narrator Instructions"
              className="w-full border border-line2 bg-bg0 px-2 py-1 text-sm font-body text-text outline-none focus:bg-bg2 resize-y min-h-[100px]"
              rows={5}
              value={instructions}
              onChange={setInstructions}
            />
          </SubSection>

          <SubSection title="Spotlight Rule">
            <ExpandableTextarea
              label="Spotlight Rule"
              className="w-full border border-line bg-bg0 px-2 py-1 text-[12px] font-body text-text2 outline-none focus:bg-bg2 resize-y min-h-[80px]"
              rows={4}
              value={spotlightRule}
              onChange={setSpotlightRule}
            />
            <span className="text-[10px] text-textdim font-body">Governs when party members speak.</span>
          </SubSection>

          <SubSection title="Post-History Instructions">
            <ExpandableTextarea
              label="Post-History Instructions"
              className="w-full border border-line2 bg-bg0 px-2 py-1 text-sm font-body text-text outline-none focus:bg-bg2 resize-y min-h-[80px]"
              rows={4}
              value={postHistory}
              placeholder="Added to the very end of the prompt, right before your message. Empty by default."
              onChange={setPostHistory}
            />
            <span className="text-[10px] text-textdim font-body">Always injected last, immediately before your input.</span>
          </SubSection>

          <SubSection title="Editor Instructions">
            <ExpandableTextarea
              label="Editor Instructions"
              className="w-full border border-line bg-bg0 px-2 py-1 text-[12px] font-body text-text2 outline-none focus:bg-bg2 resize-y min-h-[80px]"
              rows={4}
              value={plannerInstructions}
              onChange={setPlannerInstructions}
            />
            <span className="text-[10px] text-textdim font-body">Core instructions for the Editor persona (Edit Mode in chat).</span>
          </SubSection>

          <SubSection title="Skill Checks">
            <label className="flex items-center gap-2 text-[11px] text-textdim font-body">
              <input
                type="checkbox"
                checked={diceEnabled}
                onChange={(e) => setDiceEnabled(e.target.checked)}
              />
              Enable dice (d20 skill checks)
            </label>
            <span className="text-[10px] text-textdim font-body">
              For uncertain, consequential actions the Narrator asks the server to roll a
              d20 and narrates the result it's given — shown as a dice chip in chat. Per
              campaign; needs a tool-capable model.
            </span>
          </SubSection>

          <SubSection title="Lorebook Injection">
            <LorebookInjectionConfig />
          </SubSection>

          <p className="text-[10px] text-textdim font-body">
            The Scenario and First Message are edited in the Scenario tab (Lore).
          </p>
        </Section>

        {/* Voice & Audio */}
        <Section title="Voice &amp; Audio" onReset={resetVoice}>
          <TtsStatusLine />
          <label className="flex items-center gap-2 text-[11px] text-textdim font-body">
            <input
              type="checkbox"
              checked={ttsEnabled}
              onChange={(e) => setTtsEnabled(e.target.checked)}
            />
            Enable text-to-speech
          </label>
          <label className="flex items-center gap-2 text-[11px] text-textdim font-body">
            <input
              type="checkbox"
              checked={ttsAutoplay}
              onChange={(e) => setTtsAutoplay(e.target.checked)}
              disabled={!ttsEnabled}
            />
            Auto-play each finished narration turn
          </label>
          <span className="block text-[10px] text-textdim font-body">
            The Narrator (narration + NPC lines) and each party member speak with their own
            voice, cloned from a ~10&#8202;s speech sample. Without a sample, everyone shares the
            default voice. Upload character samples on their sheets (Party tab). Synthesis runs
            on this machine — it is slow without a GPU.
          </span>

          <SubSection title="Narrator Voice">
            <NarratorVoiceSample />
          </SubSection>
        </Section>

        {/* Appearance */}
        <Section title="Appearance" onReset={resetAppearance}>
          <AppearanceSection />
        </Section>

        <div className="flex items-center gap-3 pt-2">
          <button
            type="button"
            className="font-ui text-[10px] bg-golddeep text-bg0 px-4 py-2 hover:bg-gold transition-colors"
            onClick={saveAll}
          >
            SAVE
          </button>
          {saved && <span className="font-ui text-[10px] text-gold">SAVED</span>}
        </div>

        {/* Adventure Management */}
        <AdventureManagement />
      </div>
    </div>
  )
}

// Server-side TTS engine availability (install hint / device / load error).
function TtsStatusLine() {
  const status = useTtsStore((s) => s.status)
  if (!status) return null
  let text: string
  let cls = 'text-textdim'
  if (!status.installed) {
    text = 'Engine not installed — run: pip install -r server/requirements-tts.txt'
  } else if (status.error) {
    text = `Engine error: ${status.error}`
    cls = 'text-danger'
  } else if (status.loaded) {
    text = `Engine ready on ${status.device ?? 'cpu'}`
    cls = 'text-gold'
  } else {
    text = 'Engine installed (model loads on first use — the first line spoken may take a while)'
  }
  return <span className={`block text-[10px] font-body ${cls}`}>{text}</span>
}

// Upload/play/clear the active campaign's narrator voice sample.
function NarratorVoiceSample() {
  const hasVoice = useNarratorStore((s) => s.hasVoice)
  const fetchConfig = useNarratorStore((s) => s.fetchConfig)
  const inputRef = useRef<HTMLInputElement>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const [busy, setBusy] = useState(false)
  const [playing, setPlaying] = useState(false)

  const handleUpload = async (file: File) => {
    setBusy(true)
    try {
      if (await uploadNarratorVoice(file)) await fetchConfig()
    } finally {
      setBusy(false)
    }
  }

  const handlePlay = () => {
    if (playing) {
      audioRef.current?.pause()
      setPlaying(false)
      return
    }
    const audio = new Audio(`/api/narrator/voice?t=${Date.now()}`)
    audioRef.current = audio
    audio.onended = () => setPlaying(false)
    audio.onerror = () => setPlaying(false)
    setPlaying(true)
    void audio.play().catch(() => setPlaying(false))
  }

  const handleRemove = async () => {
    audioRef.current?.pause()
    setPlaying(false)
    setBusy(true)
    try {
      if (await deleteNarratorVoice()) await fetchConfig()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-1">
      <div className="flex items-center gap-2">
        <button
          type="button"
          disabled={busy}
          className="font-ui text-[9px] text-textdim hover:text-text border border-line px-1.5 py-0.5 disabled:opacity-40"
          onClick={() => inputRef.current?.click()}
        >
          {hasVoice ? 'REPLACE SAMPLE' : 'UPLOAD SAMPLE'}
        </button>
        {hasVoice && (
          <>
            <button
              type="button"
              className="font-ui text-[9px] text-textdim hover:text-text border border-line px-1.5 py-0.5"
              onClick={handlePlay}
            >
              {playing ? '■ STOP' : '▶ PLAY'}
            </button>
            <button
              type="button"
              disabled={busy}
              className="font-ui text-[9px] text-textdim hover:text-danger border border-line px-1.5 py-0.5 disabled:opacity-40"
              onClick={() => void handleRemove()}
            >
              REMOVE
            </button>
          </>
        )}
        <input
          ref={inputRef}
          type="file"
          accept="audio/*"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0]
            if (file) void handleUpload(file)
            e.target.value = ''
          }}
        />
      </div>
      <span className="block text-[10px] text-textdim font-body">
        ~10 seconds of clean speech for the narrator's voice, stored with this campaign
        (included in campaign exports). Applies immediately — no save needed.
      </span>
    </div>
  )
}

function AppearanceSection() {
  const chatFontSize = useAppearanceStore((s) => s.chatFontSize)
  const setChatFontSize = useAppearanceStore((s) => s.setChatFontSize)
  const chatBgOpacity = useAppearanceStore((s) => s.chatBgOpacity)
  const setChatBgOpacity = useAppearanceStore((s) => s.setChatBgOpacity)
  const weatherFx = useAppearanceStore((s) => s.weatherFx)
  const setWeatherFx = useAppearanceStore((s) => s.setWeatherFx)
  return (
    <div className="space-y-4">
      <label className="block">
        <span className="text-[11px] text-textdim font-body">Chat Font Size</span>
        <div className="mt-1 grid grid-cols-4 gap-1">
          {CHAT_FONT_SIZES.map((opt) => (
            <button
              key={opt.value}
              type="button"
              onClick={() => setChatFontSize(opt.value)}
              className={`font-ui text-[10px] tracking-wider uppercase px-2 py-1.5 border rounded transition-colors ${
                chatFontSize === opt.value
                  ? 'border-gold text-gold bg-gold/10'
                  : 'border-line2 text-textdim hover:text-text hover:border-line'
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
        <span className="mt-1 block text-[10px] text-textdim font-body">
          Size of the narration and dialogue text in the chat. Applies instantly and is remembered on this device.
        </span>
        <p className="chat-prose font-body text-text2 mt-2 border border-line rounded px-3 py-2 bg-bg0">
          The lantern guttered as she stepped into the hall, her shadow long across the stone.
        </p>
      </label>

      <label className="block">
        <span className="text-[11px] text-textdim font-body">
          Chat Background Opacity — {chatBgOpacity}%
        </span>
        <input
          type="range"
          min={0}
          max={100}
          step={5}
          value={chatBgOpacity}
          onChange={(e) => setChatBgOpacity(Number(e.target.value))}
          className="w-full accent-gold mt-1"
        />
        <span className="mt-1 block text-[10px] text-textdim font-body">
          How strongly the chat's dark background covers the backdrop art — lower shows more
          of the scene. Applies instantly and is remembered on this device.
        </span>
      </label>

      <label className="flex items-start gap-2 cursor-pointer">
        <input
          type="checkbox"
          checked={weatherFx}
          onChange={(e) => setWeatherFx(e.target.checked)}
          className="mt-0.5 accent-gold"
        />
        <span>
          <span className="block text-[11px] text-text font-body">Weather Effects</span>
          <span className="block text-[10px] text-textdim font-body">
            Animate the declared weather over the backdrop — rain, snow, drifting fog, and
            lightning in storms. Remembered on this device.
          </span>
        </span>
      </label>

      <BackdropManager />
    </div>
  )
}

/** Manage the scene backdrop art (server/backdrops): thumbnail grid + upload +
 *  delete. Filename words are matched to the declared location/time, so the
 *  hint teaches the naming scheme. */
function BackdropManager() {
  const [backdrops, setBackdrops] = useState<Backdrop[]>([])
  const [busy, setBusy] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const refresh = async () => {
    invalidateBackdrops()
    setBackdrops(await fetchBackdrops())
  }
  useEffect(() => { void refresh() }, [])

  const upload = async (f: File) => {
    setBusy(true)
    try {
      const fd = new FormData()
      fd.append('file', f)
      await fetch('/api/backdrops/upload', { method: 'POST', body: fd })
      await refresh()
    } finally {
      setBusy(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  const remove = async (file: string) => {
    setBusy(true)
    try {
      await api.del(`/backdrops/${encodeURIComponent(file)}`)
      await refresh()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="pt-1 space-y-2">
      <span className="block font-ui text-[10px] tracking-wider text-textsec uppercase">Backdrops</span>
      <span className="block text-[10px] text-textdim font-body">
        Scene art shown behind the chat. Name files after their scene — e.g.{' '}
        <span className="text-textsec">city_day.png</span>, <span className="text-textsec">forest_night.png</span> —
        the location words + day/night are matched to the narrator's declared scene automatically.
      </span>
      {backdrops.length > 0 && (
        <div className="grid grid-cols-3 gap-2">
          {backdrops.map((b) => (
            <div key={b.file} className="relative border border-line rounded overflow-hidden group">
              <img src={b.url} alt={b.file} className="w-full h-16 object-cover" loading="lazy" />
              <span className="block px-1.5 py-0.5 font-ui text-[8px] tracking-wider text-textdim truncate">{b.file}</span>
              <button
                type="button"
                title={`Delete ${b.file}`}
                className="absolute top-0.5 right-0.5 w-5 h-5 flex items-center justify-center rounded bg-bg0/80 text-textdim hover:text-danger opacity-0 group-hover:opacity-100 transition-opacity"
                disabled={busy}
                onClick={() => void remove(b.file)}
              >&times;</button>
            </div>
          ))}
        </div>
      )}
      {backdrops.length === 0 && (
        <span className="block text-[10px] text-textdim font-body italic">No backdrops yet — the chat shows the plain dark background.</span>
      )}
      <input
        ref={fileRef}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        className="hidden"
        onChange={(e) => { const f = e.target.files?.[0]; if (f) void upload(f) }}
      />
      <button
        type="button"
        disabled={busy}
        className="font-ui text-[9px] tracking-wider text-textsec border border-line px-3 py-1 hover:text-gold hover:border-line2 transition-colors disabled:opacity-40"
        onClick={() => fileRef.current?.click()}
      >
        + ADD BACKDROP
      </button>
    </div>
  )
}

function ModelPicker({ value, onChange, models, showAll, toolsOnly = true, blankLabel = 'Use main model' }: {
  value: string
  onChange: (v: string) => void
  models: OpenRouterModel[]
  showAll: boolean
  toolsOnly?: boolean
  blankLabel?: string
}) {
  if (models.length === 0) {
    return (
      <input
        className="w-full border border-line2 bg-bg0 px-2 py-1 text-sm font-body text-text outline-none focus:bg-bg2"
        placeholder="(use main model)"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    )
  }
  const list = showAll || !toolsOnly ? models : models.filter((m) => m.supportsTools)
  return (
    <select
      className="w-full border border-line2 bg-bg0 px-2 py-1 text-sm font-body text-text outline-none"
      value={value}
      onChange={(e) => onChange(e.target.value)}
    >
      <option value="">{blankLabel}</option>
      {/* Keep a stored id selectable even if it's missing from the list */}
      {value && !list.some((m) => m.id === value) && (
        <option value={value}>{value}</option>
      )}
      {list.map((m) => (
        <option key={m.id} value={m.id}>{m.name}{m.supportsTools ? '' : ' (no tools)'}</option>
      ))}
    </select>
  )
}

function CampaignSection() {
  const campaigns = useCampaignsStore((s) => s.campaigns)
  const activeId = useCampaignsStore((s) => s.activeId)
  const busy = useCampaignsStore((s) => s.busy)
  const create = useCampaignsStore((s) => s.create)
  const load = useCampaignsStore((s) => s.load)
  const rename = useCampaignsStore((s) => s.rename)
  const remove = useCampaignsStore((s) => s.remove)

  const [newModalOpen, setNewModalOpen] = useState(false)
  const [pendingSwitch, setPendingSwitch] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [importing, setImporting] = useState(false)
  const importRef = useRef<HTMLInputElement>(null)
  const fetchCampaigns = useCampaignsStore((s) => s.fetch)
  const active = campaigns.find((c) => c.id === activeId)

  const handleExport = () => {
    if (activeId) window.open(`/api/campaigns/${activeId}/export`, '_blank')
  }

  const handleImport = async (file: File) => {
    setImporting(true)
    try {
      const form = new FormData()
      form.append('file', file)
      const res = await fetch('/api/campaigns/import', { method: 'POST', body: form })
      if (!res.ok) throw new Error(await res.text().catch(() => 'Import failed'))
      await fetchCampaigns()
    } finally {
      setImporting(false)
    }
  }

  const inputCls = 'w-full border border-line2 bg-bg0 px-2 py-1 text-sm font-body text-text outline-none focus:bg-bg2'

  return (
    <div className="space-y-2">
      <label className="block">
        <span className="text-[11px] text-textdim font-body">Active Campaign</span>
        <select
          className="w-full border border-line2 bg-bg0 px-2 py-1 text-sm font-body text-text outline-none"
          value={activeId ?? ''}
          disabled={busy}
          onChange={(e) => { if (e.target.value && e.target.value !== activeId) setPendingSwitch(e.target.value) }}
        >
          {campaigns.map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
      </label>

      {active && (
        <label className="block">
          <span className="text-[11px] text-textdim font-body">Rename</span>
          <input
            key={active.id}
            className={inputCls}
            defaultValue={active.name}
            onBlur={(e) => { const v = e.target.value.trim(); if (v && v !== active.name) rename(active.id, v) }}
          />
        </label>
      )}

      <div className="pt-1">
        <button
          type="button"
          disabled={busy}
          className="w-full font-ui text-[10px] tracking-wider bg-golddeep text-bg0 px-3 py-2 hover:bg-gold transition-colors disabled:opacity-40"
          onClick={() => setNewModalOpen(true)}
        >
          + NEW CAMPAIGN
        </button>
      </div>

      <div className="flex flex-wrap gap-2 pt-1">
        <button
          type="button"
          disabled={busy || !activeId}
          className="font-ui text-[10px] tracking-wider text-textsec border border-line px-3 py-1.5 hover:border-line2 hover:text-text transition-colors disabled:opacity-40"
          onClick={handleExport}
        >
          EXPORT (.zip)
        </button>
        <button
          type="button"
          disabled={busy || importing}
          className="font-ui text-[10px] tracking-wider text-textsec border border-line px-3 py-1.5 hover:border-line2 hover:text-text transition-colors disabled:opacity-40"
          onClick={() => importRef.current?.click()}
        >
          {importing ? 'IMPORTING…' : 'IMPORT (.zip)'}
        </button>
        <button
          type="button"
          disabled={busy || campaigns.length <= 1}
          className="font-ui text-[10px] tracking-wider text-danger border border-danger-border px-3 py-1.5 hover:text-danger-hover transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
          onClick={() => setConfirmDelete(true)}
        >
          DELETE
        </button>
        <input
          ref={importRef}
          type="file"
          accept=".zip"
          title="Import campaign zip"
          className="hidden"
          onChange={(e) => { const f = e.target.files?.[0]; if (f) handleImport(f); e.target.value = '' }}
        />
      </div>

      <p className="text-[10px] text-textdim font-body">
        Switching loads the campaign's latest adventure. A new campaign opens in Edit Mode to build its world. Export bundles the world + its adventures + portraits into a shareable zip; import always creates a new campaign.
      </p>

      {pendingSwitch && (
        <ConfirmDialog
          confirmLabel="SWITCH"
          message={`Switch to "${campaigns.find((c) => c.id === pendingSwitch)?.name}"? Your current adventure is saved first.`}
          onConfirm={() => { load(pendingSwitch); setPendingSwitch(null) }}
          onCancel={() => setPendingSwitch(null)}
        />
      )}
      {confirmDelete && active && (
        <ConfirmDialog
          confirmLabel="DELETE"
          message={`Delete campaign "${active.name}" and ALL of its adventures? This cannot be undone.`}
          onConfirm={() => { remove(active.id); setConfirmDelete(false) }}
          onCancel={() => setConfirmDelete(false)}
        />
      )}
      {newModalOpen && (
        <NewCampaignModal
          busy={busy}
          onCreate={(name, template) => { setNewModalOpen(false); create(name || undefined, template) }}
          onCancel={() => setNewModalOpen(false)}
        />
      )}
    </div>
  )
}

interface CampaignTemplate { id: string; name: string; description: string }

function NewCampaignModal({ busy, onCreate, onCancel }: {
  busy: boolean
  onCreate: (name: string, template: string) => void
  onCancel: () => void
}) {
  const [name, setName] = useState('')
  const [templates, setTemplates] = useState<CampaignTemplate[]>([])
  const [templateId, setTemplateId] = useState('empty')

  useEffect(() => {
    api.get<{ templates: CampaignTemplate[] }>('/campaigns/templates')
      .then((r) => {
        setTemplates(r.templates)
        if (r.templates.length && !r.templates.some((t) => t.id === 'empty')) {
          setTemplateId(r.templates[0].id)
        }
      })
      .catch(() => setTemplates([]))
  }, [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onCancel() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onCancel])

  const chosen = templates.find((t) => t.id === templateId)

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onCancel}>
      <div
        className="w-full max-w-sm border border-line2 bg-bg1 rounded-md p-5 space-y-4"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="font-disp text-[18px] pt-[2px] leading-none text-text">NEW CAMPAIGN</h3>

        <label className="block space-y-1">
          <span className="text-[11px] text-textdim font-body">Name</span>
          <input
            autoFocus
            className="w-full border border-line2 bg-bg0 px-2 py-1.5 text-sm font-body text-text outline-none focus:bg-bg2"
            placeholder="My Campaign"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !busy) onCreate(name.trim(), templateId) }}
          />
        </label>

        <label className="block space-y-1">
          <span className="text-[11px] text-textdim font-body">Template</span>
          <select
            className="w-full border border-line2 bg-bg0 px-2 py-1.5 text-sm font-body text-text outline-none"
            value={templateId}
            onChange={(e) => setTemplateId(e.target.value)}
          >
            {templates.map((t) => (
              <option key={t.id} value={t.id}>{t.name}</option>
            ))}
          </select>
          {chosen?.description && (
            <span className="block text-[10px] text-textdim font-body leading-relaxed pt-0.5">{chosen.description}</span>
          )}
        </label>

        <div className="flex items-center justify-end gap-2 pt-1">
          <button
            type="button"
            className="font-ui text-[10px] tracking-wider text-textsec border border-line px-3 py-1.5 hover:border-line2 hover:text-text transition-colors"
            onClick={onCancel}
          >
            CANCEL
          </button>
          <button
            type="button"
            disabled={busy}
            className="font-ui text-[10px] tracking-wider bg-golddeep text-bg0 px-4 py-1.5 hover:bg-gold transition-colors disabled:opacity-40"
            onClick={() => onCreate(name.trim(), templateId)}
          >
            CREATE
          </button>
        </div>
      </div>
    </div>
  )
}

function LorebookInjectionConfig() {
  const config = useLoreStore((s) => s.config)
  const saveConfig = useLoreStore((s) => s.saveConfig)

  if (!config) {
    return <p className="text-[11px] text-textdim font-body">Loading…</p>
  }

  const handleOrder = (cat: LoreCategory, value: number) => {
    saveConfig({
      injectionOrder: { ...config.injectionOrder, [cat]: value },
    })
  }

  const handlePosition = (
    cat: LoreCategory,
    value: LorebookConfig['injectionPosition'][LoreCategory],
  ) => {
    saveConfig({
      injectionPosition: { ...config.injectionPosition, [cat]: value },
    })
  }

  return (
    <div className="space-y-2">
      <div className="grid grid-cols-[1fr_auto_auto] gap-2 items-center">
        <span className="font-ui text-[9px] tracking-wider text-textdim uppercase">Category</span>
        <span className="font-ui text-[9px] tracking-wider text-textdim uppercase text-center w-[64px]">Order</span>
        <span className="font-ui text-[9px] tracking-wider text-textdim uppercase text-center w-[110px]">Position</span>
        {LORE_CATEGORIES.map(({ id, label }) => (
          <FragmentRow
            key={id}
            label={label}
            order={config.injectionOrder[id] ?? 0}
            position={config.injectionPosition[id] ?? 'top'}
            onOrder={(v) => handleOrder(id, v)}
            onPosition={(v) => handlePosition(id, v)}
          />
        ))}
      </div>
      <label className="flex items-center gap-2 pt-1">
        <span className="font-body text-sm text-text">Keyword scan depth</span>
        <input
          type="number"
          min={0}
          max={20}
          title="How many recent turns (besides the new message) are scanned for lore keywords"
          className="w-[64px] border border-line bg-bg0 px-2 py-1 text-sm font-body text-text outline-none focus:border-line2 focus:bg-bg2"
          value={config.scanDepth ?? 3}
          onChange={(e) => saveConfig({ scanDepth: Math.max(0, Math.min(Number(e.target.value) || 0, 20)) })}
        />
        <span className="text-[10px] text-textdim font-body">recent turns scanned for keywords (0 = newest message only)</span>
      </label>
    </div>
  )
}

function FragmentRow({
  label,
  order,
  position,
  onOrder,
  onPosition,
}: {
  label: string
  order: number
  position: LorebookConfig['injectionPosition'][LoreCategory]
  onOrder: (v: number) => void
  onPosition: (v: LorebookConfig['injectionPosition'][LoreCategory]) => void
}) {
  return (
    <>
      <span className="font-body text-sm text-text">{label}</span>
      <input
        type="number"
        title={`${label} injection order`}
        className="w-[64px] border border-line bg-bg0 px-2 py-1 text-sm font-body text-text outline-none focus:border-line2 focus:bg-bg2"
        value={order}
        onChange={(e) => onOrder(Number(e.target.value) || 0)}
      />
      <select
        title={`${label} injection position`}
        className="w-[110px] border border-line bg-bg0 px-2 py-1 text-sm font-body text-text outline-none focus:border-line2"
        value={position}
        onChange={(e) => onPosition(e.target.value as LorebookConfig['injectionPosition'][LoreCategory])}
      >
        {INJECTION_POSITIONS.map((p) => (
          <option key={p} value={p}>{p}</option>
        ))}
      </select>
    </>
  )
}

function Section({
  title,
  defaultOpen = false,
  onReset,
  children,
}: {
  title: string
  defaultOpen?: boolean
  onReset?: () => void
  children: React.ReactNode
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <section className="border border-line rounded-md">
      <div className="w-full flex items-center justify-between px-3 py-2 hover:bg-bg2 transition-colors">
        <button
          type="button"
          className="flex-1 flex items-center gap-2 text-left"
          aria-expanded={open}
          onClick={() => setOpen((o) => !o)}
        >
          <span className="font-ui text-[10px] tracking-wider text-textsec uppercase">{title}</span>
        </button>
        <div className="flex items-center gap-3">
          {onReset && (
            <button
              type="button"
              className="font-ui text-[9px] tracking-wider text-textdim hover:text-gold uppercase transition-colors"
              onClick={(e) => { e.stopPropagation(); onReset() }}
              title="Reset this section to defaults"
            >
              Reset to defaults
            </button>
          )}
          <button
            type="button"
            className="font-ui text-[10px] text-textdim"
            aria-label={open ? 'Collapse' : 'Expand'}
            onClick={() => setOpen((o) => !o)}
          >
            {open ? '−' : '+'}
          </button>
        </div>
      </div>
      {open && <div className="px-3 pb-3 pt-1 space-y-2">{children}</div>}
    </section>
  )
}

// A lighter, nested collapsible used to differentiate sub-sections within a
// top-level Section. Open by default so the group's contents are visible.
function SubSection({
  title,
  defaultOpen = true,
  children,
}: {
  title: string
  defaultOpen?: boolean
  children: React.ReactNode
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="border-l-2 border-line pl-2.5">
      <button
        type="button"
        className="w-full flex items-center justify-between py-1 text-left"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        <span className="font-ui text-[9px] tracking-wider text-textdim uppercase">{title}</span>
        <span className="font-ui text-[9px] text-textdim">{open ? '−' : '+'}</span>
      </button>
      {open && <div className="pt-1 pb-1 space-y-2">{children}</div>}
    </div>
  )
}

function AdventureManagement() {
  const fetchParty = usePartyStore((s) => s.fetchAll)
  const fetchNarrator = useNarratorStore((s) => s.fetchConfig)
  const fetchChat = useChatStore((s) => s.fetchHistory)
  const fetchSettings = useSettingsStore((s) => s.fetchSettings)
  const fetchLoreConfig = useLoreStore((s) => s.fetchConfig)
  const fetchLoreEntries = useLoreStore((s) => s.fetchEntries)
  const fetchInventory = useItemsStore((s) => s.fetchInventory)
  const importRef = useRef<HTMLInputElement>(null)
  const [confirmAction, setConfirmAction] = useState<{ message: string; action: () => void } | null>(null)

  const refetchAll = async () => {
    await Promise.all([
      fetchParty(),
      fetchNarrator(),
      fetchChat(),
      fetchSettings(),
      fetchLoreConfig(),
      fetchLoreEntries(),
      fetchInventory(),
    ])
  }

  const handleExport = async () => {
    const data = await api.get<object>('/adventure/export')
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `wayward-adventure-${new Date().toISOString().slice(0, 10)}.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  const handleImport = async (file: File) => {
    const text = await file.text()
    const data = JSON.parse(text)
    setConfirmAction({
      message: 'Import this adventure? All current progress will be replaced.',
      action: async () => {
        await api.post('/adventure/import', data)
        await refetchAll()
      },
    })
  }

  const handleReset = () => {
    setConfirmAction({
      message: 'Start a new adventure? All current progress will be lost.',
      action: async () => {
        await api.post('/adventure/reset', {})
        await refetchAll()
      },
    })
  }

  return (
    <>
      <section className="space-y-2 border-t border-line pt-4 mt-2">
        <h3 className="font-ui text-[10px] tracking-wider text-textsec uppercase">Adventure</h3>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className="font-ui text-[10px] text-textsec border border-line px-3 py-1.5 hover:border-line2 hover:text-text transition-colors"
            onClick={handleExport}
          >
            EXPORT
          </button>
          <button
            type="button"
            className="font-ui text-[10px] text-textsec border border-line px-3 py-1.5 hover:border-line2 hover:text-text transition-colors"
            onClick={() => importRef.current?.click()}
          >
            IMPORT
          </button>
          <button
            type="button"
            className="font-ui text-[10px] text-textsec border border-line px-3 py-1.5 hover:border-line2 hover:text-text transition-colors"
            onClick={handleReset}
          >
            NEW ADVENTURE
          </button>
        </div>
        <input
          ref={importRef}
          type="file"
          accept=".json"
          title="Import adventure file"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0]
            if (file) handleImport(file)
            e.target.value = ''
          }}
        />
      </section>
      {confirmAction && (
        <ConfirmDialog
          message={confirmAction.message}
          onConfirm={() => { confirmAction.action(); setConfirmAction(null) }}
          onCancel={() => setConfirmAction(null)}
        />
      )}
    </>
  )
}

function Slider({ label, value, min, max, step, defaultValue, onChange }: {
  label: string; value: number; min: number; max: number; step: number; defaultValue?: number; onChange: (v: number) => void
}) {
  const v = value ?? defaultValue ?? min
  return (
    <label className="block">
      <span className="text-[11px] text-textdim font-body">{label} ({v.toFixed(2)})</span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        className="w-full"
        value={v}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </label>
  )
}
