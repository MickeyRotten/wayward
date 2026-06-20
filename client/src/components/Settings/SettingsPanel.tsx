import { useEffect, useRef, useState } from 'react'
import { useSettingsStore } from '../../state/settingsStore'
import { useNarratorStore } from '../../state/narratorStore'
import { usePartyStore } from '../../state/partyStore'
import { useChatStore } from '../../state/chatStore'
import { ConfirmDialog } from '../ConfirmDialog'
import { api } from '../../lib/api'

export function SettingsPanel({ onClose }: { onClose: () => void }) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

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
  const [instructions, setInstructions] = useState(narrator.instructions)
  const [scenario, setScenario] = useState(narrator.scenario)

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
  }, [settings.modelId, settings.temperature, settings.topP, settings.minP, settings.topK, settings.frequencyPenalty, settings.presencePenalty, settings.repetitionPenalty, settings.maxTokensResponse])

  useEffect(() => {
    setInstructions(narrator.instructions)
    setScenario(narrator.scenario)
  }, [narrator.instructions, narrator.scenario])

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
    })
    await narrator.saveInstructions(instructions)
    await narrator.saveScenario(scenario)
    onClose()
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-bg0/80">
      <div className="bg-bg1 border-[1.5px] border-line2 w-[560px] max-h-[85vh] overflow-y-auto p-6 space-y-5">
        <div className="flex items-start justify-between">
          <h2 className="font-disp text-[28px] pt-[4px]">Settings</h2>
          <button className="font-ui text-[10px] text-textdim hover:text-text" onClick={onClose}>
            CLOSE
          </button>
        </div>

        {/* API Key */}
        <section className="space-y-2">
          <h3 className="font-ui text-[10px] tracking-wider text-textsec uppercase">OpenRouter</h3>
          <label className="block">
            <span className="text-[11px] text-textdim font-body">
              API Key {settings.apiKeySet && <span className="text-textsec">(set)</span>}
            </span>
            <input
              type="password"
              className="w-full border-[1.5px] border-line2 bg-bg0 px-2 py-1 text-sm font-body text-text outline-none focus:bg-bg2"
              placeholder={settings.apiKeySet ? '••••••••' : 'Enter your OpenRouter API key'}
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
            />
          </label>

          {/* Model picker */}
          <label className="block">
            <span className="text-[11px] text-textdim font-body">Model</span>
            {settings.availableModels.length > 0 ? (
              <select
                className="w-full border-[1.5px] border-line2 bg-bg0 px-2 py-1 text-sm font-body text-text outline-none"
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
                {settings.availableModels.map((m) => (
                  <option key={m.id} value={m.id}>{m.name}</option>
                ))}
              </select>
            ) : (
              <input
                className="w-full border-[1.5px] border-line2 bg-bg0 px-2 py-1 text-sm font-body text-text outline-none focus:bg-bg2"
                placeholder="e.g. anthropic/claude-sonnet-4.6"
                value={modelId}
                onChange={(e) => setModelId(e.target.value)}
              />
            )}
          </label>

          <div className="grid grid-cols-2 gap-3">
            <Slider label="Temperature" value={temperature} min={0} max={2} step={0.05} onChange={setTemperature} />
            <Slider label="Top P" value={topP} min={0} max={1} step={0.05} onChange={setTopP} />
            <Slider label="Min P" value={minP} min={0} max={1} step={0.05} onChange={setMinP} />
            <label className="block">
              <span className="text-[11px] text-textdim font-body">Top K ({topK})</span>
              <input
                type="number"
                className="w-full border-[1.5px] border-line bg-bg0 px-2 py-1 text-sm font-body text-text outline-none focus:border-line2 focus:bg-bg2"
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
                className="w-full border-[1.5px] border-line bg-bg0 px-2 py-1 text-sm font-body text-text outline-none focus:border-line2 focus:bg-bg2"
                value={maxTokens}
                onChange={(e) => setMaxTokens(Number(e.target.value) || 1000)}
              />
            </label>
          </div>

          <p className="text-[10px] text-textdim font-body">
            Max context: {settings.maxContextTokens.toLocaleString()} tokens
          </p>

          {settings.apiKeySet && settings.availableModels.length === 0 && (
            <button
              className="font-ui text-[10px] text-textsec border-[1.5px] border-line px-3 py-1 hover:border-line2"
              onClick={() => settings.fetchModels()}
            >
              LOAD MODELS
            </button>
          )}
        </section>

        {/* Narrator Instructions */}
        <section className="space-y-2">
          <h3 className="font-ui text-[10px] tracking-wider text-textsec uppercase">Narrator Instructions</h3>
          <textarea
            className="w-full border-[1.5px] border-line2 bg-bg0 px-2 py-1 text-sm font-body text-text outline-none focus:bg-bg2 resize-y min-h-[100px]"
            rows={5}
            value={instructions}
            onChange={(e) => setInstructions(e.target.value)}
          />
        </section>

        {/* Scenario */}
        <section className="space-y-2">
          <h3 className="font-ui text-[10px] tracking-wider text-textsec uppercase">Scenario</h3>
          <textarea
            className="w-full border-[1.5px] border-line2 bg-bg0 px-2 py-1 text-sm font-body text-text outline-none focus:bg-bg2 resize-y min-h-[100px]"
            rows={5}
            value={scenario}
            onChange={(e) => setScenario(e.target.value)}
          />
        </section>

        <div className="flex gap-3 pt-2">
          <button
            type="button"
            className="font-ui text-[10px] bg-golddeep text-bg0 px-4 py-2 hover:bg-gold transition-colors"
            onClick={saveAll}
          >
            SAVE
          </button>
          <button
            type="button"
            className="font-ui text-[10px] text-textdim border-[1.5px] border-line px-4 py-2 hover:border-line2"
            onClick={onClose}
          >
            CANCEL
          </button>
        </div>

        {/* Adventure Management */}
        <AdventureManagement onClose={onClose} />
      </div>
    </div>
  )
}

function AdventureManagement({ onClose }: { onClose: () => void }) {
  const fetchParty = usePartyStore((s) => s.fetchAll)
  const fetchNarrator = useNarratorStore((s) => s.fetchConfig)
  const fetchChat = useChatStore((s) => s.fetchHistory)
  const fetchSettings = useSettingsStore((s) => s.fetchSettings)
  const importRef = useRef<HTMLInputElement>(null)
  const [confirmAction, setConfirmAction] = useState<{ message: string; action: () => void } | null>(null)

  const refetchAll = async () => {
    await Promise.all([fetchParty(), fetchNarrator(), fetchChat(), fetchSettings()])
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
        onClose()
      },
    })
  }

  const handleReset = () => {
    setConfirmAction({
      message: 'Start a new adventure? All current progress will be lost.',
      action: async () => {
        await api.post('/adventure/reset', {})
        await refetchAll()
        onClose()
      },
    })
  }

  return (
    <>
      <section className="space-y-2 border-t-[1.5px] border-line pt-4">
        <h3 className="font-ui text-[10px] tracking-wider text-textsec uppercase">Adventure</h3>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className="font-ui text-[10px] text-textsec border-[1.5px] border-line px-3 py-1.5 hover:border-line2 hover:text-text transition-colors"
            onClick={handleExport}
          >
            EXPORT
          </button>
          <button
            type="button"
            className="font-ui text-[10px] text-textsec border-[1.5px] border-line px-3 py-1.5 hover:border-line2 hover:text-text transition-colors"
            onClick={() => importRef.current?.click()}
          >
            IMPORT
          </button>
          <button
            type="button"
            className="font-ui text-[10px] text-textsec border-[1.5px] border-line px-3 py-1.5 hover:border-line2 hover:text-text transition-colors"
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
