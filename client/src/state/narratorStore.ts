import { create } from 'zustand'
import { api } from '../lib/api'

interface NarratorConfigResponse {
  instructions: string
  actionInstruction: string
  spotlightRule: string
  firstMessage: string
  postHistoryInstructions: string
}

interface NarratorState {
  instructions: string
  actionInstruction: string
  spotlightRule: string
  firstMessage: string
  postHistoryInstructions: string
  fetchConfig: () => Promise<void>
  save: (update: Partial<NarratorConfigResponse>) => Promise<void>
}

export const useNarratorStore = create<NarratorState>((set) => ({
  instructions: '',
  actionInstruction: '',
  spotlightRule: '',
  firstMessage: '',
  postHistoryInstructions: '',

  fetchConfig: async () => {
    const n = await api.get<NarratorConfigResponse>('/narrator')
    set({
      instructions: n.instructions,
      actionInstruction: n.actionInstruction,
      spotlightRule: n.spotlightRule,
      firstMessage: n.firstMessage,
      postHistoryInstructions: n.postHistoryInstructions,
    })
  },

  save: async (update) => {
    const n = await api.put<NarratorConfigResponse>('/narrator', update)
    set({
      instructions: n.instructions,
      actionInstruction: n.actionInstruction,
      spotlightRule: n.spotlightRule,
      firstMessage: n.firstMessage,
      postHistoryInstructions: n.postHistoryInstructions,
    })
  },
}))
