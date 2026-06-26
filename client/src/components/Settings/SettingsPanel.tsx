import { useEffect, useRef, useState } from 'react'
import { useSettingsStore } from '../../state/settingsStore'
import { useNarratorStore } from '../../state/narratorStore'
import { usePartyStore } from '../../state/partyStore'
import { useChatStore } from '../../state/chatStore'
import { useLoreStore } from '../../state/loreStore'
import { useItemsStore } from '../../state/itemsStore'
import { ConfirmDialog } from '../ConfirmDialog'
import { ExpandableTextarea } from '../common/ExpandableTextarea'
import { api } from '../../lib/api'
import type { LoreCategory, LorebookConfig } from '@shared/types/models'

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

  const [apiKey, setApiKey] = useState('')
  const [modelId, setModelId] = useState(settings.modelId)
  const [temperature, setTemperature] = useState(settings.temperature)
  const [topP, setTopP] = useState(settings.topP)
  const [minP, setMinP] = useState(settings.minP)
  const [topK, setTopK] = useState(settings.topK)
  const [freqPen, setFreqPen] = useState(settings.frequencyPenalty)
  const [presPen, setPresPen] = useState(settings.presencePenalty)
  const [repPen, setRepPen] = useState(settings.repetitionPenalty)
  const [maxTokens, setMaxTokens] = useState(settings.maxTokensResponse)
  const [maxCarrySlots, setMaxCarrySlots] = useState(settings.maxCarrySlots)
  const [maxPartySize, setMaxPartySize] = useState(settings.maxPartySize)
  const [maxToolRounds, setMaxToolRounds] = useState(settings.maxToolRounds)
  const [useTools, setUseTools] = useState(settings.useTools)
  const [wbMode, setWbMode] = useState(settings.worldbuildingMode)
  const [wbModelId, setWbModelId] = useState(settings.worldbuildingModelId)
  const [showAllModels, setShowAllModels] = useState(false)
  const [instructions, setInstructions] = useState(narrator.instructions)
  const [firstMessage, setFirstMessage] = useState(narrator.firstMessage)
  const [spotlightRule, setSpotlightRule] = useState(narrator.spotlightRule)
  const [postHistory, setPostHistory] = useState(narrator.postHistoryInstructions)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    setModelId(settings.modelId)
    setTemperature(settings.temperature)
    setTopP(settings.topP)
    setMinP(settings.minP)
    setTopK(settings.topK)
    setFreqPen(settings.frequencyPenalty)
    setPresPen(settings.presencePenalty)
    setRepPen(settings.repetitionPenalty)
    setMaxTokens(settings.maxTokensResponse)
    setMaxCarrySlots(settings.maxCarrySlots)
    setMaxPartySize(settings.maxPartySize)
    setMaxToolRounds(settings.maxToolRounds)
    setUseTools(settings.useTools)
    setWbMode(settings.worldbuildingMode)
    setWbModelId(settings.worldbuildingModelId)
  }, [settings.modelId, settings.temperature, settings.topP, settings.minP, settings.topK, settings.frequencyPenalty, settings.presencePenalty, settings.repetitionPenalty, settings.maxTokensResponse, settings.maxCarrySlots, settings.maxPartySize, settings.maxToolRounds, settings.useTools, settings.worldbuildingMode, settings.worldbuildingModelId])

  useEffect(() => {
    setInstructions(narrator.instructions)
    setFirstMessage(narrator.firstMessage)
    setSpotlightRule(narrator.spotlightRule)
    setPostHistory(narrator.postHistoryInstructions)
  }, [narrator.instructions, narrator.firstMessage, narrator.spotlightRule, narrator.postHistoryInstructions])

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
      ...(apiKey ? { apiKey } : {}),
      modelId,
      temperature,
      topP,
      minP,
      topK,
      frequencyPenalty: freqPen,
      presencePenalty: presPen,
      repetitionPenalty: repPen,
      maxTokensResponse: maxTokens,
      maxContextTokens: settings.maxContextTokens,
      maxCarrySlots,
      maxPartySize,
      maxToolRounds,
      useTools,
      worldbuildingMode: wbMode,
      worldbuildingModelId: wbModelId,
    })
    await narrator.save({ instructions, firstMessage, spotlightRule, postHistoryInstructions: postHistory })
    // Carry-slot capacity is derived server-side; refetch inventory so the
    // Items panel reflects the new max immediately.
    await useItemsStore.getState().fetchInventory()
    setApiKey('')
    setSaved(true)
    setTimeout(() => setSaved(false), 1500)
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-5 pt-5 pb-3">
        <h2 className="font-disp text-[24px] pt-[3px] leading-none text-text">CONFIG</h2>
      </div>

      <div className="flex-1 overflow-y-auto px-4 pb-4 space-y-2">
        {/* API & Model */}
        <Section title="API & Model" defaultOpen>
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
          </label>
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
                value={modelId}
                onChange={(e) => {
                  setModelId(e.target.value)
                  const model = settings.availableModels.find((m) => m.id === e.target.value)
                  if (model) {
                    settings.saveSettings({ modelId: e.target.value, maxContextTokens: model.contextLength })
                  }
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
                placeholder="e.g. anthropic/claude-sonnet-4.6"
                value={modelId}
                onChange={(e) => setModelId(e.target.value)}
              />
            )}
          </label>

          {(() => {
            const selected = settings.availableModels.find((m) => m.id === modelId)
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
          </div>

          <p className="text-[10px] text-textdim font-body">
            Max context: {settings.maxContextTokens.toLocaleString()} tokens
          </p>

          <div className="grid grid-cols-2 gap-3 pt-1">
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
          </div>
          <p className="text-[10px] text-textdim font-body">
            When on, the narrator calls tools (grant/equip/scene/etc.) over up to this many round-trips per turn. When off, it uses the legacy text-block protocol.
          </p>
        </Section>

        {/* Narration */}
        <Section title="Narration">
          <label className="block space-y-1">
            <span className="font-ui text-[10px] tracking-wider text-textsec uppercase">Narrator Instructions</span>
            <ExpandableTextarea
              label="Narrator Instructions"
              className="w-full border border-line2 bg-bg0 px-2 py-1 text-sm font-body text-text outline-none focus:bg-bg2 resize-y min-h-[100px]"
              rows={5}
              value={instructions}
              onChange={setInstructions}
            />
          </label>

          <label className="block space-y-1">
            <span className="font-ui text-[10px] tracking-wider text-textsec uppercase">First Message</span>
            <ExpandableTextarea
              label="First Message"
              className="w-full border border-line2 bg-bg0 px-2 py-1 text-sm font-body text-text outline-none focus:bg-bg2 resize-y min-h-[80px]"
              rows={4}
              value={firstMessage}
              placeholder="The opening narration shown before the player's first turn."
              onChange={setFirstMessage}
            />
            <span className="text-[10px] text-textdim font-body">
              Shown as the drop-capped opening message and included in context.
            </span>
          </label>

          <p className="text-[10px] text-textdim font-body">
            The scenario is now a locked entry in Lorebook → World.
          </p>
        </Section>

        {/* Advanced */}
        <Section title="Advanced">
          <label className="block space-y-1">
            <span className="font-ui text-[10px] tracking-wider text-textsec uppercase">Spotlight Rule</span>
            <ExpandableTextarea
              label="Spotlight Rule"
              className="w-full border border-line bg-bg0 px-2 py-1 text-[12px] font-body text-text2 outline-none focus:bg-bg2 resize-y min-h-[80px]"
              rows={4}
              value={spotlightRule}
              onChange={setSpotlightRule}
            />
            <span className="text-[10px] text-textdim font-body">
              Governs when party members speak.
            </span>
          </label>

          <label className="block space-y-1">
            <span className="font-ui text-[10px] tracking-wider text-textsec uppercase">Post-History Instructions</span>
            <ExpandableTextarea
              label="Post-History Instructions"
              className="w-full border border-line2 bg-bg0 px-2 py-1 text-sm font-body text-text outline-none focus:bg-bg2 resize-y min-h-[80px]"
              rows={4}
              value={postHistory}
              placeholder="Added to the very end of the prompt, right before your message. Empty by default."
              onChange={setPostHistory}
            />
            <span className="text-[10px] text-textdim font-body">
              Always injected last, immediately before your input.
            </span>
          </label>
        </Section>

        {/* World-building (Chronicler) */}
        <Section title="World-building">
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
              The Chronicler reviews each turn and records new lore, quests, and companions. New party members always need your approval, even in Auto.
            </span>
          </label>

          <label className="block">
            <span className="text-[11px] text-textdim font-body">Chronicler Model</span>
            {settings.availableModels.length > 0 ? (
              <select
                className="w-full border border-line2 bg-bg0 px-2 py-1 text-sm font-body text-text outline-none"
                value={wbModelId}
                onChange={(e) => setWbModelId(e.target.value)}
              >
                <option value="">Use main model</option>
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
                placeholder="(use main model)"
                value={wbModelId}
                onChange={(e) => setWbModelId(e.target.value)}
              />
            )}
            <span className="text-[10px] text-textdim font-body">
              Optional. Leave as "Use main model", or pick a cheaper/faster tool-capable model for bookkeeping.
            </span>
          </label>
        </Section>

        {/* Adventure Settings (inventory + party) */}
        <Section title="Adventure Settings">
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
          <label className="block">
            <span className="text-[11px] text-textdim font-body">Max Carry Slots</span>
            <input
              type="number"
              min={1}
              className="w-full border border-line bg-bg0 px-2 py-1 text-sm font-body text-text outline-none focus:border-line2 focus:bg-bg2"
              value={maxCarrySlots}
              onChange={(e) => setMaxCarrySlots(Math.max(1, Number(e.target.value) || 12))}
            />
            <span className="text-[10px] text-textdim font-body">
              How many distinct item stacks the party can carry.
            </span>
          </label>
        </Section>

        {/* Lorebook Injection */}
        <Section title="Lorebook Injection">
          <LorebookInjectionConfig />
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
  children,
}: {
  title: string
  defaultOpen?: boolean
  children: React.ReactNode
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <section className="border border-line rounded-md">
      <button
        type="button"
        className="w-full flex items-center justify-between px-3 py-2 text-left hover:bg-bg2 transition-colors"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        <span className="font-ui text-[10px] tracking-wider text-textsec uppercase">{title}</span>
        <span className="font-ui text-[10px] text-textdim">{open ? '−' : '+'}</span>
      </button>
      {open && <div className="px-3 pb-3 pt-1 space-y-2">{children}</div>}
    </section>
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
