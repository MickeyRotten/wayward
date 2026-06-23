import { create } from 'zustand'
import type { OpenRouterModel, OpenRouterSettings } from '@shared/types/models'
import { api } from '../lib/api'

interface SettingsState {
  modelId: string
  temperature: number
  topP: number
  minP: number
  topK: number
  frequencyPenalty: number
  presencePenalty: number
  repetitionPenalty: number
  maxTokensResponse: number
  maxContextTokens: number
  maxCarrySlots: number
  maxPartySize: number
  apiKeySet: boolean
  availableModels: OpenRouterModel[]
  fetchSettings: () => Promise<void>
  saveSettings: (update: Partial<OpenRouterSettings> & { apiKey?: string }) => Promise<void>
  fetchModels: () => Promise<void>
}

type SettingsResponse = OpenRouterSettings & { apiKeySet: boolean }

function applyResponse(s: SettingsResponse) {
  return {
    modelId: s.modelId,
    temperature: s.temperature,
    topP: s.topP,
    minP: s.minP,
    topK: s.topK,
    frequencyPenalty: s.frequencyPenalty,
    presencePenalty: s.presencePenalty,
    repetitionPenalty: s.repetitionPenalty,
    maxTokensResponse: s.maxTokensResponse,
    maxContextTokens: s.maxContextTokens,
    maxCarrySlots: s.maxCarrySlots,
    maxPartySize: s.maxPartySize,
    apiKeySet: s.apiKeySet,
  }
}

export const useSettingsStore = create<SettingsState>((set, get) => ({
  modelId: '',
  temperature: 0.7,
  topP: 1.0,
  minP: 0.0,
  topK: 0,
  frequencyPenalty: 0.0,
  presencePenalty: 0.0,
  repetitionPenalty: 1.0,
  maxTokensResponse: 1000,
  maxContextTokens: 128000,
  maxCarrySlots: 12,
  maxPartySize: 3,
  apiKeySet: false,
  availableModels: [],

  fetchSettings: async () => {
    const s = await api.get<SettingsResponse>('/settings/openrouter')
    set(applyResponse(s))
  },

  saveSettings: async (update) => {
    const state = get()
    const payload = {
      modelId: update.modelId ?? state.modelId,
      temperature: update.temperature ?? state.temperature,
      topP: update.topP ?? state.topP,
      minP: update.minP ?? state.minP,
      topK: update.topK ?? state.topK,
      frequencyPenalty: update.frequencyPenalty ?? state.frequencyPenalty,
      presencePenalty: update.presencePenalty ?? state.presencePenalty,
      repetitionPenalty: update.repetitionPenalty ?? state.repetitionPenalty,
      maxTokensResponse: update.maxTokensResponse ?? state.maxTokensResponse,
      maxContextTokens: update.maxContextTokens ?? state.maxContextTokens,
      maxCarrySlots: update.maxCarrySlots ?? state.maxCarrySlots,
      maxPartySize: update.maxPartySize ?? state.maxPartySize,
      ...(update.apiKey !== undefined ? { apiKey: update.apiKey } : {}),
    }
    const s = await api.put<SettingsResponse>('/settings/openrouter', payload)
    set(applyResponse(s))
  },

  fetchModels: async () => {
    try {
      const models = await api.get<OpenRouterModel[]>('/models')
      set({ availableModels: models })
    } catch {
      // models endpoint may fail if no API key set
    }
  },
}))
