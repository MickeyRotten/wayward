import { useEffect, useState } from 'react'
import { useSettingsStore } from '../../state/settingsStore'
import { useNarratorStore } from '../../state/narratorStore'

export function SettingsPanel({ onClose }: { onClose: () => void }) {
  const settings = useSettingsStore()
  const narrator = useNarratorStore()

  const [apiKey, setApiKey] = useState('')
  const [modelId, setModelId] = useState(settings.modelId)
  const [temperature, setTemperature] = useState(settings.temperature)
  const [maxTokens, setMaxTokens] = useState(settings.maxTokensResponse)
  const [instructions, setInstructions] = useState(narrator.instructions)
  const [scenario, setScenario] = useState(narrator.scenario)

  useEffect(() => {
    setModelId(settings.modelId)
    setTemperature(settings.temperature)
    setMaxTokens(settings.maxTokensResponse)
  }, [settings.modelId, settings.temperature, settings.maxTokensResponse])

  useEffect(() => {
    setInstructions(narrator.instructions)
    setScenario(narrator.scenario)
  }, [narrator.instructions, narrator.scenario])

  const saveAll = async () => {
    await settings.saveSettings({
      ...(apiKey ? { apiKey } : {}),
      modelId,
      temperature,
      maxTokensResponse: maxTokens,
      maxContextTokens: settings.maxContextTokens,
    })
    await narrator.saveInstructions(instructions)
    await narrator.saveScenario(scenario)
    onClose()
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-border/20">
      <div className="bg-white border-[1.5px] border-border w-[560px] max-h-[85vh] overflow-y-auto p-6 space-y-5">
        <div className="flex items-start justify-between">
          <h2 className="font-h text-[28px] pt-[4px]">Settings</h2>
          <button className="font-ui text-[10px] text-text-dim hover:text-text" onClick={onClose}>
            CLOSE
          </button>
        </div>

        {/* API Key */}
        <section className="space-y-2">
          <h3 className="font-ui text-[10px] tracking-wider text-text-sec uppercase">OpenRouter</h3>
          <label className="block">
            <span className="text-[11px] text-text-dim font-b">
              API Key {settings.apiKeySet && <span className="text-text-sec">(set)</span>}
            </span>
            <input
              type="password"
              className="w-full border-[1.5px] border-border bg-white px-2 py-1 text-sm font-b text-text outline-none focus:bg-off2"
              placeholder={settings.apiKeySet ? '••••••••' : 'Enter your OpenRouter API key'}
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
            />
          </label>

          {/* Model picker */}
          <label className="block">
            <span className="text-[11px] text-text-dim font-b">Model</span>
            {settings.availableModels.length > 0 ? (
              <select
                className="w-full border-[1.5px] border-border bg-white px-2 py-1 text-sm font-b text-text outline-none"
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
                className="w-full border-[1.5px] border-border bg-white px-2 py-1 text-sm font-b text-text outline-none focus:bg-off2"
                placeholder="e.g. anthropic/claude-sonnet-4.6"
                value={modelId}
                onChange={(e) => setModelId(e.target.value)}
              />
            )}
          </label>

          <div className="grid grid-cols-2 gap-3">
            <label className="block">
              <span className="text-[11px] text-text-dim font-b">Temperature ({temperature.toFixed(1)})</span>
              <input
                type="range"
                min="0"
                max="2"
                step="0.1"
                className="w-full"
                value={temperature}
                onChange={(e) => setTemperature(Number(e.target.value))}
              />
            </label>
            <label className="block">
              <span className="text-[11px] text-text-dim font-b">Max Tokens</span>
              <input
                type="number"
                className="w-full border-[1.5px] border-border bg-white px-2 py-1 text-sm font-b text-text outline-none focus:bg-off2"
                value={maxTokens}
                onChange={(e) => setMaxTokens(Number(e.target.value) || 1000)}
              />
            </label>
          </div>

          <p className="text-[10px] text-text-dim font-b">
            Max context: {settings.maxContextTokens.toLocaleString()} tokens
          </p>

          {settings.apiKeySet && settings.availableModels.length === 0 && (
            <button
              className="font-ui text-[10px] text-text-sec border-[1.5px] border-mid px-3 py-1 hover:border-border"
              onClick={() => settings.fetchModels()}
            >
              LOAD MODELS
            </button>
          )}
        </section>

        {/* Narrator Instructions */}
        <section className="space-y-2">
          <h3 className="font-ui text-[10px] tracking-wider text-text-sec uppercase">Narrator Instructions</h3>
          <textarea
            className="w-full border-[1.5px] border-border bg-white px-2 py-1 text-sm font-b text-text outline-none focus:bg-off2 resize-y min-h-[100px]"
            rows={5}
            value={instructions}
            onChange={(e) => setInstructions(e.target.value)}
          />
        </section>

        {/* Scenario */}
        <section className="space-y-2">
          <h3 className="font-ui text-[10px] tracking-wider text-text-sec uppercase">Scenario</h3>
          <textarea
            className="w-full border-[1.5px] border-border bg-white px-2 py-1 text-sm font-b text-text outline-none focus:bg-off2 resize-y min-h-[100px]"
            rows={5}
            value={scenario}
            onChange={(e) => setScenario(e.target.value)}
          />
        </section>

        <div className="flex gap-3 pt-2">
          <button
            className="font-ui text-[10px] bg-border text-white px-4 py-2 hover:bg-text transition-colors"
            onClick={saveAll}
          >
            SAVE
          </button>
          <button
            className="font-ui text-[10px] text-text-dim border-[1.5px] border-mid px-4 py-2 hover:border-border"
            onClick={onClose}
          >
            CANCEL
          </button>
        </div>
      </div>
    </div>
  )
}
