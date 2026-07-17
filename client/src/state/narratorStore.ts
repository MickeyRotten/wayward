import { create } from 'zustand'
import { api } from '../lib/api'

/** An alternate opening: its own narration plus its own scripted options. */
export interface OpeningAlt {
  message: string
  options: string[]
}

interface NarratorConfigResponse {
  instructions: string
  actionInstruction: string
  spotlightRule: string
  firstMessage: string
  postHistoryInstructions: string
  plannerInstructions: string
  actionSuggestionsEnabled: boolean
  actionSuggestionsInstructions: string
  actionSuggestionsMode: string
  actionOptionRules: string[]
  firstMessageOptions: string[]
  firstMessageAlternates: OpeningAlt[]
  diceEnabled: boolean
  hasVoice: boolean
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
  actionSuggestionsMode: string
  actionOptionRules: string[]
  firstMessageOptions: string[]
  firstMessageAlternates: OpeningAlt[]
  diceEnabled: boolean
  hasVoice: boolean
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
  actionSuggestionsMode: 'separate',
  actionOptionRules: [],
  firstMessageOptions: [],
  firstMessageAlternates: [],
  diceEnabled: true,
  hasVoice: false,

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
      actionSuggestionsMode: n.actionSuggestionsMode,
      actionOptionRules: n.actionOptionRules,
      firstMessageOptions: n.firstMessageOptions,
      firstMessageAlternates: n.firstMessageAlternates,
      diceEnabled: n.diceEnabled,
      hasVoice: n.hasVoice,
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
      actionSuggestionsMode: n.actionSuggestionsMode,
      actionOptionRules: n.actionOptionRules,
      firstMessageOptions: n.firstMessageOptions,
      firstMessageAlternates: n.firstMessageAlternates,
      diceEnabled: n.diceEnabled,
      hasVoice: n.hasVoice,
    })
  },
}))
