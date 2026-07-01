import { create } from 'zustand'
import { api } from '../lib/api'
import type { ScenarioFields } from '@shared/types/models'

interface ScenarioState extends ScenarioFields {
  fetchScenario: () => Promise<void>
  save: (update: Partial<ScenarioFields>) => Promise<void>
}

export const useScenarioStore = create<ScenarioState>((set) => ({
  setting: '',
  historyBrief: '',
  species: '',
  geography: '',
  techAndMagic: '',
  other: '',

  fetchScenario: async () => {
    const s = await api.get<ScenarioFields>('/scenario')
    set(s)
  },

  save: async (update) => {
    const s = await api.put<ScenarioFields>('/scenario', update)
    set(s)
  },
}))
