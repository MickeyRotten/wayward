import { create } from 'zustand'
import { api } from '../lib/api'

interface NarratorConfigResponse {
  instructions: string
  actionInstruction: string
  spotlightRule: string
  firstMessage: string
  postHistoryInstructions: string
  plannerInstructions: string
  actionSuggestionsEnabled: boolean
  actionSuggestionsInstructions: string
}

interface NarratorState {
  instructions: string
  actionInstruction: string
  spotlightRule: string
  firstMessage: string
  postHistoryInstructions: string
  plannerInstructions: string
  actionSuggestionsEnabled: boolean
  actionSuggestionsInstructions: string
  fetchConfig: () => Promise<void>
  save: (update: Partial<NarratorConfigResponse>) => Promise<void>
}

export const useNarratorStore = create<NarratorState>((set) => ({
  instructions: '',
  actionInstruction: '',
  spotlightRule: '',
  firstMessage: '',
  postHistoryInstructions: '',
  plannerInstructions: '',
  actionSuggestionsEnabled: false,
  actionSuggestionsInstructions: '',

  fetchConfig: async () => {
    const n = await api.get<NarratorConfigResponse>('/narrator')
    set({
      instructions: n.instructions,
      actionInstruction: n.actionInstruction,
      spotlightRule: n.spotlightRule,
      firstMessage: n.firstMessage,
      postHistoryInstructions: n.postHistoryInstructions,
      plannerInstructions: n.plannerInstructions,
      actionSuggestionsEnabled: n.actionSuggestionsEnabled,
      actionSuggestionsInstructions: n.actionSuggestionsInstructions,
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
      plannerInstructions: n.plannerInstructions,
      actionSuggestionsEnabled: n.actionSuggestionsEnabled,
      actionSuggestionsInstructions: n.actionSuggestionsInstructions,
    })
  },
}))
