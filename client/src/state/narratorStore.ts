import { create } from 'zustand'
import type { NarratorConfig, Scenario } from '@shared/types/models'
import { api } from '../lib/api'

interface NarratorState {
  instructions: string
  scenario: string
  fetchConfig: () => Promise<void>
  saveInstructions: (text: string) => Promise<void>
  saveScenario: (text: string) => Promise<void>
}

export const useNarratorStore = create<NarratorState>((set) => ({
  instructions: '',
  scenario: '',

  fetchConfig: async () => {
    const [narrator, scenario] = await Promise.all([
      api.get<NarratorConfig>('/narrator'),
      api.get<Scenario>('/scenario'),
    ])
    set({ instructions: narrator.instructions, scenario: scenario.description })
  },

  saveInstructions: async (text) => {
    await api.put('/narrator', { instructions: text })
    set({ instructions: text })
  },

  saveScenario: async (text) => {
    await api.put('/scenario', { description: text })
    set({ scenario: text })
  },
}))
