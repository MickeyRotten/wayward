import { create } from 'zustand'
import type { OpenRouterModel, OpenRouterSettings } from '@shared/types/models'
import { api } from '../lib/api'

interface SettingsState {
  modelId: string
  temperature: number
  maxTokensResponse: number
  maxContextTokens: number
  apiKeySet: boolean
  availableModels: OpenRouterModel[]
  fetchSettings: () => Promise<void>
  saveSettings: (update: Partial<OpenRouterSettings> & { apiKey?: string }) => Promise<void>
  fetchModels: () => Promise<void>
}

export const useSettingsStore = create<SettingsState>((set, get) => ({
  modelId: '',
  temperature: 0.7,
  maxTokensResponse: 1000,
  maxContextTokens: 128000,
  apiKeySet: false,
  availableModels: [],

  fetchSettings: async () => {
    const s = await api.get<OpenRouterSettings & { apiKeySet: boolean }>('/settings/openrouter')
    set({
      modelId: s.modelId,
      temperature: s.temperature,
      maxTokensResponse: s.maxTokensResponse,
      maxContextTokens: s.maxContextTokens,
      apiKeySet: s.apiKeySet,
    })
  },

  saveSettings: async (update) => {
    const state = get()
    const payload = {
      modelId: update.modelId ?? state.modelId,
      temperature: update.temperature ?? state.temperature,
      maxTokensResponse: update.maxTokensResponse ?? state.maxTokensResponse,
      maxContextTokens: update.maxContextTokens ?? state.maxContextTokens,
      ...(update.apiKey !== undefined ? { apiKey: update.apiKey } : {}),
    }
    const s = await api.put<OpenRouterSettings & { apiKeySet: boolean }>('/settings/openrouter', payload)
    set({
      modelId: s.modelId,
      temperature: s.temperature,
      maxTokensResponse: s.maxTokensResponse,
      maxContextTokens: s.maxContextTokens,
      apiKeySet: s.apiKeySet,
    })
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
