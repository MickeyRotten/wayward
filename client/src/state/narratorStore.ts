import { create } from 'zustand'
import type { NarratorConfig } from '@shared/types/models'
import { api } from '../lib/api'

interface NarratorState {
  instructions: string
  fetchConfig: () => Promise<void>
  saveInstructions: (text: string) => Promise<void>
}

export const useNarratorStore = create<NarratorState>((set) => ({
  instructions: '',

  fetchConfig: async () => {
    const narrator = await api.get<NarratorConfig>('/narrator')
    set({ instructions: narrator.instructions })
  },

  saveInstructions: async (text) => {
    await api.put('/narrator', { instructions: text })
    set({ instructions: text })
  },
}))
